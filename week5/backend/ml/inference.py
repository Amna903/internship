"""Load the released model safely and turn its output into a plain-language suggestion.

Checks run in this order, and the .joblib file is only unpickled after all of them pass:
  1. both files exist;
  2. the metadata parses, names this model version and declares exactly our feature schema;
  3. the installed scikit-learn is the exact version the model was saved with (a model saved by one
     version can load *silently wrong* in another);
  4. the file's SHA-256 equals the one in the metadata.

What check 4 does and does not do: it catches accidental corruption and mismatched files (a stale or
half-copied .joblib next to another version's .json). It is NOT protection against a deliberate
attacker: whoever can replace the .joblib can also edit the .json. The real protection is that we only
ever load our own committed file from the repository, never an uploaded or user-supplied one. That
matters because joblib, like pickle, can execute code while loading.

Any failure raises ModelUnavailable; the API turns that into 503 instead of crashing.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
import sklearn

from . import config
from .artifact import artifact_paths, file_sha256


class ModelUnavailable(Exception):
    """The model cannot be served. `reason` is safe to log; the API shows a generic message."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LoadedModel:
    pipeline: object
    metadata: dict

    @property
    def version(self) -> str:
        return self.metadata["model"]

    @property
    def threshold(self) -> float:
        return self.metadata["decision"]["threshold"]

    def predict(self, rows: list[dict]) -> list[dict]:
        """rows: validated feature dicts (the API validates them first). Returns one result per row."""
        frame = pd.DataFrame(rows, columns=config.FEATURES)
        probabilities = self.pipeline.predict_proba(frame)[:, 1]
        return [self._describe(float(p)) for p in probabilities]

    def _describe(self, probability: float) -> dict:
        action = suggested_action(probability, self.threshold)
        return {
            "no_show_probability": round(probability, 4),
            "suggested_action": action,
            "suggested_action_label": config.ACTIONS[action],
            "decision_threshold": round(self.threshold, 4),
            "average_no_show_rate": round(self.metadata["training_data"]["average_no_show_rate"], 4),
        }


def suggested_action(probability: float, threshold: float) -> str:
    # At exactly the threshold the suggestion applies (same >= rule used to choose the threshold).
    return "extra_reminder_suggested" if probability >= threshold else "standard_reminder"


def load(directory: Path = config.ARTIFACT_DIR, version: str = config.MODEL_VERSION) -> LoadedModel:
    model_path, meta_path = artifact_paths(directory, version)
    for path in (model_path, meta_path):
        if not path.is_file():
            raise ModelUnavailable(f"missing file: {path.name}")

    try:
        metadata = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelUnavailable(f"metadata unreadable: {exc.__class__.__name__}") from None
    if metadata.get("version") != version:
        raise ModelUnavailable(f"metadata is for version {metadata.get('version')!r}, expected {version!r}")
    if metadata.get("features") != config.FEATURE_SCHEMA:
        raise ModelUnavailable("feature schema in metadata does not match this code")

    saved_with = metadata.get("libraries", {}).get("scikit-learn")
    if saved_with != sklearn.__version__:
        raise ModelUnavailable(f"saved with scikit-learn {saved_with}, running {sklearn.__version__}")

    if file_sha256(model_path) != metadata.get("artifact_sha256"):
        raise ModelUnavailable("model file SHA-256 does not match its metadata (corrupted or mismatched file)")

    # Only now is the file unpickled: our own committed file, verified above.
    pipeline = joblib.load(model_path)
    return LoadedModel(pipeline=pipeline, metadata=metadata)


@lru_cache(maxsize=1)
def get_model() -> LoadedModel:
    """Loaded once per server process. A failure is not cached, so a fixed file is picked up on retry."""
    return load()
