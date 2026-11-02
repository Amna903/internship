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
