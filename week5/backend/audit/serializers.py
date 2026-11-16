from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()
    # For a failed sign-in the linked account is the *target* of the attempt, not who made it.
    target_email = serializers.SerializerMethodField()
    # Deletion markers: the stored id is kept, and these say whether it still points at a live row.
    profile_deleted = serializers.SerializerMethodField()
    actor_deleted = serializers.SerializerMethodField()
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditEvent
        fields = [
            "id", "created_at", "action", "action_label", "actor_email", "actor_role", "target_email",
            "actor_id", "actor_deleted", "profile_id", "profile_deleted", "changed_fields", "detail", "request_id",
        ]
        read_only_fields = fields

    def get_actor_email(self, event) -> str | None:
        return event.actor.email if event.actor_exists and event.actor_role != "anonymous" else None

    def get_target_email(self, event) -> str | None:
        return event.actor.email if event.actor_exists and event.actor_role == "anonymous" else None

    # profile_exists / actor_exists are annotated by the list view (EXISTS subqueries).
    def get_profile_deleted(self, event) -> bool:
        return event.profile_id is not None and not event.profile_exists

    def get_actor_deleted(self, event) -> bool:
        return event.actor_id is not None and not event.actor_exists
