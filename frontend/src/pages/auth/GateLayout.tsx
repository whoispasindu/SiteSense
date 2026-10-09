import type { ReactNode } from "react";

import { CraneDrawing } from "../../components/ui/CraneDrawing";
import { LogoMark } from "../../components/ui/Logo";

const GATE_NOTES = [
  ["01", "Role-based access", "Every role sees only its own work."],
  ["02", "Site scoping", "Engineers and clients see the sites they are assigned to."],
  ["03", "Two-step verification", "Coming for managers and procurement in a later release."],
] as const;

/** Split "site gate" layout shared by the sign-in and change-password screens. */
export function GateLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <aside className="on-asphalt relative flex flex-col overflow-hidden bg-asphalt text-asphalt-text">
        <div aria-hidden="true" className="hazard-band h-2 shrink-0" />
        <div className="flex items-center gap-3 px-6 py-5 lg:px-12 lg:pt-10">
          <LogoMark className="size-9" />
          <p className="font-wide text-base font-extrabold tracking-[0.18em] text-paper uppercase">SiteSense</p>
        </div>

        <div className="relative hidden flex-1 flex-col justify-center px-12 pb-12 lg:flex">
          <div className="relative z-10">
          <p className="font-mono text-xs tracking-[0.24em] text-asphalt-muted uppercase">Site gate</p>
          <p className="font-wide mt-5 max-w-lg text-5xl leading-[1.02] font-extrabold tracking-tight text-paper xl:text-6xl">
            Know which site will{" "}
            <span className="relative inline-block">
              <span className="relative z-10 text-asphalt">slip</span>
              <span aria-hidden="true" className="absolute inset-x-[-0.08em] inset-y-[0.12em] z-0 bg-hivis" />
            </span>{" "}
            before it does.
          </p>

          <ul className="mt-12 max-w-md divide-y divide-asphalt-line border-y border-asphalt-line">
            {GATE_NOTES.map(([code, title, text]) => (
              <li key={code} className="grid grid-cols-[3rem_1fr] gap-2 py-3.5">
                <span className="font-mono text-xs text-hivis">{code}</span>
                <span className="text-sm">
                  <span className="font-semibold text-paper">{title}.</span>{" "}
                  <span className="text-asphalt-muted">{text}</span>
                </span>
              </li>
            ))}
          </ul>
          </div>

          <CraneDrawing className="pointer-events-none absolute right-[-2rem] bottom-0 z-0 w-[min(20rem,42%)] text-asphalt-line opacity-80 xl:w-[min(24rem,42%)]" />
        </div>
      </aside>

      <main className="drafting-grid flex items-center justify-center px-4 py-10 sm:px-8 lg:py-16">{children}</main>
    </div>
  );
}

/** The paper "gate pass" card: perforated top edge, ticket header. */
export function GatePass({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return (
    <div className="animate-rise w-full max-w-md">
      <div className="rounded-[var(--radius-sheet)] border border-rule bg-paper-raised shadow-[var(--shadow-sheet)]">
        <div className="flex items-center justify-between border-b-2 border-dashed border-rule-strong px-6 py-3">
          <span className="font-wide text-[0.65rem] font-extrabold tracking-[0.24em] uppercase">Gate pass</span>
          <span className="font-mono text-[0.65rem] text-ink-faint">{eyebrow}</span>
        </div>
        <div className="px-6 pt-6 pb-7 sm:px-8">
          <h1 className="font-wide text-3xl font-extrabold tracking-tight">{title}</h1>
          {children}
        </div>
      </div>
    </div>
  );
}
