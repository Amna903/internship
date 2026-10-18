from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.models import User
from profiles.models import HealthProfile

from .conftest import PASSWORD, Browser, admin_login, user_login

LIST = "/api/admin/profiles/"


@pytest.mark.django_db
class TestAdminProvisioning:
    def test_create_admin_command_creates_hashed_admin(self, monkeypatch):
        monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
        call_command("create_admin", email="New.Admin@Example.test", stdout=StringIO())
        admin = User.objects.get(email="new.admin@example.test")
        assert admin.role == User.Role.ADMIN and admin.is_admin
        assert admin.password != PASSWORD and admin.check_password(PASSWORD)
        assert not HealthProfile.objects.filter(user=admin).exists()

    def test_create_admin_rejects_weak_password_and_duplicates(self, monkeypatch, admin):
        monkeypatch.setenv("ADMIN_PASSWORD", "12345678")
        with pytest.raises(CommandError, match="Weak password"):
            call_command("create_admin", email="x@example.test", stdout=StringIO())
        monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
        with pytest.raises(CommandError, match="already exists"):
            call_command("create_admin", email=admin.email, stdout=StringIO())

    def test_create_admin_needs_a_password_source_when_non_interactive(self, monkeypatch):
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        with pytest.raises(CommandError):
            call_command("create_admin", email="x@example.test", stdout=StringIO())

    def test_seed_demo_creates_admin_and_at_least_five_synthetic_users(self, monkeypatch):
        monkeypatch.setenv("SEED_ADMIN_PASSWORD", PASSWORD)
        monkeypatch.setenv("SEED_USER_PASSWORD", PASSWORD)
        call_command("seed_demo", stdout=StringIO())
        call_command("seed_demo", stdout=StringIO())  # idempotent
        assert User.objects.filter(role="admin").count() == 1
        assert User.objects.filter(role="user").count() >= 5
        assert HealthProfile.objects.count() == User.objects.filter(role="user").count()
        assert not User.objects.filter(email__endswith="@gmail.com").exists()


@pytest.mark.django_db
class TestAdminSessionLogin:
    def test_login_sets_httponly_session_cookie(self, browser, admin):
        resp = admin_login(browser, admin.email)
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "admin"
        cookie = resp.cookies["hp_admin_session"]
        assert cookie["httponly"] and cookie["secure"] and cookie["samesite"] == "Lax"
        assert "hp_access" not in resp.cookies and "hp_refresh" not in resp.cookies  # no JWT for admins
        assert browser.get("/api/admin/me/").status_code == 200

    def test_session_id_rotates_on_login(self, browser, admin):
        browser.client.cookies["hp_admin_session"] = "attacker-chosen-session-id"
        resp = admin_login(browser, admin.email)
        assert resp.cookies["hp_admin_session"].value != "attacker-chosen-session-id"

    def test_wrong_password_and_unknown_email_are_generic_401(self, browser, admin):
        a = admin_login(browser, admin.email, "Wrong-Passw0rd!!")
        b = admin_login(browser, "nobody@example.test")
        assert a.status_code == b.status_code == 401 and a.json() == b.json()

    def test_standard_user_credentials_do_not_work_on_admin_login(self, browser, user):
        assert admin_login(browser, user.email).status_code == 401
        assert "hp_admin_session" not in browser.cookies

    def test_login_requires_csrf(self, browser, admin):
        resp = browser.post("/api/admin/login/", {"email": admin.email, "password": PASSWORD}, csrf=False)
        assert resp.status_code == 403

    def test_login_is_rate_limited(self, browser, admin):
        codes = [admin_login(browser, admin.email, "Wrong-Passw0rd!!").status_code for _ in range(11)]
        assert codes[-1] == 429

    def test_logout_destroys_server_side_session(self, admin_browser):
        session_key = admin_browser.cookies["hp_admin_session"].value
        assert Session.objects.filter(session_key=session_key).exists()
        assert admin_browser.post("/api/admin/logout/").status_code == 200
        assert not Session.objects.filter(session_key=session_key).exists()
        # Replaying the old cookie (e.g. stolen) no longer works.
        replay = Browser()
        replay.cookies["hp_admin_session"] = session_key
        assert replay.get("/api/admin/me/").status_code == 401

    def test_logout_requires_csrf(self, admin_browser):
        assert admin_browser.post("/api/admin/logout/", csrf=False).status_code == 403
        assert admin_browser.get("/api/admin/me/").status_code == 200  # still signed in

    def test_expired_session_is_rejected(self, admin_browser):
        Session.objects.update(expire_date=timezone.now() - timedelta(minutes=1))
        resp = admin_browser.get("/api/admin/me/")
        assert resp.status_code == 401

    def test_session_lifetime_is_the_configured_idle_timeout(self, admin_browser):
        session = Session.objects.get()
        remaining = session.expire_date - timezone.now()
        assert timedelta(minutes=29) < remaining <= timedelta(minutes=30)


@pytest.mark.django_db
class TestAdminAuthorization:
    ENDPOINTS = [
        ("get", "/api/admin/me/"),
        ("get", LIST),
        ("get", "/api/admin/profiles/1/"),
        ("post", "/api/admin/profiles/1/deactivate/"),
        ("post", "/api/admin/profiles/1/activate/"),
    ]

    @pytest.mark.parametrize("method, url", ENDPOINTS)
    def test_anonymous_is_rejected(self, browser, method, url):
        assert getattr(browser, method)(url).status_code == 401

    @pytest.mark.parametrize("method, url", ENDPOINTS)
    def test_standard_user_jwt_does_not_grant_admin_access(self, user_browser, method, url):
        assert getattr(user_browser, method)(url).status_code in (401, 403)

    def test_forged_session_cookie_is_rejected(self, browser):
        browser.cookies["hp_admin_session"] = "forged0session0id0that0does0not0exist00"
        assert browser.get(LIST).status_code == 401

    def test_cannot_escalate_by_sending_role_hints_from_the_client(self, user_browser):
        resp = user_browser.get("/api/admin/me/", HTTP_X_ROLE="admin", HTTP_X_ADMIN="true")
        assert resp.status_code == 401
        user_browser.cookies["role"] = "admin"
        user_browser.cookies["is_admin"] = "true"
        assert user_browser.get(LIST).status_code == 401

    def test_user_who_also_holds_a_session_for_another_account_stays_a_user(self, user, admin):
        """Edge case: a browser holding a user JWT *and* someone else's admin session id is still
        decided purely by the server-side session row, never by what the client says it is."""
        b = Browser()
        user_login(b, user.email)
        b.cookies["hp_admin_session"] = "guess"
        assert b.get(LIST).status_code == 401

    def test_admin_state_changing_requests_require_csrf(self, admin_browser, user):
        pk = HealthProfile.objects.get(user=user).pk
        assert admin_browser.post(f"/api/admin/profiles/{pk}/deactivate/", csrf=False).status_code == 403
        assert HealthProfile.objects.get(pk=pk).status == "active"

    def test_admin_has_no_write_access_to_profile_content(self, admin_browser, user):
        pk = HealthProfile.objects.get(user=user).pk
        assert admin_browser.patch(f"/api/admin/profiles/{pk}/", {"full_name": "x"}).status_code == 405


@pytest.mark.django_db
class TestAdminDashboard:
    @pytest.fixture(autouse=True)
    def people(self, make_user):
        self.alice = make_user("alice@example.test", name="Alice Anderson")
        self.bob = make_user("bob@example.test", name="Bob Brown")
        self.cara = make_user("cara@example.test", name="Cara Anderson")

    def test_list_returns_all_profiles_newest_first_with_pagination_envelope(self, admin_browser):
        data = admin_browser.get(LIST).json()
        assert data["count"] == 3
        assert [r["email"] for r in data["results"]] == ["cara@example.test", "bob@example.test", "alice@example.test"]
        assert {"id", "email", "full_name", "status", "created_at"} <= set(data["results"][0])

    def test_list_never_exposes_password_hashes(self, admin_browser):
        body = admin_browser.get(LIST).content.decode() + admin_browser.get(f"{LIST}1/").content.decode()
        assert "password" not in body and "md5$" not in body

    def test_search_by_name_and_email_case_insensitive(self, admin_browser):
        by_name = admin_browser.get(LIST, {"search": "anderson"}).json()
        assert {r["full_name"] for r in by_name["results"]} == {"Alice Anderson", "Cara Anderson"}
        by_email = admin_browser.get(LIST, {"search": "BOB@"}).json()
        assert [r["email"] for r in by_email["results"]] == ["bob@example.test"]
        assert admin_browser.get(LIST, {"search": "zzz"}).json()["count"] == 0

    def test_ordering_and_status_filter_and_invalid_status(self, admin_browser):
        names = [r["full_name"] for r in admin_browser.get(LIST, {"ordering": "full_name"}).json()["results"]]
        assert names == sorted(names)
        HealthProfile.objects.filter(user=self.bob).update(status="deactivated")
        only = admin_browser.get(LIST, {"status": "deactivated"}).json()
        assert [r["email"] for r in only["results"]] == ["bob@example.test"]
        assert admin_browser.get(LIST, {"status": "bogus"}).status_code == 400

    def test_pagination(self, admin_browser):
        page1 = admin_browser.get(LIST, {"page_size": 2}).json()
        assert len(page1["results"]) == 2 and page1["count"] == 3 and page1["next"]
        page2 = admin_browser.get(LIST, {"page_size": 2, "page": 2}).json()
        assert len(page2["results"]) == 1
        assert admin_browser.get(LIST, {"page": 99}).status_code == 404

    def test_detail_view(self, admin_browser):
        pk = HealthProfile.objects.get(user=self.alice).pk
        data = admin_browser.get(f"{LIST}{pk}/").json()
        assert data["email"] == "alice@example.test" and data["account_active"] is True
        assert admin_browser.get(f"{LIST}99999/").status_code == 404

    def test_deactivate_blocks_login_and_kills_live_jwt_then_activate_restores(self, admin_browser):
        victim = Browser()
        user_login(victim, "alice@example.test")
        assert victim.get("/api/profiles/me/").status_code == 200
        pk = HealthProfile.objects.get(user=self.alice).pk

        resp = admin_browser.post(f"{LIST}{pk}/deactivate/")
        assert resp.status_code == 200 and resp.json()["status"] == "deactivated"
        assert resp.json()["deactivated_at"] and resp.json()["account_active"] is False
        assert victim.get("/api/profiles/me/").status_code == 401  # already-issued JWT is dead
        assert victim.post("/api/auth/user/refresh/").status_code == 401
        assert user_login(Browser(), "alice@example.test").status_code == 401

        resp = admin_browser.post(f"{LIST}{pk}/activate/")
        assert resp.json()["status"] == "active" and resp.json()["deactivated_at"] is None
        assert user_login(Browser(), "alice@example.test").status_code == 200

    def test_deactivate_unknown_profile_is_404(self, admin_browser):
        assert admin_browser.post(f"{LIST}99999/deactivate/").status_code == 404
