"""Feature definition shared by training and inference.

The preprocessing lives *inside* the saved sklearn Pipeline, so the API can't drift from training:
the same imputer, encoder and derived features are applied to every request.
"""

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

# What a caller provides (the API schema mirrors this exactly).
INPUT_NUMERIC = ["lead_time_days", "appointment_hour", "prior_appointments", "prior_no_shows", "distance_km"]
INPUT_CATEGORICAL = ["appointment_weekday", "age_band", "visit_type", "booking_channel"]
INPUT_BOOLEAN = ["reminder_sent"]
INPUT_COLUMNS = INPUT_NUMERIC + INPUT_CATEGORICAL + INPUT_BOOLEAN

# Never features. Identifiers would let the model memorise people; checked_in is the outcome in disguise.
EXCLUDED_COLUMNS = {
    "appointment_id": "row identifier",
    "patient_ref": "identifier; used only to keep a patient's rows in one split",
    "checked_in": "LEAKAGE: recorded after the appointment, equals NOT no_show",
    "_true_probability": "generator internals; used only to report the oracle ceiling",
}

RAW_NUMERIC = INPUT_NUMERIC + ["reminder_flag"]
# Hypotheses from the EDA (ml/reports/eda.md), each a plain row-wise formula.
ENGINEERED_NUMERIC = [
    "prior_no_show_rate",       # history matters as a *rate*: 2 misses out of 2 is not 2 out of 20
    "is_new_patient",
    "lead_time_capped",         # keeps rare 60+ day waits from dominating a linear model
    "long_wait_no_reminder",    # the EDA's biggest cell: long wait AND no reminder
    "in_person_distance_km",    # distance only matters if you have to travel (weak, >20 km)
]


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Row-wise only (no statistics from other rows), so it can't leak across splits."""
    out = df[INPUT_COLUMNS].copy()
    appts = out["prior_appointments"].astype(float)
    reminder = out["reminder_sent"].astype(bool)
    out["reminder_flag"] = reminder.astype(float)
    out["prior_no_show_rate"] = np.where(appts > 0, out["prior_no_shows"] / appts.clip(lower=1), 0.0)
    out["is_new_patient"] = (appts == 0).astype(float)
    out["lead_time_capped"] = out["lead_time_days"].clip(upper=60).astype(float)
    out["long_wait_no_reminder"] = ((out["lead_time_days"] > 30) & ~reminder).astype(float)
    out["in_person_distance_km"] = np.where(out["visit_type"] == "in_person", out["distance_km"], 0.0)
    return out


def build_preprocessor(scale: bool, engineered: bool = True) -> Pipeline:
    numeric = RAW_NUMERIC + (ENGINEERED_NUMERIC if engineered else [])
    numeric_steps = [("impute", SimpleImputer(strategy="median", add_indicator=True))]
    if scale:
        numeric_steps.append(("scale", StandardScaler()))
    columns = ColumnTransformer(
        [
            ("num", Pipeline(numeric_steps), numeric),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), INPUT_CATEGORICAL),
        ],
        verbose_feature_names_out=False,
    )
    return Pipeline([("derive", FunctionTransformer(add_derived_features)), ("columns", columns)])
