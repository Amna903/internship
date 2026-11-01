"""Strict input validation, generated from ml.config.FEATURE_SCHEMA.

The same schema is stored in the released model's metadata, and the model loader refuses a model whose
schema differs, so the API and the model cannot disagree about what a valid input is.

Deliberately stricter than DRF's defaults: DRF's IntegerField accepts "14" and True, and its
BooleanField accepts "yes" and 1. For model inputs that leniency hides client bugs, so here an integer
must be a JSON integer, a boolean must be a JSON boolean, and unknown fields are rejected (which also
keeps anything identifying, such as a name or email, out of the request).
"""

import math

from rest_framework import serializers

from ml import config


class StrictIntegerField(serializers.IntegerField):
    default_error_messages = {"strict": "Must be a whole number (JSON integer), not {kind}."}

    def to_internal_value(self, data):
        # bool is a subclass of int in Python (True == 1), so it needs its own check.
        if isinstance(data, bool) or not isinstance(data, int):
            self.fail("strict", kind=type(data).__name__ if not isinstance(data, bool) else "a boolean")
        return super().to_internal_value(data)


class StrictNumberField(serializers.FloatField):
    default_error_messages = {"strict": "Must be a number (JSON number), not {kind}.",
                              "finite": "Must be a finite number."}

    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (int, float)):
            self.fail("strict", kind=type(data).__name__ if not isinstance(data, bool) else "a boolean")
        if not math.isfinite(data):
            self.fail("finite")
        return super().to_internal_value(data)


class StrictBooleanField(serializers.BooleanField):
    default_error_messages = {"strict": "Must be true or false (JSON boolean)."}

    def to_internal_value(self, data):
        if not isinstance(data, bool):
            self.fail("strict")
        return data


class StrictChoiceField(serializers.ChoiceField):
    default_error_messages = {"invalid_choice": "{input!r} is not one of: {choices}."}

    def to_internal_value(self, data):
        if not isinstance(data, str) or data not in self.choices:
            self.fail("invalid_choice", input=data, choices=", ".join(self.choices))
        return data


def _field(spec: dict) -> serializers.Field:
    kind = spec["type"]
    if kind == "integer":
        return StrictIntegerField(min_value=spec["min"], max_value=spec["max"])
    if kind == "number":
        return StrictNumberField(min_value=spec["min"], max_value=spec["max"], allow_null=spec.get("nullable", False))
    if kind == "boolean":
        return StrictBooleanField()
    if kind == "category":
        return StrictChoiceField(choices=spec["values"])
    raise ValueError(f"Unknown schema type {kind!r}")


class NoShowInputSerializer(serializers.Serializer):
    """One appointment. The caller supplies the appointment history counts; the API does not look them up."""

    def get_fields(self):
        return {name: _field(spec) for name, spec in config.FEATURE_SCHEMA.items()}

    def to_internal_value(self, data):
        # Report every problem in one response: unknown fields AND field errors together, so the caller
        # does not have to fix and resend once per mistake.
        errors = {}
        if isinstance(data, dict):
            errors = {key: ["Unknown field."] for key in sorted(set(data) - set(config.FEATURE_SCHEMA))}
        try:
            value = super().to_internal_value(data)
        except serializers.ValidationError as exc:
            if not isinstance(exc.detail, dict):
                raise
            errors.update(exc.detail)
        if errors:
            raise serializers.ValidationError(errors)
        return value

    def validate(self, attrs):
        for name, spec in config.FEATURE_SCHEMA.items():
            limit = spec.get("at_most")
            if limit and attrs[name] > attrs[limit]:
                raise serializers.ValidationError({name: [f"Cannot be more than {limit} ({attrs[limit]})."]})
        return attrs


class PredictionSerializer(serializers.Serializer):
    no_show_probability = serializers.FloatField()
    suggested_action = serializers.ChoiceField(choices=list(config.ACTIONS))
    suggested_action_label = serializers.CharField()
    decision_threshold = serializers.FloatField()
    average_no_show_rate = serializers.FloatField()


class PredictionResponseSerializer(serializers.Serializer):
    model_version = serializers.CharField()
    prediction = PredictionSerializer()
    disclaimer = serializers.CharField()
