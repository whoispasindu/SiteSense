import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  /** Small text above the title, e.g. a breadcrumb or project code. */
  eyebrow?: ReactNode;
}

export function PageHeader({ title, description, action, eyebrow }: PageHeaderProps) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? <div className="mb-1 text-sm text-ink-faint">{eyebrow}</div> : null}
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-[1.75rem]">{title}</h1>
        {description ? <p className="mt-1.5 max-w-2xl text-ink-soft">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}
