import type { ReactNode } from "react";

import { CraneDrawing } from "../../components/ui/CraneDrawing";
import { LogoMark } from "../../components/ui/Logo";

const GATE_NOTES = [
  ["Role-based access", "Every role sees only its own work."],
  ["Site scoping", "Engineers and clients see the sites they are assigned to."],
  ["Full audit trail", "Every sign-in and change is recorded."],
] as const;

/** Split "site gate" layout shared by the sign-in and change-password screens. */
export function GateLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh bg-paper lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <aside className="on-asphalt relative flex flex-col overflow-hidden bg-asphalt text-asphalt-text">
        <div aria-hidden="true" className="hazard-band h-1.5 shrink-0" />
        <div className="flex items-center gap-3 px-6 py-5 lg:px-12 lg:pt-10">
          <LogoMark className="size-9" />
          <div className="leading-tight">
            <p className="text-base font-semibold text-white">SiteSense</p>
            <p className="text-xs text-asphalt-muted">Delay &amp; cost control</p>
          </div>
        </div>

        <div className="relative hidden flex-1 flex-col justify-center px-12 pb-12 lg:flex">
          <div className="relative z-10">
            <p className="max-w-lg text-4xl leading-[1.1] font-semibold tracking-tight text-white xl:text-5xl">
              Know which site will{" "}
              <span className="relative inline-block">
                <span className="relative z-10 text-asphalt">slip</span>
                <span aria-hidden="true" className="absolute inset-x-[-0.1em] inset-y-[0.08em] z-0 rounded-md bg-hivis" />
              </span>{" "}
              before it does.
            </p>
            <p className="mt-4 max-w-md text-asphalt-muted">
              Programmes, budgets and site records for construction teams, in one place.
            </p>

            <ul className="mt-10 max-w-md space-y-4">
              {GATE_NOTES.map(([title, text]) => (
                <li key={title} className="flex gap-3 text-sm">
                  <span aria-hidden="true" className="mt-1.5 size-2 shrink-0 rounded-full bg-hivis" />
                  <span>
                    <span className="font-medium text-white">{title}.</span>{" "}
                    <span className="text-asphalt-muted">{text}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <CraneDrawing className="pointer-events-none absolute right-[-2rem] bottom-0 z-0 w-[min(20rem,42%)] text-asphalt-line opacity-70 xl:w-[min(24rem,42%)]" />
        </div>
      </aside>

      <main className="flex items-center justify-center px-4 py-10 sm:px-8 lg:py-16">{children}</main>
    </div>
  );
}

/** The sign-in card. */
export function GatePass({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="animate-rise w-full max-w-md">
      <div className="rounded-xl border border-rule bg-paper-raised px-6 pt-7 pb-8 shadow-[var(--shadow-sheet)] sm:px-8">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {children}
      </div>
    </div>
  );
}
