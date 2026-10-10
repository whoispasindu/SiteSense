import { useProjectRisk } from "../../api/risk";
import { Alert } from "../../components/ui/Alert";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { formatSiteDate } from "../../lib/time";
import { errorText } from "../admin/adminUtils";
import { DriverList, RiskBadge, ScoreScale } from "./RiskBits";
import { delayText, overrunText } from "./risk";

/** The project's latest risk forecast: score, what it means, what moved it, and what data it lacked. */
export function ProjectRiskPanel({ projectId }: { projectId: string }) {
  const risk = useProjectRisk(projectId);

  return (
    <section aria-labelledby="risk-heading" className="space-y-4">
      <SectionHeading id="risk-heading" annotation="model estimate">
        Delay and cost risk
      </SectionHeading>
      {risk.isPending ? <p className="text-sm text-ink-faint">Loading the risk forecast…</p> : null}
      {risk.isError ? <Alert tone="error">{errorText(risk.error)}</Alert> : null}
      {risk.data && risk.data.latest === null ? (
        <Sheet className="p-5">
          <p className="text-sm text-ink-soft">Not scored yet. Every open project is scored each morning and again when a daily report is filed.</p>
        </Sheet>
      ) : null}
      {risk.data?.latest ? (
        <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
          <Sheet className="space-y-4 p-5">
            <div className="flex items-end justify-between gap-3">
              <p className="tabular text-5xl leading-none font-semibold tracking-tight text-ink">
                {risk.data.latest.score}
                <span className="ml-1 text-base font-normal text-ink-faint">/ 100</span>
              </p>
              <RiskBadge level={risk.data.latest.level} />
            </div>
            <ScoreScale score={risk.data.latest.score} level={risk.data.latest.level} />
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-ink-faint">Handover</dt>
                <dd className="font-medium text-ink">{delayText(risk.data.latest.delay_days)}</dd>
              </div>
              <div>
                <dt className="text-ink-faint">Cost</dt>
                <dd className="font-medium text-ink">{overrunText(risk.data.latest.overrun_pct)}</dd>
              </div>
            </dl>
            <p className="border-t border-rule pt-3 text-xs text-ink-faint">
              An estimate from risk model v{risk.data.latest.model_version}, trained on simulated projects, scored{" "}
              {formatSiteDate(new Date(risk.data.latest.scored_at))}. It suggests; people decide.
            </p>
          </Sheet>
          <Sheet className="p-5">
            <p className="text-sm font-semibold text-ink">What moved the forecast</p>
            <p className="mb-2 text-xs text-ink-faint">Compared with a typical project at the same stage (approximate shares).</p>
            <DriverList drivers={risk.data.latest.drivers} />
            {risk.data.latest.notes.length > 0 ? (
              <div className="mt-4 rounded-lg bg-paper-sunk px-3 py-2.5">
                <p className="text-xs font-medium text-ink-soft">Gaps in the data</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-ink-faint">
                  {risk.data.latest.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Sheet>
        </div>
      ) : null}
    </section>
  );
}
