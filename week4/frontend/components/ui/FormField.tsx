import type { ReactNode } from "react";

/** Props a control must spread so its label, hint and error are announced by screen readers. */
export type ControlProps = {
  id: string;
  name: string;
  required?: boolean;
  "aria-invalid"?: true;
  "aria-describedby"?: string;
};

type FormFieldProps = {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
  /**
   * "single": one control with a <label>.
   * "group": a set of radios/checkboxes wrapped in <fieldset>/<legend>.
   */
  kind?: "single" | "group";
  children: (control: ControlProps) => ReactNode;
};

export function FormField({ id, label, error, hint, required, kind = "single", children }: FormFieldProps) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const control: ControlProps = {
    id,
    name: id,
    required,
    ...(error ? { "aria-invalid": true as const } : {}),
    ...(describedBy ? { "aria-describedby": describedBy } : {}),
  };
  const marker = required ? <span aria-hidden="true" className="req"> *</span> : null;
  const help = (
    <>
      {hint && <div id={hintId} className="hint">{hint}</div>}
      {error && <div id={errorId} className="field-error">{error}</div>}
    </>
  );

  if (kind === "group") {
    return (
      <fieldset className="field" aria-describedby={describedBy}>
        <legend>{label}{marker}</legend>
        {children(control)}
        {help}
      </fieldset>
    );
  }
  return (
    <div className="field">
      <label htmlFor={id}>{label}{marker}</label>
      {children(control)}
      {help}
    </div>
  );
}
