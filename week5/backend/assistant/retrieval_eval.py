"""Retrieval-only evaluation on the frozen Week 5 set (Step 2): no model is called.

How a run works:
1. Inside a transaction that is always rolled back, every live document is retired and the frozen Week 5
   corpus is built from its pinned files (frozen.WEEK5_CORPUS_FILES): the 12 policies as v1, then
   cancellation v2 approved over v1. The searchable set is checked against frozen.WEEK5_CORPUS (it fails
   loudly otherwise) and the snapshot is recorded. Nothing outlives the run, so the live database and the
   Week 4 corpus check are untouched.
2. Each question is searched once with no floor and no cut-off, so ranks are known for every K.
3. Hits use the hit rule: a chunk is a hit for an evidence quote when it contains the whole quote (case and
   whitespace normalised). Quotes are one sentence, and the chunker never splits a sentence, so every chunk
   size is scored fairly.

Metrics, per answerable question and K in (1, 3, 5): recall (every evidence quote found in the top K), hit
(at least one found), document recall (every evidence document present), and reciprocal rank of the first
chunk containing any quote. Per unanswerable question: the top score, and whether it clears the floor
(false retrieval). Also "as shipped": what the real settings (floor, top-k) would return.

Only this module reads the evaluation file (tests/test_retrieval_sets.py enforces it).
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from django.db import transaction

from . import frozen
from .documents import CorpusMismatch, add_version, approve_version, check_corpus, create_document, retire
from .embeddings import Embedder
from .indexing import RetrievalConfig, candidates, order, returned
from .models import PolicyDocument
from .tuning import load_tuned

KS = (1, 3, 5)
OUT = Path(__file__).resolve().parent / "eval"
CAVEAT = ("The corpus was deliberately built to be harder by the same author who builds the retrieval, so the size of "
          "any improvement may not transfer to other document sets.")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def load_cases(path: Path = frozen.RETRIEVAL_CASES) -> list[dict]:
    return json.loads(path.read_text())["cases"]


# ---------------------------------------------------------------- the frozen corpus, built in isolation

def build_corpus(embedder: Embedder, chunk_tokens: int | None = None) -> list[dict]:
    """Must run inside a transaction that the caller rolls back. Returns the checked snapshot."""
    for d in PolicyDocument.objects.exclude(status=PolicyDocument.Status.RETIRED):
        retire(d, None)
    built: dict[str, PolicyDocument] = {}
    for name, version, file, area in frozen.WEEK5_CORPUS_FILES:
        data = (frozen.ROOT / file).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        expected_version, expected_sha = frozen.WEEK5_CORPUS[name]
        if sha != frozen._pinned(file) or (version == expected_version and sha != expected_sha):
            raise CorpusMismatch(f"{file} (as {name} v{version}) does not match its frozen SHA-256; refusing to evaluate.")
        if version == 1:
            built[name] = create_document(name, data.decode("utf-8"), sha, PolicyDocument.Source.SEED, None, policy_area=area)
            pending = built[name].versions.get(number=1)
        else:
            pending = add_version(built[name], data.decode("utf-8"), sha, None)
        approve_version(pending, None, embedder, chunk_tokens)
    return check_corpus(frozen.WEEK5_CORPUS)


# ---------------------------------------------------------------- scoring

@dataclass
class Ranked:
    texts: list[str]
    documents: list[str]
    scores: list[float]
    passage_ids: list[str] = field(default_factory=list)


def first_rank(case: dict, ranked: Ranked) -> int | None:
    """1-based rank of the first chunk containing any evidence quote."""
    quotes = [norm(e["quote"]) for e in case["evidence"]]
    for i, text in enumerate(ranked.texts):
        if any(q in norm(text) for q in quotes):
            return i + 1
    return None


def found_at(case: dict, ranked: Ranked, k: int) -> list[bool]:
    top = [norm(t) for t in ranked.texts[:k]]
    return [any(norm(e["quote"]) in t for t in top) for e in case["evidence"]]


def score_case(case: dict, ranked: Ranked, floor: float, top_k: int, shipped: list[str] | None = None) -> dict:
    """`shipped`: the chunk texts the assistant would use. Without it, the Week 4 rule applies (the top-k
    chunks of the ranking whose score clears the floor)."""
    top_score = ranked.scores[0] if ranked.scores else None
    if shipped is None:
        shipped = [t for t, s in zip(ranked.texts[:top_k], ranked.scores[:top_k]) if s >= floor]
    if not case["answerable"]:
        return {"id": case["id"], "answerable": False, "top_score": top_score,
                "false_retrieval": len(shipped) > 0, "shipped_returned": len(shipped)}
    rank = first_rank(case, ranked)
    got = [norm(t) for t in shipped]
    out = {"id": case["id"], "answerable": True, "top_score": top_score, "first_rank": rank,
           "reciprocal_rank": 1 / rank if rank else 0.0, "shipped_returned": len(shipped),
           "shipped_hit": bool(shipped) and all(any(norm(e["quote"]) in t for t in got) for e in case["evidence"])}
    for k in KS:
        found = found_at(case, ranked, k)
        docs = set(ranked.documents[:k])
        out[f"recall@{k}"] = all(found)
        out[f"hit@{k}"] = any(found)
        out[f"doc_recall@{k}"] = {e["document"] for e in case["evidence"]} <= docs
    return out


def aggregate(rows: list[dict]) -> dict:
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    agg = {"questions": len(rows), "answerable": len(answerable), "unanswerable": len(unanswerable),
           "shipped_hits": sum(r["shipped_hit"] for r in answerable),
           "false_retrievals": sum(r["false_retrieval"] for r in unanswerable)}
    for k in KS:
        for m in ("recall", "hit", "doc_recall"):
            agg[f"{m}@{k}"] = sum(r[f"{m}@{k}"] for r in answerable) / len(answerable) if answerable else None
    agg["mrr"] = sum(r["reciprocal_rank"] for r in answerable) / len(answerable) if answerable else None
    agg["shipped_hit_rate"] = sum(r["shipped_hit"] for r in answerable) / len(answerable) if answerable else None
    agg["false_retrieval_rate"] = (sum(r["false_retrieval"] for r in unanswerable) / len(unanswerable)
                                   if unanswerable else None)
    return agg


# ---------------------------------------------------------------- running

def run_config(cases: list[dict], embedder: Embedder, cfg: RetrievalConfig, use_filters: bool = False) -> dict:
    """Score each case under one configuration. Must run inside the corpus-building transaction.
    `use_filters` applies a case's labelled area as the opt-in filter (as if the user picked it)."""
    out = {}
    for c in cases:
        cand = candidates(c["question"], embedder, area=c.get("area") if use_filters else None)
        ranked_ids = order(cand, cfg)
        ch = cand.chunks
        ranked = Ranked([ch[i].text for i in ranked_ids], [ch[i].document.filename for i in ranked_ids],
                        [float(cand.cosine[i]) for i in ranked_ids], [ch[i].passage_id for i in ranked_ids])
        shipped = [ch[i].text for i in returned(cand, cfg)]
        out[c["id"]] = (ranked, shipped)
    return out


def evaluate(embedder: Embedder, cases: list[dict] | None = None, label: str = "baseline",
             cfg: RetrievalConfig | None = None, use_filters: bool = False, method_note: str = "") -> dict:
    cases = cases if cases is not None else load_cases()
    if cfg is None:  # the Week 4 shipped retrieval, with the tuned floor and top-k
        tuned = load_tuned()
        cfg = RetrievalConfig(floor=tuned["floor"], top_k=tuned["top_k"], chunk_tokens=_chunk_tokens())
    with transaction.atomic():
        snapshot = build_corpus(embedder, cfg.chunk_tokens)
        scored = run_config(cases, embedder, cfg, use_filters)
        transaction.set_rollback(True)  # the built corpus never outlives the run
    rows = [score_case(c, scored[c["id"]][0], cfg.floor, cfg.top_k, shipped=scored[c["id"]][1]) | {
        "top_passages": scored[c["id"]][0].passage_ids[:5], "top_scores": [round(x, 3) for x in scored[c["id"]][0].scores[:5]]}
        for c in cases]
    by = lambda key: {v: aggregate([r for r, c in zip(rows, cases) if c[key] == v]) for v in sorted({c[key] for c in cases})}
    method = method_note or ("semantic only (Week 4 retrieval)" if cfg.method == "semantic" and not use_filters else
                             f"{cfg.method}, gate {cfg.gate}" + (" with the opt-in area filter" if use_filters else ""))
    return {"label": label, "method": method, "embedder": embedder.identity,
            "settings": cfg.as_dict() | {"filters": use_filters},
            "frozen_sha256": {k: frozen.WEEK5_FROZEN_SHA256[k] for k in ("eval/retrieval_cases.json",)},
            "corpus": snapshot, "overall": aggregate(rows), "by_category": by("category"), "by_author": by("author"),
            "cases": rows}


def _chunk_tokens() -> int:
    from .chunking import CHUNK_TOKENS
    return CHUNK_TOKENS


# ---------------------------------------------------------------- report

def pct(v) -> str:
    return "–" if v is None else f"{100 * v:.0f}%"


def count(k: int, n: int) -> str:
    """Counts first: with 5 unanswerable questions, one miss is 20 percentage points."""
    return "–" if not n else f"{k} of {n} ({100 * k / n:.0f}%)"


def build_report(result: dict, cases: list[dict]) -> str:
    o, s = result["overall"], result["settings"]
    by_id = {c["id"]: c for c in cases}
    rows = "\n".join(
        f"| {r['id']} | {by_id[r['id']]['category']} | {by_id[r['id']]['author']} | "
        + (f"{r['first_rank'] or '–'} | {'yes' if r['recall@3'] else 'no'} | {'yes' if r['shipped_hit'] else '**no**'} | "
           if r["answerable"] else f"– | – | {'**returned something**' if r['false_retrieval'] else 'nothing returned'} | ")
        + f"{r['top_score']:.3f} | {', '.join(r['top_passages'][:3])} |"
        for r in result["cases"])
    table = lambda groups: "\n".join(
        f"| {name} | {g['answerable']} + {g['unanswerable']} | {pct(g['recall@1'])} | {pct(g['recall@3'])} | {pct(g['recall@5'])} | "
        f"{'–' if g['mrr'] is None else f'{g['mrr']:.2f}'} | {count(g['shipped_hits'], g['answerable'])} | {count(g['false_retrievals'], g['unanswerable'])} |"
        for name, g in groups.items())
    return f"""# Retrieval evaluation ({result['label']}): {result['method']}

> Generated by `python manage.py evaluate_retrieval`; do not edit by hand. Embedder `{result['embedder']}`.
> Retrieval only: **no language model is called**. Frozen set SHA-256 `{result['frozen_sha256']['eval/retrieval_cases.json'][:16]}…`.

**{CAVEAT}**

The corpus (12 documents; cancellation is v2) is built inside a rolled-back transaction and checked against
the frozen manifest before any question runs. A hit means a retrieved chunk contains the **whole** evidence quote.
Chunk size {s['chunk_tokens']} tokens. "As shipped" uses floor {s['floor']:.2f} and top-k {s['top_k']}{f", RRF k {s['rrf_k']}, gate {s['gate']}" + (f" (keyword threshold {s['f_kw']:.1f})" if s['gate'] == 'S+K' else '') if s['method'] == 'hybrid' else ''}.

## Overall ({o['answerable']} answerable + {o['unanswerable']} unanswerable)

**Headline measure (chosen by the user on 2026-11-01, after seeing the baseline and before any Step 3 work):**
the as-shipped hit rate on answerable questions, with false retrieval on unanswerable questions as a
guardrail that must not rise. Secondary: Recall@1 and MRR. The guardrail rests on only {o['unanswerable']}
unanswerable questions, so one miss moves it by {100 // max(o['unanswerable'], 1)} percentage points; counts are shown, not only percentages.

| metric | value |
|---|---|
| Recall@1 / @3 / @5 (every evidence quote in the top K) | {pct(o['recall@1'])} / {pct(o['recall@3'])} / {pct(o['recall@5'])} (Recall@3 was already at the ceiling in the baseline) |
| Hit rate@1 / @3 / @5 (at least one quote in the top K) | {pct(o['hit@1'])} / {pct(o['hit@3'])} / {pct(o['hit@5'])} |
| Document recall@3 | {pct(o['doc_recall@3'])} |
| MRR | {'–' if o['mrr'] is None else f"{o['mrr']:.2f}"} |
| **Primary: as shipped, answerable questions whose evidence is returned** | **{count(o['shipped_hits'], o['answerable'])}** |
| **Guardrail: as shipped, unanswerable questions where something is returned** (must not rise) | **{count(o['false_retrievals'], o['unanswerable'])}** |

## By category

| category | answerable + unanswerable | R@1 | R@3 | R@5 | MRR | as shipped: hit | false retrieval |
|---|---|---|---|---|---|---|---|
{table(result['by_category'])}

## By author

The user's questions (paraphrase, area hint and unanswerable) and the assistant's are reported separately: the
assistant also builds the retrieval, so its questions are less independent.

| author | answerable + unanswerable | R@1 | R@3 | R@5 | MRR | as shipped: hit | false retrieval |
|---|---|---|---|---|---|---|---|
{table(result['by_author'])}

## Every question

| id | category | author | first rank | R@3 | as shipped | top score | top 3 passages |
|---|---|---|---|---|---|---|---|
{rows}

With 23 questions, one question is about 4–6 percentage points; small differences are noise.
"""


def save(result: dict, cases: list[dict]) -> tuple[Path, Path]:
    j, m = OUT / f"retrieval_{result['label']}.json", OUT / f"retrieval_{result['label']}.md"
    j.write_text(json.dumps(result, indent=1) + "\n")
    m.write_text(build_report(result, cases))
    return j, m


# ---------------------------------------------------------------- Step 3: before/after report

def _load(label: str) -> dict:
    return json.loads((OUT / f"retrieval_{label}.json").read_text())


def _line(name: str, r: dict) -> str:
    o, s = r["overall"], r["settings"]
    setting = (f"{s['method']}, chunk {s['chunk_tokens']}, floor {s['floor']:.2f}, top-k {s['top_k']}"
               + (f", RRF k {s['rrf_k']}, gate {s['gate']}" if s["method"] == "hybrid" else "")
               + (", area filter" if s.get("filters") else ""))
    return (f"| {name} | {setting} | **{count(o['shipped_hits'], o['answerable'])}** | {count(o['false_retrievals'], o['unanswerable'])} | "
            f"{pct(o['recall@1'])} | {o['mrr']:.2f} | {pct(o['recall@3'])} |")


def _dev_unanswerable_ids() -> set[str]:
    return {c["id"] for c in json.loads(frozen.RETRIEVAL_DEV.read_text())["cases"] if not c["answerable"]}


def compare_report(selection: dict) -> str:
    before, after = _load("baseline"), _load("after")
    head = "| run | setting | as shipped (primary) | false retrieval (guardrail) | R@1 | MRR | R@3 |\n|---|---|---|---|---|---|---|"
    cats = sorted(before["by_category"])
    cat_rows = "\n".join(
        f"| {c} | {count(before['by_category'][c]['shipped_hits'], before['by_category'][c]['answerable'])} | "
        f"{count(after['by_category'][c]['shipped_hits'], after['by_category'][c]['answerable'])} | "
        f"{count(before['by_category'][c]['false_retrievals'], before['by_category'][c]['unanswerable'])} | "
        f"{count(after['by_category'][c]['false_retrievals'], after['by_category'][c]['unanswerable'])} |" for c in cats)
    auth_rows = "\n".join(
        f"| {a} | {count(before['by_author'][a]['shipped_hits'], before['by_author'][a]['answerable'])} | "
        f"{count(after['by_author'][a]['shipped_hits'], after['by_author'][a]['answerable'])} |" for a in sorted(before["by_author"]))
    sizes = "\n".join(_line(f"chunk {n}", _load(f"after_chunk{n}") if n != 120 else after) for n in (40, 80, 120, 200))
    b_o, a_o = before["overall"], after["overall"]
    verdict = ("improved" if a_o["shipped_hits"] > b_o["shipped_hits"] else
               "did not improve" if a_o["shipped_hits"] == b_o["shipped_hits"] else "got worse")
    d = selection["decision"]
    false_ids = sorted(q for q, ids in selection["returned"]["champion"].items()
                       if ids and q in _dev_unanswerable_ids())
    champion_false = selection["champion_score"]["false"]
    methods = selection["best_by_method"]
    best_semantic = methods["semantic, gate S"]["best_hits"]
    best_hybrid = max(v["best_hits"] or 0 for k, v in methods.items() if k.startswith("hybrid"))
    blocked = [r["id"] for r, x in zip(before["cases"], after["cases"])
               if r["answerable"] and r["shipped_hit"] and not x["shipped_hit"]]
    return f"""# Retrieval before/after (Step 3)

> Generated by `python manage.py compare_retrieval`; do not edit by hand. Frozen Week 5 set (23 questions:
> {b_o['answerable']} answerable, {b_o['unanswerable']} unanswerable); embedder `{before['embedder']}`. No language model is called.

**{CAVEAT}**

**Headline measure (chosen by the user after seeing the baseline, before any Step 3 work):** as-shipped hit
rate on answerable questions, with false retrieval on the {b_o['unanswerable']} unanswerable questions as a guardrail
that must not rise (one miss = {100 // b_o['unanswerable']} points). Secondary: Recall@1 and MRR. Recall@3 was already at the ceiling.

## Result: the dev-chosen setting {verdict} on the primary measure

{head}
{_line("**before** (Week 4 retrieval)", before)}
{_line("**after** (dev winner)", after)}

"After" is the configuration the pre-declared rules picked on the dev set ({selection['configurations']} configurations;
{selection['tied_at_top']} tied at the top with {selection['best_hits']} of {selection['dev_answerable']} dev hits). It was run on the frozen
set once and is reported as it came out; nothing was re-tuned on these results (rule 5).

**Why:** on the dev set, Week 4's retrieval returned something for {champion_false} of the {selection['dev_unanswerable']} unanswerable
questions ({', '.join(false_ids) or 'none'}), so the rules required a configuration with no false retrievals on dev. The
dev winner's floor is {after['settings']['floor']:.2f} (Week 4: {before['settings']['floor']:.2f}); on the frozen set,
{len(blocked)} correct answer(s) found by "before" are not returned by "after" ({', '.join(blocked) or 'none'}). The real bottleneck is the abstention gate: correct-but-paraphrased
chunks and near-misses score in the same cosine range, and on the dev set the best hybrid configuration reached
{best_hybrid} of {selection['dev_answerable']} hits against {best_semantic} for semantic. The secondary measures moved slightly (Recall@1 +1
question, MRR {b_o['mrr']:.2f} → {a_o['mrr']:.2f}), from the larger chunk size.

**Shipping (champion/challenger, dev only): {'the challenger ships' if d['challenger_ships'] else 'the champion stays'}.** {d['reason'].capitalize()}.
Dev: challenger {selection['winner_score']['hits']} of {selection['dev_answerable']} hits, {selection['winner_score']['false']} of {selection['dev_unanswerable']} false;
champion {selection['champion_score']['hits']} of {selection['dev_answerable']} hits, {selection['champion_score']['false']} of {selection['dev_unanswerable']} false.
{'' if d['challenger_ships'] else 'Because no challenger ships, the safety gate (rule 7) did not run.'}

## By category (as shipped)

| category | before: hits | after: hits | before: false retrieval | after: false retrieval |
|---|---|---|---|---|
{cat_rows}

## By author (as shipped)

| author | before | after |
|---|---|---|
{auth_rows}

The user's questions (paraphrase, area hint, unanswerable) are harder for the shipped gate than the assistant's.

## Chunk-size comparison (frozen set, the winner's other settings; reporting only)

{head}
{sizes}

## Opt-in area filter (frozen set; applied only to the 3 cases with a labelled area; reporting only)

{head}
{_line("before", before)}
{_line("before + filter", _load("baseline_filtered"))}
{_line("after", after)}
{_line("after + filter", _load("after_filtered"))}

The filter narrows what is searched, but it cannot lift a correct chunk over the floor, so it changes nothing
as shipped here.
"""
