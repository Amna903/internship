# Evaluation suite (Week 6 Step 9)

- **Run with:** `make eval`. It needs the stack and Ollama, and took about 45 minutes.
- **Generated report:** [`backend/eval_suite/report.md`](../backend/eval_suite/report.md); raw numbers in [`results.json`](../backend/eval_suite/results.json).
- **Rules:** [REQUIREMENTS.md](REQUIREMENTS.md), "Step 9 rules", committed before the run. Nothing was tuned in this step.

| Part | What is measured | Week 6 result | Baseline |
|---|---|---|---|
| **V1 Supervised** | The release rebuilt from scratch (`ml.verify_release`), plus the test metrics recorded once in Week 3 | **Reproduced**. PR-AUC 0.280, ROC-AUC 0.663, Brier 0.1307 | Floor (dummy) PR-AUC 0.164; raw logistic 0.267; oracle ceiling 0.321 |
| **V2 Clustering** | Silhouette and planted-control recovery | Real patients: k-means k=3, silhouette **0.169**, the same as shuffled data (median 0.168), so **no real structure**: the clusters are exploratory only, as Week 4 concluded. Control: silhouette 0.295, ARI 0.52 | Shuffled-data silhouette; planted control |
| **V3 RAG** | 23 frozen questions (≥ 20): retrieval, and end to end with `llama3.2:3b`, seeds 42–44 | Recall@3 **100%**, MRR 0.97, no false retrieval. End to end: 7/18 key facts, **10/18 false abstentions**, 1 wrong answer, 5/5 correct "no answer", 0 rejected citations | Week 5 first measurement: **identical on every number** |
| **V4 Agent** | 20 frozen tasks, recovery cases, 11 red-team cases, 3 seeds each | Success **14/20**, right tools 17/20, valid arguments 14/20. **Red-team gate passed 11/11**, recovery passed | Week 5 round 1: 9/20 and gate **failed**. Week 5 final: 13/20 and gate passed |

## Reading the results honestly

- **RAG is unchanged from Week 5, as it should be.** Same frozen set, same model and seeds, and Week 6 changed no retrieval or prompt code, so identical numbers show the integrated, containerised stack reproduces Week 5 exactly.
  - Its weakness is still **false abstention** (10 of 18 answerable questions get "not enough information"). The assistant is cautious by design: it would rather abstain than answer without a verified citation. This is a known gap carried from Week 5 ([known_gaps.md](../backend/assistant/eval/known_gaps.md)), and it was not tuned here.
- **Agent: 14/20, up from Week 5's final 13/20.** No agent code changed in Week 6, so the single extra success is within run-to-run noise from the local model. It is **not** claimed as an improvement. The safety result is what matters: no red-team case leaked data, confirmed a booking without approval or acted for another user.
- **Supervised and clustering are unchanged by design.** The release is rebuilt byte for byte, and the test set is not scored again.
- **Time:** the end-to-end and agent runs took longer than in Week 5 (560 s against 211 s, and 1162 s against 763 s), because the backend now runs in Docker on a memory-constrained laptop while the model runs on the host.
