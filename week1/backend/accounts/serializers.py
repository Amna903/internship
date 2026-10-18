from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import User


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "role"]
        read_only_fields = fields


class SignupSerializer(serializers.Serializer):
    """Public signup. Note there is no ``role`` field: unknown keys are ignored, so a client
    cannot ask to become an admin."""

    name = serializers.CharField(min_length=2, max_length=120)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128, style={"input_type": "password"}
    )

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        try:
            validate_password(attrs["password"], user=User(email=attrs["email"]))
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
