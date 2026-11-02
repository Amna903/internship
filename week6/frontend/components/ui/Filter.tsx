"use client";

export type Option = { value: string; label: string };

type SelectFilterProps = {
  id: string;
  label: string;
  value: string;
  options: Option[];
  /** Label for the empty value, e.g. "Any city". */
  anyLabel: string;
  onChange: (value: string) => void;
};

export function SelectFilter({ id, label, value, options, anyLabel, onChange }: SelectFilterProps) {
  return (
    <div className="filter">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{anyLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

type ChipFilterProps = {
  label: string;
  values: string[];
  options: Option[];
  onChange: (values: string[]) => void;
};

/** Multi-select as toggle chips (real checkboxes underneath, so keyboard and screen readers just work). */
export function ChipFilter({ label, values, options, onChange }: ChipFilterProps) {
  const toggle = (v: string) => onChange(values.includes(v) ? values.filter((x) => x !== v) : [...values, v]);
  return (
    <fieldset className="filter chips">
      <legend>{label}</legend>
      <div className="chip-row">
        {options.map((o) => (
          <label key={o.value} className="chip">
            <input type="checkbox" checked={values.includes(o.value)} onChange={() => toggle(o.value)} />
            <span>{o.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
