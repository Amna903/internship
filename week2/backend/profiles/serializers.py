import datetime

from django.core.validators import RegexValidator
from rest_framework import serializers

from .models import HealthProfile

PHONE_VALIDATOR = RegexValidator(r"^\+?[0-9 ()\-]{7,20}$", "Enter a valid phone number (digits, spaces, + ( ) -).")


class CompletionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=HealthProfile.CompletionStatus.choices)
    percent = serializers.IntegerField(min_value=0, max_value=100)
    missing_sections = serializers.ListField(child=serializers.CharField())


class HealthProfileSerializer(serializers.ModelSerializer):
    """Profile as seen and edited by its owner.

    ``status`` and the timestamps are read-only, so a user cannot reactivate themselves or forge
    timestamps by adding fields to a PATCH body.
    """

    email = serializers.EmailField(source="user.email", read_only=True)
    wellness_goals = serializers.ListField(
        child=serializers.CharField(max_length=100), max_length=10, required=False
    )
    allergies = serializers.ListField(child=serializers.CharField(max_length=100), max_length=20, required=False)
    emergency_contact_phone = serializers.CharField(
        max_length=30, required=False, allow_blank=True, validators=[PHONE_VALIDATOR]
    )
    completion = CompletionSerializer(read_only=True)

    class Meta:
        model = HealthProfile
        fields = [
            "email",
            "full_name",
            "date_of_birth",
            "age_range",
            "contact_preference",
            "wellness_goals",
            "allergies",
            "emergency_contact_name",
            "emergency_contact_phone",
            "emergency_contact_relationship",
            "lifestyle_notes",
            "status",
            "completion",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "completion", "created_at", "updated_at"]
        extra_kwargs = {
            "full_name": {"min_length": 2},
            "lifestyle_notes": {"max_length": 1000},
        }

    def validate_date_of_birth(self, value):
        if value is None:
            return value
        if value > datetime.date.today():
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        if value < datetime.date(1900, 1, 1):
            raise serializers.ValidationError("Date of birth is not plausible.")
        return value

    def validate(self, attrs):
        if attrs.get("date_of_birth") and attrs.get("age_range"):
            raise serializers.ValidationError(
                {"age_range": "Provide either date_of_birth or age_range, not both."}
            )
        return attrs

    def update(self, instance, validated_data):
        # Setting one of the alternatives clears the other (keeps the DB constraint satisfied).
        if validated_data.get("date_of_birth"):
            validated_data["age_range"] = ""
        elif validated_data.get("age_range"):
            validated_data["date_of_birth"] = None
        return super().update(instance, validated_data)


class AdminProfileListSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = HealthProfile
        fields = [
            "id", "user_id", "email", "full_name", "age_range", "contact_preference", "status",
            "completion_status", "created_at",
        ]
        read_only_fields = fields


class AdminProfileDetailSerializer(HealthProfileSerializer):
    """Everything the owner sees plus account metadata. Admins get read access only."""

    account_active = serializers.BooleanField(source="user.is_active", read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)

    class Meta(HealthProfileSerializer.Meta):
        fields = ["id", "user_id", *HealthProfileSerializer.Meta.fields, "deactivated_at", "account_active", "last_login"]
        read_only_fields = fields
