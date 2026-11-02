"""EXPLAIN ANALYZE the exact SQL the admin endpoints execute, on synthetic data.

The SQL is not hand-written: each scenario runs the real DRF view code (get_queryset, the search
and ordering filters, the paginator's COUNT and the page slice) and captures what Django sends.

Reproduce (PostgreSQL only, uses a throwaway database):
    createdb hp_bench
    export DATABASE_URL=postgres://localhost/hp_bench
    python manage.py migrate
    python manage.py seed_demo --bulk 20000 --bulk-audit 60000
    python manage.py benchmark_admin_queries --compare-without-index

Numbers are from synthetic rows on whatever machine runs this. They show the effect of an index on
a plan; they do not predict production latency.
"""

import statistics

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count
from django.test.utils import CaptureQueriesContext
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from accounts.models import User
from adminpanel.views import AdminAuditEventListView, AdminProfileListView
from audit.models import AuditEvent
from profiles.models import HealthProfile

TABLES = ["accounts_user", "profiles_healthprofile", "audit_auditevent"]


def endpoint_sql(view_class, path: str, params: dict) -> list[tuple[str, str]]:
    """Run the view's queryset pipeline exactly as a GET would, and return the SQL it executed."""
    view = view_class()
    view.request = Request(APIRequestFactory().get(path, params))
    view.args, view.kwargs, view.format_kwarg = (), {}, None
    queryset = view.filter_queryset(view.get_queryset())
    with CaptureQueriesContext(connection) as captured:
        view.paginate_queryset(queryset)  # COUNT(*) then the LIMIT/OFFSET page, as in list()
    labels = ["paginator COUNT", "page of rows"]
    return [
        (labels[i] if i < len(labels) else f"query {i + 1}", q["sql"]) for i, q in enumerate(captured.captured_queries)
    ]


class Command(BaseCommand):
    help = "EXPLAIN (ANALYZE, BUFFERS) the admin endpoints' exact SQL. PostgreSQL only; synthetic data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--repeat", type=int, default=5, help="Runs per query; the median execution time is reported."
        )
        parser.add_argument(
            "--compare-without-index",
            action="store_true",
            help="Also run each query with its index dropped inside a transaction that is rolled back.",
        )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("Needs PostgreSQL (EXPLAIN ANALYZE timings). For a SQLite plan use explain_queries.")
        if not HealthProfile.objects.filter(user__email__startswith="bulk").exists():
            raise CommandError("No synthetic rows. Run: python manage.py seed_demo --bulk 20000 --bulk-audit 60000")

        with connection.cursor() as cursor:
            for table in TABLES:
                cursor.execute(f"ANALYZE {table}")
        busiest = AuditEvent.objects.values("profile_id").annotate(n=Count("id")).order_by("-n").first() or {}
        scenarios = [
            (
                "GET /api/admin/profiles/?status=active",
                AdminProfileListView,
                "/api/admin/profiles/",
                {"status": "active"},
                "hp_status_created_idx",
            ),
            (
                "GET /api/admin/profiles/?completion=incomplete",
                AdminProfileListView,
                "/api/admin/profiles/",
                {"completion": "incomplete"},
                "hp_completion_created_idx",
            ),
            (
                "GET /api/admin/profiles/?ordering=full_name",
                AdminProfileListView,
                "/api/admin/profiles/",
                {"ordering": "full_name"},
                "hp_full_name_idx",
            ),
            (
                "GET /api/admin/profiles/?search=khan  (ILIKE '%khan%': no B-tree index can serve it)",
                AdminProfileListView,
                "/api/admin/profiles/",
                {"search": "khan"},
                None,
            ),
            (
                f"GET /api/admin/audit-events/?profile={busiest.get('profile_id')}  (busiest profile, {busiest.get('n')} events)",
                AdminAuditEventListView,
                "/api/admin/audit-events/",
                {"profile": str(busiest.get("profile_id"))},
                "audit_profile_created_idx",
            ),
        ]

        self._header()
        for title, view_class, path, params, index in scenarios:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n## {title}"))
            for label, sql in endpoint_sql(view_class, path, params):
                self.stdout.write(f"\n### {label}\n{sql}\n")
                self._explain("with indexes", sql, options["repeat"])
                if options["compare_without_index"] and index:
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(f"DROP INDEX {index}")
                        self._explain(f"without {index}", sql, options["repeat"])
                        transaction.set_rollback(True)  # the index comes straight back

    def _header(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0]
            cursor.execute(
                "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE tablename = ANY(%s) ORDER BY 1, 2",
                [TABLES],
            )
            indexes = cursor.fetchall()
        self.stdout.write("# Admin endpoint query plans (SYNTHETIC DATA: not a production latency prediction)\n")
        self.stdout.write(f"Database: {version}")
        self.stdout.write(
            f"Rows: {User.objects.count()} users, {HealthProfile.objects.count()} profiles, "
            f"{AuditEvent.objects.count()} audit events"
        )
        self.stdout.write("Data: seed_demo --bulk / --bulk-audit (random.Random(42), fictional names, .test emails)")
        self.stdout.write("Indexes:")
        for table, name, definition in indexes:
            self.stdout.write(f"  {table}.{name}: {definition}")

    def _explain(self, label: str, sql: str, repeat: int):
        times, plan = [], []
        with connection.cursor() as cursor:
            for _ in range(repeat):
                cursor.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql)
                plan = [row[0] for row in cursor.fetchall()]
                times.append(float(next(line for line in plan if line.startswith("Execution Time")).split()[2]))
        self.stdout.write(f"-- {label}: median {statistics.median(times):.3f} ms over {repeat} runs")
        self.stdout.write("\n".join("   " + line for line in plan))
