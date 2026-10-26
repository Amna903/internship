"""Engineered features, as a scikit-learn transformer so they travel inside the saved pipeline.

Each one comes from a finding in ml/reports/eda.md. All are fixed formulas: nothing is learned from
the data, so this step cannot leak information from validation or test rows.
"""

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

REMINDER_FULL_EFFECT_DAYS = 30  # EDA §6.2: the reminder's extra benefit grows up to ~30 days ahead

ENGINEERED_NUMERIC = ["log_lead_time", "prior_no_show_rate", "has_history", "reminder_x_lead"]


def engineer(X: pd.DataFrame) -> pd.DataFrame:
    out = X.copy()
    lead = out["lead_time_days"].astype(float)
    # EDA §6.1, the curve. log1p, not log: same-day appointments have lead time 0 and log(0) = -inf.
    out["log_lead_time"] = np.log1p(lead)
    # EDA §6.3, the habit. No history means nothing to divide by: the ratio is defined as 0, and
    # has_history tells "new patient" apart from "never missed" (15.6% vs 13.5% no-shows in the EDA).
    appointments = out["prior_appointments"].astype(float)
    has_history = appointments > 0
    out["has_history"] = has_history.astype(float)
    out["prior_no_show_rate"] = np.where(
        has_history, out["prior_no_shows"].astype(float) / appointments.where(has_history, 1.0), 0.0
    )
    # EDA §6.2, the interaction: a reminder matters more the further ahead the appointment is.
    out["reminder_x_lead"] = out["reminder_sent"].astype(float) * np.minimum(lead, REMINDER_FULL_EFFECT_DAYS) / REMINDER_FULL_EFFECT_DAYS
    # Always the same column order, so feature names match what the pipeline was fitted on.
    return out[list(X.columns) + ENGINEERED_NUMERIC]


class EngineeredFeatures(BaseEstimator, TransformerMixin):
    """Adds ENGINEERED_NUMERIC columns. Stateless: fit() learns nothing."""

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return engineer(X)

    def get_feature_names_out(self, input_features=None):
        return np.asarray(list(input_features) + ENGINEERED_NUMERIC, dtype=object)
