from collections.abc import Iterable

from .models import AuditEvent


def record_event(request, action: str, *, actor=None, profile=None, changed_fields: Iterable[str] = ()) -> AuditEvent:
    """Write one audit row. ``actor`` defaults to the authenticated user on the request."""
    actor = actor or request.user
    return AuditEvent.objects.create(
        actor=actor,
        actor_role=actor.role,
        action=action,
        profile=profile,
        changed_fields=sorted(set(changed_fields)),
        request_id=getattr(request, "request_id", ""),
    )


def record_failed_admin_login(request, email: str) -> AuditEvent:
    """Record a rejected admin sign-in without storing what was typed.

    The event points at the targeted account only when that email really exists. The raw email is
    never stored: people sometimes type their password into the email box. The client still gets
    the same generic 401 either way, so this adds no account-enumeration signal.
    """
    from accounts.models import User

    target = User.objects.filter(email=email.strip().lower()).first()
    return AuditEvent.objects.create(
        actor=target,
        actor_role="anonymous",
        action=AuditEvent.Action.ADMIN_LOGIN_FAILED,
        request_id=getattr(request, "request_id", ""),
    )
