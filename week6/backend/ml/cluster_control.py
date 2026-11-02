"""Positive control for clustering: a small, separate generator with PLANTED engagement habits.

Why it exists: the main synthetic data has no patient habits (every engagement column is drawn
independently for each appointment, see ml/cluster_features.py), so clustering it can only show "no
structure found". A positive control checks the other half: when habits DO exist, do the methods recover
them? It is a separate dataset with its own seed and module; it never touches ml/data.py, and its planted
habit labels are used only to score recovery, never as clustering inputs.

Four habits, planted with overlap (a "mixed" group sits between the others, and every habit has spread),
so recovery is a real test rather than a formality. The number of appointments is drawn the same way for
every habit, so the count can't give the groups away.
"""

import numpy as np
import pandas as pd

from . import config

CONTROL_SEED = 7  # not config.SEED (42) and not the holdout's (20261101)
N_PATIENTS = 1_500
ID_OFFSET = 20_000_000  # control patient IDs can't collide with the main data or the holdout

# Each habit: mean lead time (days, exponential), telehealth probability, booking-channel probabilities
# (web, phone, app), mean appointment hour (normal, sd 2.5, clipped to opening hours).
HABITS = {
    "early planners": {"lead": 30.0, "telehealth": 0.15, "channel": (0.70, 0.15, 0.15), "hour": 10.0},
    "last-minute phone bookers": {"lead": 3.0, "telehealth": 0.20, "channel": (0.15, 0.70, 0.15), "hour": 14.0},
    "telehealth app users": {"lead": 10.0, "telehealth": 0.80, "channel": (0.15, 0.15, 0.70), "hour": 17.0},
    "mixed": {"lead": 12.0, "telehealth": 0.25, "channel": (0.45, 0.30, 0.25), "hour": 13.0},
}
HOUR_SD = 2.5
MEAN_APPOINTMENTS = 4


def generate_control(seed: int = CONTROL_SEED, n_patients: int = N_PATIENTS) -> tuple[pd.DataFrame, pd.Series]:
    """(appointments, planted habit per patient). Appointments have the columns cluster_features needs."""
    rng = np.random.default_rng(seed)
    names = list(HABITS)
    rows, habit_of = [], {}
    for i in range(n_patients):
        patient_id = ID_OFFSET + i + 1
        habit = names[rng.integers(len(names))]
        habit_of[patient_id] = habit
        h = HABITS[habit]
        for _ in range(1 + int(rng.poisson(MEAN_APPOINTMENTS - 1))):
            rows.append(
                {
                    "patient_id": patient_id,
                    "lead_time_days": int(min(rng.exponential(h["lead"]), config.LEAD_TIME_MAX_DAYS)),
                    "visit_type": "telehealth" if rng.random() < h["telehealth"] else "in_person",
                    "booking_channel": rng.choice(config.BOOKING_CHANNELS, p=h["channel"]),
                    "appointment_hour": int(np.clip(round(rng.normal(h["hour"], HOUR_SD)), *config.HOUR_RANGE)),
                }
            )
    return pd.DataFrame(rows), pd.Series(habit_of, name="planted_habit")
