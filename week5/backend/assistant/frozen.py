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

# The corpus the Week 4 development and evaluation sets were written against: exactly these six policies,
# each as version 1 with its frozen text, and nothing else searchable. The runners check it before any case
# runs and refuse to run against anything else (Week 5 Step 1), so results can't quietly drift.
WEEK4_CORPUS = {name.removeprefix("policies/"): (1, sha) for name, sha in FROZEN_SHA256.items()
                if name.startswith("policies/")}


# ---------------------------------------------------------------- Week 5 (Step 2), frozen 2026-11-01

# Frozen before any Step 3 design work. The corpus was deliberately built to be harder by the same author who
# builds the retrieval, so the size of any improvement may not transfer to other document sets.
WEEK5_FROZEN_ON = "2026-11-01"
RETRIEVAL_CASES = ROOT / "eval" / "retrieval_cases.json"
RETRIEVAL_DEV = ROOT / "dev" / "retrieval_dev.json"
WEEK5_FROZEN_SHA256 = {
    "eval/retrieval_cases.json": "7a40e307ca00ba0db640bf2f3100dc3dc460a9b887b2cbb505d74801f9e57a82",
    "dev/retrieval_dev.json": "2c4e3620fefbbc89be826bc2a1f5ef722dfdb222f7852f343bbdc238540c3d0b",
    "corpus_week5/accessibility.md": "13fb0bcf249d147509c43748b8dd5c16eea596ace9e4ffc11d02d4a1881cc9b4",
    "corpus_week5/cancellation.v2.md": "f4c51ee5c08b6ade01c38d54e281cfd7f9ac63b079d12120b81f68e0bb41643e",
    "corpus_week5/interpreter-services.md": "187fe1ca0a650c79b5cb520149a6a3576f67154182fb4e90d45d753c601160a5",
    "corpus_week5/lab-results-admin.md": "c5d0f7dbeb22a6d51925dc67ea201dfbb051ec4cd4f26c934e4bce202581eeb1",
    "corpus_week5/parking.md": "a05551a631d571dc216a0d4d922f28f7fb503f1823fd595835cf3ed2acd31f88",
    "corpus_week5/payment-plans.md": "395d0cf7cdcdf25dc15daf864c6267a9c3376abbbb6c1e42b8c9dfaefaee18cb",
    "corpus_week5/records-requests.md": "be159543f595f87c438b4d369d815d60831ff1162cbea494867d61920dc64fd1",
}

# The Week 5 corpus, in build order: (filename, version, file, policy area). The six Week 4 policies (their
# hashes are pinned above), six new policies, then cancellation v2, which replaces v1. The retrieval evaluation
# builds exactly this inside a rolled-back transaction and records the snapshot.
WEEK5_CORPUS_FILES = [
    ("billing.md", 1, "policies/billing.md", "billing"),
    ("cancellation.md", 1, "policies/cancellation.md", "cancellation"),
    ("privacy.md", 1, "policies/privacy.md", "privacy"),
    ("reminders.md", 1, "policies/reminders.md", "reminders"),
    ("rescheduling.md", 1, "policies/rescheduling.md", "rescheduling"),
    ("telehealth.md", 1, "policies/telehealth.md", "telehealth"),
    ("accessibility.md", 1, "corpus_week5/accessibility.md", "access"),
    ("interpreter-services.md", 1, "corpus_week5/interpreter-services.md", "access"),
    ("lab-results-admin.md", 1, "corpus_week5/lab-results-admin.md", "results"),
    ("parking.md", 1, "corpus_week5/parking.md", "access"),
    ("payment-plans.md", 1, "corpus_week5/payment-plans.md", "billing"),
    ("records-requests.md", 1, "corpus_week5/records-requests.md", "privacy"),
    ("cancellation.md", 2, "corpus_week5/cancellation.v2.md", "cancellation"),
]


def _pinned(file: str) -> str:
    return FROZEN_SHA256.get(file) or WEEK5_FROZEN_SHA256[file]


# What must be searchable after the build: the current edition of each document.
WEEK5_CORPUS = {name: (version, _pinned(file)) for name, version, file, _ in WEEK5_CORPUS_FILES}


# Step 3 round 2 (2026-11-02): the dev set expanded by 10 questions (7 of them unanswerable near-misses), so the
# relevance gate isn't decided by 3 unanswerable questions. Dev only; the evaluation set is unchanged.
RETRIEVAL_DEV_ROUND2 = ROOT / "dev" / "retrieval_dev_round2.json"
WEEK5_FROZEN_SHA256["dev/retrieval_dev_round2.json"] = "ebade698ea5215491cf0205d28ef6921f0cb289beeb9a51212147fa904a9fc84"


# Step 4 (2026-11-02): the generation answer key, frozen before any Step 4 run (the user reviewed U01-U08).
GENERATION_KEYS = ROOT / "eval" / "generation_keys.json"
WEEK5_FROZEN_SHA256["eval/generation_keys.json"] = "e8c3d6c063c706edfbea78c42c2d9d8ed2ac33b5aee3dc271ae747540f3e55b4"

# Step 5 (2026-11-02): follow-up conversations (C1-C5 by the user) and the history red-team (H1-H3 by the
# user), frozen before any Step 5 code.
CONVERSATIONS = ROOT / "eval" / "conversations.json"
HISTORY_REDTEAM = ROOT / "eval" / "history_redteam.json"
WEEK5_FROZEN_SHA256["eval/conversations.json"] = "0120953bae3f303b89c7bd33a910f11daf43e55939cbd951fd20caa3ae21f21e"
WEEK5_FROZEN_SHA256["eval/history_redteam.json"] = "d6b8ec594421e8370df86fecacb1d103e92bc7bdac4635108fa18622dc5b0d6a"

# Step 8 (2026-11-02): agent tool-selection tasks with the recovery set (T-U1..T-U8 by the user) and the agent
# red-team (A1-A6 by the user), frozen before any Step 8 code. Dates are against the fixed clock 2026-11-02.
AGENT_TASKS = ROOT / "eval" / "agent_tasks.json"
AGENT_REDTEAM = ROOT / "eval" / "agent_redteam.json"
WEEK5_FROZEN_SHA256["eval/agent_tasks.json"] = "14160f3e6bf0b371a46a8484a2c98df9614b5231d2950f9338aa7fefba6f3615"
WEEK5_FROZEN_SHA256["eval/agent_redteam.json"] = "99f84d666ba1e06f2c6b3429eb52e1a362afd86608c1c32a964c96dde45e1b49"

# Step 8 round 2 (2026-11-02): a fresh agent holdout, all written by the user, frozen before any round-2 code.
# The clean measure for round 2 (the frozen agent sets above informed the fixes). Fixed clock 2026-11-26.
AGENT_HOLDOUT = ROOT / "eval" / "agent_holdout.json"
WEEK5_FROZEN_SHA256["eval/agent_holdout.json"] = "57566b070c66a2331250618cb6bcae95e778d86e3a989c7fb97c5cb6afd82284"
