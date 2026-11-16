"""Issue a short-lived MCP access token for an admin (Week 5 Step 9). The token is printed once; only its hash
is stored. Anyone holding it acts as that admin until it expires or is revoked: keep it out of shared files."""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from agent.mcp_tokens import DEFAULT_HOURS, MAX_HOURS, TokenRefused, issue


class Command(BaseCommand):
    help = f"Issue an MCP access token for an admin (default {DEFAULT_HOURS} h, at most {MAX_HOURS} h)."

    def add_arguments(self, parser):
        parser.add_argument("--admin", required=True, help="the admin's email")
        parser.add_argument("--hours", type=int, default=DEFAULT_HOURS)

    def handle(self, *args, **options):
        user = User.objects.filter(email=options["admin"].strip().lower()).first()
        try:
            if user is None:
                raise TokenRefused("not_admin")
            token, row = issue(user, options["hours"])
        except TokenRefused:
            raise CommandError("No active admin with that email.") from None
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(f"Token id: {row.id}\nExpires: {row.expires_at:%Y-%m-%d %H:%M %Z}\n"
                          f"Token (shown once; set it as HEALTHPROFILE_MCP_TOKEN in the MCP client's server config):\n{token}")
