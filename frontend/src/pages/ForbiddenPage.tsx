import { Link } from "react-router";

export function ForbiddenPage() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-start py-16">
      <p className="font-mono text-xs tracking-[0.2em] text-ink-faint uppercase">Error 403 · Restricted area</p>
      <h1 className="font-wide mt-4 text-5xl font-extrabold tracking-tight sm:text-6xl">Authorised personnel only.</h1>
      <p className="mt-5 text-lg text-ink-soft">
        Your role does not include this part of SiteSense. If you need it for your work, ask your company admin to
        review your access.
      </p>
      <div aria-hidden="true" className="hazard-band mt-10 h-2 w-full max-w-sm rounded-[2px]" />
      <Link
        to="/"
        className="font-wide mt-10 inline-flex min-h-11 items-center rounded-[var(--radius-sheet)] border-2 border-ink bg-hivis px-5 text-xs font-bold tracking-[0.12em] uppercase shadow-[3px_3px_0_0_var(--color-ink)] hover:bg-hivis-deep"
      >
        Back to your dashboard
      </Link>
    </div>
  );
}
