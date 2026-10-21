from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()
    # For a failed sign-in the linked account is the *target* of the attempt, not who made it.
    target_email = serializers.SerializerMethodField()
    # The id survives deletion of the profile (see AuditEvent.subject_profile_id).
    profile_id = serializers.IntegerField(source="subject_profile_id", read_only=True, allow_null=True)
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditEvent
        fields = [
            "id", "created_at", "action", "action_label", "actor_email", "actor_role", "target_email",
            "profile_id", "changed_fields", "request_id",
        ]
        read_only_fields = fields

    def get_actor_email(self, event) -> str | None:
        return event.actor.email if event.actor and event.actor_role != "anonymous" else None

    def get_target_email(self, event) -> str | None:
        return event.actor.email if event.actor and event.actor_role == "anonymous" else None
