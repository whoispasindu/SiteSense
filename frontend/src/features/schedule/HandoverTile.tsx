import type { Network } from "../../api/schedule";
import type { Risk } from "../../api/risk";
import { formatDate } from "../projects/dates";
import { disagreement, modelWindow, slipText } from "./network";

/**
 * Forecast handover, two ways, each labelled: the programme's own calculation at current rates (Phase 9),
 * and the risk model's likely range (risk:read only). They answer different questions, so both show.
 */
export function HandoverTile({
  network,
  contractEnd,
  risk,
  showRisk,
}: {
  network: Network | undefined;
  contractEnd: string;
  risk: Risk | null | undefined;
  showRisk: boolean;
}) {
  const atRates = network?.forecast_end ?? null;
  const span = network ? modelWindow(network.planned_end, risk) : null;
  const note = atRates && span ? disagreement(atRates, span) : null;
  const late = network ? network.slip_days > 0 : false;

  return (
    <div
      role="group"
      aria-label="Forecast handover"
      className="rounded-[var(--radius-sheet)] border border-rule bg-paper-raised p-5 shadow-[var(--shadow-sheet)]"
    >
      <p className="text-sm font-medium text-ink-soft">Forecast handover</p>
      <dl className="mt-2 space-y-3">
        <div>
          <dt className="text-xs text-ink-faint">At current rates</dt>
          <dd className={`tabular text-[1.375rem] leading-tight font-semibold tracking-tight ${late ? "text-signal-high" : "text-ink"}`}>
            {atRates ? formatDate(atRates) : "—"}
          </dd>
          <dd className="text-xs text-ink-faint">
            {network ? `${slipText(network.slip_days)} against ${formatDate(network.planned_end)}` : `Contract end ${formatDate(contractEnd)}`}
          </dd>
        </div>
        {showRisk ? (
          <div>
            <dt className="text-xs text-ink-faint">Risk model, likely range</dt>
            <dd className="tabular text-sm font-medium text-ink">
              {span ? `${formatDate(span.from)} to ${formatDate(span.to)}` : "from the next scoring"}
            </dd>
          </div>
        ) : null}
      </dl>
      {note ? <p className="mt-2 border-t border-rule pt-2 text-xs text-signal-medium">{note}</p> : null}
    </div>
  );
}
