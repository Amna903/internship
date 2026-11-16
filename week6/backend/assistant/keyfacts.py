"""Key-fact matching for the generation evaluation (Week 5 Step 4): lexical, whole words, after normalising
number words, so "three hours" and "3 hours" match, and "twice" matches "2 times".

A match does NOT count when it is directly negated: one of not / no / never / cannot (contractions such as
"isn't" and "won't" become "not") within the 2 words before it, as in "not allowed", "not free", "isn't
welcome" or "no longer allowed". Two words, not more, so "No, there is no interest" still counts for "no
interest". A fact counts if any occurrence of any phrasing is not negated."""

import re

NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "hundred": 100,
}
MULTIPLES = {"once": "1 time", "twice": "2 times", "thrice": "3 times"}


def normalise(text: str) -> str:
    t = text.lower().replace("-", " ").replace("’", "'")
    t = re.sub(r"n't\b", " not", t)
    t = re.sub(r"\b(" + "|".join(MULTIPLES) + r")\b", lambda m: MULTIPLES[m.group(1)], t)
    t = re.sub(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", lambda m: str(NUMBER_WORDS[m.group(1)]), t)
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


NEGATORS = {"not", "no", "never", "cannot"}
WINDOW = 2


def has_fact(answer: str, alternatives: list[str]) -> bool:
    """True if any alternative phrasing appears in the answer as whole words, not directly negated."""
    words = normalise(answer).split()
    for alt in alternatives:
        target = normalise(alt).split()
        for i in range(len(words) - len(target) + 1):
            if words[i : i + len(target)] == target and not NEGATORS & set(words[max(0, i - WINDOW) : i]):
                return True
    return False


def all_facts(answer: str, facts: list[list[str]]) -> bool:
    return all(has_fact(answer, alts) for alts in facts)
