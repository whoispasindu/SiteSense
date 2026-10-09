import { STATUS_LABELS, type ProjectStatus } from "../../api/projects";
import { Icon, type IconName } from "../../components/ui/icons";
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
 * The contract period as a slim bar with a "today" mark. Decorative: the dates are always printed
 * next to it as text.
 */
export function ProgrammeBar({ start, end, today = new Date() }: { start: string; end: string; today?: Date }) {
  const { elapsed, state } = programmeProgress(start, end, today);
  return (
    <div aria-hidden="true" className="relative h-2 w-full rounded-full bg-paper-sunk">
      <div
        className={`h-full rounded-full ${state === "overdue" ? "bg-signal-high" : "bg-ink-faint/70"}`}
        style={{ width: `${String(Math.min(100, elapsed))}%` }}
      />
      {state === "running" ? (
        <span
          className="absolute -top-1 -bottom-1 w-[3px] -translate-x-1/2 rounded-full bg-accent-line"
          style={{ left: `${String(elapsed)}%` }}
        />
      ) : null}
    </div>
  );
}

const TONE_TEXT: Record<Tone, string> = {
  ok: "text-signal-low",
  warn: "text-signal-medium",
  down: "text-signal-high",
  idle: "text-ink",
};

export function KpiTile({
  label,
  value,
  note,
  title,
  icon,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  title?: string;
  icon?: IconName;
  /** Colours the value; the note must still say in words what the colour means. */
  tone?: Tone;
}) {
  return (
    <div role="group" aria-label={label} className="rounded-[var(--radius-sheet)] border border-rule bg-paper-raised p-5 shadow-[var(--shadow-sheet)]">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-ink-soft">{label}</p>
        {icon ? (
          <span className="grid size-8 place-items-center rounded-lg bg-paper-sunk text-ink-faint">
            <Icon name={icon} className="size-4" />
          </span>
        ) : null}
      </div>
      <p className={`tabular mt-2 text-[1.75rem] leading-tight font-semibold tracking-tight ${TONE_TEXT[tone ?? "idle"]}`} title={title}>
        {value}
      </p>
      {note ? <p className="mt-1 text-sm text-ink-faint">{note}</p> : null}
    </div>
  );
}
