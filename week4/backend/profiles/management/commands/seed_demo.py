"""Seed synthetic demo data. Everything here is fictional; emails use the reserved .test TLD."""

import os
import random
import secrets
from datetime import date, timedelta

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from profiles.completion import evaluate
from profiles.models import HealthProfile

# (name, email-local-part, date_of_birth | None, age_range, contact, goals, allergies, ec name, ec phone, relation, notes)
DEMO_USERS = [
    ("Amina Rahman", "amina.rahman", date(1994, 3, 14), "", "email",
     ["Walk 8,000 steps daily", "Sleep 7+ hours"], ["Pollen"],
     "Tariq Rahman", "+1 555 010 0101", "Brother", "Desk job, trying to move more."),
    ("Daniel Okafor", "daniel.okafor", None, "35-44", "sms",
     ["Reduce sugar intake", "Run a 10k"], [],
     "Ngozi Okafor", "+1 555 010 0102", "Spouse", "Weekend cyclist."),
    ("Sofia Marin", "sofia.marin", date(1988, 11, 2), "", "phone",
     ["Build a stretching routine"], ["Peanuts", "Latex"],
     "Elena Marin", "+1 555 010 0103", "Mother", ""),
    ("Hiroshi Tanaka", "hiroshi.tanaka", None, "55-64", "email",
     ["Improve balance", "Join a walking group"], [],
     "Yuki Tanaka", "+1 555 010 0104", "Daughter", "Prefers morning activity."),
    ("Lena Fischer", "lena.fischer", date(2001, 6, 21), "", "none",
     ["Try meal prepping", "Drink more water"], ["Shellfish"],
     "Jonas Fischer", "+1 555 010 0105", "Friend", "Student, irregular schedule."),
    # Deliberately left without an emergency contact so the demo has an incomplete profile.
    ("Carlos Mendez", "carlos.mendez", None, "25-34", "email",
     ["Lower stress", "Meditate 10 min/day"], [],
     "", "", "", ""),
]

_FIRST = ["Alex", "Bina", "Chen", "Dara", "Eli", "Farah", "Gus", "Hana", "Ivan", "Jia", "Kofi", "Lia", "Mo", "Nia"]
_LAST = ["Abbas", "Bauer", "Cruz", "Dubois", "Evans", "Farouk", "Gomez", "Hughes", "Ito", "Jensen", "Khan", "Lopez"]
_GOALS = ["Sleep better", "Walk more", "Eat more vegetables", "Stretch daily", "Cut caffeine", "Try yoga"]


class Command(BaseCommand):
    help = "Create the demo admin, at least 5 synthetic users with profiles, and optional bulk filler rows."

    def add_arguments(self, parser):
        parser.add_argument("--bulk", type=int, default=0, help="Also create N synthetic filler users (for EXPLAIN demos).")
        parser.add_argument(
            "--bulk-audit", type=int, default=0,
            help="Also create N synthetic audit events spread over the bulk profiles (for EXPLAIN demos).",
        )

    def handle(self, *args, **options):
        admin_email = os.environ.get("SEED_ADMIN_EMAIL", "admin@example.test").strip().lower()
        admin_pw = os.environ.get("SEED_ADMIN_PASSWORD") or secrets.token_urlsafe(14)
        user_pw = os.environ.get("SEED_USER_PASSWORD") or secrets.token_urlsafe(14)
        generated = []

        with transaction.atomic():
            if not User.objects.filter(email=admin_email).exists():
                User.objects.create_admin(admin_email, admin_pw)
                self.stdout.write(f"Created admin {admin_email}")
                if not os.environ.get("SEED_ADMIN_PASSWORD"):
                    generated.append(f"admin password: {admin_pw}")

            created = 0
            for name, local, dob, age, contact, goals, allergies, ec_name, ec_phone, ec_rel, notes in DEMO_USERS:
                email = f"{local}@example.test"
                if User.objects.filter(email=email).exists():
                    continue
                user = User.objects.create_user(email, user_pw)
                HealthProfile.objects.create(
                    user=user, full_name=name, date_of_birth=dob, age_range=age, contact_preference=contact,
                    wellness_goals=goals, allergies=allergies, emergency_contact_name=ec_name,
                    emergency_contact_phone=ec_phone, emergency_contact_relationship=ec_rel, lifestyle_notes=notes,
                )
                created += 1
            if created and not os.environ.get("SEED_USER_PASSWORD"):
                generated.append(f"user password (all seeded users): {user_pw}")
            self.stdout.write(f"Created {created} synthetic demo users")

            if options["bulk"]:
                self._bulk(options["bulk"])
            if options["bulk_audit"]:
                self._bulk_audit(options["bulk_audit"])

        for line in generated:
            self.stdout.write(self.style.WARNING(f"  {line}"))

    def _bulk(self, count: int):
        """Filler rows for query-plan demos. Unusable passwords: these accounts cannot log in."""
        rng = random.Random(42)  # deterministic
        unusable = make_password(None)
        existing = User.objects.filter(email__startswith="bulk").count()
        users = [
            User(email=f"bulk{existing + i:06d}@example.test", password=unusable, role=User.Role.USER)
            for i in range(count)
        ]
        User.objects.bulk_create(users)
        fresh = list(User.objects.filter(email__in=[u.email for u in users]))
        now = timezone.now()
        profiles = []
        for user in fresh:
            deactivated = rng.random() < 0.1
            has_contact = rng.random() < 0.6
            profile = HealthProfile(
                user=user,
                full_name=f"{rng.choice(_FIRST)} {rng.choice(_LAST)}",
                age_range=rng.choice(HealthProfile.AgeRange.values),
                contact_preference=rng.choice(HealthProfile.ContactPreference.values),
                wellness_goals=rng.sample(_GOALS, 2),
                emergency_contact_name=f"{rng.choice(_FIRST)} {rng.choice(_LAST)}" if has_contact else "",
                emergency_contact_phone="+1 555 010 0199" if has_contact else "",
                emergency_contact_relationship="Friend" if has_contact else "",
                status=HealthProfile.Status.DEACTIVATED if deactivated else HealthProfile.Status.ACTIVE,
                deactivated_at=now if deactivated else None,
            )
            profile.completion_status = evaluate(profile).status  # bulk_create skips save()
            profiles.append(profile)
        HealthProfile.objects.bulk_create(profiles)
        # bulk_create bypasses auto_now_add's per-row clock; spread created_at so ordering is meaningful.
        for offset, profile in enumerate(HealthProfile.objects.filter(user__in=fresh).order_by("id")):
            profile.created_at = now - timedelta(minutes=offset)
            profile.save(update_fields=["created_at"])
        User.objects.filter(pk__in=[u.pk for u in fresh if u.profile.status == "deactivated"]).update(is_active=False)
        self.stdout.write(f"Created {count} bulk filler users")

    def _bulk_audit(self, count: int):
        """Filler audit events, deterministic (seed 42), timestamps spread over the last ~60 days.

        Inserts only: the audit table rejects UPDATE, so created_at is set at insert time instead of
        afterwards. auto_now_add is switched off just for this bulk insert.
        """
        rng = random.Random(42)
        profiles = list(HealthProfile.objects.filter(user__email__startswith="bulk").values_list("id", "user_id"))
        if not profiles:
            self.stdout.write(self.style.WARNING("No bulk profiles: run with --bulk first."))
            return
        admin = User.objects.filter(role=User.Role.ADMIN).first()
        now = timezone.now()
        events = []
        for i in range(count):
            profile_id, owner_id = rng.choice(profiles)
            by_admin = admin is not None and rng.random() < 0.3
            events.append(AuditEvent(
                actor_id=admin.id if by_admin else owner_id,
                actor_role="admin" if by_admin else "user",
                action=AuditEvent.Action.ADMIN_PROFILE_VIEWED if by_admin else AuditEvent.Action.PROFILE_UPDATED,
                profile_id=profile_id,
                changed_fields=[] if by_admin else ["lifestyle_notes"],
                created_at=now - timedelta(seconds=rng.randint(0, 60 * 24 * 3600)),
            ))
        created_at = AuditEvent._meta.get_field("created_at")
        created_at.auto_now_add = False
        try:
            AuditEvent.objects.bulk_create(events, batch_size=5000)
        finally:
            created_at.auto_now_add = True
        self.stdout.write(f"Created {count} bulk audit events")
