"""Load the saved pipeline safely and score one appointment.

joblib files are pickles: loading one runs code. So the loader only reads from the configured
artifact directory and refuses the file unless (1) its SHA-256 matches the metadata written at
training time and (2) the installed scikit-learn is the version it was trained with.
"""

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
import sklearn

from . import config
from .features import INPUT_COLUMNS

DISCLAIMER = (
    "Educational prototype trained on synthetic data. Estimates appointment attendance only; "
    "not a medical assessment and not clinically validated."
)


class ModelUnavailable(Exception):
    """The model can't be served (missing, tampered with, or built for other library versions)."""


@dataclass(frozen=True)
class LoadedModel:
    pipeline: object
    metadata: dict

    @property
    def version(self) -> str:
        return f"{self.metadata['model_name']}-{self.metadata['model_version']}"


@lru_cache(maxsize=4)
def load(artifact_dir: str, name: str = config.MODEL_NAME, version: str = config.MODEL_VERSION) -> LoadedModel:
    base = Path(artifact_dir)
    meta_path = base / f"{name}-{version}.json"
    if not meta_path.exists():
        raise ModelUnavailable(f"No metadata for {name}-{version}. Run `python -m ml.train`.")
    metadata = json.loads(meta_path.read_text())
    artifact = base / metadata["artifact_file"]
    if not artifact.exists():
        raise ModelUnavailable(f"Artifact {artifact.name} is missing. Run `python -m ml.train`.")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if digest != metadata["artifact_sha256"]:
        raise ModelUnavailable("Artifact checksum does not match its metadata; refusing to load it.")
    trained_with = metadata["environment"]["scikit_learn"]
    if trained_with != sklearn.__version__:
        raise ModelUnavailable(f"Model was trained with scikit-learn {trained_with}, found {sklearn.__version__}.")
    return LoadedModel(pipeline=joblib.load(artifact), metadata=metadata)


def risk_band(probability: float, threshold: float, base_rate: float) -> str:
    if probability >= threshold:
        return "high"
    if probability >= base_rate:
        return "medium"
    return "low"


def predict(model: LoadedModel, features: dict) -> dict:
    """``features`` must already be validated (the API serializer does that)."""
    missing = set(INPUT_COLUMNS) - set(features)
    if missing:
        raise ValueError(f"missing features: {sorted(missing)}")
    row = pd.DataFrame([{name: features[name] for name in INPUT_COLUMNS}], columns=INPUT_COLUMNS)
    row["distance_km"] = row["distance_km"].astype(float)  # None -> NaN, imputed like in training
    probability = float(model.pipeline.predict_proba(row)[0, 1])
    threshold = model.metadata["decision_threshold"]
    base_rate = model.metadata["train_no_show_rate"]
    return {
        "no_show_probability": round(probability, 4),
        "risk_band": risk_band(probability, threshold, base_rate),
        "decision_threshold": threshold,
        "baseline_no_show_rate": base_rate,
    }
