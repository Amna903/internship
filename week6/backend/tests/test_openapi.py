"""Week 6 Step 4: the brief's endpoint paths, the versioned artifact with its preprocessing, and OpenAPI examples."""

import pytest
from drf_spectacular.generators import SchemaGenerator

from config.openapi import EXAMPLES, PROBES


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def test_every_core_operation_has_representative_examples(schema):
    for (path, method), (body, _) in EXAMPLES.items():
        op = schema["paths"][path][method]
        assert op["responses"]["200"]["content"]["application/json"]["examples"]
        if body is not None:
            assert all(m.get("examples") for m in op["requestBody"]["content"].values()), path


def test_health_and_ready_are_documented(schema):
    for path in PROBES:
        assert schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["examples"]


def test_operation_ids_are_unique(schema):
    ids = [op["operationId"] for p in schema["paths"].values() for op in p.values() if isinstance(op, dict)]
    assert len(ids) == len(set(ids))


@pytest.mark.django_db
def test_predict_alias_matches_the_original_path(admin_browser):
    from config.openapi import PREDICT_IN

    a = admin_browser.client.post("/api/v1/predict/", PREDICT_IN, format="json", **admin_browser._csrf_headers()).json()
    b = admin_browser.client.post(
        "/api/v1/predictions/no-show/", PREDICT_IN, format="json", **admin_browser._csrf_headers()
    ).json()
    assert a == b and a["model_version"] == "no-show-1.0.0"


@pytest.mark.django_db
def test_the_model_card_reports_preprocessing_from_the_versioned_artifact(admin_browser):
    card = admin_browser.client.get("/api/v1/models/no-show/").json()
    assert card["model_version"] == "no-show-1.0.0" and len(card["artifact_sha256"]) == 64
    assert card["preprocessing"] and all("class" in s for s in card["preprocessing"])


@pytest.mark.django_db
def test_the_new_path_keeps_the_admin_and_csrf_rules(browser, user):
    assert browser.client.post("/api/v1/predict/", {}, format="json").status_code in (401, 403)
