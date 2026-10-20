from rest_framework import serializers

from ml.data import AGE_BANDS, CHANNELS, VISIT_TYPES, WEEKDAYS
from ml.features import INPUT_COLUMNS


class StrictSerializer(serializers.Serializer):
    """Rejects keys it doesn't know, so a typo (``lead_time``) is an error, not a silent default."""

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"non_field_errors": ["Expected a JSON object."]})
        unknown = sorted(set(data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError({name: ["Unknown field."] for name in unknown})
        return super().to_internal_value(data)


class NoShowRequestSerializer(StrictSerializer):
    """Inference schema. Ranges are the plausible range for a clinic booking, wider than the training data."""

    lead_time_days = serializers.IntegerField(min_value=0, max_value=365, help_text="Days between booking and appointment.")
    appointment_weekday = serializers.ChoiceField(choices=WEEKDAYS)
    appointment_hour = serializers.IntegerField(min_value=7, max_value=20, help_text="Clinic hours, 24h clock.")
    age_band = serializers.ChoiceField(choices=AGE_BANDS)
    visit_type = serializers.ChoiceField(choices=VISIT_TYPES)
    booking_channel = serializers.ChoiceField(choices=CHANNELS)
    reminder_sent = serializers.BooleanField()
    prior_appointments = serializers.IntegerField(min_value=0, max_value=200)
    prior_no_shows = serializers.IntegerField(min_value=0, max_value=200)
    distance_km = serializers.FloatField(min_value=0, max_value=500, required=False, allow_null=True, default=None,
                                         help_text="Optional; missing values are imputed as in training.")

    def validate(self, attrs):
        if attrs["prior_no_shows"] > attrs["prior_appointments"]:
            raise serializers.ValidationError({"prior_no_shows": ["Cannot exceed prior_appointments."]})
        assert set(attrs) == set(INPUT_COLUMNS)
        return attrs


class NoShowPredictionSerializer(serializers.Serializer):
    no_show_probability = serializers.FloatField(min_value=0, max_value=1)
    risk_band = serializers.ChoiceField(choices=["low", "medium", "high"])
    decision_threshold = serializers.FloatField()
    baseline_no_show_rate = serializers.FloatField()


class NoShowResponseSerializer(serializers.Serializer):
    model_version = serializers.CharField()
    prediction = NoShowPredictionSerializer()
    disclaimer = serializers.CharField()
