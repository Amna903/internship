import pytest
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import User

from .conftest import PASSWORD, Browser, admin_login, user_login
from .helpers import decode_payload, expired_access_token, tamper_payload, unsigned_token

ME = "/api/profiles/me/"


@pytest.mark.django_db
class TestUserLogin:
    def test_login_sets_httponly_cookies_and_returns_no_token_in_body(self, browser, user):
        resp = user_login(browser, user.email)
        assert resp.status_code == 200
        assert resp.json()["user"] == {"id": user.id, "email": user.email, "role": "user"}
        assert "access" not in resp.content.decode().lower().replace("access_expires_in", "")
        access, refresh = resp.cookies["hp_access"], resp.cookies["hp_refresh"]
        for cookie in (access, refresh):
            assert cookie["httponly"] and cookie["secure"] and cookie["samesite"] == "Lax"
        assert access["path"] == "/"
        assert refresh["path"] == "/api/auth/user/"  # refresh token is not sent to normal API calls
        assert int(access["max-age"]) == 600

    def test_jwt_claims_contain_no_password_or_secret(self, browser, user):
        resp = user_login(browser, user.email)
        claims = decode_payload(resp.cookies["hp_access"].value)
        assert set(claims) == {"token_type", "exp", "iat", "jti", "user_id"}
        assert PASSWORD not in str(claims)

    def test_wrong_password_and_unknown_email_give_the_same_generic_error(self, browser, user):
        wrong = user_login(browser, user.email, "Wrong-Passw0rd!!")
        unknown = user_login(browser, "ghost@example.test")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()
        assert wrong.json()["error"]["code"] == "invalid_credentials"
        assert "hp_access" not in wrong.cookies

    def test_login_is_case_insensitive_on_email(self, browser, user):
        assert user_login(browser, user.email.upper()).status_code == 200

    def test_admin_credentials_do_not_work_on_user_login(self, browser, admin):
        assert user_login(browser, admin.email).status_code == 401

    def test_deactivated_account_cannot_log_in(self, browser, user):
        user.is_active = False
        user.save()
        assert user_login(browser, user.email).status_code == 401

    def test_login_requires_csrf(self, browser, user):
        resp = browser.post("/api/auth/user/login/", {"email": user.email, "password": PASSWORD}, csrf=False)
        assert resp.status_code == 403

    def test_login_is_rate_limited(self, browser, user):
        codes = [user_login(browser, user.email, "Wrong-Passw0rd!!").status_code for _ in range(11)]
        assert codes[:10] == [401] * 10
        assert codes[10] == 429
        # Even the right password is refused while throttled.
        assert user_login(browser, user.email).status_code == 429


@pytest.mark.django_db
class TestJwtProtection:
    def test_protected_endpoint_requires_authentication(self, browser):
        resp = browser.get(ME)
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "not_authenticated"

    def test_valid_cookie_grants_access(self, user_browser):
        assert user_browser.get(ME).status_code == 200

    def test_expired_access_token_is_rejected(self, browser, user):
        browser.cookies["hp_access"] = expired_access_token(user)
        resp = browser.get(ME)
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "token_not_valid"

    @pytest.mark.parametrize("garbage", ["not-a-jwt", "a.b.c", ""])
    def test_malformed_token_is_rejected(self, browser, garbage):
        browser.cookies["hp_access"] = garbage
        assert browser.get(ME).status_code == 401

    def test_tampered_payload_fails_signature_check(self, browser, user, admin):
        token = str(AccessToken.for_user(user))
        browser.cookies["hp_access"] = tamper_payload(token, user_id=admin.id)
        assert browser.get(ME).status_code == 401

    def test_alg_none_forgery_is_rejected(self, browser, user):
        browser.cookies["hp_access"] = unsigned_token(token_type="access", user_id=user.id, exp=9999999999, jti="x")
        assert browser.get(ME).status_code == 401

    def test_refresh_token_cannot_be_used_as_access_token(self, browser, user):
        browser.cookies["hp_access"] = str(RefreshToken.for_user(user))
        assert browser.get(ME).status_code == 401

    def test_authorization_header_is_ignored(self, browser, user):
        token = str(AccessToken.for_user(user))
        assert browser.get(ME, HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401

    def test_unsafe_request_with_cookie_but_no_csrf_token_is_blocked(self, user_browser):
        resp = user_browser.patch(ME, {"full_name": "Hacked Name"}, csrf=False)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "csrf_failed"

    def test_user_jwt_gives_no_admin_privileges(self, user_browser):
        for url in ("/api/admin/me/", "/api/admin/profiles/", "/api/admin/profiles/1/"):
            assert user_browser.get(url).status_code == 401
        assert user_browser.post("/api/admin/profiles/1/deactivate/").status_code in (401, 403)

    def test_deactivated_user_loses_access_immediately(self, user_browser, user):
        assert user_browser.get(ME).status_code == 200
        User.objects.filter(pk=user.pk).update(is_active=False)
        assert user_browser.get(ME).status_code == 401


@pytest.mark.django_db
class TestRefreshAndLogout:
    def test_refresh_rotates_tokens_and_old_refresh_is_single_use(self, browser, user):
        login = user_login(browser, user.email)
        old_refresh = login.cookies["hp_refresh"].value

        resp = browser.post("/api/auth/user/refresh/")
        assert resp.status_code == 200
        assert resp.cookies["hp_refresh"].value != old_refresh
        assert browser.get(ME).status_code == 200

        replay = Browser()
        replay.cookies["hp_refresh"] = old_refresh
        assert replay.post("/api/auth/user/refresh/").status_code == 401

    def test_refresh_without_cookie_is_401(self, browser):
        assert browser.post("/api/auth/user/refresh/").status_code == 401

    def test_refresh_denied_after_deactivation(self, browser, user):
        user_login(browser, user.email)
        User.objects.filter(pk=user.pk).update(is_active=False)
        assert browser.post("/api/auth/user/refresh/").status_code == 401

    def test_admin_cannot_obtain_user_tokens_via_refresh(self, browser, admin):
        browser.cookies["hp_refresh"] = str(RefreshToken.for_user(admin))
        assert browser.post("/api/auth/user/refresh/").status_code == 401

    def test_logout_clears_cookies_and_blacklists_refresh_token(self, user_browser):
        refresh = user_browser.cookies["hp_refresh"].value
        resp = user_browser.post("/api/auth/user/logout/")
        assert resp.status_code == 200
        assert resp.cookies["hp_access"].value == "" and resp.cookies["hp_refresh"].value == ""

        stolen = Browser()
        stolen.cookies["hp_refresh"] = refresh
        assert stolen.post("/api/auth/user/refresh/").status_code == 401

    def test_after_logout_browser_is_unauthenticated(self, user_browser):
        user_browser.post("/api/auth/user/logout/")
        # Browsers delete the expired cookies; the test client keeps them, so emulate the browser.
        user_browser.cookies.pop("hp_access", None)
        assert user_browser.get(ME).status_code == 401

    def test_logout_requires_csrf(self, user_browser):
        assert user_browser.post("/api/auth/user/logout/", csrf=False).status_code == 403

    def test_logout_is_idempotent_when_signed_out(self, browser):
        assert browser.post("/api/auth/user/logout/").status_code == 200


@pytest.mark.django_db
def test_admin_session_does_not_authenticate_user_endpoints(admin, browser):
    assert admin_login(browser, admin.email).status_code == 200
    assert browser.get(ME).status_code == 401
