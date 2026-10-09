import { DimensionHeading } from "../../components/ui/DimensionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { MILESTONES, PHASES, PROGRAMME_WEEKS, phaseStatus, type Phase, type PhaseStatus } from "../../lib/programme";

const STATUS_TEXT: Record<PhaseStatus, string> = {
  done: "Complete",
  active: "In progress",
  planned: "Planned",
};

const BAR: Record<PhaseStatus, string> = {
  done: "bg-ink border-ink",
  active: "hazard-band border-ink shadow-[2px_2px_0_0_var(--color-ink)]",
  planned: "bg-paper-sunk border-dashed border-rule-strong",
};

const WEEKS = Array.from({ length: PROGRAMME_WEEKS }, (_, i) => i + 1);

function weeksLabel(phase: Phase): string {
  return phase.startWeek === phase.endWeek ? `Week ${phase.startWeek}` : `Weeks ${phase.startWeek}–${phase.endWeek}`;
}

function TrackGrid({ children }: { children?: React.ReactNode }) {
  return (
    <div
      className="relative grid h-full items-center"
      style={{ gridTemplateColumns: `repeat(${PROGRAMME_WEEKS}, minmax(0, 1fr))` }}
    >
      {children}
    </div>
  );
}

function PhaseRow({ phase }: { phase: Phase }) {
  const status = phaseStatus(phase.number);
  const active = status === "active";

  return (
    <li
      className={`grid grid-cols-1 gap-2 border-b border-rule py-3 md:grid-cols-[17rem_1fr] md:gap-6 ${active ? "bg-hivis/10" : ""}`}
    >
      <div className="flex items-start gap-3 px-4 md:px-5">
        <span
          className={`tabular mt-0.5 font-mono text-xs ${active ? "font-semibold text-ink" : "text-ink-faint"}`}
        >
          P{String(phase.number).padStart(2, "0")}
        </span>
        <div className="min-w-0">
          <p className={`text-sm leading-snug ${active ? "font-semibold" : ""}`}>{phase.name}</p>
          <p className="mt-0.5 text-xs text-ink-faint">
            <span className="md:sr-only">{weeksLabel(phase)} · </span>
            <span className={active ? "font-semibold text-signal-medium" : ""}>{STATUS_TEXT[status]}</span>
            <span className="sr-only">. Delivers: {phase.output}</span>
          </p>
        </div>
      </div>
      <div aria-hidden="true" className="hidden h-7 pr-5 md:block">
        <TrackGrid>
          <div
            title={`${phase.output} (${weeksLabel(phase)})`}
            className={`h-4 rounded-[2px] border ${BAR[status]}`}
            style={{ gridColumn: `${phase.startWeek} / ${phase.endWeek + 1}` }}
          />
        </TrackGrid>
      </div>
    </li>
  );
}

function MilestoneRow({ label, week }: { label: string; week: number }) {
  return (
    <li className="grid grid-cols-1 border-b border-rule bg-paper-sunk/60 py-2 md:grid-cols-[17rem_1fr] md:gap-6">
      <p className="font-wide flex items-center gap-2 px-4 text-[0.68rem] font-bold tracking-[0.18em] uppercase md:px-5">
        <span aria-hidden="true" className="inline-block size-2 rotate-45 bg-ink" />
        Release {label}
        <span className="font-mono font-normal tracking-normal text-ink-faint normal-case md:sr-only">
          · end of week {week}
        </span>
      </p>
      <div aria-hidden="true" className="hidden h-5 pr-5 md:block">
        <TrackGrid>
          <span
            className="flex items-center justify-end gap-2 font-mono text-[0.65rem] text-ink-soft"
            style={{ gridColumn: `1 / ${week + 1}` }}
          >
            {label}
            <span className="inline-block size-2.5 rotate-45 border border-ink bg-hivis" />
          </span>
        </TrackGrid>
      </div>
    </li>
  );
}

export function BuildProgramme() {
  const rows = PHASES.flatMap((phase) => {
    const milestone = MILESTONES.find((m) => m.afterPhase === phase.number);
    return milestone
      ? [
          <PhaseRow key={phase.number} phase={phase} />,
          <MilestoneRow key={milestone.label} label={milestone.label} week={milestone.week} />,
        ]
      : [<PhaseRow key={phase.number} phase={phase} />];
  });

  return (
    <section aria-labelledby="programme-heading">
      <DimensionHeading id="programme-heading" annotation={`${PROGRAMME_WEEKS} wk · ${PHASES.length} phases`}>
        Build programme
      </DimensionHeading>

      <Sheet className="overflow-hidden">
        <div
          aria-hidden="true"
          className="hidden grid-cols-[17rem_1fr] gap-6 border-b border-rule-strong bg-paper-sunk py-2 md:grid"
        >
          <span className="font-wide px-5 text-[0.65rem] font-bold tracking-[0.18em] text-ink-soft uppercase">
            Phase
          </span>
          <div className="pr-5">
            <TrackGrid>
              {WEEKS.map((week) => (
                <span
                  key={week}
                  className={`border-l border-rule-strong pl-0.5 font-mono text-[0.6rem] text-ink-faint ${week % 2 === 0 ? "max-lg:invisible" : ""}`}
                >
                  {week}
                </span>
              ))}
            </TrackGrid>
          </div>
        </div>
        <ol aria-label="Build phases and releases">{rows}</ol>
      </Sheet>
    </section>
  );
}
