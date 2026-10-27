"""The dashboard form and the API share frontend/lib/noShowSchema.json. These tests stop the two from
drifting apart, and prove each "Fill example" preset really gives the result its button promises."""

import json
from pathlib import Path

import pytest

from ml import config
from ml.inference import get_model
from predictions.serializers import NoShowInputSerializer

SHARED = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "noShowSchema.json"
DOC = json.loads(SHARED.read_text())


def test_shared_schema_equals_the_api_schema():
    assert DOC["features"] == config.FEATURE_SCHEMA
    assert DOC["actions"] == config.ACTIONS
    assert DOC["model"] == f"{config.MODEL_NAME}-{config.MODEL_VERSION}"


@pytest.mark.parametrize("preset", DOC["presets"], ids=[p["id"] for p in DOC["presets"]])
def test_each_preset_is_valid_and_gives_its_promised_suggestion(preset):
    serializer = NoShowInputSerializer(data=preset["values"])
    assert serializer.is_valid(), serializer.errors
    assert get_model().predict([serializer.validated_data])[0]["suggested_action"] == preset["expected_action"]


def test_presets_show_both_suggestions():
    assert {p["expected_action"] for p in DOC["presets"]} == set(config.ACTIONS)
