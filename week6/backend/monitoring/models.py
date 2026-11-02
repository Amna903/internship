"""One row per no-show prediction (Week 5 Step 11). Never the input values, never the user."""

from django.db import models


class PredictionLog(models.Model):
    class Source(models.TextChoices):
        API = "api", "Prediction API"
        AGENT = "agent", "Agent tool"

    class Outcome(models.TextChoices):
        OK = "ok", "Predicted"
        INVALID_INPUT = "invalid_input", "Rejected input"
        FAILED = "failed", "Model unavailable or failed"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    model_version = models.CharField(max_length=40)
    source = models.CharField(max_length=10, choices=Source.choices)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    probability = models.FloatField(null=True, blank=True)
    latency_ms = models.FloatField()

    class Meta:
        ordering = ["-created_at", "-id"]
