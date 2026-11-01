# Week 2 requirement → evidence checklist

One row per requirement in the **full-stack brief** (Role-Based Health Profiles and Database Engineering). Each row gives:
- the code that implements it,
- the automated test that checks it,
- the moment in the Loom demo that shows it.

> The requirement wording comes from the README checklist. Check it against the brief PDF and add any requirement that's missing before relying on this table.

**Who ran what.** Keep these separate:

| Source | Meaning |
|---|---|
| **CI** | `.github/workflows/ci.yml` runs every backend test on PostgreSQL 16 and SQLite, plus frontend typecheck, tests and build, on every push and PR. |
| **AI session** | Claude Code ran it during development (2026-10-21): 192 passed + 1 PostgreSQL-only skip on SQLite; the full suite on PostgreSQL 14.21; the benchmark in `docs/benchmarks/`. |
| **Me** | Fill in the date you re-ran it yourself. Don't tick this column until you have. |

Demo column: section numbers of the Loom walkthrough. Replace them with timestamps once it's recorded.

| # | Requirement | Code | Test(s) | Demo | Me |
|---|---|---|---|---|---|
| 1 | Members sign up and log in with JWT | `accounts/views.py` (`SignupView`, `UserLoginView`), `accounts/cookies.py` | `test_signup.py::test_valid_signup_creates_user_and_profile`, `test_user_auth.py::test_login_sets_httponly_cookies_and_returns_no_token_in_body` | §2 | ☐ |
| 2 | Admins created only by management command; session login | `accounts/management/commands/create_admin.py`, `adminpanel/views.py::AdminLoginView` | `test_signup.py::test_cannot_self_register_as_admin`, `::test_no_public_admin_signup_endpoint_exists`, `test_admin.py::test_login_sets_httponly_session_cookie` | §3 | ☐ |
| 3 | Admin session and member JWT paths stay distinct | `DEFAULT_AUTHENTICATION_CLASSES = []` in `config/settings.py`; per-view authenticators | `test_user_auth.py::test_user_jwt_gives_no_admin_privileges`, `::test_admin_session_does_not_authenticate_user_endpoints`, `::TestLogoutAndRevocationLifecycle::test_member_and_admin_sign_outs_are_independent` | §4 | ☐ |
| 4 | Profile sections: demographics, emergency contact, wellness preferences | `profiles/models.py`, `profiles/serializers.py`, `frontend/app/profile/page.tsx` | `test_profiles.py::test_full_profile_update_with_all_fields` | §2 | ☐ |
| 5 | Profile completion status | `profiles/completion.py`, `completion_status` column | `test_completion.py` (10 tests, e.g. `::test_completion_cannot_be_set_by_the_client`) | §2 | ☐ |
| 6 | User-owned profile CRUD | `profiles/views.py::MeProfileView` (POST/GET/PATCH/DELETE `/api/profiles/me/`) | `test_profiles.py::TestDeleteOwnProfile`, `::test_post_creates_profile_when_missing`, `::test_partial_update_changes_only_sent_fields` | §2 | ☐ |
| 7 | **No horizontal privilege escalation**: a member can't read or change another member's profile, including by direct API request and after logout or expiry | No `/profiles/<id>` route for members; user taken from the token | `test_profiles.py::test_there_is_no_route_to_address_another_profile_by_id`, `::test_patch_never_touches_another_users_profile`, `::test_cannot_use_a_token_belonging_to_a_different_user`, `test_user_auth.py::test_expired_access_token_is_rejected`, `::TestLogoutAndRevocationLifecycle::test_access_token_copied_before_logout_is_rejected_after_logout`, `::test_copied_access_token_cannot_change_the_profile_after_logout` | §4 | ☐ |
| 8 | Admin-only listing, search, filter, pagination | `adminpanel/views.py::AdminProfileListView` | `test_admin.py::test_search_by_name_and_email_case_insensitive`, `::test_ordering_and_status_filter_and_invalid_status`, `::test_pagination`, `::test_anonymous_is_rejected`, `::test_standard_user_jwt_does_not_grant_admin_access` | §3, §4 | ☐ |
| 9 | Audit events for profile edits and admin actions, with no values or secrets stored | `audit/` app, `audit/services.py` | `test_audit.py::test_values_and_secrets_are_never_stored`, `::test_login_view_deactivate_activate_logout_are_all_recorded`, `::test_failed_admin_login_is_recorded_against_the_targeted_account` | §5 | ☐ |
| 10 | **Audit stays attributable after deletion** (stable id plus deletion marker) | `audit/models.py` (no-constraint FKs), `AuditEventSerializer.profile_deleted` / `actor_deleted` | `test_audit.py::TestDeletionKeepsAttribution` (3 tests) | §5 | ☐ |
| 11 | **Audit log is append-only**, enforced by the database, not only the model | Triggers in `audit/migrations/0004_immutable_stable_ids.py` | `test_audit.py::TestDatabaseEnforcesAppendOnly`: queryset update/delete, bulk_update, raw SQL, TRUNCATE (PostgreSQL), triggers present | §5 | ☐ |
| 12 | Validate input; hide sensitive fields | Serializers; read-only `status`, `completion`, `email` | `test_profiles.py::test_validation_errors`, `::test_read_only_and_foreign_fields_are_ignored`, `test_signup.py::test_response_never_contains_password_or_hash`, `test_admin.py::test_list_never_exposes_password_hashes` | §2 | ☐ |
| 13 | Hashed passwords, JWT expiry and refresh, secure token storage, CSRF | Argon2id in `settings.py`; `accounts/cookies.py`; `CookieJWTAuthentication._enforce_csrf` | `test_signup.py::test_password_is_hashed_not_stored_in_plaintext`, `test_user_auth.py::test_refresh_rotates_tokens_and_old_refresh_is_single_use`, `::test_unsafe_request_with_cookie_but_no_csrf_token_is_blocked` | §2 | ☐ |
| 14 | Normalised relations, foreign keys, unique and indexed fields | `accounts/models.py`, `profiles/models.py`, `audit/models.py` | `test_database.py` (10 tests, e.g. `::test_email_unique_at_database_level`, `::test_declared_indexes_exist_in_database`) | (none) | ☐ |
| 15 | Migrations | `*/migrations/` | CI step `makemigrations --check` (fails if a model change has no migration) | §6 | ☐ |
| 16 | Composite indexes justified by query patterns, with EXPLAIN evidence | `profiles/models.py`, `audit/models.py` | `test_database.py::test_admin_list_query_uses_the_composite_index`; reproducible `benchmark_admin_queries` ([explain-postgres.md](explain-postgres.md)) | §6 | ☐ |
| 17 | API docs | drf-spectacular, `/api/docs/` | (manual) | (none) | ☐ |
| 18 | Production configuration fails closed | `config/settings.py` | `test_config.py` (14 tests) | §6 | ☐ |
| 19 | CI blocks merging on failure | `.github/workflows/ci.yml` (`ci-passed` job) | Needs branch protection on `main` requiring `ci-passed` (repository setting, see README) | §6 | ☐ |
