"""Week 5 Step 1, part 2: versions own the text.

Removes the text and SHA-256 from the document (they live in DocumentVersion now), makes every chunk
belong to a version, and makes chunks unique per version instead of per document, so an update's new
chunks can be written before the old edition's are removed, in one transaction.
Reversible: the document fields come back nullable, are refilled from v1, and only then become required
and unique again.
"""

import django.db.models.deletion
from django.db import migrations, models


def refill_document_fields(apps, schema_editor):
    """Reverse only: copy each document's v1 text and SHA-256 back before the fields become required."""
    PolicyDocument = apps.get_model("assistant", "PolicyDocument")
    DocumentVersion = apps.get_model("assistant", "DocumentVersion")
    for d in PolicyDocument.objects.all():
        v = DocumentVersion.objects.filter(document=d, number=1).first()
        if v is not None:
            PolicyDocument.objects.filter(pk=d.pk).update(content=v.content, sha256=v.sha256)


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0002_document_versions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="policydocument",
            name="sha256",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name="policydocument",
            name="content",
            field=models.TextField(null=True),
        ),
        migrations.RunPython(migrations.RunPython.noop, refill_document_fields),
        migrations.RemoveField(model_name="policydocument", name="sha256"),
        migrations.RemoveField(model_name="policydocument", name="content"),
        migrations.AlterField(
            model_name="chunk",
            name="version",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chunks", to="assistant.documentversion"),
        ),
        migrations.RemoveConstraint(model_name="chunk", name="chunk_unique_per_model"),
        migrations.AddConstraint(
            model_name="chunk",
            constraint=models.UniqueConstraint(fields=("version", "position", "embedding_model"), name="chunk_unique_per_version_and_model"),
        ),
    ]
