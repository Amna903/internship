from django.conf import settings
from django.db import models
from django.db.models import Q


class AuditEvent(models.Model):
    """Append-only record of profile edits and admin actions.

    Stores *who* did *what* to *which* profile and *which fields* changed, never the values:
    no passwords, tokens, request bodies or profile contents ever land here.
    """

    class Action(models.TextChoices):
        PROFILE_CREATED = "profile.created", "Profile created"
        PROFILE_UPDATED = "profile.updated", "Profile updated"
        PROFILE_DELETED = "profile.deleted", "Profile deleted by its owner"
        ADMIN_LOGIN = "admin.login", "Admin signed in"
        ADMIN_LOGIN_FAILED = "admin.login_failed", "Failed admin sign-in"
        ADMIN_LOGOUT = "admin.logout", "Admin signed out"
        ADMIN_PROFILE_VIEWED = "admin.profile_viewed", "Admin viewed profile"
        ADMIN_PROFILE_DEACTIVATED = "admin.profile_deactivated", "Admin deactivated profile"
        ADMIN_PROFILE_ACTIVATED = "admin.profile_activated", "Admin reactivated profile"
        ADMIN_PREDICTION_MADE = "admin.prediction_made", "Admin requested a no-show estimate"
        ADMIN_CLUSTERS_VIEWED = "admin.clusters_viewed", "Admin viewed the exploratory clusters"
        ADMIN_DOCUMENT_UPLOADED = "admin.document_uploaded", "Admin uploaded a policy document (pending)"
        ADMIN_DOCUMENT_APPROVED = "admin.document_approved", "Admin approved a policy document"
        ADMIN_DOCUMENTS_REINDEXED = "admin.documents_reindexed", "Admin re-indexed the policy documents"
        ADMIN_ASSISTANT_ASKED = "admin.assistant_asked", "Admin asked the policy assistant"
        ADMIN_DOCUMENT_VERSION_UPLOADED = "admin.document_version_uploaded", "Admin uploaded a new document version (pending)"
        ADMIN_DOCUMENT_VERSION_REJECTED = "admin.document_version_rejected", "Admin rejected a pending document version"
        ADMIN_DOCUMENT_RETIRED = "admin.document_retired", "Admin retired a policy document"
        AGENT_TOOL_CALLED = "agent.tool_called", "An agent tool was called (tool name and outcome only)"
        AGENT_ACTION_PROPOSED = "agent.action_proposed", "A write was proposed and awaits confirmation"
        AGENT_ACTION_CONFIRMED = "agent.action_confirmed", "Admin confirmed a proposed write"
        AGENT_ACTION_DECLINED = "agent.action_declined", "Admin declined a proposed write"
        AGENT_ACTION_EXPIRED = "agent.action_expired", "A proposed write expired unconfirmed"
        AGENT_ACTION_FAILED = "agent.action_failed", "A confirmed write failed: the slot was already taken"

    created_at = models.DateTimeField(auto_now_add=True)
    # Stable identifiers, not live links: DO_NOTHING + db_constraint=False means deleting the user or
    # profile never rewrites an audit row (a SET NULL cascade would be an UPDATE, which the database
    # triggers below forbid). The ids stay; the API reports a deleted subject as a deletion marker.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, db_constraint=False, null=True, related_name="+",
    )
    # "anonymous" is only used for failed sign-ins, where nobody is authenticated.
    actor_role = models.CharField(max_length=10)
    action = models.CharField(max_length=40, choices=Action.choices)
    # db_index=False: the composite (profile, -created_at) index below already starts with profile_id,
    # so Django's default single-column FK index would be pure write overhead (measured: unused).
    profile = models.ForeignKey(
        "profiles.HealthProfile", on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True,
        related_name="+", db_index=False,
    )
    changed_fields = models.JSONField(default=list, blank=True)  # field *names* only
    # A short non-sensitive label, e.g. the model version behind a prediction. Never input values.
    # Nullable with no default on purpose: SQLite can then add it with ALTER TABLE ADD COLUMN instead
    # of rebuilding the table, which would drop the append-only triggers (tests check they survive).
    detail = models.CharField(max_length=64, null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            # "History of this profile, newest first" (admin profile detail page).
            models.Index(fields=["profile", "-created_at"], name="audit_profile_created_idx"),
            # "All deactivations this week" (admin audit list filtered by action).
            models.Index(fields=["action", "-created_at"], name="audit_action_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(actor_role__in=["user", "admin", "anonymous"]), name="audit_actor_role_valid"),
        ]

    # These two guards give a clear error in application code. They are NOT what makes the log
    # append-only: QuerySet.update()/delete(), bulk operations and raw SQL skip them. The database
    # triggers created in migration 0004 reject every UPDATE and DELETE on this table.
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Audit events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit events are append-only.")

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_role} {self.action}"
