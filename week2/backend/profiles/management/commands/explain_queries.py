"""Print query plans for the queries our indexes exist to serve (assignment: demonstrate an indexed query)."""

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from accounts.models import User
from audit.models import AuditEvent
from profiles.models import HealthProfile


class Command(BaseCommand):
    help = "Show EXPLAIN output for the login lookup and the admin dashboard queries."

    def handle(self, *args, **options):
        queries = {
            "1. Login lookup by email  (unique index on accounts_user.email)":
                User.objects.filter(email="amina.rahman@example.test"),
            "2. Admin list: status filter + newest first  (composite index hp_status_created_idx)":
                HealthProfile.objects.filter(status="active").order_by("-created_at")[:10],
            "3. Admin list sorted by name  (index hp_full_name_idx)":
                HealthProfile.objects.order_by("full_name")[:10],
            "4. Incomplete profiles, newest first  (composite index hp_completion_created_idx)":
                HealthProfile.objects.filter(completion_status="incomplete").order_by("-created_at")[:10],
            "5. Audit history of one profile, incl. after deletion  (composite index audit_subject_created_idx)":
                AuditEvent.objects.filter(subject_profile_id=1).order_by("-created_at")[:20],
            "6. Nulling the FK when a profile is deleted  (composite index audit_profile_created_idx)":
                AuditEvent.objects.filter(profile_id=1).values("id"),
        }
        self.stdout.write(f"Database: {connection.vendor} | profiles: {HealthProfile.objects.count()}\n")
        with transaction.atomic():
            if connection.vendor == "postgresql":
                # On tiny tables PostgreSQL's planner prefers a seq scan. Discourage it so the plan
                # shows which index *would* be used as the table grows. Rolled back with the transaction.
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL enable_seqscan = off")
            for title, queryset in queries.items():
                self.stdout.write(self.style.MIGRATE_HEADING(title))
                self.stdout.write(str(queryset.query))
                self.stdout.write(queryset.explain() + "\n")
