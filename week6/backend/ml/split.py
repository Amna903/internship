"""Train / validation / test split, grouped by patient.

Every patient's appointments land in exactly one part. If one person appeared in both train and test,
the model could score well by recognising that person (their distance, age band, history) instead of
learning patterns that transfer to new patients.

Run:  python -m ml.split      (prints the split summary)
"""

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from . import config
from .data import generate

TRAIN_SHARE, VALIDATION_SHARE, TEST_SHARE = 0.6, 0.2, 0.2


def split(df: pd.DataFrame, seed: int = config.SEED) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """60/20/20 by patient. scikit-learn has no three-way grouped split, so split twice:
    train vs the rest (60/40), then the rest in half (20/20)."""
    groups = df["patient_id"]
    first = GroupShuffleSplit(n_splits=1, test_size=VALIDATION_SHARE + TEST_SHARE, random_state=seed)
    train_idx, rest_idx = next(first.split(df, groups=groups))
    rest = df.iloc[rest_idx]
    second = GroupShuffleSplit(n_splits=1, test_size=TEST_SHARE / (VALIDATION_SHARE + TEST_SHARE), random_state=seed)
    val_idx, test_idx = next(second.split(rest, groups=rest["patient_id"]))
    return df.iloc[train_idx], rest.iloc[val_idx], rest.iloc[test_idx]


def summary(parts: dict[str, pd.DataFrame]) -> pd.DataFrame:
    total = sum(len(p) for p in parts.values())
    return pd.DataFrame(
        [
            {
                "part": name,
                "rows": len(p),
                "share": round(len(p) / total, 3),
                "patients": p["patient_id"].nunique(),
                "no_show_rate": round(p[config.LABEL].mean(), 4),
            }
            for name, p in parts.items()
        ]
    ).set_index("part")


def main():
    train, validation, test = split(generate())
    print(summary({"train": train, "validation": validation, "test": test}).to_string())


if __name__ == "__main__":
    main()
