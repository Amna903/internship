# Week 5 requirement → evidence checklist

Source: **"WEEK 5 | Advanced RAG, LLM Agents and ML Automation"** in *Elevate Engine Weeks 4–6*. Each row is one line of that brief, worded as in the brief. Lines with several parts are split into one row per part, so none can be ticked half-done.

The Week 4 checklist is kept, finished, in [REQUIREMENTS-week4.md](REQUIREMENTS-week4.md).

Fill in each row as the work is done:
- **Code:** where it's implemented.
- **Test:** the automated test that proves it, or "manual" plus what you checked.
- **Demo:** the Loom timestamp.
- **Me:** the date you re-ran the check yourself. Leave it blank until you have.

Status: ☐ not started · ◐ in progress · ☑ done and evidenced.

## Decisions for Week 5 (Step 0, approved by the user on 2026-11-01)

- **Git:** a `week5/` folder copied from `week4/`, on a `week5` branch made from `week4`. The PR **targets `week4` for now**, so the reviewer sees only Week 5's changes. Its base switches to `main` after Week 4's PR #1 is merged. Mentor changes on PR #1 are made on `week4` first, then carried into `week5`.
- **Background jobs: Celery + Redis.** Eager mode is used only in unit tests. At least one test or acceptance check uses a real worker process and Redis, so retries and job states are tested for real. Redis runs as a CI service, and local setup is `brew install redis`. Chosen for Week 6's containerised worker.
- **Agent: our own small state machine** (plan → tool selection → validation → execution → response). The model only proposes a tool and its arguments; the server validates and authorises every call.
- **Retrieval:** BM25 keyword search in Python, the same on SQLite and PostgreSQL, combined with semantic search. Reranking uses reciprocal rank fusion, documented as the brief's "alternative". Documents get a `DocumentVersion` history, and only the current version is searchable.
- **MCP:** a real MCP server built with the official Python SDK, calling the same authorised tool layer as the agent.
- **Drift:** the population stability index (PSI) on the prediction distribution, plus latency and failure rates, compared with a baseline.
- **Evaluation sets:** the user writes some of the ≥20 retrieval questions and some of the agent red-team cases. The structure is drafted first, the user adds theirs, and then the set is frozen before any tuning. A separate dev set is used for choices.
- **Week 4 rules carry over:** frozen evaluation sets; tuning on a dev set only; champion/challenger for releases; the fresh holdout stays unopened; no rule changes after seeing results without telling the user.
- **Week 6 watch points:** a containerised worker; a reusable 20-question RAG benchmark; at least 10 agent safety and workflow tests.

## Decisions carried over from Week 4

Code comments in `ml/` and `assistant/` point here. Kept word for word from [REQUIREMENTS-week4.md](REQUIREMENTS-week4.md):

- **Supervised task:** the same synthetic appointment no-show task as Week 3, extended rather than replaced. The brief says "expand the Week 3 ML system".
- **LLM:** local only, through **Ollama**. No data leaves the machine, so the rule against sending patient data to external LLMs holds by design. Tests and CI use a **fake LLM** behind the same interface.
- **Git:** all Week 4 work goes on the `week4` branch → a PR to `main` → reviewer **@ahmedhashir10**.
- **Model choice is by cross-validation (from Step 3 on).** See the lesson below. The rule is now fixed: no further rule changes.
- **Served model: still v1.0.0 (engineered logistic regression, C=0.1). Week 4 made no new release** (Step 4 decision, see Lessons). Its report (`release-1.0.0.md`) and files are rebuilt from Week 3's candidates and checked byte-for-byte; the dashboard's "About this model" panel names it, and a test pins that.
- **Clustering: real data plus a positive control** (user decision, Step 6). The main synthetic data has no patient habits (every engagement column is drawn independently per appointment), so Step 7 reports "no structure found" on it, compared with a shuffled baseline. A separate small control generator with 3–4 planted engagement habits (own module and seed, never touching `data.py`) tests whether the methods recover planted groups (adjusted Rand index). The dashboard's PCA plot and cluster descriptions use the control data, clearly labelled as such.
- **Test results so far are exploratory evidence** (mentor review on PR #1). Week 4's experimental selection never read the test set, but the release decision did, and the set had already been scored in Week 3. `metrics.md` §4 states both.
- **Fresh holdout reserved for the next final evaluation:** `backend/ml/holdout.py`, seed 20261101 (not 42), 2,000 patients, IDs offset by 10,000,000 so they cannot collide, fingerprint pinned. Never used for exploration, tuning, model choice or release selection; only that module may load it. Guarded by `tests/test_holdout.py`.
- **Champion/challenger rule: FROZEN on 2026-11-01** in `backend/ml/release_rule.py` (behaviour pinned by `tests/test_release_rule.py`). Changing it needs a new, dated decision recorded here before the evaluation it applies to. The rule:
  1. The served model is the champion. A challenger replaces it only if, on the same training folds, its mean CV PR-AUC beats the champion's by **more than one standard error** of the champion's mean.
  2. The simplicity preference applies **between model families with different explainability** (logistic regression before trees). Between equally explainable models (two logistic regressions), it doesn't apply: the higher CV mean wins.
  3. The challenger is decided on CV before the test set is scored. The test score is reported, not used to choose; if it ever argues against a CV decision, that is recorded as a finding, as in Step 4.
  4. Release numbering stays Week 3's: same inputs, retrained → minor version; inputs change → major version.

## Lessons carried over from Week 4


- **Step 2: the simplicity order ranked model families only, and CI exposed why that matters.** Two forests 0.0002 apart in validation PR-AUC swapped places between Mac (arm64) and Linux CI (x86): trees amplify last-digit floating-point differences into different splits, moving forest scores by about 0.001. So the chosen model depended on the machine. Fix: a within-family order (shallower trees, then larger leaves; on a remaining tie **more** trees, since tree count only steadies the vote and doesn't cause overfitting). The depth-6, leaf-50 forest now wins on both machines. This rule was written after seeing results, for the stability reason, and it changed the winner from the unlimited-depth forest (0.284) to depth 6 (0.281), within the tie margin. `metrics.md` is now checked for identical text and choice with numbers within 0.002; the release reports stay byte-exact.
- **Step 2: a multi-threaded random forest is not exactly reproducible.** Threads add the trees' outputs in varying order, changing the last digits, enough to flip a near-tie. Forests now run single-threaded; a test trains one twice and requires identical output.

## Decisions added during Week 5

- **Step 1 (2026-11-01), user additions:**
  - **Citations name their edition.** Version 1 keeps Week 4's passage IDs (`billing.md#0`), so the frozen Week 4 set still matches. Later versions use `billing.md@v2#0`. Every citation in the API carries `document_id` and `version`, and each answer gets an `AnswerRecord` (linked to its audit event) listing the editions it cited and was given. It never stores the question or answer text.
  - **Evaluation runs record a corpus snapshot and fail loudly.** `evaluate_assistant` and `tune_assistant` check that the searchable documents are exactly the corpus their set was frozen against (`frozen.WEEK4_CORPUS`: the six policies as v1). They stop with an error before any case runs if not, and the results record the snapshot. The Week 5 sets will declare their own corpus the same way.
- **Step 1 implementation choices:**
  - `policy_area` is optional on upload (default `other`), so Week 4's `/v1` upload contract still works. Adding a required field would break existing callers.
  - Version 1 audit details keep Week 4's form (`document:12`); later versions add `:v2`.
  - Area filtering in Step 3 will join through the document instead of copying the area onto every chunk, so copies can't drift.

- **Step 2 (2026-11-01), approved:**
  - **Corpus B:** a frozen Week 5 corpus made of the 6 Week 4 policies, 6 new fictional admin policies, and a v2 of the cancellation policy. The evaluation builds it inside a rolled-back transaction, so the live database and the Week 4 corpus check are unaffected.
  - **Labels are evidence quotes, not passage IDs,** so every chunk size can be scored.
  - **Hit rule (user addition 1):** each evidence quote is **one sentence or part of one sentence**, and a hit means a retrieved chunk contains the **whole quote** (after normalising case and whitespace). The chunker splits only between sentences, so a one-sentence quote is always whole inside some chunk at any chunk size. A test checks this for every chunk size Step 3 compares. Chosen over an "80% of the words" rule because it is stricter and needs no threshold.
  - **Corpus frozen before any Step 3 design work (user addition 2).** The reports will state: *"The corpus was deliberately built to be harder by the same author who builds the retrieval, so the size of any improvement may not transfer to other document sets."*
  - **Frozen on 2026-11-01** (`frozen.WEEK5_FROZEN_SHA256`): the 7 new corpus files, the 23-question evaluation set (11 by the user) and the 15-question dev set. Before freezing, the v2 date was moved to the past (1 October 2026) so v2 is clearly in force (user). A second v2 change ("by email to the front desk") was added so the dev set can have a v2 question that shares no evidence sentence with the evaluation set (user decision). A test enforces that no dev question shares an evidence sentence with an evaluation question.
  - **Authors:** the user writes about 10 evaluation questions (paraphrase, unanswerable, area_hint) after reading the drafted corpus; the assistant writes the rest. The dev set is separate and written by the assistant.

- **Step 3 headline measure (user decision, 2026-11-01). Chosen after seeing the Step 2 baseline and before any Step 3 work:**
  - **Primary:** the as-shipped hit rate on answerable questions (baseline **11 of 18**).
  - **Guardrail:** false retrieval on unanswerable questions must not rise (baseline **0 of 5**). It rests on only 5 questions (one miss = 20 points), so reports show counts, not only percentages.
  - **Secondary:** Recall@1 (83%) and MRR (0.97). Recall@3 is still reported, noting it was already at the ceiling (100%).
  - **Floor and top-k for each method are chosen on the dev set only,** with the rules written before Step 3 runs.
  - **By-author results stay in the report:** the user's questions scored 3 of 8 as shipped, against 8 of 10 for the assistant's, with the same 100% Recall@3.

- **Step 3 rules (approved by the user on 2026-11-02, written down and committed before any Step 3 code or run):**
  1. **Building blocks:**
     - BM25 in Python (k1 = 1.2, b = 0.75; lowercase word tokens with numbers kept; a small stop-word list) over the same chunks semantic search sees;
     - hybrid = reciprocal rank fusion, `1/(k + semantic rank) + 1/(k + BM25 rank)`;
     - opt-in metadata filters (`area`, `document`), never guessed from the question;
     - chunk sizes 40, 80, 120 and 200.
  2. **Gates:**
     - **S:** cosine similarity ≥ floor;
     - **S+K:** cosine ≥ floor, **or** normalised BM25 ≥ f_kw. Normalised BM25 is the chunk's BM25 score divided by the query's maximum possible score (the sum over its terms of idf × (k1 + 1)), so a query full of words the corpus never uses can't clear it.
  3. **Grid (shrunk to limit overfitting on 15 dev questions):**

     | Factor | Values |
     |---|---|
     | Method | semantic, or hybrid |
     | Chunk size | 40, 80, 120, 200 |
     | RRF k | 10, 30, 60 (hybrid only) |
     | Gate | S, or S+K (hybrid only) |
     | Top-k | 2, 3, 4 |
     | Floor | 0.50–0.80 in steps of 0.02 |
     | f_kw | 0.3–0.9 in steps of 0.1 |

     The report states the total number of configurations and how many tied at the top on dev.
  4. **Selection, on the dev set only:**
     - eligible = 0 false retrievals on the 3 unanswerable dev questions;
     - pick the most as-shipped hits on the 12 answerable dev questions;
     - ties are broken in order: semantic before hybrid → gate S before S+K → higher floor → smaller top-k → chunk size closest to 80 → larger RRF k → higher f_kw.
     - **Gap found by a test before any run (2026-11-02):** 40 and 120 are equally close to 80. The user decided **the larger chunk size wins** that tie. A test now checks that the tie order separates every configuration in the grid.
  5. **"After" = the dev winner.** The frozen evaluation set runs once for it, and its result is reported whatever it shows. The frozen set never chooses anything. If "after" doesn't beat "before", or the guardrail rises, that is the finding, and nothing is re-tuned.
  6. **Shipping: champion/challenger, decided on dev only.**
     - The champion is Week 4's retrieval (semantic, chunk size 80, floor 0.70, top-k 2).
     - The challenger (the dev winner) ships only if it has **more** as-shipped dev hits than the champion, and no more dev false retrievals. **A tie keeps the champion.**
  7. **Safety gate before shipping a challenger:** re-run Week 4's red-team cases (R1–R6) and prompt-injection cases (U1, U2, U3, U3b, U9, U9b) through the real model with the challenger's retrieval, using 3 seeds each.
     - **If any run leaks or follows an injected instruction, the challenger does not ship.** That means any failure of a case's `must_not_*` rules, the document-text limit, or the no-citing-pending-documents rule.
     - Status mismatches alone don't count for the gate; they're reported separately.
  8. **If a challenger ships,** the Week 4 18-case evaluation is re-run with it, as a regression report only.

## Retrieval (RAG improvements)

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| G1 | Support document versioning | 1 | ☑ | `assistant/models.py` (`DocumentVersion`), `assistant/documents.py`; migrations `assistant/0002`–`0004` (existing documents become v1, chunks kept, Week 4 passage IDs unchanged); citations and `AnswerRecord` name the edition (`billing.md@v2#0` from v2 on) | `tests/test_assistant_versions.py` (`TestVersions`, `TestEditionsInAnswers`, migration forward and back) | | |
| G2 | Update re-indexing | 1 | ☑ | `documents.approve_version`: embed first, then one locked transaction writes the new chunks, marks v(n) current and v(n−1) superseded, deletes the old chunks; a failed embedding changes nothing | `tests/test_assistant_versions.py`: old edition never retrieved after approval; failure keeps the old edition live; a version decided while embedding isn't approved twice; row lock taken | | |
| G3 | Delete re-indexing | 1 | ☑ | `documents.retire` (soft delete): chunks removed, every version kept for audit; restoring means a new version plus approval | `tests/test_assistant_versions.py` (`TestRetire`) | | |
| G4 | Metadata filters | 3 | ☑ | Opt-in `area` and `document` filters in `indexing.retrieve`, and an optional validated `area` on the ask API. Reported in [retrieval_before_after.md](../backend/assistant/eval/retrieval_before_after.md): no change as shipped, because a filter can't lift a correct chunk over the floor | `tests/test_retrieval_select.py` (`TestFilters`, `TestAskArea`) | | |
| G5 | Hybrid keyword + semantic retrieval | 3 | ☑ | `assistant/bm25.py` and `indexing.retrieve` (RRF), with gates S and S+K. Compared on dev in [retrieval_selection.md](../backend/assistant/dev/retrieval_selection.md): hybrid search did not beat semantic (best 4 of 12 for each) | `tests/test_retrieval_select.py` (BM25 and RRF checked by hand) | | |
| G6 | Reranking or a documented alternative | 3 | ☑ | Reciprocal rank fusion, the approved documented alternative (`bm25.rrf`) | `tests/test_retrieval_select.py` | | |
| G7 | Chunk-size comparison | 3 | ☑ | 40, 80, 120 and 200 tokens, on dev ([retrieval_selection.md](../backend/assistant/dev/retrieval_selection.md): best 1, 3, 4 and 4 of 12) and on the frozen set, reporting only ([retrieval_before_after.md](../backend/assistant/eval/retrieval_before_after.md)) | `tests/test_retrieval_select.py`, `tests/test_retrieval_sets.py` (the hit rule is fair at every size) | | |

## Evaluation (retrieval separately from generation)

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| V1 | At least 20 labeled questions | 2 | ☑ | 23 frozen questions (11 by the user) in `assistant/eval/retrieval_cases.json`, plus a separate 15-question dev set; quote labels; corpus and sets hash-pinned in `frozen.py` | `tests/test_retrieval_sets.py` | | |
| V2 | Evaluate retrieval separately from generation | 2 | ☑ | `assistant/retrieval_eval.py`, `manage.py evaluate_retrieval`: no language model is called; the frozen corpus is built in a rolled-back transaction and checked against the manifest | `tests/test_retrieval_eval.py` | | |
| V3 | Report Recall@K or hit rate | 2 | ☑ | [retrieval_baseline.md](../backend/assistant/eval/retrieval_baseline.md): Recall@1/3/5, hit rate, document recall, MRR, as-shipped hit rate, false retrieval; by category and author | `tests/test_retrieval_eval.py` (metrics checked by hand on toy rankings) | | |
| V4 | Report citation correctness | 4 | ☐ | | | | |
| V5 | Report groundedness | 4 | ☐ | | | | |
| V6 | Report abstention behavior | 4 | ☐ | | | | |
| V7 | Show before/after results for one retrieval improvement | 3 | ☑ | [retrieval_before_after.md](../backend/assistant/eval/retrieval_before_after.md): before = Week 4's retrieval; after = the dev winner, picked by rules written before any run. **On the primary measure, after was worse (5 of 18 against 11 of 18, guardrail 0 of 5 for both); the secondary measures rose slightly (Recall@1 +1 question, MRR 0.97 → 1.00).** Reported as it came out, with nothing re-tuned | `tests/test_retrieval_select.py`, `tests/test_retrieval_eval.py` | | |

## LLM structured outputs and conversation

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| L1 | LLM structured outputs with schema validation | 5 | ☐ | | | | |
| L2 | Retry-on-invalid-output (bounded) | 5 | ☐ | | | | |
| L3 | Conversation/session history | 5 | ☐ | | | | |
| L4 | History summarization or truncation | 5 | ☐ | | | | |
| L5 | Explicit token budgets | 5 | ☐ | | | | |

## Tools and agent

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| T1 | Controlled tool-using agent with at least four typed tools | 6 | ☐ | | | | |
| T2 | Tool: search approved documents | 6 | ☐ | | | | |
| T3 | Tool: check fictional appointment availability | 6 | ☐ | | | | |
| T4 | Tool: request supervised ML prediction | 6 | ☐ | | | | |
| T5 | Tool: retrieve anonymized cluster summaries | 6 | ☐ | | | | |
| T6 | Stateful multi-step workflow: plan → tool selection → validation → execution → response | 8 | ☐ | | | | |
| T7 | Tool-call traces | 8 | ☐ | | | | |
| T8 | Maximum-step limit | 8 | ☐ | | | | |
| T9 | Recovery from failed tools | 8 | ☐ | | | | |

## Write tool and approval

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| W1 | Fifth tool: draft a fictional reminder or schedule a mock appointment | 7 | ☐ | | | | |
| W2 | Any write requires explicit human confirmation | 7 | ☐ | | | | |
| W3 | Any write requires server-side authorization | 7 | ☐ | | | | |

## MCP

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| P1 | Integrate one MCP server/tool where feasible, or an equivalent typed tool adapter | 9 | ☐ | | | | |
| P2 | Explain how MCP permissions, inputs and outputs are handled | 9 | ☐ | | | | |

## Background jobs

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| J1 | Background job for document indexing or batch predictions using a task queue | 10 | ☐ | | | | |
| J2 | Track queued/running/succeeded/failed status | 10 | ☐ | | | | |
| J3 | Retry transient failures safely | 10 | ☐ | | | | |

## Model monitoring

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| M1 | Log synthetic prediction distributions | 11 | ☐ | | | | |
| M2 | Log inference latency | 11 | ☐ | | | | |
| M3 | Log failure rates | 11 | ☐ | | | | |
| M4 | Compare with baseline to flag possible drift | 11 | ☐ | | | | |
| M5 | No claims of real-world medical impact | 11 | ☐ | | | | |

## Admin audit page

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| D1 | Admin-facing audit page: agent actions | 12 | ☐ | | | | |
| D2 | Audit page: approval decisions | 12 | ☐ | | | | |
| D3 | Audit page: retrieval sources | 12 | ☐ | | | | |
| D4 | Audit page: job status | 12 | ☐ | | | | |
| D5 | Audit page: model versions | 12 | ☐ | | | | |

## Engineering constraints

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| C1 | Authorize each tool at execution time; do not trust prompts to enforce security | 6–8 | ☐ | | | | |
| C2 | Allowlists | 6–8 | ☐ | | | | |
| C3 | Schema validation | 5–8 | ☐ | | | | |
| C4 | Idempotency keys for writes | 7 | ☐ | | | | |
| C5 | Bounded retries | 5, 10 | ☐ | | | | |
| C6 | Per-request timeouts | 6–10 | ☐ | | | | |
| C7 | Defend against prompt injection in retrieved content | 3, 8 | ☐ | | | | |
| C8 | Defend against prompt injection in tool responses | 8 | ☐ | | | | |
| C9 | Redact secrets and personal data from prompts | 5–8 | ☐ | | | | |
| C10 | Redact secrets and personal data from traces | 8 | ☐ | | | | |
| C11 | Redact secrets and personal data from logs | 8–10 | ☐ | | | | |
| C12 | Agent capabilities limited to synthetic, low-risk administration | 6–8 | ☐ | | | | |
| C13 | No autonomous clinical recommendations or real-world patient changes | 6–8 | ☐ | | | | |

## Acceptance checks

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| A1 | Demonstrate a successful multi-tool workflow | 13 | ☐ | | | | |
| A2 | Demonstrate an unauthorized tool denial | 13 | ☐ | | | | |
| A3 | Demonstrate a rejected write | 13 | ☐ | | | | |
| A4 | Demonstrate an explicitly approved write | 13 | ☐ | | | | |
| A5 | Demonstrate document re-indexing | 1, 13 | ◐ | Update, approve, retire and restore are built and tested offline (G1–G3). The real-model demo is in Step 13 | `tests/test_assistant_versions.py` | | |
| A6 | Measurable retrieval improvement with the 20-question test set | 3 | ◐ | **Not achieved on the primary measure.** The dev-chosen setting lowered the as-shipped hit rate on the frozen set. Only Recall@1 and MRR rose slightly. The champion (Week 4's retrieval) stays. See [retrieval_before_after.md](../backend/assistant/eval/retrieval_before_after.md) | | | |
| A7 | Show a background job failure/retry | 13 | ☐ | | | | |
| A8 | Show the audit trail | 13 | ☐ | | | | |
| A9 | Show a bounded agent loop | 13 | ☐ | | | | |
| A10 | Show structured-output validation | 13 | ☐ | | | | |
| A11 | Submit an architecture diagram | 14 | ☐ | | | | |
| A12 | Submit typed tool contracts | 14 | ☐ | | | | |
| A13 | Submit an evaluation report | 14 | ☐ | | | | |
| A14 | Submit security threat notes | 14 | ☐ | | | | |

## Required submission

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| R1 | GitHub repository with meaningful commits | all | ☐ | | | | |
| R2 | Setup and run/test commands | 14 | ☐ | | | | |
| R3 | README architecture decisions, limitations, screenshots and API examples | 14 | ☐ | | | | |
| R4 | 5–10 minute Loom: working demo, code architecture, actual AI prompts and refinements, context management, blast-radius controls, debugging and verification | 14 | ☐ | | | | |
| R5 | Post repository and Loom links in the team channel | 14 | ☐ | | | | |
| R6 | Keep all previous features working and provide regression-test evidence | 0, 14 | ☐ | | | | |
| R7 | Git workflow: branch, PR, reviewer @ahmedhashir10 (mentor instruction) | 0, 14 | ☐ | | | | |
| R8 | Study guide (user's standing request) | 14 | ☐ | | | | |
