"""Revoke an MCP access token by its id (Week 5 Step 9). It stops working on the next call."""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from agent.mcp_tokens import revoke
from agent.models import McpToken


class Command(BaseCommand):
    help = "Revoke an MCP access token by its id."

    def add_arguments(self, parser):
        parser.add_argument("token_id")

    def handle(self, *args, **options):
        try:
            row = revoke(options["token_id"])
        except (McpToken.DoesNotExist, ValidationError):
            raise CommandError("No MCP token with that id.") from None
        self.stdout.write(f"Revoked {row.id} at {row.revoked_at:%Y-%m-%d %H:%M %Z}.")
