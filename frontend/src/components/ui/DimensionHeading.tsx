import type { ReactNode } from "react";

interface DimensionHeadingProps {
  id?: string;
  children: ReactNode;
  /** Small mono annotation on the right, like a dimension value. */
  annotation?: ReactNode;
}

/**
 * Section heading drawn as an architectural dimension line: |-- LABEL ----------| value
 */
export function DimensionHeading({ id, children, annotation }: DimensionHeadingProps) {
  return (
    <div className="mb-4 flex items-center gap-3">
      <span aria-hidden="true" className="h-3 w-px bg-ink-soft" />
      <span aria-hidden="true" className="h-px w-4 bg-ink-soft" />
      <h2 id={id} className="font-wide shrink-0 text-xs font-bold tracking-[0.2em] text-ink uppercase">
        {children}
      </h2>
      <span aria-hidden="true" className="h-px flex-1 bg-ink-soft/50" />
      {annotation ? <span className="shrink-0 font-mono text-xs text-ink-faint">{annotation}</span> : null}
      <span aria-hidden="true" className="h-3 w-px bg-ink-soft" />
    </div>
  );
}
