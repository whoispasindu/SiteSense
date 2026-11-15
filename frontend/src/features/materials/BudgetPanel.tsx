import { useBudget } from "../../api/materials";
import { Alert } from "../../components/ui/Alert";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { formatCompactMoney, formatMoney, toNumber } from "../../lib/money";
import { errorText } from "../admin/adminUtils";
import { formatDate } from "../projects/dates";
import { KpiTile } from "../projects/ProjectBits";
import { currencyCode } from "../../lib/locale";

const LEGEND = [
  { label: "Spent (delivered)", className: "bg-signal-low" },
  { label: "On order", className: "bg-accent-line" },
  { label: "Approved, not ordered", className: "bg-rule-strong" },
];

/** "Trend 1.20 on 23% of the budget", or why there is no trend yet. */
function basisText(trend: string | null, basisPct: string): string {
  if (trend === null) return "No commitments yet: forecast = budget";
  return `Trend ${toNumber(trend).toFixed(2)} on ${basisPct}% of the budget`;
}

function VarianceText({ variance, pct }: { variance: string; pct: string | null }) {
  const n = toNumber(variance);
  if (n === 0) return <span className="text-ink-soft">On budget</span>;
  const share = pct === null ? "" : ` · ${String(Math.abs(toNumber(pct)))}%`;
  return n < 0 ? (
    <span className="text-signal-high">
      {formatCompactMoney(Math.abs(n))} over{share}
    </span>
  ) : (
    <span className="text-signal-low">
      {formatCompactMoney(n)} under{share}
    </span>
  );
}

function overNote(overCount: number, variance: number): string {
  if (overCount > 0) return `${String(overCount)} section${overCount === 1 ? "" : "s"} more than 5% over`;
  return variance < 0 ? "Over budget, within 5% in every section" : "Within budget";
}

/**
 * Budget, committed, spent, forecast final cost and variance per BOQ section. "Committed" is
 * cumulative: every approved, ordered or delivered request counted once at its latest value. The
 * forecast is committed cost plus the remaining budget at the cost trend so far (Phase 8); a section
 * forecast more than 5% over its budget alerts the PM and QS once.
 */
export function BudgetPanel({ projectId }: { projectId: string }) {
  const budget = useBudget(projectId);
  if (budget.isPending) return <p className="text-sm text-ink-faint">Loading cost figures…</p>;
  if (budget.isError) return <Alert tone="error">{errorText(budget.error)}</Alert>;
  const { lines, totals } = budget.data;
  if (lines.length === 0) return null;
  const variance = toNumber(totals.variance);
  const overCount = lines.filter((l) => l.over_alert_line).length;

  return (
    <section aria-labelledby="cost-heading" className="space-y-4">
      <SectionHeading id="cost-heading" annotation="committed cost plus the remaining budget at the trend so far">
        Cost control
      </SectionHeading>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiTile icon="cost" label="Cost budget" value={formatCompactMoney(totals.budget)} title={formatMoney(totals.budget)} />
        <KpiTile
          icon="reports"
          label="Committed"
          value={formatCompactMoney(totals.committed)}
          title={formatMoney(totals.committed)}
          note={`Spent ${formatCompactMoney(totals.spent)} · on order ${formatCompactMoney(totals.on_order)}`}
        />
        <KpiTile
          icon="materials"
          label="Forecast final cost"
          value={formatCompactMoney(totals.forecast_final)}
          title={formatMoney(totals.forecast_final)}
          note={basisText(totals.trend, totals.basis_pct)}
        />
        <KpiTile
          icon="risk"
          label={variance < 0 ? "Forecast overrun" : "Forecast saving"}
          value={formatCompactMoney(Math.abs(variance))}
          title={formatMoney(totals.variance)}
          tone={variance < 0 ? "down" : "ok"}
          note={overNote(overCount, variance)}
        />
      </div>

      <Sheet className="relative overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">
            Cost budget, spent, committed, forecast final cost and variance by BOQ section, in {currencyCode()}
          </caption>
          <thead className="border-b border-rule bg-paper-sunk/60 text-xs font-medium whitespace-nowrap text-ink-faint">
            <tr>
              <th scope="col" className="px-4 py-2.5 text-left font-medium">Section</th>
              <th scope="col" className="hidden w-[26%] px-4 py-2.5 text-left font-medium lg:table-cell">
                <span className="sr-only">Use of budget</span>
              </th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Budget</th>
              <th scope="col" className="hidden px-4 py-2.5 text-right font-medium md:table-cell">Spent</th>
              <th scope="col" className="hidden px-4 py-2.5 text-right font-medium sm:table-cell">Committed</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Forecast</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Variance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {lines.map((line) => {
              const scale = Math.max(toNumber(line.budget), toNumber(line.committed), toNumber(line.forecast_final), 1);
              const width = (value: string) => `${String((toNumber(value) / scale) * 100)}%`;
              return (
                <tr key={line.section_id} className={line.over_alert_line ? "bg-signal-high-tint/30" : undefined}>
                  <th scope="row" className="px-4 py-3 text-left font-normal">
                    <span className="mr-2 font-mono text-xs text-ink-faint">{line.code}</span>
                    {line.name}
                    {line.over_alert_line ? (
                      <span className="mt-0.5 block text-xs text-signal-high">
                        Forecast more than 5% over
                        {line.over_budget_since ? ` · PM and QS alerted ${formatDate(line.over_budget_since)}` : ""}
                      </span>
                    ) : null}
                  </th>
                  <td aria-hidden="true" className="hidden px-4 py-3 lg:table-cell">
                    <div className="relative flex h-2.5 rounded-full bg-paper-sunk">
                      <div className="h-full rounded-l-full bg-signal-low" style={{ width: width(line.spent) }} />
                      <div className="h-full bg-accent-line" style={{ width: width(line.on_order) }} />
                      <div className="h-full bg-rule-strong" style={{ width: width(line.approved) }} />
                      <span className="absolute -inset-y-1 w-px bg-ink-faint" style={{ left: width(line.budget) }} />
                      <span
                        className={`absolute -inset-y-1.5 w-0.5 rounded-full ${line.over_alert_line ? "bg-signal-high" : "bg-ink"}`}
                        style={{ left: width(line.forecast_final) }}
                      />
                    </div>
                  </td>
                  <td className="tabular px-4 py-3 text-right whitespace-nowrap text-ink-soft">{formatCompactMoney(line.budget)}</td>
                  <td className="tabular hidden px-4 py-3 text-right whitespace-nowrap text-ink md:table-cell">
                    {formatCompactMoney(line.spent)}
                  </td>
                  <td className="tabular hidden px-4 py-3 text-right whitespace-nowrap text-ink sm:table-cell">
                    {formatCompactMoney(line.committed)}
                  </td>
                  <td className="tabular px-4 py-3 text-right whitespace-nowrap text-ink" title={basisText(line.trend, line.basis_pct)}>
                    {formatCompactMoney(line.forecast_final)}
                    <span className="block text-xs text-ink-faint">
                      {line.trend === null ? "no trend yet" : `trend ${toNumber(line.trend).toFixed(2)}`}
                    </span>
                  </td>
                  <td className="tabular px-4 py-3 text-right font-medium whitespace-nowrap">
                    <VarianceText variance={line.variance} pct={line.variance_pct} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="flex flex-wrap gap-x-5 gap-y-1 border-t border-rule px-4 py-2.5 text-xs text-ink-faint">
          {LEGEND.map((l) => (
            <span key={l.label} className="flex items-center gap-1.5">
              <span aria-hidden="true" className={`inline-block h-2 w-4 rounded-full ${l.className}`} />
              {l.label}
            </span>
          ))}
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-3 w-0.5 rounded-full bg-ink" />
            Forecast final cost
          </span>
          <span>
            Forecast = committed + the budget not yet committed × the cost trend so far (committed ÷ budgeted value of the same
            work). Early in a section the trend rests on little.
          </span>
        </p>
      </Sheet>
    </section>
  );
}
