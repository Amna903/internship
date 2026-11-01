"""Load the six frozen fictional policies as approved, searchable documents (idempotent)."""

import hashlib

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from assistant.embeddings import get_embedder
from assistant.frozen import FROZEN_SHA256, POLICY_DIR
from assistant.indexing import approve
from assistant.models import PolicyDocument


class Command(BaseCommand):
    help = "Load the approved fictional clinic policies and index them with the current embedder."

    def add_arguments(self, parser):
        parser.add_argument("--admin", required=True, help="Email of the admin recorded as approving them.")

    def handle(self, *args, admin, **options):
        approver = User.objects.filter(email=admin.strip().lower(), role="admin").first()
        if approver is None:
            raise CommandError("No admin account with that email.")
        embedder, loaded = get_embedder(), 0
        for path in sorted(POLICY_DIR.glob("*.md")):
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if FROZEN_SHA256.get(f"policies/{path.name}") != digest:
                raise CommandError(f"{path.name} does not match its frozen SHA-256; refusing to load it.")
            if PolicyDocument.objects.filter(sha256=digest).exists():
                continue
            document = PolicyDocument.objects.create(filename=path.name, sha256=digest, content=data.decode("utf-8"),
                                                     source=PolicyDocument.Source.SEED)
            approve(document, approver, embedder)
            loaded += 1
        self.stdout.write(f"Loaded {loaded} new policies (embedder {embedder.identity}).")
