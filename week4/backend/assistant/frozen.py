"""Files frozen before any tuning (2026-11-01): the 18 evaluation cases and the six policies they refer to.

Their SHA-256 values are pinned here, so a change to any of them fails tests/test_eval_freeze.py. Changing
a frozen file needs a new, dated decision in docs/REQUIREMENTS.md, made before the evaluation it affects.
The evaluation cases are read only by the evaluation runner (Step 12); tuning code (similarity floor,
top-k, prompts, groundedness threshold) uses the separate development questions and may never read them.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
FROZEN_ON = "2026-11-01"
EVAL_CASES = ROOT / "eval" / "eval_cases.json"
POLICY_DIR = ROOT / "policies"

FROZEN_SHA256 = {
    "eval/eval_cases.json": "a1584626df260e3fd29e840fb88a4a39be0f9bf588a13f17fa6ebd3baaad663b",
    "policies/billing.md": "b7f158d91efdfd4167b3981c54af7480b4094137f981bdc081d2c015769fc03b",
    "policies/cancellation.md": "6d6f436b1c60c12dbf16e8ea269b5a4e0b50e7a8d5d98a3aa38c2b1d542ac578",
    "policies/privacy.md": "c9f2bc5f7d3264bb6ee9e504a2dc558f4a70b5438240e16ad14f211f3d24ba91",
    "policies/reminders.md": "47a9067b477addeef2c744c0311c67895ef2f289f8332f40ea65f8a878328a8f",
    "policies/rescheduling.md": "6a1e12a241f68b361f88372c14cf6f0f1eebe5b0a2afb81656ea3e6487667885",
    "policies/telehealth.md": "3b11b21980242ee8c006bdc43bdfa8ccf49172074af20f3abc906a7e39fd34a8",
}
