import json

import pytest

from audit.models import AuditEvent

from .conftest import Browser, PASSWORD, admin_login

ME = "/api/profiles/me/"
AUDIT = "/api/admin/audit-events/"


def actions():
    return list(AuditEvent.objects.order_by("id").values_list("action", flat=True))


@pytest.mark.django_db
class TestProfileEditEvents:
    def test_signup_records_profile_created(self, browser):
        resp = browser.post("/api/auth/signup/", {"name": "New Person", "email": "new@example.test", "password": PASSWORD})
        assert resp.status_code == 201
        event = AuditEvent.objects.get()
        assert event.action == "profile.created" and event.actor.email == "new@example.test"
        assert event.actor_role == "user" and event.profile.full_name == "New Person"

    def test_edit_records_changed_field_names_actor_and_request_id(self, user_browser, user):
        resp = user_browser.patch(ME, {"full_name": "Alice Renamed", "age_range": "25-34"})
        assert resp.status_code == 200
        event = AuditEvent.objects.get(action="profile.updated")
        assert event.actor == user and event.actor_role == "user" and event.profile == user.profile
        assert event.changed_fields == ["age_range", "full_name"]
        assert event.request_id and event.request_id == resp["X-Request-ID"]

    def test_values_and_secrets_are_never_stored(self, user_browser):
        secret_phone = "+1 555 987 6543"
        user_browser.patch(ME, {"emergency_contact_phone": secret_phone, "lifestyle_notes": "very private note"})
        event = AuditEvent.objects.get(action="profile.updated")
        stored = json.dumps(
            {f.name: str(getattr(event, f.attname)) for f in AuditEvent._meta.concrete_fields}
        )
        assert secret_phone not in stored and "very private note" not in stored
        assert PASSWORD not in stored
        assert event.changed_fields == ["emergency_contact_phone", "lifestyle_notes"]

    def test_no_op_and_invalid_edits_record_nothing(self, user_browser, user):
        user_browser.patch(ME, {"full_name": user.profile.full_name})  # same value
        user_browser.patch(ME, {"date_of_birth": "2999-01-01"})  # rejected by validation
        assert not AuditEvent.objects.filter(action="profile.updated").exists()


@pytest.mark.django_db
class TestAdminActionEvents:
    def test_login_view_deactivate_activate_logout_are_all_recorded(self, admin, user):
        b = Browser()
        assert admin_login(b, admin.email).status_code == 200
        pid = user.profile.id
        b.get(f"/api/admin/profiles/{pid}/")
        b.post(f"/api/admin/profiles/{pid}/deactivate/")
        b.post(f"/api/admin/profiles/{pid}/activate/")
        b.post("/api/admin/logout/")
        assert actions() == [
            "admin.login",
            "admin.profile_viewed",
            "admin.profile_deactivated",
            "admin.profile_activated",
            "admin.logout",
        ]
        assert set(AuditEvent.objects.values_list("actor_role", flat=True)) == {"admin"}
        assert AuditEvent.objects.get(action="admin.profile_deactivated").changed_fields == ["status"]

    def test_failed_admin_login_is_recorded_against_the_targeted_account(self, browser, admin):
        assert admin_login(browser, admin.email, "wrong-password-123").status_code == 401
        event = AuditEvent.objects.get()
        assert (event.action, event.actor_role, event.actor_id) == ("admin.login_failed", "anonymous", admin.id)

    def test_failed_login_for_unknown_email_stores_nothing_typed(self, browser):
        typed = "my-Secret-Pass-9@typo.test"
        assert admin_login(browser, typed, "whatever-123456").status_code == 401
        event = AuditEvent.objects.get()
        assert (event.action, event.actor_id) == ("admin.login_failed", None)
        row = json.dumps(list(AuditEvent.objects.values()), default=str)
        assert "Secret" not in row and "typo" not in row

    def test_member_trying_admin_login_is_recorded(self, browser, user):
        assert admin_login(browser, user.email).status_code == 401
        assert AuditEvent.objects.get().action == "admin.login_failed"

    def test_failed_login_is_shown_as_target_not_actor(self, browser, admin, admin_browser):
        admin_login(browser, admin.email, "wrong-password-123")
        row = admin_browser.get(AUDIT, {"action": "admin.login_failed"}).json()["results"][0]
        assert row["actor_email"] is None and row["target_email"] == admin.email


@pytest.mark.django_db
class TestAuditEndpoint:
    def test_admin_can_list_and_filter_events(self, admin_browser, user, other_user):
        admin_browser.get(f"/api/admin/profiles/{user.profile.id}/")
        admin_browser.get(f"/api/admin/profiles/{other_user.profile.id}/")
        admin_browser.post(f"/api/admin/profiles/{user.profile.id}/deactivate/")

        body = admin_browser.get(AUDIT).json()
        assert body["count"] == 4  # login + 2 views + deactivate
        assert body["results"][0]["action"] == "admin.profile_deactivated"  # newest first
        assert body["results"][0]["actor_email"] == "root@example.test"

        rows = admin_browser.get(AUDIT, {"profile": user.profile.id}).json()["results"]
        assert [r["action"] for r in rows] == ["admin.profile_deactivated", "admin.profile_viewed"]
        rows = admin_browser.get(AUDIT, {"action": "admin.profile_viewed"}).json()["results"]
        assert len(rows) == 2

    @pytest.mark.parametrize("params", [{"action": "drop.table"}, {"profile": "1 OR 1=1"}])
    def test_bad_filters_are_rejected(self, admin_browser, params):
        assert admin_browser.get(AUDIT, params).status_code == 400

    def test_users_and_anonymous_cannot_read_the_audit_log(self, browser, user_browser):
        assert browser.get(AUDIT).status_code == 401
        assert user_browser.get(AUDIT).status_code in (401, 403)

    def test_endpoint_is_read_only(self, admin_browser):
        assert admin_browser.post(AUDIT, {"action": "admin.login"}).status_code == 405


@pytest.mark.django_db
class TestAppendOnlyAndRequestId:
    def test_events_cannot_be_modified_or_deleted(self, user_browser):
        user_browser.patch(ME, {"full_name": "Changed Name"})
        event = AuditEvent.objects.get()
        event.changed_fields = []
        with pytest.raises(ValueError):
            event.save()
        with pytest.raises(ValueError):
            event.delete()

    def test_well_formed_incoming_request_id_is_reused_and_junk_is_replaced(self, browser):
        good = browser.get("/api/health/", HTTP_X_REQUEST_ID="trace-abc-12345")
        assert good["X-Request-ID"] == "trace-abc-12345"
        bad = browser.get("/api/health/", HTTP_X_REQUEST_ID="<script>alert(1)</script>")
        assert bad["X-Request-ID"] != "<script>alert(1)</script>" and len(bad["X-Request-ID"]) == 32


@pytest.mark.django_db
def test_history_survives_profile_deletion(user_browser, user, admin_browser):
    pid = user.profile.id
    user_browser.patch(ME, {"lifestyle_notes": "walks daily"})
    admin_browser.get(f"/api/admin/profiles/{pid}/")
    user_browser.client.delete(ME, HTTP_X_CSRFTOKEN=user_browser.cookies["csrftoken"].value)

    rows = admin_browser.get(AUDIT, {"profile": pid}).json()["results"]
    assert [r["action"] for r in rows] == ["profile.deleted", "admin.profile_viewed", "profile.updated"]
    assert {r["profile_id"] for r in rows} == {pid}
