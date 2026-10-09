import type { ReactNode } from "react";

interface SectionHeadingProps {
  id?: string;
  children: ReactNode;
  /** Short supporting text on the right, e.g. "8 sections". */
  annotation?: ReactNode;
  /** Optional action (button or link) aligned right. */
  action?: ReactNode;
}

export function SectionHeading({ id, children, annotation, action }: SectionHeadingProps) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <div className="flex items-baseline gap-3">
        <h2 id={id} className="text-base font-semibold text-ink">
          {children}
        </h2>
        {annotation ? <span className="text-sm text-ink-faint">{annotation}</span> : null}
      </div>
      {action}
    </div>
  );
}
