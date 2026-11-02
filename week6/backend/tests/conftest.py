import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import User
from profiles.models import HealthProfile

PASSWORD = "Sturdy-Passw0rd!x"


@pytest.fixture(autouse=True)
def _fast_password_hasher(settings):
    # Argon2 is deliberately slow; tests only need *a* hash, not a strong one.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


class Browser:
    """A cookie-keeping client that behaves like the SPA: CSRF checks are ON, and the CSRF
    cookie is fetched on start-up and echoed back in X-CSRFToken for unsafe requests."""

    def __init__(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.get("/api/auth/csrf/")

    @property
    def cookies(self):
        return self.client.cookies

    def _csrf_headers(self):
        morsel = self.client.cookies.get("csrftoken")
        return {"HTTP_X_CSRFTOKEN": morsel.value} if morsel else {}

    def get(self, url, params=None, **extra):
        return self.client.get(url, params, **extra)

    def _unsafe(self, method, url, data, csrf):
        headers = self._csrf_headers() if csrf else {}
        return getattr(self.client, method)(url, data if data is not None else {}, format="json", **headers)

    def post(self, url, data=None, csrf=True):
        return self._unsafe("post", url, data, csrf)

    def patch(self, url, data=None, csrf=True):
        return self._unsafe("patch", url, data, csrf)


@pytest.fixture
def browser():
    return Browser()


@pytest.fixture
def make_user(db):
    def _make(email="user@example.test", password=PASSWORD, name="Test User"):
        user = User.objects.create_user(email, password)
        HealthProfile.objects.create(user=user, full_name=name)
        return user

    return _make


@pytest.fixture
def user(make_user):
    return make_user("alice@example.test", name="Alice Example")


@pytest.fixture
def other_user(make_user):
    return make_user("bob@example.test", name="Bob Example")


@pytest.fixture
def admin(db):
    return User.objects.create_admin("root@example.test", PASSWORD)


def user_login(browser, email, password=PASSWORD):
    return browser.post("/api/auth/user/login/", {"email": email, "password": password})


def admin_login(browser, email, password=PASSWORD):
    return browser.post("/api/admin/login/", {"email": email, "password": password})


@pytest.fixture
def user_browser(user):
    b = Browser()
    assert user_login(b, user.email).status_code == 200
    return b


@pytest.fixture
def admin_browser(admin):
    b = Browser()
    assert admin_login(b, admin.email).status_code == 200
    return b


# Week 6 Step 5: CI runs three groups by marker. Files not listed here are unit/API integration tests.
RAG_FILES = (
    "test_assistant_",
    "test_retrieval_",
    "test_generation_",
    "test_conversation_",
    "test_dev_questions",
    "test_eval_freeze",
    "test_index_",
)
ML_FILES = ("test_ml_", "test_holdout", "test_release_rule", "test_cluster_features", "test_supervised_doc")


def ci_group(filename):
    if filename.startswith(RAG_FILES):
        return "rag"
    if filename.startswith(ML_FILES):
        return "ml_pipeline"
    return None


def pytest_collection_modifyitems(config, items):
    for item in items:
        group = ci_group(item.path.name)
        if group:
            item.add_marker(getattr(pytest.mark, group))
