"""Server-side date resolution for the agent (Week 5 Step 8 round 2): the model never does date arithmetic.

Rules in docs/REQUIREMENTS.md ("Step 8 round 2 rules", rule 2), applied to the user's own message with the
fixed clock:
- "today", "tomorrow": the clock date and the next day;
- a bare weekday, or "next <weekday>": the next such day AFTER today;
- "next week": the following week's days on which the clinic schedule has slots;
- an explicit date ("10 November", "4 Dec", "November 10", "2026-11-10"): that date this year;
- an explicit date that has passed, an impossible date (30 February) and "yesterday" are UNRESOLVED.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
    )
}
MONTHS |= {m[:3]: n for m, n in list(MONTHS.items())} | {"sept": 9}
MONTH = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)"
DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
PATTERNS = [
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")),
    ("day_month", re.compile(rf"\b{DAY}\s+(?:of\s+)?{MONTH}\b", re.I)),
    ("month_day", re.compile(rf"\b{MONTH}\s+{DAY}\b", re.I)),
    ("next_week", re.compile(r"\bnext\s+week\b", re.I)),
    ("weekday", re.compile(r"\b(?:next\s+|on\s+|this\s+)?(" + "|".join(WEEKDAYS) + r")(?:'s)?\b", re.I)),
    ("relative", re.compile(r"\b(today|tomorrow|yesterday)\b", re.I)),
]


@dataclass
class Resolution:
    dates: dict = field(default_factory=dict)  # phrase as written -> list of ISO dates
    unresolved: list = field(default_factory=list)  # phrases that name a past or impossible date

    @property
    def mentioned(self) -> bool:
        return bool(self.dates or self.unresolved)

    def allowed(self) -> set[str]:
        return {d for ds in self.dates.values() for d in ds}

    def prompt_lines(self) -> str:
        if not self.mentioned:
            return ""
        lines = ["Dates in this request, resolved by the server (use exactly these; never work out dates yourself):"]
        for phrase, ds in self.dates.items():
            lines.append(f'- "{phrase}" = ' + ", ".join(f"{date.fromisoformat(d):%A} {d}" for d in ds))
        for phrase in self.unresolved:
            lines.append(f'- "{phrase}" has passed or is not a real date: ask the user for a valid date; do not book.')
        return "\n".join(lines)


def is_schedule_day(weekday: int) -> bool:
    from .read_tools import OPEN_WEEKDAYS  # the same days check_availability opens

    return weekday in OPEN_WEEKDAYS


def resolve(message: str, today: date) -> Resolution:
    res = Resolution()
    taken: list[tuple[int, int]] = []  # spans already matched, so "November 10" isn't also read as a weekday etc.

    def free(m) -> bool:
        return not any(a < m.end() and m.start() < b for a, b in taken)

    for kind, pattern in PATTERNS:
        for m in pattern.finditer(message):
            if not free(m):
                continue
            if kind == "weekday" and re.search(r"\b(a|an|every|each)\s+$", message[: m.start()], re.I):
                continue  # "on a Wednesday at 9" describes a kind of day, not a date
            taken.append((m.start(), m.end()))
            phrase = m.group(0).strip()
            got = _resolve_one(kind, m, today)
            if got is None:
                res.unresolved.append(phrase)
            else:
                res.dates[phrase] = got
    return res


def _explicit(year: int, month: int, day: int, today: date):
    try:
        d = date(year, month, day)
    except ValueError:
        return None  # e.g. 30 February
    return [d.isoformat()] if d >= today else None  # a past explicit date is unresolved, never rolled forward


def _resolve_one(kind: str, m, today: date):
    if kind == "iso":
        return _explicit(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
    if kind == "day_month":
        return _explicit(today.year, MONTHS[m.group(2).lower()], int(m.group(1)), today)
    if kind == "month_day":
        return _explicit(today.year, MONTHS[m.group(1).lower()], int(m.group(2)), today)
    if kind == "relative":
        word = m.group(1).lower()
        return None if word == "yesterday" else [(today + timedelta(days=0 if word == "today" else 1)).isoformat()]
    if kind == "weekday":
        target = WEEKDAYS.index(m.group(1).lower())
        ahead = (target - today.weekday()) % 7 or 7  # the next such day AFTER today
        return [(today + timedelta(days=ahead)).isoformat()]
    if kind == "next_week":
        monday = today + timedelta(days=7 - today.weekday())
        return [(monday + timedelta(days=i)).isoformat() for i in range(7) if is_schedule_day(i)]
    return None
