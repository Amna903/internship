"""Week 5 Step 7: mock bookings and the pending actions a human must confirm.

No patient data anywhere: a booking is a fictional slot (date, time, fictional clinician), the visit type,
the admin who confirmed it and when. A pending action stores only validated tool arguments; the summary a
human confirms is generated from those fields by the server (agent/write_tools.py), never stored model text.
"""

import uuid

from django.conf import settings
from django.db import models


class MockBooking(models.Model):
    date = models.DateField()
    time = models.CharField(max_length=5)  # "09:30", from the fixed schedule
    clinician = models.CharField(max_length=20)  # fictional: "Clinician A".."Clinician D"
    visit_type = models.CharField(max_length=12)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "time", "clinician"]
        # One booking per clinician and time: racing confirmations can't both succeed.
        constraints = [models.UniqueConstraint(fields=["date", "time", "clinician"], name="one_booking_per_slot")]


class PendingAction(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        CONFIRMED = "confirmed"
        DECLINED = "declined"
        EXPIRED = "expired"
        FAILED = "failed"  # the slot was taken before confirmation; nothing written

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # unguessable
    tool = models.CharField(max_length=40)
    args = models.JSONField()  # validated tool arguments only
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    proposed_by_agent = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    booking = models.OneToOneField(MockBooking, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    idempotency_key = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "idempotency_key"], name="one_use_per_idempotency_key")]


class AgentRun(models.Model):
    """One agent run's trace (Week 5 Step 8): outcome, counts and per-step records with free-text arguments
    replaced by "[text: N characters]". Never the message, tool output or answer text."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10)  # done | stopped | failed | refused
    stopped_reason = models.CharField(max_length=20, blank=True)
    kind = models.CharField(max_length=10, blank=True)
    offered = models.JSONField(default=list)  # tool names offered to the model
    steps = models.JSONField(default=list)
    tool_calls = models.PositiveSmallIntegerField(default=0)
    model_calls = models.PositiveSmallIntegerField(default=0)
    tokens = models.PositiveIntegerField(default=0)
    seconds = models.FloatField(default=0)
    model = models.CharField(max_length=100, blank=True)
    pending_action = models.ForeignKey(PendingAction, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class McpToken(models.Model):
    """A short-lived MCP access token (Week 5 Step 9). Only the SHA-256 of the token is stored; the token itself
    is shown once when issued. The holder acts as `user`, re-checked on every call."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    token_sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    first_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class McpTokenUse(models.Model):
    """Calls per token per minute, in the database so the limit holds across server processes."""

    token = models.ForeignKey(McpToken, on_delete=models.CASCADE, related_name="+")
    minute = models.DateTimeField()
    calls = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["token", "minute"], name="one_counter_per_token_minute")]
