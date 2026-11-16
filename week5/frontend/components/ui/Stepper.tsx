type Step = { id: string; label: string };

/** Progress indicator only; navigation happens through the form's Previous/Next buttons. */
export function Stepper({ steps, current }: { steps: readonly Step[]; current: number }) {
  return (
    <nav aria-label="Progress">
      <ol className="stepper">
        {steps.map((s, i) => {
          const state = i < current ? "done" : i === current ? "current" : "todo";
          return (
            <li key={s.id} className={`step ${state}`} aria-current={state === "current" ? "step" : undefined}>
              <span className="step-num" aria-hidden="true">{state === "done" ? "✓" : i + 1}</span>
              <span className="step-label">
                {s.label}
                <span className="visually-hidden">{state === "done" ? " (completed)" : state === "todo" ? " (not started)" : ""}</span>
              </span>
            </li>
          );
        })}
      </ol>
      <p className="visually-hidden" aria-live="polite">Step {current + 1} of {steps.length}: {steps[current]?.label}</p>
    </nav>
  );
}
