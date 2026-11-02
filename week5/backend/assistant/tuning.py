"""Week 4 Step 11: set the similarity floor, top-k and groundedness threshold on the DEVELOPMENT questions only.

Run (needs the local model and the policies loaded):  python manage.py tune_assistant
Writes assistant/dev/dev_tuning.json (every run, every score, the chosen values) and assistant/dev/dev_tuning.md.
The frozen evaluation cases are never read here (tests/test_eval_freeze.py enforces it).

Rules, approved and written before running:
  - Floor: the lowest top retrieval score among the ANSWERABLE dev questions, minus FLOOR_MARGIN, rounded
    down to 0.01. No answerable dev question is blocked; the floor only removes clear misses, and near-miss
    questions are left to the citation and groundedness checks. The medical dev question is refused before
    retrieval, so it plays no part.
  - top-k: TOP_K_OPTIONS are tried. Each dev question runs RUNS_PER_K times per k, with fixed seeds
    SEED, SEED+1, SEED+2 (temperature 0.1), and counts as correct for that k only if at least
    MAJORITY runs are correct. The most correct questions wins; on a tie, the smaller k.
  - Groundedness threshold: server checks run with threshold 0 during tuning, so every reply's groundedness
    is recorded. At the chosen k: the lowest groundedness among CORRECT dev answers, minus
    GROUNDEDNESS_MARGIN, never below GROUNDEDNESS_MIN. If there are no correct dev answers the provisional
    value stays and the report says tuning failed. The report also counts how many INCORRECT dev answers
    the chosen value blocks, and says plainly if it blocks none.
A run is correct when the server-decided status matches, and for answerable questions the answer cites the
expected policy and contains the expected facts.

The dev set is small (11 questions), so these values are uncertain; the report says so.
"""

import json
import math
import re
from pathlib import Path

from django.conf import settings

from . import verify
from .embeddings import Embedder
from .indexing import search
from .llm import LLMClient, LLMError
from .prompts import build_prompt
from .schema import ANSWER_SCHEMA, InvalidAnswer, parse_reply

DEV_DIR = Path(__file__).resolve().parent / "dev"
DEV_QUESTIONS = DEV_DIR / "dev_questions.json"
RESULT = DEV_DIR / "dev_tuning.json"
REPORT = DEV_DIR / "dev_tuning.md"

FLOOR_MARGIN = 0.02
TOP_K_OPTIONS = (2, 3, 4)
RUNS_PER_K = 3
MAJORITY = 2
GROUNDEDNESS_MARGIN = 0.05
GROUNDEDNESS_MIN = 0.3


def load_dev() -> list[dict]:
    return json.loads(DEV_QUESTIONS.read_text())["questions"]


# ---------------------------------------------------------------- the rules (pure; re-checked by tests)

def choose_floor(top_scores: dict[str, float], dev: list[dict]) -> float:
    answerable = [top_scores[q["id"]] for q in dev if q["expected_status"] == "answered"]
    return math.floor((min(answerable) - FLOOR_MARGIN) * 100) / 100


def run_is_correct(q: dict, run: dict) -> bool:
    if run["status"] != q["expected_status"]:
        return False
    if run["status"] != "answered":
        return True
    sources = {c["passage_id"].split("#")[0] for c in run["citations"]}
    answer = run["answer"].lower()
    return (q["expected_source"] in sources and all(f.lower() in answer for f in q.get("must_contain", []))
            and (not q.get("must_contain_any")
                 or any(re.search(rf"\b{re.escape(f.lower())}\b", answer) for f in q["must_contain_any"])))


def question_is_correct(q: dict, runs: list[dict]) -> bool:
    return sum(run_is_correct(q, r) for r in runs) >= MAJORITY


def choose_top_k(correct_counts: dict[int, int]) -> int:
    best = max(correct_counts.values())
    return min(k for k, n in correct_counts.items() if n == best)


def choose_threshold(correct_groundedness: list[float]) -> float | None:
    """None means no correct dev answer: tuning failed and the provisional value stays."""
    if not correct_groundedness:
        return None
    return max(GROUNDEDNESS_MIN, math.floor((min(correct_groundedness) - GROUNDEDNESS_MARGIN) * 100) / 100)


def groundedness_split(dev: list[dict], runs: dict) -> tuple[list[float], list[float]]:
    """Groundedness of replies that passed every check except the threshold, split into correct and incorrect."""
    correct, incorrect = [], []
    for q in dev:
        for r in runs[q["id"]]:
            if r["status"] == "answered" and r.get("groundedness") is not None:
                (correct if run_is_correct(q, r) else incorrect).append(r["groundedness"])
    return correct, incorrect


def decide(result: dict, dev: list[dict]) -> dict:
    """Apply the rules to recorded runs. Used by tune() and, without a model, by the tests."""
    floor = choose_floor(result["top_scores"], dev)
    correct_by_k = {int(k): sum(question_is_correct(q, runs[q["id"]]) for q in dev) for k, runs in result["runs"].items()}
    top_k = choose_top_k(correct_by_k)
    good, bad = groundedness_split(dev, result["runs"][str(top_k)])  # run keys are strings (as saved in JSON)
    threshold = choose_threshold(good)
    effective = verify.GROUNDEDNESS_THRESHOLD if threshold is None else threshold
    chosen_runs = result["runs"][str(top_k)]
    polarity_blocked = [(q["id"], run_is_correct(q, r["without_polarity"])) for q in dev for r in chosen_runs[q["id"]]
                        if r.get("polarity_blocked")]
    return {"floor": floor, "correct_by_top_k": correct_by_k, "top_k": top_k, "groundedness_threshold": threshold,
            "polarity_blocked_runs": len(polarity_blocked),
            "polarity_blocked_correct": [qid for qid, was_correct in polarity_blocked if was_correct],
            "short_answer_runs": sum(r["reason"] == "answer too short to verify" for q in dev for r in chosen_runs[q["id"]]),
            "effective_groundedness_threshold": effective, "groundedness_correct": good, "groundedness_incorrect": bad,
            "incorrect_blocked": sum(g < effective for g in bad)}


# ---------------------------------------------------------------- running against the model

def run_once(q: dict, llm: LLMClient, embedder: Embedder, top_k: int, floor: float, seed: int) -> dict:
    cfg = settings.ASSISTANT
    if verify.is_medical_advice_request(q["question"]):
        return {"status": "refused", "reason": "server medical-advice check", "citations": [], "answer": "", "raw": None}
    found = search(q["question"], embedder, top_k=top_k, floor=floor)
    if not found.passages:
        return {"status": "insufficient_information", "reason": "below floor", "citations": [], "answer": "", "raw": None}
    prompt = build_prompt(q["question"], found.passages, cfg["CONTEXT_TOKENS"], cfg["MAX_OUTPUT_TOKENS"])
    try:
        raw = llm.chat(prompt.messages, ANSWER_SCHEMA, seed=seed).text
        reply = parse_reply(raw)
    except (LLMError, InvalidAnswer) as exc:
        return {"status": "invalid_output", "reason": exc.__class__.__name__, "citations": [], "answer": "", "raw": None}
    given = [p for p in found.passages if p.id in prompt.included]
    verdict = verify.decide(q["question"], reply, given, threshold=0.0)
    without_polarity = verify.decide(q["question"], reply, given, threshold=0.0, check_polarity=False)
    blocked_by_polarity = verdict.reason == "polarity mismatch"
    return {"status": verdict.status, "reason": verdict.reason, "citations": verdict.verified,
            "answer": reply.answer if verdict.status == "answered" else "", "groundedness": verdict.groundedness,
            "rejected_citations": verdict.rejected_citations, "raw": raw,
            # What the polarity check changed: the run as it would have been without it.
            "polarity_blocked": blocked_by_polarity,
            "without_polarity": {"status": without_polarity.status, "citations": without_polarity.verified,
                                 "answer": reply.answer if without_polarity.status == "answered" else ""}}


def tune(llm: LLMClient, embedder: Embedder) -> dict:
    from . import frozen
    from .documents import check_corpus
    corpus = check_corpus(frozen.WEEK4_CORPUS)  # the dev set was written against the same six policies
    dev = load_dev()
    base_seed = settings.ASSISTANT["SEED"]
    seeds = [base_seed + i for i in range(RUNS_PER_K)]
    top_scores = {q["id"]: (search(q["question"], embedder, top_k=1, floor=-1.0).scores or [-1.0])[0] for q in dev}
    floor = choose_floor(top_scores, dev)
    runs = {str(k): {q["id"]: [run_once(q, llm, embedder, k, floor, s) for s in seeds] for q in dev} for k in TOP_K_OPTIONS}
    recorded = {"model": llm.model, "embedder": embedder.identity, "temperature": settings.ASSISTANT["TEMPERATURE"],
                "seeds": seeds, "dev_questions": len(dev), "corpus": corpus, "top_scores": top_scores, "runs": runs}
    return recorded | {"chosen": decide(recorded, dev)}


# ---------------------------------------------------------------- report

def build_report(result: dict, dev: list[dict]) -> str:
    c = result["chosen"]
    answerable = [result["top_scores"][q["id"]] for q in dev if q["expected_status"] == "answered"]
    uncovered = [result["top_scores"][q["id"]] for q in dev if q["expected_status"] == "insufficient_information"]
    gap = min(answerable) - max(uncovered)
    runs = result["runs"][str(c["top_k"])]
    rows = "\n".join(
        f"| {q['id']} | {q['expected_status']} | {result['top_scores'][q['id']]:.3f} | "
        f"{', '.join(r['status'] for r in runs[q['id']])} | {'yes' if question_is_correct(q, runs[q['id']]) else '**no**'} |"
        for q in dev)
    by_k = ", ".join(f"k={k}: {n} of {result['dev_questions']}" for k, n in c["correct_by_top_k"].items())
    polarity_line = ("**it blocked no correct dev answer.**" if not c["polarity_blocked_correct"] else
                     f"**it blocked correct answers to {', '.join(sorted(set(c['polarity_blocked_correct'])))}** "
                     f"({len(c['polarity_blocked_correct'])} runs), which would otherwise have passed.")
    if c["groundedness_threshold"] is None:
        threshold_line = (f"**Tuning failed for the threshold: no correct dev answer.** The provisional "
                          f"{c['effective_groundedness_threshold']:.2f} stays.")
    else:
        threshold_line = (f"lowest groundedness of a correct dev answer ({min(c['groundedness_correct']):.2f}) minus "
                          f"{GROUNDEDNESS_MARGIN}, never below {GROUNDEDNESS_MIN}")
    if not c["groundedness_incorrect"]:
        blocked = ("No incorrect dev answer passed the citation checks, so the threshold had nothing to block on the "
                   "dev set: **it blocks none of the incorrect dev answers**, and its value rests only on keeping "
                   "correct answers.")
    elif c["incorrect_blocked"] == 0:
        blocked = (f"**It blocks none of the {len(c['groundedness_incorrect'])} incorrect dev answers** that passed the "
                   f"citation checks; those were stopped, if at all, by other checks.")
    else:
        blocked = (f"It blocks {c['incorrect_blocked']} of the {len(c['groundedness_incorrect'])} incorrect dev answers "
                   f"that passed the citation checks.")
    return f"""# Assistant tuning on the development questions

> Generated by `python manage.py tune_assistant`; do not edit by hand. Development questions only; the frozen
> evaluation cases were never read. Model `{result['model']}`, temperature {result['temperature']}, seeds
> {', '.join(map(str, result['seeds']))} (one per run; repeatable on the same machine), embedder `{result['embedder']}`.

| setting | value | rule |
|---|---|---|
| similarity floor | **{c['floor']:.2f}** | lowest top score of an answerable dev question ({min(answerable):.3f}) minus {FLOOR_MARGIN}, rounded down |
| top-k | **{c['top_k']}** | most dev questions correct in at least {MAJORITY} of {RUNS_PER_K} runs ({by_k}); ties go to the smaller k |
| groundedness threshold | **{c['effective_groundedness_threshold']:.2f}** | {threshold_line} |

Groundedness threshold and incorrect answers: {blocked}

Polarity check (negation in the answer but not its quotes, or the reverse): it changed {c['polarity_blocked_runs']} of the
{RUNS_PER_K * result['dev_questions']} runs at the chosen top-k; {polarity_line}
Answers too short to verify (fewer than {verify.MIN_KEY_TERMS} key terms): {c['short_answer_runs']} runs.

**Limitation: these checks compare words, not meaning, so they can't fully verify an answer. A negation flip can
still get through in other forms (an antonym, "only after" versus "before", a negation word the list doesn't
cover).** The evaluation's failure analysis looks for these.

Dev data correction (2026-11-01, after the first run): D12 required the word "never", but "No, reminders don't
include test results" is also correct; it now accepts no / never / not.

Top retrieval scores: answerable dev questions {min(answerable):.3f}–{max(answerable):.3f}; questions no policy covers
{min(uncovered):.3f}–{max(uncovered):.3f} (gap {gap:.3f}).

**Note that the floor is set from a small dev set (11 questions, ~{gap:.2f} gap), so it's uncertain; the citation and
groundedness checks remain the main defence for near-miss questions.**

Outcomes at the chosen top-k ({RUNS_PER_K} runs per question):

| dev question | expected | top score | statuses of the {RUNS_PER_K} runs | correct (majority) |
|---|---|---|---|---|
{rows}
"""


def save(result: dict) -> None:
    RESULT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    REPORT.write_text(build_report(json.loads(RESULT.read_text()), load_dev()))


def load_tuned() -> dict:
    """The chosen values, for the question endpoint."""
    chosen = json.loads(RESULT.read_text())["chosen"]
    return {"floor": chosen["floor"], "top_k": chosen["top_k"],
            "groundedness_threshold": chosen["effective_groundedness_threshold"]}
