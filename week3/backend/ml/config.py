"""Single source of truth for the Week 3 ML pipeline: seed, sizes, paths and column roles."""

from pathlib import Path

SEED = 42  # every random draw in data generation (and later, training) derives from this

N_PATIENTS = 5_000
MEAN_APPOINTMENTS_PER_PATIENT = 4  # ~20,000 appointments in total
MISSING_DISTANCE_RATE = 0.08  # share of distance_km deliberately left blank

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR / "data"  # generated CSVs live here and are git-ignored (rebuildable from SEED)
DATASET_CSV = DATA_DIR / "appointments.csv"

# ---- Column roles. Anything not in FEATURES must never reach a model. ----
ID_COLUMNS = ["appointment_id", "patient_id"]  # patient_id is used ONLY to group the split
LABEL = "no_show"
# The generator's true probability. Used ONLY to compute the "oracle ceiling" (the best score any
# model could reach). Feeding it to a model would be leakage; a test enforces that it is not a feature.
ORACLE = "true_no_show_probability"

NUMERIC_FEATURES = ["lead_time_days", "appointment_hour", "prior_appointments", "prior_no_shows", "distance_km"]
CATEGORICAL_FEATURES = ["appointment_weekday", "age_band", "visit_type", "booking_channel"]
BOOLEAN_FEATURES = ["reminder_sent"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES + BOOLEAN_FEATURES

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
VISIT_TYPES = ["in_person", "telehealth"]
BOOKING_CHANNELS = ["web", "phone", "app"]
HOUR_RANGE = (7, 19)  # clinic opening hours, inclusive
LEAD_TIME_MAX_DAYS = 90

# ---- Model release (Step 6) ----
MODEL_NAME = "no-show"
MODEL_VERSION = "1.0.0"  # major: inputs change · minor: retrained, same inputs · patch: metadata only
ARTIFACT_DIR = ML_DIR / "artifacts"

DISCLAIMER = (
    "Educational prototype trained on synthetic data. Estimates whether a fictional appointment may be "
    "missed, to help plan reminders. Not a medical assessment and not clinically validated."
)
# Plain, non-clinical wording: the only action the estimate can support is an extra reminder.
ACTIONS = {
    "extra_reminder_suggested": "Extra reminder suggested",
    "standard_reminder": "Standard reminder",
}

# Input schema shared by the saved model's metadata and the API's validation (Step 7).
FEATURE_SCHEMA = {
    "lead_time_days": {"type": "integer", "min": 0, "max": LEAD_TIME_MAX_DAYS},
    "appointment_weekday": {"type": "category", "values": WEEKDAYS},
    "appointment_hour": {"type": "integer", "min": HOUR_RANGE[0], "max": HOUR_RANGE[1]},
    "age_band": {"type": "category", "values": AGE_BANDS},
    "visit_type": {"type": "category", "values": VISIT_TYPES},
    "booking_channel": {"type": "category", "values": BOOKING_CHANNELS},
    "reminder_sent": {"type": "boolean"},
    "prior_appointments": {"type": "integer", "min": 0, "max": 500},
    "prior_no_shows": {"type": "integer", "min": 0, "max": 500, "at_most": "prior_appointments"},
    "distance_km": {"type": "number", "min": 0, "max": 500, "nullable": True},
}
