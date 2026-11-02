import pytest

from accounts.models import User
from audit.models import AuditEvent
from profiles.models import HealthProfile

from .conftest import Browser, user_login

ME = "/api/profiles/me/"


@pytest.mark.django_db
class TestOwnProfile:
    def test_get_returns_own_profile(self, user_browser, user):
        data = user_browser.get(ME).json()
        assert data["email"] == user.email
        assert data["full_name"] == "Alice Example"
        assert data["status"] == "active"
        assert "created_at" in data and "updated_at" in data

    def test_partial_update_changes_only_sent_fields(self, user_browser, user):
        resp = user_browser.patch(ME, {"wellness_goals": ["Sleep 8 hours"], "contact_preference": "sms"})
        assert resp.status_code == 200
        profile = HealthProfile.objects.get(user=user)
        assert profile.wellness_goals == ["Sleep 8 hours"]
        assert profile.contact_preference == "sms"
        assert profile.full_name == "Alice Example"  # untouched

    def test_full_profile_update_with_all_fields(self, user_browser, user):
        payload = {
            "full_name": "Alice Q. Example",
            "date_of_birth": "1990-05-17",
            "contact_preference": "phone",
            "wellness_goals": ["Walk more", "Eat more vegetables"],
            "allergies": ["Pollen"],
            "emergency_contact_name": "Sam Example",
            "emergency_contact_phone": "+1 555 010 0199",
            "emergency_contact_relationship": "Sibling",
            "lifestyle_notes": "Works from home.",
        }
        resp = user_browser.patch(ME, payload)
        assert resp.status_code == 200
        for key, value in payload.items():
            assert resp.json()[key] == value

    def test_updated_at_changes_on_update(self, user_browser, user):
        before = HealthProfile.objects.get(user=user).updated_at
        user_browser.patch(ME, {"lifestyle_notes": "changed"})
        assert HealthProfile.objects.get(user=user).updated_at > before

    @pytest.mark.parametrize(
        "payload, field",
        [
            ({"date_of_birth": "2999-01-01"}, "date_of_birth"),
            ({"date_of_birth": "1800-01-01"}, "date_of_birth"),
            ({"date_of_birth": "not-a-date"}, "date_of_birth"),
            ({"age_range": "200+"}, "age_range"),
            ({"date_of_birth": "1990-01-01", "age_range": "25-34"}, "age_range"),
            ({"contact_preference": "carrier-pigeon"}, "contact_preference"),
            ({"emergency_contact_phone": "call me maybe"}, "emergency_contact_phone"),
            ({"wellness_goals": ["x"] * 11}, "wellness_goals"),
            ({"wellness_goals": "not-a-list"}, "wellness_goals"),
            ({"allergies": ["y" * 101]}, "allergies"),
            ({"full_name": "A"}, "full_name"),
            ({"full_name": ""}, "full_name"),
            ({"lifestyle_notes": "z" * 1001}, "lifestyle_notes"),
        ],
    )
    def test_validation_errors(self, user_browser, payload, field):
        resp = user_browser.patch(ME, payload)
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "validation_error"
        assert field in resp.json()["error"]["details"]

    def test_setting_dob_clears_age_range_and_vice_versa(self, user_browser):
        user_browser.patch(ME, {"age_range": "25-34"})
        resp = user_browser.patch(ME, {"date_of_birth": "1995-02-02"})
        assert resp.json()["age_range"] == "" and resp.json()["date_of_birth"] == "1995-02-02"
        resp = user_browser.patch(ME, {"age_range": "35-44"})
        assert resp.json()["date_of_birth"] is None and resp.json()["age_range"] == "35-44"

    def test_read_only_and_foreign_fields_are_ignored(self, user_browser, user, other_user):
        original_email = user.email
        user_browser.patch(
            ME,
            {
                "status": "deactivated",
                "created_at": "2000-01-01T00:00:00Z",
                "email": "evil@example.test",
                "user": other_user.id,
                "user_id": other_user.id,
                "id": 9999,
            },
        )
        profile = HealthProfile.objects.get(user=user)
        assert profile.status == "active"
        assert profile.created_at.year != 2000
        assert profile.user_id == user.id
        user.refresh_from_db()
        assert user.email == original_email
        assert User.objects.get(pk=other_user.pk).email == "bob@example.test"

    def test_post_conflicts_when_profile_exists(self, user_browser):
        resp = user_browser.post(ME, {"full_name": "Dup"})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "conflict"

    def test_post_creates_profile_when_missing(self, db, browser):
        orphan = User.objects.create_user("orphan@example.test", "Sturdy-Passw0rd!x")
        user_login(browser, orphan.email)
        assert browser.get(ME).status_code == 404
        resp = browser.post(ME, {"full_name": "Orphan Person"})
        assert resp.status_code == 201
        assert HealthProfile.objects.get(user=orphan).full_name == "Orphan Person"

    def test_unauthenticated_access_is_rejected(self, browser):
        assert browser.get(ME).status_code == 401
        assert browser.patch(ME, {"full_name": "Nope"}).status_code == 401


@pytest.mark.django_db
class TestCrossUserAccess:
    def test_each_user_sees_only_their_own_profile(self, user, other_user):
        a, b = Browser(), Browser()
        user_login(a, user.email)
        user_login(b, other_user.email)
        assert a.get(ME).json()["email"] == user.email
        assert b.get(ME).json()["email"] == other_user.email

    def test_patch_never_touches_another_users_profile(self, user, other_user):
        a = Browser()
        user_login(a, user.email)
        victim = HealthProfile.objects.get(user=other_user)
        a.patch(ME, {"full_name": "Pwned", "user": other_user.id, "id": victim.id})
        victim.refresh_from_db()
        assert victim.full_name == "Bob Example"
        assert HealthProfile.objects.get(user=user).full_name == "Pwned"

    def test_there_is_no_route_to_address_another_profile_by_id(self, user_browser, other_user):
        pk = HealthProfile.objects.get(user=other_user).pk
        for path in (f"/api/profiles/{pk}/", f"/api/profiles/{other_user.pk}/", f"/api/users/{other_user.pk}/"):
            assert user_browser.get(path).status_code == 404
            assert user_browser.patch(path, {"full_name": "x"}).status_code == 404

    def test_other_users_data_never_appears_in_response(self, user_browser, other_user):
        assert other_user.email not in user_browser.get(ME).content.decode()

    def test_cannot_use_a_token_belonging_to_a_different_user(self, user, other_user):
        a, b = Browser(), Browser()
        user_login(a, user.email)
        user_login(b, other_user.email)
        b_token = b.cookies["hp_access"].value
        a.cookies["hp_access"] = b_token  # the token still identifies b, never a
        assert a.get(ME).json()["email"] == other_user.email


@pytest.mark.django_db
class TestDeleteOwnProfile:
    """The D in CRUD: a member can delete their own profile, and only their own."""

    def test_member_deletes_own_profile_and_account_remains(self, user_browser, user, other_user):
        resp = user_browser.client.delete(ME, HTTP_X_CSRFTOKEN=user_browser.cookies["csrftoken"].value)
        assert resp.status_code == 204
        assert not HealthProfile.objects.filter(user=user).exists()
        assert HealthProfile.objects.filter(user=other_user).exists()  # nobody else touched
        user.refresh_from_db()
        assert user.is_active  # account kept; profile only
        assert user_browser.get(ME).status_code == 404

    def test_delete_is_audited_without_profile_data(self, user_browser, user):
        name = user.profile.full_name
        user_browser.client.delete(ME, HTTP_X_CSRFTOKEN=user_browser.cookies["csrftoken"].value)
        event = AuditEvent.objects.get(action="profile.deleted")
        assert event.actor == user and event.actor_role == "user"
        # The id is kept as a stable identifier (no SET NULL cascade); the profile row itself is gone.
        assert event.profile_id is not None and not HealthProfile.objects.filter(pk=event.profile_id).exists()
        assert name not in str(event.changed_fields)

    def test_member_can_create_a_new_profile_after_deleting(self, user_browser):
        user_browser.client.delete(ME, HTTP_X_CSRFTOKEN=user_browser.cookies["csrftoken"].value)
        resp = user_browser.post(ME, {"full_name": "Fresh Start"})
        assert resp.status_code == 201 and resp.json()["completion"]["percent"] == 0

    def test_second_delete_is_404(self, user_browser):
        csrf = user_browser.cookies["csrftoken"].value
        assert user_browser.client.delete(ME, HTTP_X_CSRFTOKEN=csrf).status_code == 204
        assert user_browser.client.delete(ME, HTTP_X_CSRFTOKEN=csrf).status_code == 404

    def test_delete_requires_csrf(self, user_browser, user):
        assert user_browser.client.delete(ME).status_code == 403
        assert HealthProfile.objects.filter(user=user).exists()

    def test_anonymous_and_admin_cannot_delete_through_member_route(self, browser, admin_browser, user):
        assert browser.client.delete(ME, HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value).status_code == 401
        resp = admin_browser.client.delete(ME, HTTP_X_CSRFTOKEN=admin_browser.cookies["csrftoken"].value)
        assert resp.status_code in (401, 403)
        assert HealthProfile.objects.filter(user=user).exists()
