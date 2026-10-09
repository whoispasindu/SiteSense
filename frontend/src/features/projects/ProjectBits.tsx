import { STATUS_LABELS, type ProjectStatus } from "../../api/projects";
import { StatusBadge, type Tone } from "../../components/ui/StatusBadge";
import { programmeProgress } from "./dates";

const STATUS_TONES: Record<ProjectStatus, Tone> = {
  planning: "idle",
  active: "ok",
  on_hold: "warn",
  completed: "ok",
  cancelled: "down",
};

export function ProjectStatusBadge({ status }: { status: ProjectStatus }) {
  return <StatusBadge tone={STATUS_TONES[status]} label={STATUS_LABELS[status]} />;
}

/**
 * The contract period drawn as a programme bar with a "today" mark. Decorative: the dates are
 * always printed next to it as text.
 */
export function ProgrammeBar({ start, end, today = new Date() }: { start: string; end: string; today?: Date }) {
  const { elapsed, state } = programmeProgress(start, end, today);
  return (
    <div aria-hidden="true" className="relative h-2.5 w-full rounded-[2px] border border-rule-strong bg-paper-sunk">
      <div
        className={`h-full ${state === "overdue" ? "bg-signal-high" : "bg-ink"}`}
        style={{ width: `${String(Math.min(100, elapsed))}%` }}
      />
      {state === "running" ? (
        <span className="absolute -top-1 -bottom-1 w-0.5 bg-hivis" style={{ left: `${String(elapsed)}%` }} />
      ) : null}
    </div>
  );
}

export function KpiTile({
  label,
  value,
  note,
  sheetCode,
  title,
}: {
  label: string;
  value: string;
  note?: string;
  sheetCode: string;
  title?: string;
}) {
  return (
    <div className="relative rounded-[var(--radius-sheet)] border border-rule bg-paper-raised p-5 shadow-[var(--shadow-sheet)]">
      <span
        aria-hidden="true"
        className="absolute top-0 right-0 border-b border-l border-rule px-2 py-0.5 font-mono text-[0.65rem] text-ink-faint"
      >
        {sheetCode}
      </span>
      <p className="font-wide pr-10 text-[0.68rem] font-bold tracking-[0.18em] text-ink-soft uppercase">{label}</p>
      <p className="tabular mt-4 font-mono text-2xl leading-none font-medium tracking-tight" title={title}>
        {value}
      </p>
      {note ? <p className="mt-3 text-xs text-ink-faint">{note}</p> : null}
    </div>
  );
}
