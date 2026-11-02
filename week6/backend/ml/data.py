"""Seeded generator for the synthetic appointment no-show dataset.

Every row is fictional. The no-show probability comes from a formula written below, so we know
the ground truth: later steps can check what a model actually learned and compare it with the
best possible score (the "oracle ceiling").

The formula deliberately contains structure a plain linear model on raw inputs cannot fully see:
  * a curve: the lead-time effect rises fast for the first days, then flattens (log);
  * an interaction: a reminder helps much more for appointments booked far ahead;
  * a hidden per-patient reliability, visible only indirectly through the no-show history.
That is what gives an "improved" model something real to improve on.

Run:  python -m ml.data      (writes ml/data/appointments.csv and prints a summary)
"""

import hashlib

import numpy as np
import pandas as pd

from . import config

# ---- Planted effects, on the log-odds scale (positive = more likely to miss) ----
INTERCEPT = -2.95  # tuned so the overall no-show rate lands around 16%
LEAD_TIME_LOG = 0.55  # times log(1 + lead_time_days): a curve, not a straight line
REMINDER_BASE = -0.15  # a reminder always helps a little...
REMINDER_PER_LEAD = -0.45  # ...and up to this much more when booked 30+ days ahead (interaction)
AGE_EFFECT = {"18-24": 0.60, "25-34": 0.30, "35-44": 0.0, "45-54": -0.15, "55-64": -0.30, "65+": -0.20}
DISTANCE_PER_KM = 0.012
TELEHEALTH = -0.35  # no travel needed
WEEKDAY_EFFECT = {"monday": 0.10, "tuesday": 0.0, "wednesday": 0.0, "thursday": 0.0, "friday": 0.15, "saturday": -0.10}
CHANNEL_EFFECT = {"web": 0.05, "phone": -0.10, "app": 0.0}
EARLY_HOUR = 0.15  # 7-8 am
LATE_HOUR = 0.10  # 5 pm onwards
RELIABILITY_SD = 0.6  # spread of the hidden per-patient habit
PRIOR_HISTORY_MEAN = 3  # appointments a patient had before the dataset window starts


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def true_log_odds(
    lead_time_days, reminder_sent, age_band, distance_km, visit_type, weekday, booking_channel, hour, reliability
):
    """The ground-truth formula for one appointment (scalars)."""
    reminder_strength = REMINDER_BASE + REMINDER_PER_LEAD * min(lead_time_days, 30) / 30
    return (
        INTERCEPT
        + LEAD_TIME_LOG * np.log1p(lead_time_days)
        + (reminder_strength if reminder_sent else 0.0)
        + AGE_EFFECT[age_band]
        + DISTANCE_PER_KM * distance_km
        + (TELEHEALTH if visit_type == "telehealth" else 0.0)
        + WEEKDAY_EFFECT[weekday]
        + CHANNEL_EFFECT[booking_channel]
        + (EARLY_HOUR if hour <= 8 else LATE_HOUR if hour >= 17 else 0.0)
        + reliability
    )


def generate(seed: int = config.SEED, n_patients: int = config.N_PATIENTS) -> pd.DataFrame:
    """Return the full synthetic dataset. Same seed -> identical DataFrame, byte for byte."""
    rng = np.random.default_rng(seed)
    rows = []
    appointment_id = 0

    for patient_id in range(1, n_patients + 1):
        # --- Patient-level attributes (fixed across all of this patient's appointments) ---
        age_band = rng.choice(config.AGE_BANDS, p=[0.14, 0.20, 0.20, 0.18, 0.15, 0.13])
        distance_km = float(np.round(rng.gamma(shape=2.0, scale=6.0), 1))  # mostly near, a long tail
        reliability = rng.normal(0.0, RELIABILITY_SD)  # hidden: never written to the dataset

        # --- History before the dataset window: a noisy view of the hidden reliability ---
        prior_appointments = int(rng.poisson(PRIOR_HISTORY_MEAN))
        prior_no_shows = int(rng.binomial(prior_appointments, _sigmoid(-1.8 + reliability)))

        n_appointments = 1 + int(rng.poisson(config.MEAN_APPOINTMENTS_PER_PATIENT - 1))
        for _ in range(n_appointments):
            appointment_id += 1
            lead_time = int(min(rng.exponential(12.0), config.LEAD_TIME_MAX_DAYS))
            weekday = rng.choice(config.WEEKDAYS, p=[0.19, 0.19, 0.19, 0.19, 0.16, 0.08])
            hour = int(rng.integers(config.HOUR_RANGE[0], config.HOUR_RANGE[1] + 1))
            visit_type = rng.choice(config.VISIT_TYPES, p=[0.75, 0.25])
            channel = rng.choice(config.BOOKING_CHANNELS, p=[0.45, 0.30, 0.25])
            reminder = bool(rng.random() < 0.65)

            probability = float(
                _sigmoid(
                    true_log_odds(
                        lead_time,
                        reminder,
                        age_band,
                        distance_km,
                        visit_type,
                        weekday,
                        channel,
                        hour,
                        reliability,
                    )
                )
            )
            no_show = bool(rng.random() < probability)  # the weighted coin flip: noise is built in

            rows.append(
                {
                    "appointment_id": appointment_id,
                    "patient_id": patient_id,
                    "lead_time_days": lead_time,
                    "appointment_weekday": weekday,
                    "appointment_hour": hour,
                    "age_band": age_band,
                    "visit_type": visit_type,
                    "booking_channel": channel,
                    "reminder_sent": reminder,
                    "prior_appointments": prior_appointments,
                    "prior_no_shows": prior_no_shows,
                    "distance_km": distance_km,
                    config.ORACLE: round(probability, 6),
                    config.LABEL: no_show,
                }
            )
            # This appointment becomes history for the patient's next one (time order matters).
            prior_appointments += 1
            prior_no_shows += int(no_show)

    df = pd.DataFrame(rows)
    # Missing values, planted on purpose: completely at random, so the missingness itself carries
    # no signal. (Real-world missingness is rarely this kind; the data card says so.)
    missing = rng.random(len(df)) < config.MISSING_DISTANCE_RATE
    df.loc[missing, "distance_km"] = np.nan
    return df


def dataset_hash(df: pd.DataFrame) -> str:
    """SHA-256 of a canonical CSV rendering: proves two datasets are identical."""
    return hashlib.sha256(df.to_csv(index=False, float_format="%.6f").encode()).hexdigest()


def summary(df: pd.DataFrame) -> dict:
    return {
        "rows": len(df),
        "patients": int(df["patient_id"].nunique()),
        "no_show_rate": round(float(df[config.LABEL].mean()), 4),
        "missing_distance_rate": round(float(df["distance_km"].isna().mean()), 4),
        "sha256": dataset_hash(df),
    }


def main():
    df = generate()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(config.DATASET_CSV, index=False, float_format="%.6f")
    for key, value in summary(df).items():
        print(f"{key:>22}: {value}")
    print(f"{'written to':>22}: {config.DATASET_CSV}")


if __name__ == "__main__":
    main()
