import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-start py-16">
      <p className="font-mono text-xs tracking-[0.2em] text-ink-faint uppercase">Error 404 · Sheet missing</p>
      <h1 className="font-wide mt-4 text-5xl font-extrabold tracking-tight sm:text-6xl">Off the drawings.</h1>
      <p className="mt-5 text-lg text-ink-soft">
        This area is not on the site plan. It may arrive in a later phase, or the link may be wrong.
      </p>

      <div aria-hidden="true" className="mt-10 flex w-full items-center gap-2 font-mono text-xs text-ink-faint">
        <span className="h-4 w-px bg-ink-soft" />
        <span className="h-px flex-1 border-t border-dashed border-ink-soft" />
        <span>?? m</span>
        <span className="h-px flex-1 border-t border-dashed border-ink-soft" />
        <span className="h-4 w-px bg-ink-soft" />
      </div>

      <Link
        to="/"
        className="font-wide mt-10 inline-flex min-h-11 items-center rounded-[var(--radius-sheet)] border-2 border-ink bg-hivis px-5 text-xs font-bold tracking-[0.12em] uppercase shadow-[3px_3px_0_0_var(--color-ink)] hover:bg-hivis-deep"
      >
        Back to the site office
      </Link>
    </div>
  );
}
