"""Loom replay of the negation/idiom fix (Week 4, Step 11): the original failing phrase, the changed check, and
its regression tests. Run: DJANGO_SETTINGS_MODULE=config.settings_test python scripts/demo_idiom_fix.py

Before the fix, has_negation() treated every "no" as a negation, so the correct D3 answer was blocked because its
quote says "at no cost". The fix (verify.NON_NEGATING) removes exactly two phrases that occur in the policies,
and deliberately not "no fee" / "no charge", which would hide a flipped fee."""

import subprocess
import sys
from pathlib import Path
from unittest import mock

import django

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
django.setup()

from assistant import tuning, verify  # noqa: E402
from assistant.prompts import Passage  # noqa: E402
from assistant.schema import Citation, ModelReply  # noqa: E402

QUOTE = "An appointment can be moved to a new date or time up to 2 hours before it starts, at no cost."
ANSWER = "An appointment can be moved up to 2 hours before it starts."  # the correct D3 answer
FLIP = (
    "There is no fee for a late cancellation within 12 months.",
    "A late cancellation fee of 15 euros applies to the third late cancellation within 12 months",
)


def run(answer: str, quote: str, source: str) -> str:
    p = Passage(f"{source}#0", source, quote)
    v = verify.decide(
        "Up to how many hours before can I move it?",
        ModelReply(answer, (Citation(p.id, quote),), False),
        [p],
        threshold=tuning.load_tuned()["groundedness_threshold"],
        relevance_variant="off",
    )
    return f"{v.status} ({v.reason or 'all checks passed'})"


print("1. Original failing phrase (D3):", ANSWER)
print("   quote:", QUOTE)
with mock.patch.object(verify, "NON_NEGATING", {}):
    print("   BEFORE the fix ->", run(ANSWER, QUOTE, "rescheduling.md"))
print("   AFTER the fix  ->", run(ANSWER, QUOTE, "rescheduling.md"))
print("\n2. Changed check: verify.NON_NEGATING =")
for phrase, why in verify.NON_NEGATING.items():
    print(f"   {phrase!r}: {why}")
print("\n3. The flip it must still catch ('no fee' is deliberately NOT an idiom):")
print("   ", FLIP[0], "->", run(*FLIP, "cancellation.md"))
print("\n4. Regression tests:", flush=True)
sys.exit(
    subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_assistant_polarity.py",
            "-k",
            "idiom or no_fee or negation_detection",
        ]
    )
)
