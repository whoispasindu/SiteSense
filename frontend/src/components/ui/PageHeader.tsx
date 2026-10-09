import type { ReactNode } from "react";

interface PageHeaderProps {
  sheet: string;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}

export function PageHeader({ sheet, title, description, action }: PageHeaderProps) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-6">
      <div className="min-w-0">
        <p className="font-mono text-xs tracking-[0.2em] text-ink-faint uppercase">Sheet {sheet}</p>
        <h1 className="font-wide mt-3 text-4xl font-extrabold tracking-tight sm:text-5xl">{title}</h1>
        {description ? <p className="mt-3 max-w-2xl text-ink-soft">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}
