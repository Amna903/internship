"""Choosing the retrieval setting on the DEV set only (Week 5 Step 3), by rules written down before any run
(docs/REQUIREMENTS.md, "Step 3 rules").

For each chunk size, the frozen corpus is built in a rolled-back transaction and every dev question is scored
once (cosine and normalised BM25 for every chunk); then every configuration in the grid is evaluated from
those scores without touching the model or the database again.

- Eligible: 0 false retrievals on the unanswerable dev questions.
- Winner: the most as-shipped hits on the answerable dev questions; ties broken in the fixed order
  semantic → gate S → higher floor → smaller top-k → chunk size closest to 80 (40 vs 120: the larger) →
  larger RRF k → higher f_kw.
- Champion/challenger: the winner (challenger) ships only if it has MORE dev hits than Week 4's retrieval
  (champion) and no more dev false retrievals; a tie keeps the champion. A shipping challenger must still
  pass the safety gate (assistant/safety_gate.py).

This module reads only the dev file; the evaluation file is never seen here.
"""

import json
from dataclasses import replace
from pathlib import Path

from django.db import transaction

from . import frozen
from .embeddings import Embedder
from .indexing import GATE_S, GATE_SK, HYBRID, SEMANTIC, Candidates, RetrievalConfig, candidates, returned
from .retrieval_eval import build_corpus, norm

CHUNK_SIZES = (40, 80, 120, 200)
RRF_KS = (10, 30, 60)
TOP_KS = (2, 3, 4)
FLOORS = tuple(round(0.50 + 0.02 * i, 2) for i in range(16))  # 0.50 … 0.80
F_KWS = tuple(round(0.3 + 0.1 * i, 1) for i in range(7))     # 0.3 … 0.9
CHAMPION = RetrievalConfig()  # Week 4: semantic, floor 0.70, top-k 2, chunk size 80
OUT = Path(__file__).resolve().parent / "dev"


def load_dev() -> list[dict]:
    return json.loads(frozen.RETRIEVAL_DEV.read_text())["cases"]


def grid() -> list[RetrievalConfig]:
    configs = []
    for size in CHUNK_SIZES:
        for top_k in TOP_KS:
            for floor in FLOORS:
                configs.append(RetrievalConfig(SEMANTIC, floor, top_k, chunk_tokens=size))
                for k in RRF_KS:
                    configs.append(RetrievalConfig(HYBRID, floor, top_k, k, GATE_S, chunk_tokens=size))
                    configs += [RetrievalConfig(HYBRID, floor, top_k, k, GATE_SK, f, chunk_tokens=size) for f in F_KWS]
    return configs


def tie_key(cfg: RetrievalConfig):
    """Smaller is preferred: the fixed tie order from the rules."""
    return (cfg.method != SEMANTIC, cfg.gate != GATE_S, -cfg.floor, cfg.top_k, abs(cfg.chunk_tokens - 80),
            -cfg.chunk_tokens,  # 40 and 120 are equally close to 80: the larger wins (user decision, before any run)
            -cfg.rrf_k if cfg.method == HYBRID else 0, -cfg.f_kw if cfg.gate == GATE_SK else 0)


def score(cfg: RetrievalConfig, dev: list[dict], cands: dict[int, dict[str, Candidates]]) -> dict:
    hits = false = 0
    for case in dev:
        c = cands[cfg.chunk_tokens][case["id"]]
        texts = [norm(c.chunks[i].text) for i in returned(c, cfg)]
        if case["answerable"]:
            hits += bool(texts) and all(any(norm(e["quote"]) in t for t in texts) for e in case["evidence"])
        else:
            false += bool(texts)
    return {"hits": hits, "false": false}


def score_all(configs, dev, cands) -> list[tuple[RetrievalConfig, dict]]:
    return [(cfg, score(cfg, dev, cands)) for cfg in configs]


def choose(scored: list[tuple[RetrievalConfig, dict]]) -> dict:
    eligible = [(c, s) for c, s in scored if s["false"] == 0]
    if not eligible:
        return {"winner": None, "eligible": 0, "tied_at_top": 0, "best_hits": None}
    best = max(s["hits"] for _, s in eligible)
    top = sorted((c for c, s in eligible if s["hits"] == best), key=tie_key)
    return {"winner": top[0], "eligible": len(eligible), "tied_at_top": len(top), "best_hits": best}


def ship_decision(winner: RetrievalConfig | None, winner_score: dict | None, champion_score: dict) -> dict:
    if winner is None:
        return {"challenger_ships": False, "reason": "no eligible configuration"}
    if winner == CHAMPION:
        return {"challenger_ships": False, "reason": "the dev winner is the champion itself"}
    if winner_score["hits"] > champion_score["hits"] and winner_score["false"] <= champion_score["false"]:
        return {"challenger_ships": True, "reason": "more dev hits than the champion, no more dev false retrievals "
                                                     "(subject to the safety gate)"}
    return {"challenger_ships": False, "reason": "it does not beat the champion on dev (a tie keeps the champion)"}


def collect(embedder: Embedder, dev: list[dict]) -> tuple[dict[int, dict[str, Candidates]], list[dict]]:
    cands, snapshot = {}, []
    for size in CHUNK_SIZES:
        with transaction.atomic():
            snapshot = build_corpus(embedder, size)
            cands[size] = {c["id"]: candidates(c["question"], embedder) for c in dev}
            transaction.set_rollback(True)
    return cands, snapshot


def select(embedder: Embedder) -> dict:
    dev = load_dev()
    cands, snapshot = collect(embedder, dev)
    configs = grid()
    scored = score_all(configs, dev, cands)
    chosen = choose(scored)
    lookup = {c: s for c, s in scored}
    champion_score = lookup[CHAMPION]
    winner = chosen["winner"]
    decision = ship_decision(winner, lookup.get(winner), champion_score)
    per_question = {}
    for name, cfg in (("champion", CHAMPION), ("winner", winner)):
        if cfg is None:
            continue
        per_question[name] = {case["id"]: [cands[cfg.chunk_tokens][case["id"]].chunks[i].passage_id
                                           for i in returned(cands[cfg.chunk_tokens][case["id"]], cfg)] for case in dev}
    best_by_method = {}
    for m, g in ((SEMANTIC, GATE_S), (HYBRID, GATE_S), (HYBRID, GATE_SK)):
        sub = choose([(c, s) for c, s in scored if c.method == m and c.gate == g])
        best_by_method[f"{m}, gate {g}"] = {"best_hits": sub["best_hits"], "tied_at_top": sub["tied_at_top"],
                                            "winner": sub["winner"].as_dict() if sub["winner"] else None}
    best_by_size = {size: choose([(c, s) for c, s in scored if c.chunk_tokens == size])["best_hits"] for size in CHUNK_SIZES}
    return {"embedder": embedder.identity, "dev_questions": len(dev),
            "dev_answerable": sum(c["answerable"] for c in dev), "dev_unanswerable": sum(not c["answerable"] for c in dev),
            "dev_sha256": frozen.WEEK5_FROZEN_SHA256["dev/retrieval_dev.json"], "corpus": snapshot,
            "configurations": len(configs), "eligible": chosen["eligible"], "tied_at_top": chosen["tied_at_top"],
            "best_hits": chosen["best_hits"], "winner": winner.as_dict() if winner else None,
            "winner_score": lookup.get(winner), "champion": CHAMPION.as_dict(), "champion_score": champion_score,
            "decision": decision, "best_by_method": best_by_method, "best_by_chunk_size": best_by_size,
            "returned": per_question}


def build_report(r: dict) -> str:
    w, c = r["winner"], r["champion"]
    fmt = lambda cfg: ("–" if cfg is None else f"{cfg['method']}, chunk {cfg['chunk_tokens']}, floor {cfg['floor']:.2f}, "
                       f"top-k {cfg['top_k']}" + (f", RRF k {cfg['rrf_k']}, gate {cfg['gate']}" if cfg['method'] == 'hybrid' else "")
                       + (f", f_kw {cfg['f_kw']:.1f}" if cfg['gate'] == 'S+K' else ""))
    a, u = r["dev_answerable"], r["dev_unanswerable"]
    methods = "\n".join(f"| {name} | {v['best_hits']} of {a} | {v['tied_at_top']} | {fmt(v['winner'])} |"
                        for name, v in r["best_by_method"].items())
    sizes = "\n".join(f"| {size} | {hits} of {a} |" for size, hits in r["best_by_chunk_size"].items())
    rows = "\n".join(f"| {q} | {', '.join(r['returned']['champion'][q]) or '–'} | {', '.join(r['returned'].get('winner', {}).get(q, [])) or '–'} |"
                     for q in r["returned"]["champion"])
    return f"""# Retrieval selection on the dev set (Step 3)

> Generated by `python manage.py select_retrieval`; do not edit by hand. Dev set only ({r['dev_questions']} questions:
> {a} answerable, {u} unanswerable); the frozen evaluation set is never read here. Rules written before any run
> (docs/REQUIREMENTS.md, "Step 3 rules").

**{r['configurations']} configurations** were tried; **{r['eligible']}** had 0 false retrievals on dev; the best had
**{r['best_hits']} of {a}** dev hits, and **{r['tied_at_top']} configurations tied at that score**, so the fixed tie order
decided. With {r['dev_questions']} dev questions and this many configurations, the winner is partly luck; the frozen
evaluation set is the honest check.

| | setting | dev hits | dev false retrievals |
|---|---|---|---|
| **Winner (challenger)** | {fmt(w)} | {r['winner_score']['hits'] if w else '–'} of {a} | {r['winner_score']['false'] if w else '–'} of {u} |
| Champion (Week 4) | {fmt(c)} | {r['champion_score']['hits']} of {a} | {r['champion_score']['false']} of {u} |

**Ship decision (champion/challenger, dev only): {'the challenger ships, subject to the safety gate' if r['decision']['challenger_ships'] else 'the champion stays'}**: {r['decision']['reason']}.

## Best per method (0 dev false retrievals)

| method | best dev hits | configurations tied | first in tie order |
|---|---|---|---|
{methods}

## Best per chunk size (any method)

| chunk size | best dev hits |
|---|---|
{sizes}

## What each one returns on the dev set

| dev question | champion | winner |
|---|---|---|
{rows}
"""


def save(r: dict) -> Path:
    (OUT / "retrieval_selection.json").write_text(json.dumps(r, indent=1, default=str) + "\n")
    path = OUT / "retrieval_selection.md"
    path.write_text(build_report(r))
    return path


def config_from(d: dict) -> RetrievalConfig:
    return replace(RetrievalConfig(), **d)
