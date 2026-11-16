"""Profile completion: which sections of a wellness profile are filled in.

Kept as pure functions over a profile so the same rules drive the stored ``completion_status``
column (filterable by admins), the API response and the tests.
"""

from dataclasses import dataclass

COMPLETE = "complete"
INCOMPLETE = "incomplete"


def _demographics(p) -> bool:
    return bool(p.full_name and p.full_name.strip()) and (p.date_of_birth is not None or bool(p.age_range))


def _emergency_contact(p) -> bool:
    return all(
        (value or "").strip()
        for value in (p.emergency_contact_name, p.emergency_contact_phone, p.emergency_contact_relationship)
    )


def _wellness_preferences(p) -> bool:
    return bool(p.contact_preference) and bool(p.wellness_goals)


# Order matters: it is the order sections are listed to the user.
SECTIONS = {
    "demographics": _demographics,
    "emergency_contact": _emergency_contact,
    "wellness_preferences": _wellness_preferences,
}


@dataclass(frozen=True)
class Completion:
    status: str
    percent: int
    missing_sections: list[str]


def evaluate(profile) -> Completion:
    missing = [name for name, is_done in SECTIONS.items() if not is_done(profile)]
    done = len(SECTIONS) - len(missing)
    return Completion(
        status=COMPLETE if not missing else INCOMPLETE,
        percent=round(100 * done / len(SECTIONS)),
        missing_sections=missing,
    )
