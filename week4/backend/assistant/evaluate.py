"""Week 4 Step 12: run the 18 frozen evaluation cases against the real local model, for two settings.

Run (needs the local model and the policies loaded):  python manage.py evaluate_assistant
Writes assistant/eval/eval_results.json (every run) and assistant/eval/eval_report.md.

Settings, named before any case was run:
  A (shipped)    the values tuned on the development set (assistant/dev/dev_tuning.json).
  B (comparison) the same, except top-k 4. On the dev set k = 2, 3 and 4 tied (11 of 11), so the dev set
                 gave no evidence either way; only one thing changes, so any difference can be attributed.
The comparison is for reporting only. Setting A is what ships and stays; if B does better here, that is a
finding and a candidate for a future dev-set round, never a reason to change the configuration.

Each case runs RUNS times per setting with seeds SEED, SEED+1, SEED+2 (temperature 0.1) and passes if at
least MAJORITY runs pass. Uploads (U3 pending, U3b approved) are created inside a transaction that is rolled
back after each run, so no case affects another and the database is left unchanged.

Scoring a run against its frozen expectations:
  - expected_status: the server-decided status must be one of them;
  - expected_source / must_contain (answered cases), if_answered (only when answered);
  - must_not_contain / must_not_match / must_not_start_with / max_document_chars, checked against the text the
    MODEL produced and the user sees: the answer, the citation quotes and the cited passage ids. The fixed,
    server-written disclaimer and refusal message are excluded: they are the same for every request and were
    reviewed once (they mention "fictional clinic", which is also a forbidden system-prompt fragment for U1).
"""

import json
import re
from pathlib import Path

from django.db import transaction

from . import frozen
from .answering import answer_question
from .embeddings import Embedder
from .indexing import approve
from .llm import LLMClient
from .models import PolicyDocument
from .tuning import load_tuned
from .uploads import validate_upload

EVAL_DIR = Path(__file__).resolve().parent / "eval"
RESULT = EVAL_DIR / "eval_results.json"
REPORT = EVAL_DIR / "eval_report.md"

RUNS = 3
MAJORITY = 2
SHIPPED = "A (shipped)"
COMPARISON = "B (comparison)"
LESS_INDEPENDENT = {"A1", "A6"}  # share their meaning with the question the Step 9 design was built on


def settings_under_test() -> dict[str, dict]:
    shipped = load_tuned()
    return {SHIPPED: shipped, COMPARISON: shipped | {"top_k": 4}}


def load_cases() -> list[dict]:
    return json.loads(frozen.EVAL_CASES.read_text())["cases"]


# ---------------------------------------------------------------- scoring (pure; re-checked by tests)

def shown_text(run: dict) -> str:
    """What the model produced and the user sees (see module docstring)."""
    parts = [run["answer"]] if run["status"] == "answered" else []
    for c in run["citations"]:
        parts += [c["passage_id"], c["quote"]]
    return "\n".join(parts)


def run_failures(case: dict, run: dict) -> list[str]:
    """Every rule this run broke (empty list = the run passes)."""
    problems = []
    if run["status"] not in case["expected_status"]:
        problems.append(f"status {run['status']} not in {case['expected_status']}")
    text = shown_text(run).lower()
    sources = {c["passage_id"].split("#")[0] for c in run["citations"]}
    answered = run["status"] == "answered"
    rules = {"expected_source": case.get("expected_source"), "must_contain": case.get("must_contain", [])}
    if answered and "if_answered" in case:
        rules["expected_source"] = case["if_answered"].get("expected_source", rules["expected_source"])
        rules["must_contain"] = rules["must_contain"] + case["if_answered"].get("must_contain", [])
    if answered and rules["expected_source"] and rules["expected_source"] not in sources:
        problems.append(f"does not cite {rules['expected_source']}")
    if answered:
        for fact in rules["must_contain"]:
            if fact.lower() not in run["answer"].lower():
                problems.append(f"answer lacks '{fact}'")
    for forbidden in case.get("must_not_contain", []):
        if forbidden.lower() in text:
            problems.append(f"contains '{forbidden}'")
    for pattern in case.get("must_not_match", []):
        if re.search(pattern, text, re.I):
            problems.append(f"matches /{pattern}/")
    start = case.get("must_not_start_with")
    if start and answered and re.match(rf"\s*{re.escape(start)}\b", run["answer"], re.I):
        problems.append(f"answer starts with '{start}'")
    limit = case.get("max_document_chars")
    if limit is not None and sum(len(c["quote"]) for c in run["citations"]) > limit:
        problems.append(f"more than {limit} characters of document text")
    return problems


def case_passes(runs: list[dict]) -> bool:
    return sum(not r["failures"] for r in runs) >= MAJORITY


# ---------------------------------------------------------------- running against the model

def _prepare_upload(case: dict, admin, embedder: Embedder) -> None:
    upload = case.get("upload")
    if not upload:
        return
    valid = validate_upload(upload["filename"], upload["content"].encode())
    document = PolicyDocument.objects.create(filename=valid.filename, sha256=valid.sha256, content=valid.content,
                                             source=PolicyDocument.Source.UPLOAD, uploaded_by=admin)
    if upload["approval"] == "approved":
        approve(document, admin, embedder)


def run_case(case: dict, settings: dict, seed: int, llm: LLMClient, embedder: Embedder, admin) -> dict:
    with transaction.atomic():
        _prepare_upload(case, admin, embedder)
        answered = answer_question(case["question"], llm, embedder, tuned=settings, seed=seed)
        transaction.set_rollback(True)  # the upload never outlives its run
    r = answered.result
    run = {"seed": seed, "status": r.status, "reason": r.reason, "public_reason": answered.public_reason,
           "answer": r.answer if r.status == "answered" else "", "citations": r.citations,
           "rejected_citations": r.rejected_citations, "groundedness": r.groundedness,
           "model_called": r.model_called, "sources": answered.sources,
           "tokens": (r.usage or {}).get("total_tokens", 0)}
    run["failures"] = run_failures(case, run)
    return run


def evaluate(llm: LLMClient, embedder: Embedder, admin, base_seed: int) -> dict:
    seeds = [base_seed + i for i in range(RUNS)]
    under_test = settings_under_test()
    results = {name: {c["id"]: [run_case(c, s, seed, llm, embedder, admin) for seed in seeds] for c in load_cases()}
               for name, s in under_test.items()}
    return {"model": llm.model, "embedder": embedder.identity, "seeds": seeds, "settings": under_test,
            "frozen_eval_sha256": frozen.FROZEN_SHA256["eval/eval_cases.json"], "results": results}


# ---------------------------------------------------------------- report

def _rate(cases: list[dict], runs: dict) -> str:
    passed = sum(case_passes(runs[c["id"]]) for c in cases)
    return f"{passed} of {len(cases)}" if cases else "–"


def summary(result: dict, cases: list[dict]) -> dict:
    out = {}
    for name, runs in result["results"].items():
        all_runs = [r for c in cases for r in runs[c["id"]]]
        answered = [r for r in all_runs if r["status"] == "answered"]
        out[name] = {
            "passed": sum(case_passes(runs[c["id"]]) for c in cases),
            "verified_citations": sum(len(r["citations"]) for r in all_runs),
            "rejected_citations": sum(r["rejected_citations"] for r in all_runs),
            "answered_runs": len(answered),
            "answered_runs_citing_expected": sum(
                1 for c in cases for r in runs[c["id"]] if r["status"] == "answered"
                and (c.get("expected_source") or c.get("if_answered", {}).get("expected_source"))
                in {x["passage_id"].split("#")[0] for x in r["citations"]}),
            "tokens": sum(r["tokens"] for r in all_runs),
        }
    return out


def build_report(result: dict, cases: list[dict]) -> str:
    names = list(result["results"])
    a, b = names
    s = summary(result, cases)
    groups = {}
    for c in cases:
        groups.setdefault(c["category"], []).append(c)
    category_rows = "\n".join(f"| {cat} | {len(cs)} | " + " | ".join(_rate(cs, result["results"][n]) for n in names) + " |"
                              for cat, cs in sorted(groups.items()))
    by_author = {"user": [c for c in cases if c["author"] == "user"],
                 "assistant": [c for c in cases if c["author"] != "user"]}
    author_rows = "\n".join(f"| {who} | {len(cs)} | " + " | ".join(_rate(cs, result["results"][n]) for n in names) + " |"
                            for who, cs in by_author.items())
    independent = [c for c in cases if c["id"] not in LESS_INDEPENDENT]

    def passes(n, cid):
        return sum(not r["failures"] for r in result["results"][n][cid])

    case_rows = []
    for c in cases:
        cells = []
        for n in names:
            runs = result["results"][n][c["id"]]
            stopped = sorted({r["reason"] or "answered" for r in runs})
            cells.append(f"{'**pass**' if case_passes(runs) else 'FAIL'} ({passes(n, c['id'])}/3) · {', '.join(r['status'] for r in runs)} · {'; '.join(stopped)}")
        case_rows.append(f"| {c['id']} | {c['category']} | {c['author']} | " + " | ".join(cells) + " |")
    disagree = [c["id"] for c in cases if case_passes(result["results"][a][c["id"]]) != case_passes(result["results"][b][c["id"]])]
    unstable = sorted({c["id"] for c in cases for n in names if passes(n, c["id"]) in (1, 2)})
    failures = []
    for c in cases:
        for n in names:
            if not case_passes(result["results"][n][c["id"]]):
                details = sorted({f for r in result["results"][n][c["id"]] for f in r["failures"]})
                failures.append(f"- **{c['id']}** ({n}, {c['category']}): {'; '.join(details)}")
    better = s[b]["passed"] - s[a]["passed"]

    return f"""# Assistant evaluation: 18 frozen cases, two settings

> Generated by `python manage.py evaluate_assistant`; do not edit by hand. Model `{result['model']}`, embedder
> `{result['embedder']}`, seeds {', '.join(map(str, result['seeds']))}, frozen cases SHA-256 `{result['frozen_eval_sha256'][:16]}…`.
> Each case ran 3 times per setting and passes if at least 2 runs pass.

## Settings (named before any case ran)

| setting | floor | top-k | groundedness threshold | role |
|---|---|---|---|---|
| {a} | {result['settings'][a]['floor']:.2f} | {result['settings'][a]['top_k']} | {result['settings'][a]['groundedness_threshold']:.2f} | **shipped**: tuned on the dev set |
| {b} | {result['settings'][b]['floor']:.2f} | {result['settings'][b]['top_k']} | {result['settings'][b]['groundedness_threshold']:.2f} | comparison only (top-k tied on the dev set) |

**The comparison is for reporting only. Setting A ships and stays.** {
f"Setting B passed {better} more case(s) here: a finding and a candidate for a future dev-set round, not a reason to switch." if better > 0 else
f"Setting B passed {-better} fewer case(s)." if better < 0 else "Both settings passed the same number of cases."}

**With 18 cases, a difference of 1–2 cases between A and B is within noise, so don't over-interpret small gaps.**

## Results

| | {a} | {b} |
|---|---|---|
| cases passed | **{s[a]['passed']} of {len(cases)}** | **{s[b]['passed']} of {len(cases)}** |
| without A1 and A6 (less independent of the Step 9 design) | {_rate(independent, result['results'][a])} | {_rate(independent, result['results'][b])} |
| verified citations / rejected citations | {s[a]['verified_citations']} / {s[a]['rejected_citations']} | {s[b]['verified_citations']} / {s[b]['rejected_citations']} |
| answered runs citing the expected policy | {s[a]['answered_runs_citing_expected']} of {s[a]['answered_runs']} | {s[b]['answered_runs_citing_expected']} of {s[b]['answered_runs']} |
| tokens used (all runs) | {s[a]['tokens']:,} | {s[b]['tokens']:,} |

| category | cases | {a} | {b} |
|---|---|---|---|
{category_rows}

| author | cases | {a} | {b} |
|---|---|---|---|
{author_rows}

Cases where A and B disagree: {', '.join(disagree) if disagree else 'none'}.
Unstable cases (passed only 1 or 2 of their 3 runs in some setting; close to a coin flip): {', '.join(unstable) if unstable else 'none'}.

## Every case: outcome, runs, and which check decided it

| case | category | author | {a} | {b} |
|---|---|---|---|---|
{chr(10).join(case_rows)}

## Failure analysis

{chr(10).join(failures) if failures else 'No case failed in either setting.'}

**Limitation: the server checks compare words, not meaning.** A negation flip can still get through in forms
the polarity check doesn't recognise (an antonym such as "refused" for "paid back", or "only after" versus
"before"), and a partly unsupported answer can pass when most of its key terms match; both are kept as known
gaps in `tests/test_assistant_polarity.py`. "You can cancel late at no cost" against the fee quote is stopped
only by groundedness (0.33 against {result['settings'][a]['groundedness_threshold']:.2f}). Answered runs above were not
checked for such flips beyond the frozen expectations, so a passing case is not proof that no flip occurred.
"""


def save(result: dict) -> None:
    RESULT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    REPORT.write_text(build_report(json.loads(RESULT.read_text()), load_cases()))
