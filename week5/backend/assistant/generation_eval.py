"""Generation evaluation on the frozen Week 5 set, separately from retrieval (Week 5 Step 4).

Two modes, both with the shipped generation stack (Week 4 prompt, server checks, groundedness threshold):
- A, oracle context (the main measure): an answerable question gets its gold chunk(s), the highest-scoring
  chunk containing each evidence quote, plus one near-miss distractor (the highest-scoring chunk containing
  no evidence quote). An unanswerable question gets its top 2 retrieved chunks. So retrieval is taken out of
  the picture: can the model answer, cite and stay grounded when the right text is there, and abstain when
  only related text is there?
- B, end to end: the shipped retrieval (Week 4's champion) and generation, as a user gets it.

Per run: status, key-fact correctness (assistant/keyfacts.py, frozen answer key), citation precision (cited
passages that contain evidence) and recall (every evidence quote cited), groundedness, tokens. Each question
runs with seeds 42–44 and each measure is decided by a 2-of-3 majority. Reporting only: nothing is tuned.
The frozen corpus is built inside a rolled-back transaction and checked against the manifest.
"""

import json
import time
from pathlib import Path

from django.db import transaction

from . import frozen
from .answering import answer_question
from .embeddings import Embedder
from .indexing import candidates
from .keyfacts import all_facts
from .llm import LLMClient
from .prompts import Passage
from .retrieval_eval import CAVEAT, build_corpus, count, norm
from .service import ask
from .tuning import load_tuned

RUNS, MAJORITY = 3, 2
OUT = Path(__file__).resolve().parent / "eval"


def load_cases() -> list[dict]:
    return json.loads(frozen.RETRIEVAL_CASES.read_text())["cases"]


def load_keys() -> dict:
    return json.loads(frozen.GENERATION_KEYS.read_text())["keys"]


def _passage(ch) -> Passage:
    return Passage(ch.passage_id, ch.document.filename, ch.text, version=ch.version.number,
                   document_id=ch.document_id, sha256=ch.version.sha256)


def oracle_context(case: dict, cand) -> list[Passage]:
    """Gold chunk(s) plus one near-miss distractor, in cosine order; top 2 for unanswerable questions."""
    ranked = sorted(range(len(cand.chunks)), key=lambda i: (-float(cand.cosine[i]), i))
    texts = [norm(cand.chunks[i].text) for i in ranked]
    if not case["answerable"]:
        chosen = ranked[:2]
    else:
        quotes = [norm(e["quote"]) for e in case["evidence"]]
        gold = []
        for q in quotes:
            first = next(i for i, t in zip(ranked, texts) if q in t)
            if first not in gold:
                gold.append(first)
        distractor = next(i for i, t in zip(ranked, texts) if not any(q in t for q in quotes))
        chosen = gold + [distractor]
    return [_passage(cand.chunks[i]) for i in sorted(chosen, key=ranked.index)]


def score_run(case: dict, key: list | None, status: str, answer: str, citations: list, texts: dict) -> dict:
    answered = status == "answered"
    out = {"status": status, "answered": answered}
    if not case["answerable"]:
        out["abstained"] = not answered
        return out
    quotes = [norm(e["quote"]) for e in case["evidence"]]
    cited = [norm(texts.get(c["passage_id"], "")) for c in citations]
    out["key_fact_ok"] = answered and all_facts(answer, key)
    out["false_abstention"] = not answered
    out["answered_wrong"] = answered and not out["key_fact_ok"]
    out["citations"] = len(cited)
    out["gold_citations"] = sum(any(q in t for q in quotes) for t in cited)
    out["citation_recall"] = answered and all(any(q in t for t in cited) for q in quotes)
    return out


def majority(runs: list[dict], key: str) -> bool:
    return sum(bool(r.get(key)) for r in runs) >= MAJORITY


def run_mode(mode: str, cases, keys, llm, embedder, tuned, seeds) -> dict:
    out = {}
    for case in cases:
        cand = candidates(case["question"], embedder)
        texts = {c.passage_id: c.text for c in cand.chunks}
        runs = []
        for seed in seeds:
            start = time.perf_counter()
            if mode == "A":
                r = ask(case["question"], oracle_context(case, cand), llm,
                        groundedness_threshold=tuned["groundedness_threshold"], seed=seed)
            else:
                r = answer_question(case["question"], llm, embedder, tuned=tuned, seed=seed).result
            run = score_run(case, keys.get(case["id"]), r.status, r.answer if r.status == "answered" else "",
                            r.citations, texts)
            run |= {"seed": seed, "answer": r.answer if r.status == "answered" else "", "reason": r.reason,
                    "cited": [c["passage_id"] for c in r.citations], "rejected_citations": r.rejected_citations,
                    "groundedness": r.groundedness, "tokens": (r.usage or {}).get("total_tokens", 0),
                    "seconds": round(time.perf_counter() - start, 2)}
            runs.append(run)
        out[case["id"]] = runs
    return out


def aggregate(cases: list[dict], runs: dict) -> dict:
    ans = [c for c in cases if c["answerable"]]
    una = [c for c in cases if not c["answerable"]]
    all_runs = [r for c in cases for r in runs[c["id"]]]
    ans_runs = [r for c in ans for r in runs[c["id"]]]
    cited = sum(r["citations"] for r in ans_runs)
    g = [r["groundedness"] for r in all_runs if r["answered"] and r["groundedness"] is not None]
    return {"answerable": len(ans), "unanswerable": len(una),
            "key_fact_ok": sum(majority(runs[c["id"]], "key_fact_ok") for c in ans),
            "false_abstention": sum(majority(runs[c["id"]], "false_abstention") for c in ans),
            "answered_wrong": sum(majority(runs[c["id"]], "answered_wrong") for c in ans),
            "citation_recall": sum(majority(runs[c["id"]], "citation_recall") for c in ans),
            "abstained": sum(majority(runs[c["id"]], "abstained") for c in una),
            "citations": cited, "gold_citations": sum(r["gold_citations"] for r in ans_runs),
            "rejected_citations": sum(r["rejected_citations"] for r in all_runs),
            "groundedness_median": round(sorted(g)[len(g) // 2], 2) if g else None,
            "tokens": sum(r["tokens"] for r in all_runs), "seconds": round(sum(r["seconds"] for r in all_runs), 1)}


def evaluate(llm: LLMClient, embedder: Embedder, base_seed: int, cases: list[dict] | None = None) -> dict:
    cases = cases if cases is not None else load_cases()
    keys, tuned = load_keys(), load_tuned()
    seeds = [base_seed + i for i in range(RUNS)]
    with transaction.atomic():
        snapshot = build_corpus(embedder, 80)
        modes = {m: run_mode(m, cases, keys, llm, embedder, tuned, seeds) for m in ("A", "B")}
        transaction.set_rollback(True)
    by = lambda key, runs: {v: aggregate([c for c in cases if c[key] == v], runs) for v in sorted({c[key] for c in cases})}
    return {"model": llm.model, "embedder": embedder.identity, "seeds": seeds, "settings": tuned, "corpus": snapshot,
            "frozen_sha256": {k: frozen.WEEK5_FROZEN_SHA256[k] for k in ("eval/retrieval_cases.json", "eval/generation_keys.json")},
            "modes": {m: {"overall": aggregate(cases, runs), "by_category": by("category", runs),
                          "by_author": by("author", runs), "runs": runs} for m, runs in modes.items()}}


# ---------------------------------------------------------------- report

def _row(name: str, g: dict) -> str:
    a, u = g["answerable"], g["unanswerable"]
    prec = f"{g['gold_citations']} of {g['citations']}" if g["citations"] else "–"
    return (f"| {name} | {count(g['key_fact_ok'], a)} | {count(g['false_abstention'], a)} | {count(g['answered_wrong'], a)} | "
            f"{count(g['citation_recall'], a)} | {prec} | {count(g['abstained'], u)} |")


HEAD = ("| | key fact correct | false abstention | answered but wrong | citation recall | citation precision (runs) | "
        "correct abstention (unanswerable) |\n|---|---|---|---|---|---|---|")


def build_report(r: dict, cases: list[dict]) -> str:
    A, B = r["modes"]["A"], r["modes"]["B"]
    cat = "\n".join(_row(f"{c} (A)", A["by_category"][c]) + "\n" + _row(f"{c} (B)", B["by_category"][c])
                    for c in sorted(A["by_category"]))
    auth = "\n".join(_row(f"{a} (A)", A["by_author"][a]) + "\n" + _row(f"{a} (B)", B["by_author"][a])
                     for a in sorted(A["by_author"]))
    per = []
    for c in cases:
        for m, mode in (("A", A), ("B", B)):
            runs = mode["runs"][c["id"]]
            if c["answerable"]:
                verdict = "correct" if majority(runs, "key_fact_ok") else ("abstained" if majority(runs, "false_abstention") else "**wrong**")
            else:
                verdict = "abstained" if majority(runs, "abstained") else "**answered**"
            per.append(f"| {c['id']} | {m} | {c['category']} | {', '.join(x['status'] for x in runs)} | {verdict} | "
                       f"{'; '.join(sorted({x['answer'][:90] for x in runs if x['answer']})) or '–'} |")
    oa, ob = A["overall"], B["overall"]
    return f"""# Generation evaluation, separately from retrieval (Step 4)

> Generated by `python manage.py evaluate_generation`; do not edit by hand. Model `{r['model']}`, seeds
> {', '.join(map(str, r['seeds']))} (each measure by 2-of-3 majority). Frozen Week 5 set and frozen answer key.
> Shipped settings (floor {r['settings']['floor']}, top-k {r['settings']['top_k']}, groundedness {r['settings']['groundedness_threshold']}). **Reporting only: nothing was tuned.**

**{CAVEAT}**

- **Mode A, oracle context (the main generation measure):** gold chunk(s) plus one near-miss distractor; top 2
  retrieved chunks for unanswerable questions. Retrieval is taken out of the picture.
- **Mode B, end to end:** the shipped retrieval and generation.

Key facts are matched as whole words after normalising number words; a directly negated match doesn't count.

## Overall ({oa['answerable']} answerable, {oa['unanswerable']} unanswerable)

{HEAD}
{_row("**A: oracle context**", oa)}
{_row("**B: end to end**", ob)}

Groundedness (median, answered runs): A {oa['groundedness_median']}, B {ob['groundedness_median']}. Server-rejected
citations: A {oa['rejected_citations']}, B {ob['rejected_citations']}. Tokens: A {oa['tokens']:,}, B {ob['tokens']:,}. Model time:
A {oa['seconds']} s, B {ob['seconds']} s.

**Reading A against B:** a question correct in A but not in B lost its answer to retrieval; a question wrong or
abstained in A is a generation problem even with the right text in front of the model.

## By category

{HEAD}
{cat}

## By author

{HEAD}
{auth}

## Every question

| id | mode | category | statuses (3 runs) | majority verdict | answers |
|---|---|---|---|---|---|
{chr(10).join(per)}

With 23 questions, one question is 4–6 percentage points; small differences are noise.
"""


def save(r: dict, cases: list[dict]) -> Path:
    (OUT / "generation_eval.json").write_text(json.dumps(r, indent=1, default=str) + "\n")
    path = OUT / "generation_eval.md"
    path.write_text(build_report(r, cases))
    return path
