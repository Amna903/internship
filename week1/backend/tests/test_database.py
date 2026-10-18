import pytest
from django.db import IntegrityError, connection, transaction

from accounts.models import User
from profiles.models import HealthProfile


@pytest.mark.django_db
class TestConstraints:
    def test_email_unique_at_database_level(self):
        User.objects.create_user("dup@example.test", "x")
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(email="dup@example.test", password="!")])  # bypasses save()

    def test_database_rejects_non_normalised_email(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(email="MiXeD@Example.test", password="!")])

    def test_database_rejects_unknown_role(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(email="r@example.test", password="!", role="superhero")])

    def test_dob_and_age_range_are_mutually_exclusive_in_db(self, make_user):
        user = make_user()
        with pytest.raises(IntegrityError), transaction.atomic():
            HealthProfile.objects.filter(user=user).update(date_of_birth="1990-01-01", age_range="25-34")

    def test_profile_status_check_constraint(self, make_user):
        user = make_user()
        with pytest.raises(IntegrityError), transaction.atomic():
            HealthProfile.objects.filter(user=user).update(status="zombie")

    def test_one_profile_per_user(self, make_user):
        user = make_user()
        with pytest.raises(IntegrityError), transaction.atomic():
            HealthProfile.objects.create(user=user, full_name="Second")

    def test_deleting_user_cascades_to_profile(self, make_user):
        user = make_user()
        user.delete()
        assert HealthProfile.objects.count() == 0


@pytest.mark.django_db
class TestIndexes:
    def index_names(self, model):
        with connection.cursor() as cursor:
            return set(connection.introspection.get_constraints(cursor, model._meta.db_table))

    def test_declared_indexes_exist_in_database(self):
        assert {"hp_status_created_idx", "hp_full_name_idx"} <= self.index_names(HealthProfile)

    def test_email_has_a_unique_index(self):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, User._meta.db_table)
        assert any(c["unique"] and c["columns"] == ["email"] for c in constraints.values())

    def test_admin_list_query_uses_the_composite_index(self, make_user):
        for i in range(5):
            make_user(f"u{i}@example.test")
        plan = HealthProfile.objects.filter(status="active").order_by("-created_at")[:10].explain()
        assert "hp_status_created_idx" in plan
