"""Make the audit table append-only at the database level.

1. Turn the actor/profile foreign keys into stable identifiers (no DB constraint, DO_NOTHING):
   deleting a user or profile no longer rewrites audit rows via ON DELETE SET NULL.
2. Restore profile_id on rows whose link was already nulled, from the copy kept in 0003.
3. Drop that now-redundant copy.
4. Install triggers that reject every UPDATE and DELETE (and TRUNCATE on PostgreSQL), so
   QuerySet.update()/delete(), bulk operations and raw SQL cannot change history either.

Note for SQLite: Django rebuilds a table to alter it, which drops its triggers. Any future
migration that alters this table must re-create them; tests/test_audit.py checks they exist.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F

POSTGRES_FORWARD = """
CREATE FUNCTION audit_event_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_auditevent is append-only (% blocked)', TG_OP;
END $$;
CREATE TRIGGER audit_event_no_change BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_event_immutable();
CREATE TRIGGER audit_event_no_truncate BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_immutable();
"""
POSTGRES_REVERSE = """
DROP TRIGGER IF EXISTS audit_event_no_truncate ON audit_auditevent;
DROP TRIGGER IF EXISTS audit_event_no_change ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_event_immutable();
"""
SQLITE_FORWARD = [
    """CREATE TRIGGER audit_event_no_update BEFORE UPDATE ON audit_auditevent
       BEGIN SELECT RAISE(ABORT, 'audit_auditevent is append-only (UPDATE blocked)'); END;""",
    """CREATE TRIGGER audit_event_no_delete BEFORE DELETE ON audit_auditevent
       BEGIN SELECT RAISE(ABORT, 'audit_auditevent is append-only (DELETE blocked)'); END;""",
]
SQLITE_REVERSE = ["DROP TRIGGER IF EXISTS audit_event_no_update;", "DROP TRIGGER IF EXISTS audit_event_no_delete;"]


def restore_profile_ids(apps, schema_editor):
    AuditEvent = apps.get_model("audit", "AuditEvent")
    AuditEvent.objects.filter(profile__isnull=True, subject_profile_id__isnull=False).update(
        profile_id=F("subject_profile_id")
    )


def _run(schema_editor, postgres, sqlite):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(postgres, params=None)  # None: the "%" in RAISE is not a placeholder
    elif vendor == "sqlite":
        for statement in sqlite:
            schema_editor.execute(statement)
    else:
        raise RuntimeError(f"No append-only triggers defined for database vendor {vendor!r}.")


def install_triggers(apps, schema_editor):
    _run(schema_editor, POSTGRES_FORWARD, SQLITE_FORWARD)


def remove_triggers(apps, schema_editor):
    _run(schema_editor, POSTGRES_REVERSE, SQLITE_REVERSE)


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0003_audit_hardening"),
        ("profiles", "0002_completion_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditevent",
            name="actor",
            field=models.ForeignKey(db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="auditevent",
            name="profile",
            field=models.ForeignKey(blank=True, db_constraint=False, db_index=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name="+", to="profiles.healthprofile"),
        ),
        migrations.RunPython(restore_profile_ids, migrations.RunPython.noop),
        migrations.RemoveIndex(model_name="auditevent", name="audit_subject_created_idx"),
        migrations.RemoveField(model_name="auditevent", name="subject_profile_id"),
        migrations.RunPython(install_triggers, remove_triggers),
    ]
