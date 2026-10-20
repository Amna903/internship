from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True, default=None)
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditEvent
        fields = [
            "id", "created_at", "action", "action_label", "actor_email", "actor_role",
            "profile_id", "changed_fields", "request_id",
        ]
        read_only_fields = fields
