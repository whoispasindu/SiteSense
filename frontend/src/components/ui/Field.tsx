import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

const CONTROL =
  "w-full min-h-11 rounded-[var(--radius-sheet)] border-2 border-rule-strong bg-paper-raised px-3 text-base text-ink placeholder:text-ink-faint transition-colors focus:border-ink focus:outline-none aria-[invalid=true]:border-signal-high disabled:opacity-60";

interface FieldShellProps {
  label: string;
  hint?: ReactNode;
  error?: string | undefined;
  children: (ids: { inputId: string; describedBy: string | undefined }) => ReactNode;
}

function FieldShell({ label, hint, error, children }: FieldShellProps) {
  const inputId = useId();
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className="space-y-1.5">
      <label htmlFor={inputId} className="block font-mono text-[0.7rem] tracking-[0.14em] text-ink-soft uppercase">
        {label}
      </label>
      {children({ inputId, describedBy })}
      {hint && !error ? (
        <p id={hintId} className="text-xs text-ink-faint">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-sm font-medium text-signal-high">
          {error}
        </p>
      ) : null}
    </div>
  );
}

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  label: string;
  hint?: ReactNode;
  error?: string | undefined;
  trailing?: ReactNode;
}

export function TextField({ label, hint, error, trailing, className = "", ...props }: TextFieldProps) {
  return (
    <FieldShell label={label} hint={hint} error={error}>
      {({ inputId, describedBy }) => (
        <div className="relative">
          <input
            id={inputId}
            aria-invalid={error ? true : undefined}
            aria-describedby={describedBy}
            className={`${CONTROL} ${trailing ? "pr-20" : ""} ${className}`}
            {...props}
          />
          {trailing ? <div className="absolute inset-y-0 right-1 flex items-center">{trailing}</div> : null}
        </div>
      )}
    </FieldShell>
  );
}

interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> {
  label: string;
  hint?: ReactNode;
  error?: string | undefined;
  children: ReactNode;
}

export function SelectField({ label, hint, error, children, className = "", ...props }: SelectFieldProps) {
  return (
    <FieldShell label={label} hint={hint} error={error}>
      {({ inputId, describedBy }) => (
        <select
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={`${CONTROL} ${className}`}
          {...props}
        >
          {children}
        </select>
      )}
    </FieldShell>
  );
}
