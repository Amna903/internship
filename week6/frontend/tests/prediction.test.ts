import { describe as group, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import {
  ACTIONS,
  buildRequest,
  DEFAULT_FORM,
  describe,
  errorView,
  FIELDS,
  FormState,
  LABELS,
  percent,
  PRESETS,
  presetToForm,
  SCHEMA,
} from "@/lib/prediction";
import schemaDoc from "@/lib/noShowSchema.json";

const form = (patch: Partial<FormState> = {}): FormState => ({ ...DEFAULT_FORM, ...patch });

group("buildRequest", () => {
  it("sends exactly the ten API fields and nothing else", () => {
    const { payload } = buildRequest(form());
    expect(Object.keys(payload!).sort()).toEqual([...FIELDS].sort());
    expect(FIELDS).toHaveLength(10);
  });

  it("sends numbers as JSON numbers and the toggle as a boolean", () => {
    const { payload } = buildRequest(form({ lead_time_days: "14", distance_km: "6.5", reminder_sent: false }));
    expect(payload!.lead_time_days).toBe(14);
    expect(payload!.distance_km).toBe(6.5);
    expect(payload!.reminder_sent).toBe(false);
  });

  it("turns a blank distance into null (unknown) but rejects other blanks", () => {
    expect(buildRequest(form({ distance_km: "  " })).payload!.distance_km).toBeNull();
    expect(buildRequest(form({ lead_time_days: "" })).errors.lead_time_days).toBe("Required.");
  });

  it("rejects decimals for whole-number fields and out-of-range values", () => {
    expect(buildRequest(form({ appointment_hour: "10.5" })).errors.appointment_hour).toBe("Enter a whole number.");
    expect(buildRequest(form({ appointment_hour: "22" })).errors.appointment_hour).toBe("Must be between 7 and 19.");
    expect(buildRequest(form({ distance_km: "-1" })).errors.distance_km).toBe("Must be between 0 and 500.");
    expect(buildRequest(form({ lead_time_days: "abc" })).errors.lead_time_days).toBe("Enter a number.");
  });

  it("rejects more missed than earlier appointments, and nothing is sent", () => {
    const { payload, errors } = buildRequest(form({ prior_appointments: "2", prior_no_shows: "3" }));
    expect(payload).toBeNull();
    expect(errors.prior_no_shows).toMatch(/Cannot be more than earlier appointments \(2\)/);
  });

  it("rejects a category that is not an option", () => {
    expect(buildRequest(form({ appointment_weekday: "funday" })).errors.appointment_weekday).toBeDefined();
  });
});

group("presets (Fill example buttons)", () => {
  it("every preset fills a valid form", () => {
    for (const preset of PRESETS) expect(buildRequest(presetToForm(preset.values)).payload).toEqual(preset.values);
  });

  it("there is one preset for each suggestion", () => {
    expect(new Set(PRESETS.map((p) => p.expected_action))).toEqual(new Set(Object.keys(ACTIONS)));
  });

  it("a null distance preset becomes a blank field", () => {
    const preset = PRESETS.find((p) => p.values.distance_km === null)!;
    expect(presetToForm(preset.values).distance_km).toBe("");
  });
});

group("wording", () => {
  const response = (action: keyof typeof ACTIONS) => ({
    model_version: "no-show-1.0.0",
    disclaimer: "Educational prototype. Not a medical assessment.",
    prediction: {
      no_show_probability: 0.6582,
      suggested_action: action,
      suggested_action_label: ACTIONS[action],
      decision_threshold: 0.1688,
      average_no_show_rate: 0.1645,
    },
  });

  it("shows the suggestion, the percentage, the version and the disclaimer", () => {
    const text = describe(response("extra_reminder_suggested"));
    expect(text.headline).toBe("Extra reminder suggested");
    expect(text.chance).toBe("65.8% estimated chance this appointment is missed");
    expect(text.version).toBe("Model no-show-1.0.0");
    expect(text.disclaimer).toMatch(/not a medical assessment/i);
  });

  it("never uses clinical or alarming words anywhere on the page's text", () => {
    const everything = JSON.stringify([
      describe(response("extra_reminder_suggested")),
      describe(response("standard_reminder")),
      LABELS,
      ACTIONS,
      PRESETS.map((p) => p.label),
    ]).toLowerCase();
    for (const word of ["risk", "high", "danger", "diagnos", "disease", "illness", "patient is", "alarm"]) {
      expect(everything).not.toContain(word);
    }
  });

  it("formats percentages with one decimal", () => {
    expect(percent(0.1279)).toBe("12.8%");
  });
});

group("errorView", () => {
  it("maps each failure to what the page shows", () => {
    expect(errorView(new ApiError(503, "model_unavailable", "x")).kind).toBe("unavailable");
    expect(errorView(new ApiError(401, "not_authenticated", "x")).kind).toBe("signed_out");
    expect(errorView(new ApiError(403, "permission_denied", "x")).kind).toBe("signed_out");
    expect(errorView(new TypeError("fetch failed")).kind).toBe("network");
    expect(errorView(new ApiError(500, "server_error", "x")).kind).toBe("unknown");
  });

  it("puts server field errors next to the fields", () => {
    const view = errorView(
      new ApiError(400, "validation_error", "x", {
        appointment_hour: ["Ensure this value is less than or equal to 19."],
      }),
    );
    expect(view).toMatchObject({
      kind: "fields",
      fields: { appointment_hour: "Ensure this value is less than or equal to 19." },
    });
  });

  it("tells the user how long to wait when rate limited", () => {
    const view = errorView(new ApiError(429, "throttled", "x", { retry_after_seconds: "42" }));
    expect(view).toMatchObject({ kind: "throttled", message: "Too many requests. Try again in 42 seconds." });
  });
});

group("shared schema", () => {
  it("the form is built from the same schema the backend tests compare with the API", () => {
    expect(SCHEMA).toBe(schemaDoc.features);
    expect(Object.keys(LABELS).sort()).toEqual([...FIELDS].sort());
  });
});
