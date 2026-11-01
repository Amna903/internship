from django.conf import settings
from django.db import models
from django.db.models import Q

from .completion import COMPLETE, INCOMPLETE, evaluate


class HealthProfile(models.Model):
    """Wellness profile (NOT a medical record). Synthetic/fictional data only."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DEACTIVATED = "deactivated", "Deactivated"

    class CompletionStatus(models.TextChoices):
        INCOMPLETE = INCOMPLETE, "Incomplete"
        COMPLETE = COMPLETE, "Complete"

    class ContactPreference(models.TextChoices):
        EMAIL = "email", "Email"
        PHONE = "phone", "Phone call"
        SMS = "sms", "SMS"
        NONE = "none", "Do not contact"

    class AgeRange(models.TextChoices):
        R18_24 = "18-24", "18-24"
        R25_34 = "25-34", "25-34"
        R35_44 = "35-44", "35-44"
        R45_54 = "45-54", "45-54"
        R55_64 = "55-64", "55-64"
        R65_PLUS = "65+", "65+"

    # One profile per account. Deleting the account deletes the profile (no orphaned personal data).
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")

    full_name = models.CharField(max_length=120)
    date_of_birth = models.DateField(null=True, blank=True)
    age_range = models.CharField(max_length=10, choices=AgeRange.choices, blank=True, default="")
    contact_preference = models.CharField(
        max_length=10, choices=ContactPreference.choices, default=ContactPreference.EMAIL
    )
    wellness_goals = models.JSONField(default=list, blank=True)  # list[str], validated in the serializer
    allergies = models.JSONField(default=list, blank=True)  # optional, list[str]
    emergency_contact_name = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    emergency_contact_relationship = models.CharField(max_length=60, blank=True)
    lifestyle_notes = models.TextField(blank=True)

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    # Derived from the section fields on every save (see completion.py). Stored, not computed per
    # request, so admins can filter on it and the database can index it.
    completion_status = models.CharField(
        max_length=12, choices=CompletionStatus.choices, default=CompletionStatus.INCOMPLETE, editable=False
    )
    deactivated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # Admin list: `WHERE status = ? ORDER BY created_at DESC LIMIT n`
            # -> equality on the leading column, then rows already sorted by the second.
            models.Index(fields=["status", "-created_at"], name="hp_status_created_idx"),
            # Admin list sorted by name (`?ordering=full_name`) with pagination.
            models.Index(fields=["full_name"], name="hp_full_name_idx"),
            # Admin follow-up list: `WHERE completion_status = 'incomplete' ORDER BY created_at DESC`.
            models.Index(fields=["completion_status", "-created_at"], name="hp_completion_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["active", "deactivated"]), name="hp_status_is_valid"),
            # DOB and age range are alternatives, never both (they could contradict each other).
            models.CheckConstraint(
                condition=Q(date_of_birth__isnull=True) | Q(age_range=""),
                name="hp_dob_or_age_range",
            ),
            models.CheckConstraint(
                condition=Q(completion_status__in=["incomplete", "complete"]), name="hp_completion_is_valid"
            ),
        ]

    def save(self, *args, **kwargs):
        self.completion_status = evaluate(self).status
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "completion_status"}
        super().save(*args, **kwargs)

    @property
    def completion(self):
        return evaluate(self)

    def __str__(self) -> str:
        return f"{self.full_name} ({self.user.email})"
