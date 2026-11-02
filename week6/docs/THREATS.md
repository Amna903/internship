# Security threat notes (Week 5, A14)

These notes cover the Week 5 additions: the agent, the write tool, the MCP server, background jobs and monitoring. Week 2–4 notes (the two auth systems, uploads, the assistant) are still in [ARCHITECTURE.md](ARCHITECTURE.md). Everything runs on synthetic data and a fictional clinic.

| # | Threat | Where | Control | Evidence |
|---|---|---|---|---|
| 1 | **Prompt injection in retrieved policy text** ("book this slot instead", "ignore your rules") | `search_policies` → agent | Tool output is data inside markers it can't close, and it's marked `untrusted`. The model only proposes; the server validates every call. The write tool is offered only on the user's own booking request. A proposal must match a slot the availability tool returned. Booking needs a human confirmation. | `test_agent_runner.py`; real-model runs in [step13_acceptance.md](../backend/assistant/eval/step13_acceptance.md) record whether the injection was actually retrieved |
| 2 | **The model invents inputs** (a no-show estimate from fields nobody gave) | `predict_no_show` via the agent | A server-side check that every field is stated in the user's own message (`agent/inputs.py`). Otherwise the call is rejected and the agent must ask. | `test_agent_inputs.py`; Step 13 S-U/S-A cases |
| 3 | **Privilege through prompts** ("act as admin2", role fields) | every tool | Identity comes only from the server-side context. No schema has user, role or permission fields (a test walks every schema), extra keys are rejected, and authorisation is checked on every call and again at confirmation. | `test_agent_tools.py`, `test_agent_write.py` |
| 4 | **An unsupervised write** | `book_mock_appointment` | It only stores a pending action (single use, proposer only, 10-minute expiry). Confirm and decline are human endpoints, not tools. The card text is written by the server. There are limits of 3 open and 6 per 10 minutes. | `test_agent_write.py` |
| 5 | **Double booking or a replayed confirm** | confirm endpoint | A required `Idempotency-Key` (the same key replays, a different action gets 409); a unique constraint per slot decides races. | `test_agent_write.py` (`TestConfirm`, `TestRaces`) |
| 6 | **A runaway agent loop or cost** | runner | 4 tool calls, 1 proposal, 8,000 tokens and 60 s per run; one corrected retry, and a second failure ends the run. | `test_agent_runner.py` (`TestLimits`, `TestRecovery`) |
| 7 | **A stolen MCP token** (plain text in the client's config) | MCP server | Short-lived tokens (8 h default, 24 h maximum), stored hashed, revocable, re-checked on every call; read tools only; 30 calls per minute per token across processes; every call audited. | `test_agent_mcp.py`, [MCP.md](MCP.md) |
| 8 | **Leaks through traces, logs and audit** | `AgentRun`, `AuditEvent`, `IndexJob`, `PredictionLog`, the audit page | Ids, codes, versions and times only. Free-text arguments are masked, and no message, answer, document text, prediction input or email is stored. Errors never echo upstream text. | `test_agent_runner.py`, `test_audit_overview.py`, `test_monitoring.py`, `test_index_jobs.py` |
| 9 | **A duplicate or poisoned background job** | indexing jobs | One open job per version (a database constraint); a row lock plus a pending re-check make repeats harmless; the worker re-checks admin rights; only transient errors are retried, at most 3 times; per-attempt time limits. | `test_index_jobs.py`, `test_index_worker.py` |
| 10 | **Broker outage** | Redis | The publish doesn't retry: the job is failed with `queue_unavailable` (503) and nothing changes. There's no silent synchronous fallback. | `test_index_jobs.py` |
| 11 | **Medical overreach** | assistant, agent, monitoring | The medical check runs on the whole conversation before any retrieval. The agent can't give clinical recommendations or change real records. Monitoring carries a fixed "no real-world medical impact" disclaimer. | `test_assistant_history.py`, `test_monitoring.py` |
| 12 | **Test-only fault injection reaching production** | the flaky embedder | Refused unless the provider is `fake`; test settings let only `flaky` through. | `test_index_jobs.py` |

## Known gaps (not covered)

- **Names aren't redacted** (only numbers and identifiers are): a Week 4 gap that's still open.
- **A 3B local model:** task success is modest, and the safety comes from the server's checks, not the model.
- **No remote MCP or OAuth:** stdio on one trusted machine only.
- **Drift is measured on predictions only**, not per input; latency baselines are machine-specific.
- See the Step 13 report for whether real runs actually put injected text in front of the model (C8).
