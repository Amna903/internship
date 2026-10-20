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
