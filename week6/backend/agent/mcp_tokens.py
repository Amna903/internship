"""MCP access tokens (Week 5 Step 9): issued by an admin, short-lived, stored only as a hash, revocable, and
rate-limited per token. Rules in docs/REQUIREMENTS.md ("Step 9 rules")."""

import hashlib
import secrets
from datetime import timedelta
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent
from audit.services import record_event

from .models import McpToken, McpTokenUse

PREFIX = "hpmcp_"
DEFAULT_HOURS, MAX_HOURS = 8, 24
CALLS_PER_MINUTE = 30


class TokenRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code  # invalid | expired | revoked | not_admin | rate_limited


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _audit(user, action, token: McpToken) -> None:
    record_event(SimpleNamespace(user=user, request_id=f"mcp:{token.id}"), action, detail=str(token.id))


def issue(user, hours: int = DEFAULT_HOURS) -> tuple[str, McpToken]:
    if not (getattr(user, "is_admin", False) and user.is_active):
        raise TokenRefused("not_admin")
    if not 1 <= hours <= MAX_HOURS:
        raise ValueError(f"hours must be between 1 and {MAX_HOURS}")
    token = PREFIX + secrets.token_urlsafe(32)
    row = McpToken.objects.create(
        user=user, token_sha256=digest(token), expires_at=timezone.now() + timedelta(hours=hours)
    )
    _audit(user, AuditEvent.Action.MCP_TOKEN_ISSUED, row)
    return token, row


def revoke(token_id) -> McpToken:
    row = McpToken.objects.get(id=token_id)
    if row.revoked_at is None:
        row.revoked_at = timezone.now()
        row.save(update_fields=["revoked_at"])
        _audit(row.user, AuditEvent.Action.MCP_TOKEN_REVOKED, row)
    return row


def resolve(token) -> McpToken:
    """The token's row, re-checked now: valid, unexpired, unrevoked, and its user still an active admin."""
    if not isinstance(token, str) or not token.startswith(PREFIX) or len(token) > 200:
        raise TokenRefused("invalid")
    row = McpToken.objects.select_related("user").filter(token_sha256=digest(token)).first()
    if row is None:
        raise TokenRefused("invalid")
    if row.revoked_at is not None:
        raise TokenRefused("revoked")
    if row.expires_at <= timezone.now():
        raise TokenRefused("expired")
    if not (row.user.is_active and row.user.is_admin):
        raise TokenRefused("not_admin")
    if row.first_used_at is None:
        row.first_used_at = timezone.now()
        row.save(update_fields=["first_used_at"])
        _audit(row.user, AuditEvent.Action.MCP_TOKEN_FIRST_USED, row)
    return row


def count_call(row: McpToken, limit: int = CALLS_PER_MINUTE) -> None:
    """One call against this token's per-minute budget; raises rate_limited over the limit (no call counted)."""
    minute = timezone.now().replace(second=0, microsecond=0)
    with transaction.atomic():
        try:
            with transaction.atomic():
                use, _ = McpTokenUse.objects.get_or_create(token=row, minute=minute)
        except IntegrityError:  # another process created this minute's counter first
            use = McpTokenUse.objects.get(token=row, minute=minute)
        use = McpTokenUse.objects.select_for_update().get(pk=use.pk)
        if use.calls >= limit:
            raise TokenRefused("rate_limited")
        use.calls += 1
        use.save(update_fields=["calls"])
