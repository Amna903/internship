"""The preprocessing half of every model pipeline.

    ColumnGuard → [EngineeredFeatures] → ColumnTransformer
                                           ├─ numbers:    median imputation (+ missing flag) → scaling
                                           ├─ categories: one-hot
                                           └─ booleans:   0/1

Everything that learns a value (the imputation median, the scaler's mean and spread, the one-hot
categories) learns it in fit(), and fit() is only ever called on the training split. Validation and
test rows are only transformed. Because preprocessing and model are one Pipeline object, they are
also saved together (constraint E2).
"""

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from . import config
from .features import ENGINEERED_NUMERIC, EngineeredFeatures


class ColumnGuard(BaseEstimator, TransformerMixin):
    """Rejects any column that is not a declared feature: IDs, the label and the oracle can never
    reach a model, even by accident. Also rejects a missing feature instead of silently dropping it."""

    def fit(self, X, y=None):
        self._check(X)
        return self

    def transform(self, X):
        self._check(X)
        return X[config.FEATURES]

    def get_feature_names_out(self, input_features=None):
        return np.asarray(config.FEATURES, dtype=object)

    @staticmethod
    def _check(X):
        columns = set(X.columns)
        extra = columns - set(config.FEATURES)
        missing = set(config.FEATURES) - columns
        if extra or missing:
            raise ValueError(f"Bad model input. Not allowed: {sorted(extra)}; missing: {sorted(missing)}")


def _as_float(X):
    return np.asarray(X, dtype=float)


def build_preprocessor(engineered: bool) -> Pipeline:
    numeric = config.NUMERIC_FEATURES + (ENGINEERED_NUMERIC if engineered else [])
    columns = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        # add_indicator=True adds a distance_missing column for features with gaps in training.
                        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            ),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), config.CATEGORICAL_FEATURES),
            ("boolean", FunctionTransformer(_as_float, feature_names_out="one-to-one"), config.BOOLEAN_FEATURES),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    steps = [("guard", ColumnGuard())]
    if engineered:
        steps.append(("engineer", EngineeredFeatures()))
    steps.append(("columns", columns))
    return Pipeline(steps)


def model_input(df: pd.DataFrame) -> pd.DataFrame:
    """The only way training code should hand rows to a pipeline: features only."""
    return df[config.FEATURES]
