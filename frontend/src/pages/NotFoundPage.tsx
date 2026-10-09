import { Link } from "react-router";

import { primaryLinkClass } from "../components/ui/Button";

export function NotFoundPage() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-start py-16">
      <span className="rounded-full bg-paper-sunk px-3 py-1 text-sm font-medium text-ink-soft">Error 404</span>
      <h1 className="mt-5 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">Off the drawings.</h1>
      <p className="mt-3 text-ink-soft">
        This page is not on the site plan. It may arrive in a later phase, or the link may be wrong.
      </p>

      <div aria-hidden="true" className="mt-8 flex w-full max-w-sm items-center gap-2 text-xs text-ink-faint">
        <span className="h-4 w-px bg-rule-strong" />
        <span className="h-px flex-1 border-t border-dashed border-rule-strong" />
        <span className="tabular">?? m</span>
        <span className="h-px flex-1 border-t border-dashed border-rule-strong" />
        <span className="h-4 w-px bg-rule-strong" />
      </div>

      <Link to="/" className={`mt-8 ${primaryLinkClass}`}>
        Back to the dashboard
      </Link>
    </div>
  );
}
