"""The server decides whether a prediction's inputs were given (Week 5 Step 8, input-check rules).

Before `predict_no_show` runs for the agent, every field's value must be stated in the user's own message;
otherwise the call is rejected and the agent must ask. This stops estimates built on inputs the model invented.

"Stated" is a conservative word match, built from the tool's allowed values and general English (rule 2). It
extracts what the message says for each field and compares it with the value the model sent: a field the
message doesn't mention, or mentions with a different value, is missing. Unclear phrasing counts as missing:
safe, at the cost of sometimes asking for something that was given.
"""

import re

from assistant.keyfacts import NUMBER_WORDS

TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
FIELDS = (
    "lead_time_days",
    "appointment_weekday",
    "appointment_hour",
    "age_band",
    "visit_type",
    "booking_channel",
    "reminder_sent",
    "prior_appointments",
    "prior_no_shows",
    "distance_km",
)


def normalise(text: str) -> str:
    """Lower case, number words to digits (including "twenty-one"), dashes and punctuation to spaces."""
    t = text.lower().replace("’", "'")
    t = re.sub(
        r"\b(" + "|".join(TENS) + r")[\s-]+(one|two|three|four|five|six|seven|eight|nine)\b",
        lambda m: str(TENS[m.group(1)] + NUMBER_WORDS[m.group(2)]),
        t,
    )
    words = {**NUMBER_WORDS, **TENS}
    t = re.sub(r"\b(" + "|".join(sorted(words, key=len, reverse=True)) + r")\b", lambda m: str(words[m.group(1)]), t)
    t = re.sub(r"(\d)\s*[–—-]\s*(\d)", r"\1-\2", t)  # keep ranges like 35-44 together
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)  # a dot survives only inside a number like 4.5
    t = re.sub(r"[^\w\s:+.-]", " ", t)
    return " ".join(t.split())


def _ints(pattern: str, t: str) -> set[int]:
    return {int(m.group(1)) for m in re.finditer(pattern, t)}


def stated(message: str) -> dict[str, set]:
    """What the message itself says for each field (empty set: not stated)."""
    t = normalise(message)
    s: dict[str, set] = {f: set() for f in FIELDS}
    s["lead_time_days"] = _ints(r"\b(\d+) days?\b", t) | {7 * n for n in _ints(r"\b(\d+) weeks?\b", t)}
    if re.search(r"\b(a|1) week (ahead|before|in advance|early)\b", t):
        s["lead_time_days"].add(7)
    s["appointment_weekday"] = {d for d in WEEKDAYS if re.search(rf"\b{d}s?\b", t)}
    for m in re.finditer(r"\b(?:at )?(\d{1,2})(?::(\d{2}))? ?(am|pm|o'clock|o clock)?\b", t):
        hour, minutes, suffix = int(m.group(1)), m.group(2), m.group(3)
        if not (m.group(0).startswith("at ") or minutes or suffix):
            continue  # a bare number is not a time
        if suffix == "pm" and hour < 12:
            hour += 12
        if minutes in (None, "00") and 0 <= hour <= 23:
            s["appointment_hour"].add(hour)
    for m in re.finditer(r"\b(\d{2})(?:-| to )(\d{2})\b", t):
        s["age_band"].add(f"{m.group(1)}-{m.group(2)}")
    if re.search(r"\b(65\+|65 plus|over 65|65 or older)", t):
        s["age_band"].add("65+")
    if re.search(r"\b(in[ -]person|face[ -]to[ -]face)\b", t):
        s["visit_type"].add("in_person")
    if re.search(r"\b(telehealth|video|virtual|online visit|online appointment)\b", t):
        s["visit_type"].add("telehealth")
    if re.search(r"\bapp\b", t):
        s["booking_channel"].add("app")
    if re.search(r"\b(website|web|online booking|booked online|books online)\b", t):
        s["booking_channel"].add("web")
    if re.search(r"\b(phone|call|called|calls)\b", t):
        s["booking_channel"].add("phone")
    if re.search(r"\b(no reminder|without a reminder|not reminded|reminder not sent|no reminders)\b", t):
        s["reminder_sent"].add(False)
    elif re.search(r"\b(reminder sent|with a reminder|reminded|sent a reminder|reminders sent)\b", t):
        s["reminder_sent"].add(True)
    s["prior_appointments"] = _ints(
        r"\b(\d+) (?:earlier |previous |prior |past )?(?:appointments?|visits?)\b", t
    ) | _ints(r"\bout of (\d+)\b", t)
    s["prior_no_shows"] = _ints(r"\b(\d+) (?:missed|no shows?|no-shows?)\b", t) | _ints(r"\bmissed (\d+)\b", t)
    if re.search(r"\b(none missed|never missed|none of them missed|no missed|missed none|0 missed)\b", t):
        s["prior_no_shows"].add(0)
    s["distance_km"] = {float(m.group(1)) for m in re.finditer(r"\b(\d+(?:\.\d+)?) ?(?:km|kilomet(?:er|re)s?)\b", t)}
    if re.search(
        r"\b(distance (?:is )?unknown|unknown distance|distance not known|don't know the distance|distance unknown)\b",
        t,
    ):
        s["distance_km"].add(None)
    return s


def missing_fields(args: dict, message: str) -> list[str]:
    """Fields whose value the model sent but the message did not state (in field order)."""
    s = stated(message)
    out = []
    for f in FIELDS:
        value = args.get(f)
        if f == "distance_km" and value is not None:
            ok = any(v is not None and abs(v - float(value)) < 1e-9 for v in s[f])
        else:
            ok = value in s[f]
        if not ok:
            out.append(f)
    return out
