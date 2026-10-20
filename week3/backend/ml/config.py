"""One place for every knob that affects the trained model, so a run is fully described by this file."""

from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
DATA_PATH = ML_DIR / "data" / "appointments_synthetic.csv"
ARTIFACT_DIR = ML_DIR / "artifacts"
REPORT_DIR = ML_DIR / "reports"

MODEL_NAME = "no-show"
MODEL_VERSION = "1.0.0"

SEED = 42
N_ROWS = 20_000
N_PATIENTS = 7_000
# Patient-grouped split: train / validation / test.
VAL_SIZE = 0.2
TEST_SIZE = 0.2

TARGET = "no_show"
