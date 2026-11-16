"""Explicit admin command: re-embed every approved document with the current embedder.

Search never re-embeds anything during a request; it skips chunks from another embedder and reports them.
Run this after changing the embedding model. Recorded in the audit log.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from assistant.embeddings import get_embedder
from assistant.indexing import reindex_all
from assistant.llm import LLMError
from audit.models import AuditEvent


class Command(BaseCommand):
    help = "Re-embed all approved policy documents with the current embedder (admin command, audited)."

    def add_arguments(self, parser):
        parser.add_argument("--admin", required=True, help="Email of the admin running the re-index.")

    def handle(self, *args, admin, **options):
        actor = User.objects.filter(email=admin.strip().lower(), role="admin").first()
        if actor is None:
            raise CommandError("No admin account with that email.")
        embedder = get_embedder()
        try:
            summary = reindex_all(embedder)
        except LLMError as exc:
            raise CommandError(f"Re-index failed, nothing changed for the failed document: {exc.reason}") from None
        AuditEvent.objects.create(
            actor=actor,
            actor_role="admin",
            action=AuditEvent.Action.ADMIN_DOCUMENTS_REINDEXED,
            detail=embedder.identity[:64],
        )
        self.stdout.write(
            f"Re-indexed {summary['documents']} documents into {summary['chunks']} chunks with "
            f"{embedder.identity}; removed {summary['stale_removed']} stale chunks."
        )
