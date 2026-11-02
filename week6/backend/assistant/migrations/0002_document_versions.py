"""Week 5 Step 1, part 1: document versions.

Adds DocumentVersion and the new document fields, then moves every existing document into version 1:
its text and SHA-256 become v1 (current if approved, pending otherwise), and its chunks are attached to
v1 as they are. Nothing is re-embedded, and v1 passage IDs keep Week 4's form (`billing.md#0`).
Reversible: going back maps the statuses back (0003's reverse restores the text from v1).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

AREAS = ("billing", "cancellation", "privacy", "reminders", "rescheduling", "telehealth")


def to_versions(apps, schema_editor):
    PolicyDocument = apps.get_model("assistant", "PolicyDocument")
    DocumentVersion = apps.get_model("assistant", "DocumentVersion")
    Chunk = apps.get_model("assistant", "Chunk")
    for d in PolicyDocument.objects.all():
        approved = d.status == "approved"
        v = DocumentVersion.objects.create(
            document=d, number=1, content=d.content, sha256=d.sha256, status="current" if approved else "pending",
            uploaded_by_id=d.uploaded_by_id, decided_by_id=d.approved_by_id if approved else None,
            decided_at=d.approved_at if approved else None)
        DocumentVersion.objects.filter(pk=v.pk).update(created_at=d.created_at)
        stem = d.filename.rsplit(".", 1)[0].lower()
        d.policy_area = stem if stem in AREAS else "other"
        d.current_version = v if approved else None
        d.save(update_fields=["policy_area", "current_version"])
        Chunk.objects.filter(document=d).update(version=v)


def from_versions(apps, schema_editor):
    """Reverse: 0003's reverse has already refilled the text; map Week 5 statuses back to Week 4's."""
    PolicyDocument = apps.get_model("assistant", "PolicyDocument")
    PolicyDocument.objects.filter(status="retired").update(status="pending")


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number", models.PositiveIntegerField()),
                ("content", models.TextField()),
                ("sha256", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("pending", "Waiting for approval"), ("current", "The approved, searchable edition"), ("superseded", "Replaced by a later approved edition"), ("rejected", "Rejected by an admin")], default="pending", max_length=12)),
                ("effective_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="versions", to="assistant.policydocument")),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["document_id", "number"],
                "constraints": [models.UniqueConstraint(fields=("document", "number"), name="version_number_per_document")],
            },
        ),
        migrations.AddField(
            model_name="policydocument",
            name="policy_area",
            field=models.CharField(choices=[("billing", "billing"), ("cancellation", "cancellation"), ("privacy", "privacy"), ("reminders", "reminders"), ("rescheduling", "rescheduling"), ("telehealth", "telehealth"), ("other", "other")], default="other", max_length=20),
        ),
        migrations.AddField(
            model_name="policydocument",
            name="current_version",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="assistant.documentversion"),
        ),
        migrations.AddField(
            model_name="policydocument",
            name="retired_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="policydocument",
            name="retired_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="policydocument",
            name="status",
            field=models.CharField(choices=[("pending", "No approved version yet"), ("approved", "Approved: its current version is searchable"), ("retired", "Retired: not searchable, kept for audit")], default="pending", max_length=10),
        ),
        migrations.AlterField(
            model_name="policydocument",
            name="approved_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="chunk",
            name="version",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="chunks", to="assistant.documentversion"),
        ),
        migrations.RunPython(to_versions, from_versions),
    ]
