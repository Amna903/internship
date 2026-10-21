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

    created_at = models.DateTimeField(auto_now_add=True)
    # SET_NULL keeps the trail when an account is deleted; actor_role still says what kind of actor it was.
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    # "anonymous" is only used for failed sign-ins, where nobody is authenticated.
    actor_role = models.CharField(max_length=10)
    action = models.CharField(max_length=40, choices=Action.choices)
    # db_index=False: the composite (profile, -created_at) index below already starts with profile_id,
    # so Django's default single-column FK index would be pure write overhead (measured: unused).
    profile = models.ForeignKey(
        "profiles.HealthProfile", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_events", db_index=False,
    )
    # Copy of the profile id taken when the event is written. The FK above becomes NULL when the owner
    # deletes their profile; this number does not, so that profile's history (including the
    # "deleted" event itself) can still be found afterwards.
    subject_profile_id = models.PositiveBigIntegerField(null=True, blank=True)
    changed_fields = models.JSONField(default=list, blank=True)  # field *names* only
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            # "History of this profile, newest first" (admin profile detail page).
            models.Index(fields=["profile", "-created_at"], name="audit_profile_created_idx"),
            # "History of this profile id, newest first", including after the profile was deleted.
            models.Index(fields=["subject_profile_id", "-created_at"], name="audit_subject_created_idx"),
            # "All deactivations this week" (admin audit list filtered by action).
            models.Index(fields=["action", "-created_at"], name="audit_action_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(actor_role__in=["user", "admin", "anonymous"]), name="audit_actor_role_valid"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Audit events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit events are append-only.")

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_role} {self.action}"
