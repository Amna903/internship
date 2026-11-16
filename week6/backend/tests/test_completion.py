from io import StringIO

import pytest
from django.core.management import call_command

from profiles.completion import evaluate
from profiles.models import HealthProfile

ME = "/api/profiles/me/"
LIST = "/api/admin/profiles/"

FULL = {
    "age_range": "25-34",
    "wellness_goals": ["Walk more"],
    "emergency_contact_name": "Sam Example",
    "emergency_contact_phone": "+1 555 010 0199",
    "emergency_contact_relationship": "Friend",
}


@pytest.mark.django_db
class TestCompletionRules:
    def test_new_profile_from_signup_is_incomplete_with_every_section_missing(self, user):
        result = evaluate(user.profile)
        assert result.status == "incomplete" and result.percent == 0
        assert result.missing_sections == ["demographics", "emergency_contact", "wellness_preferences"]
        assert user.profile.completion_status == "incomplete"

    @pytest.mark.parametrize("age", [{"age_range": "45-54"}, {"date_of_birth": "1990-01-01"}])
    def test_dob_or_age_range_both_satisfy_demographics(self, user_browser, age):
        body = user_browser.patch(ME, {**FULL, "age_range": "", **age}).json()
        assert "demographics" not in body["completion"]["missing_sections"]

    def test_partial_emergency_contact_does_not_count(self, user_browser):
        body = user_browser.patch(ME, {**FULL, "emergency_contact_relationship": ""}).json()
        assert body["completion"] == {"status": "incomplete", "percent": 67, "missing_sections": ["emergency_contact"]}


@pytest.mark.django_db
class TestCompletionApi:
    def test_filling_every_section_marks_profile_complete_in_api_and_db(self, user_browser, user):
        resp = user_browser.patch(ME, FULL)
        assert resp.status_code == 200
        assert resp.json()["completion"] == {"status": "complete", "percent": 100, "missing_sections": []}
        user.profile.refresh_from_db()
        assert user.profile.completion_status == "complete"

    def test_clearing_a_section_drops_back_to_incomplete(self, user_browser, user):
        user_browser.patch(ME, FULL)
        resp = user_browser.patch(ME, {"wellness_goals": []})
        assert resp.json()["completion"]["status"] == "incomplete"
        user.profile.refresh_from_db()
        assert user.profile.completion_status == "incomplete"

    def test_completion_cannot_be_set_by_the_client(self, user_browser, user):
        resp = user_browser.patch(ME, {"completion_status": "complete", "completion": {"status": "complete"}})
        assert resp.status_code == 200 and resp.json()["completion"]["status"] == "incomplete"
        user.profile.refresh_from_db()
        assert user.profile.completion_status == "incomplete"

    def test_update_fields_save_still_refreshes_completion(self, user):
        profile = user.profile
        for field, value in FULL.items():
            setattr(profile, field, value)
        profile.save(update_fields=list(FULL))
        profile.refresh_from_db()
        assert profile.completion_status == "complete"


@pytest.mark.django_db
class TestAdminCompletionFilter:
    def test_admin_list_shows_and_filters_by_completion(self, admin_browser, make_user):
        done = make_user("done@example.test", name="Done Person")
        for field, value in FULL.items():
            setattr(done.profile, field, value)
        done.profile.save()
        make_user("todo@example.test", name="Todo Person")

        rows = admin_browser.get(LIST, {"completion": "complete"}).json()["results"]
        assert [r["email"] for r in rows] == ["done@example.test"]
        assert rows[0]["completion_status"] == "complete"
        rows = admin_browser.get(LIST, {"completion": "incomplete"}).json()["results"]
        assert [r["email"] for r in rows] == ["todo@example.test"]

    def test_unknown_completion_value_is_rejected(self, admin_browser):
        resp = admin_browser.get(LIST, {"completion": "half"})
        assert resp.status_code == 400 and "completion" in resp.json()["error"]["details"]

    def test_bulk_seed_rows_get_correct_completion(self, monkeypatch):
        # bulk_create skips save(); the seeder must compute the column itself.
        monkeypatch.setenv("SEED_ADMIN_PASSWORD", "Sturdy-Passw0rd!x")
        monkeypatch.setenv("SEED_USER_PASSWORD", "Sturdy-Passw0rd!x")
        call_command("seed_demo", bulk=40, stdout=StringIO())
        profiles = list(HealthProfile.objects.all())
        assert {p.completion_status for p in profiles} == {"complete", "incomplete"}
        assert all(p.completion_status == evaluate(p).status for p in profiles)
