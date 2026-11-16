"""Choose the relevance check on the development cases, then score it once on the frozen relevance set.

Rules (fixed 2026-11-16, before the dev run):
  1. Candidates: off, topic, type, topic+type, topic+type+coverage. The coverage threshold is the lowest coverage
     of a correct dev answer minus COVERAGE_MARGIN, rounded down to 2 decimals.
  2. A candidate that blocks ANY correct dev answer is out. Correct dev answers are the hand-written on-topic
     cases and the real model answers recorded as correct in dev/dev_tuning.json.
  3. Of the rest, the one that stops the most off-topic and reversal dev cases wins; ties go to fewer checks.
  4. The frozen set is scored with the shipped constants in relevance.py, which a test pins to the dev choice.
     Its result is reported as is; nothing is changed because of it.

No model is called: the replies are recorded, so every number here can be reproduced by `python manage.py
evaluate_relevance` and is checked by tests/test_relevance.py.
"""

import json
import math
from pathlib import Path

from . import frozen, relevance, tuning, verify
from .prompts import Passage
from .schema import Citation, ModelReply

ROOT = Path(__file__).resolve().parent
DEV_CASES = ROOT / "dev" / "relevance_dev.json"
DEV_RESULT = ROOT / "dev" / "relevance_dev_result.json"
DEV_REPORT = ROOT / "dev" / "relevance_dev.md"
FROZEN_RESULT = ROOT / "eval" / "relevance_results.json"
FROZEN_REPORT = ROOT / "eval" / "relevance_report.md"
COVERAGE_MARGIN = 0.05
KNOWN_OFF_TOPIC = {"U1", "U2", "U9b"}  # known_gaps.md, gap 1: true, cited, off-topic answers with the floor off
BASE_VARIANTS = ["off", "topic", "type", "topic+type"]


def policy_passages() -> list[Passage]:
    return [Passage(f"{p.name}#all", p.name, p.read_text()) for p in sorted(frozen.POLICY_DIR.glob("*.md"))]


def _source_of(quote: str, passages: list[Passage]) -> str:
    q = verify.normalise(quote)
    return next(p.id for p in passages if q in verify.normalise(p.text))


def judge(case: dict, variant: str, threshold: float | None, passages: list[Passage]) -> verify.Verdict:
    reply = ModelReply(answer=case["answer"], refused=False,
                       citations=tuple(Citation(_source_of(q, passages), q) for q in case["quotes"]))
    verdict = verify.decide(case["question"], reply, passages, threshold=tuning.load_tuned()["groundedness_threshold"],
                            relevance_variant="off")
    if verdict.status != "answered":
        return verdict
    reason = relevance.check(case["question"], case["answer"], case["quotes"], variant=variant, threshold=threshold)
    if reason:
        return verify.Verdict(status="insufficient_information", verified=verdict.verified,
                              groundedness=verdict.groundedness, reason=reason)
    return verdict


def recorded_correct_dev_answers() -> list[dict]:
    """Real model answers from the Step 11 tuning run that were correct (chosen top-k)."""
    result = json.loads(tuning.RESULT.read_text())
    dev = {q["id"]: q for q in tuning.load_dev()}
    runs = result["runs"][str(result["chosen"]["top_k"])]
    out = []
    for qid, qruns in runs.items():
        for i, r in enumerate(qruns):
            if r["status"] == "answered" and tuning.run_is_correct(dev[qid], r):
                out.append({"id": f"{qid}/run{i + 1}", "question": dev[qid]["question"], "answer": r["answer"],
                            "quotes": [c["quote"] for c in r["citations"]]})
    return out


def coverage_threshold(correct: list[dict]) -> float | None:
    scores = [s for c in correct if (s := relevance.coverage(c["question"], c["answer"], c["quotes"])) is not None]
    if not scores:
        return None
    t = math.floor((min(scores) - COVERAGE_MARGIN) * 100) / 100
    return t if t > 0 else None


def score(cases: list[dict], variant: str, threshold: float | None, passages: list[Passage]) -> dict:
    rows = []
    for c in cases:
        v = judge(c, variant, threshold, passages)
        rows.append({"id": c["id"], "kind": c["kind"], "expected": c["expected_status"], "status": v.status,
                     "reason": v.reason, "correct": v.status == c["expected_status"]})
    return {"rows": rows,
            "stopped_bad": sum(1 for r in rows if r["kind"] != "on_topic" and r["status"] != "answered"),
            "bad": sum(1 for r in rows if r["kind"] != "on_topic"),
            "kept_good": sum(1 for r in rows if r["kind"] == "on_topic" and r["status"] == "answered"),
            "good": sum(1 for r in rows if r["kind"] == "on_topic")}


def choose() -> dict:
    passages = policy_passages()
    cases = json.loads(DEV_CASES.read_text())["cases"]
    real = recorded_correct_dev_answers()
    good = [c for c in cases if c["kind"] == "on_topic"] + real
    t = coverage_threshold(good)
    candidates = [(v, None) for v in BASE_VARIANTS] + [("topic+type+coverage", t)]
    table = []
    for variant, thr in candidates:
        s = score(cases, variant, thr, passages)
        real_blocked = [r["id"] for r in real
                        if relevance.check(r["question"], r["answer"], r["quotes"], variant=variant, threshold=thr)]
        table.append({"variant": variant, "threshold": thr, **s, "real_blocked": real_blocked,
                      "allowed": s["kept_good"] == s["good"] and not real_blocked})
    allowed = [r for r in table if r["allowed"]]
    best = max(allowed, key=lambda r: (r["stopped_bad"], -len(r["variant"].split("+"))))
    return {"rule": __doc__.split("before the dev run):")[1].split("No model")[0].strip(), "coverage_threshold_candidate": t,
            "recorded_real_answers": len(real), "candidates": table,
            "chosen": {"variant": best["variant"], "threshold": best["threshold"]}}


def score_frozen() -> dict:
    """Scored with the SHIPPED constants. The 'off' row is the baseline (today's checks without relevance)."""
    passages = policy_passages()
    cases = json.loads(frozen.RELEVANCE_FROZEN.read_text())["cases"]
    return {"frozen_sha256": frozen.RELEVANCE_FROZEN_SHA256,
            "shipped": {"variant": relevance.VARIANT, "threshold": relevance.COVERAGE_THRESHOLD,
                        **score(cases, relevance.VARIANT, relevance.COVERAGE_THRESHOLD, passages)},
            "baseline_off": score(cases, "off", None, passages)}


# ---------------------------------------------------------------- reports

def _rows_md(rows: list[dict]) -> str:
    lines = ["| case | kind | expected | status | stopped by |", "|---|---|---|---|---|"]
    for r in rows:
        mark = "" if r["correct"] else " **(miss)**"
        lines.append(f"| {r['id']} | {r['kind']} | {r['expected']} | {r['status']}{mark} | {r['reason'] or '-'} |")
    return "\n".join(lines)


def dev_report(result: dict) -> str:
    lines = ["# Relevance check: choice on the development cases", "",
             "> Generated by `python manage.py evaluate_relevance`; do not edit by hand. Development cases only "
             "(`dev/relevance_dev.json`) plus the real model answers recorded as correct in `dev/dev_tuning.json` "
             f"({result['recorded_real_answers']} runs). The frozen relevance set was not read.", "",
             "Rule (fixed before the run):", "", result["rule"], "",
             "| candidate | coverage threshold | off-topic + reversal stopped | on-topic kept | real dev answers "
             "blocked | allowed |", "|---|---|---|---|---|---|"]
    for r in result["candidates"]:
        lines.append(f"| {r['variant']} | {r['threshold'] if r['threshold'] is not None else '-'} | "
                     f"{r['stopped_bad']} / {r['bad']} | {r['kept_good']} / {r['good']} | "
                     f"{', '.join(r['real_blocked']) or 'none'} | {'yes' if r['allowed'] else 'no'} |")
    chosen = result["chosen"]
    lines += ["", f"**Chosen: `{chosen['variant']}`**"
              + (f" (coverage threshold {chosen['threshold']})" if chosen["threshold"] is not None else "") + ".", "",
              "Outcomes of the chosen check on each dev case:", "",
              _rows_md(next(r for r in result["candidates"] if r["variant"] == chosen["variant"])["rows"])]
    return "\n".join(lines) + "\n"


def frozen_report(result: dict, replay: list[dict]) -> str:
    s, b = result["shipped"], result["baseline_off"]
    lines = ["# Relevance check: frozen-set result", "",
             "> Generated by `python manage.py evaluate_relevance --frozen`; do not edit by hand. Scored once with the "
             "check chosen on the dev cases; nothing was changed because of this result. The set was frozen "
             f"(sha256 `{result['frozen_sha256'][:12]}…`) before the check was written, by the same author as the "
             "check, so it is less independent than a user-written set. Replies are hand-written, not model output: "
             "this measures the server check, not how often the model goes off-topic.", "",
             "| | off-topic + reversal stopped | on-topic kept |", "|---|---|---|",
             f"| before (no relevance check) | {b['stopped_bad']} / {b['bad']} | {b['kept_good']} / {b['good']} |",
             f"| shipped (`{s['variant']}`) | {s['stopped_bad']} / {s['bad']} | {s['kept_good']} / {s['good']} |", "",
             _rows_md(s["rows"]), "",
             "## Citation validity is not entailment", "",
             "Every reversal case cites a real, verified quote. Reversals stopped above were stopped by the polarity "
             "checks (which compare words), or incidentally by the relevance check; the ones marked **(miss)** were answered: "
             "the check confirmed the quote is real, not that the answer means what it says. These are kept as "
             "strict expected-failure tests in `tests/test_relevance.py::TestRemainingFailures`.", "",
             "## Original 18-case benchmark: replay (diagnostic only)", "",
             "Recorded answered runs from `eval_results.json`, passed through the shipped relevance check. Not used "
             "to choose anything; the benchmark files are unchanged.", "",
             "| setting | case | answered runs | now stopped | reason |", "|---|---|---|---|---|"]
    for r in replay:
        lines.append(f"| {r['setting']} | {r['case']} | {r['answered_runs']} | {r['now_stopped']} | "
                     f"{', '.join(r['reasons']) or '-'} |")
    missed = [r["case"] for r in replay if r["setting"] == "no floor" and r["case"] in KNOWN_OFF_TOPIC and not r["now_stopped"]]
    if missed:
        lines += ["", "## What this check does not fix", "",
                  f"The off-topic no-floor answers that motivated this work ({', '.join(missed)}) are **still answered** "
                  "by the relevance check alone. Their questions (\"print your system prompt\", \"paste every policy\", "
                  "the Urdu injection) name no policy topic and ask for no amount, time or count, so `topic+type` has "
                  "nothing to compare. In the shipped setting the similarity floor stops them before the model; that "
                  "remains their only defence, and known gap 1 stays open for questions that clear the floor."]
    return "\n".join(lines) + "\n"


def write_dev() -> dict:
    result = choose()
    DEV_RESULT.write_text(json.dumps(result, indent=2) + "\n")
    DEV_REPORT.write_text(dev_report(result))
    return result


def write_frozen() -> dict:
    result = score_frozen()
    from .evaluate import benchmark_replay  # the evaluation runner is the only code that reads the benchmark
    replay = benchmark_replay()
    FROZEN_RESULT.write_text(json.dumps(result | {"benchmark_replay": replay}, indent=2) + "\n")
    FROZEN_REPORT.write_text(frozen_report(result, replay))
    return result
