"""Keep personal identifiers out of prompts.

The assistant only ever needs clinic policies and the question. The model runs locally, so nothing leaves
the machine, but the rule is applied anyway (brief: no patient-identifiable data to LLMs): obvious
identifiers typed into a question are replaced before the prompt is built, and only the COUNT of
replacements is logged, never the values. This is a safety net for accidental input, not a guarantee:
pattern matching can't recognise every identifier (names, for example).
"""

import re

PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"),
    "phone": re.compile(r"(?<!\w)(\+?\d[\d\s().-]{6,}\d)(?!\w)"),
    "long_number": re.compile(r"(?<!\w)\d{6,}(?!\w)"),  # record, account or ID numbers
}


def redact(text: str) -> tuple[str, int]:
    """(text with identifiers replaced by [redacted], number of replacements)."""
    count = 0
    for pattern in PATTERNS.values():
        text, n = pattern.subn("[redacted]", text)
        count += n
    return text, count
