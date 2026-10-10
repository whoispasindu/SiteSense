import { useBudget } from "../../api/materials";
import { Alert } from "../../components/ui/Alert";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { formatAmount, formatCompactLKR, toNumber } from "../../lib/money";
import { errorText } from "../admin/adminUtils";
import { KpiTile } from "../projects/ProjectBits";

const LEGEND = [
  { label: "Spent (delivered)", className: "bg-signal-low" },
  { label: "Committed (ordered)", className: "bg-accent-line" },
  { label: "Approved, not ordered", className: "bg-rule-strong" },
];

/** Budget against approved, committed and spent cost per BOQ section. Updates itself from orders and deliveries. */
export function BudgetPanel({ projectId }: { projectId: string }) {
  const budget = useBudget(projectId);
  if (budget.isPending) return <p className="text-sm text-ink-faint">Loading cost figures…</p>;
  if (budget.isError) return <Alert tone="error">{errorText(budget.error)}</Alert>;
  const { lines, totals } = budget.data;
  if (lines.length === 0) return null;
  const variance = toNumber(totals.variance);

  return (
    <section aria-labelledby="cost-heading" className="space-y-4">
      <SectionHeading id="cost-heading" annotation="from purchase orders and deliveries">
        Cost control
      </SectionHeading>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiTile icon="cost" label="Cost budget" value={formatCompactLKR(totals.budget)} title={`LKR ${formatAmount(totals.budget)}`} />
        <KpiTile
          icon="materials"
          label="Spent"
          value={formatCompactLKR(totals.spent)}
          title={`LKR ${formatAmount(totals.spent)}`}
          note={`Committed ${formatCompactLKR(totals.committed)} more on orders`}
        />
        <KpiTile
          icon="reports"
          label="Forecast cost"
          value={formatCompactLKR(totals.forecast)}
          title={`LKR ${formatAmount(totals.forecast)}`}
          note="Spent + committed + approved"
        />
        <KpiTile
          icon="risk"
          label={variance < 0 ? "Over budget" : "Left in budget"}
          value={formatCompactLKR(Math.abs(variance))}
          title={`LKR ${formatAmount(totals.variance)}`}
          tone={variance < 0 ? "down" : "ok"}
          note={variance < 0 ? "Forecast exceeds the budget" : "Budget less forecast"}
        />
      </div>

      <Sheet className="relative overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Cost budget, spent, committed and approved cost by BOQ section, in LKR</caption>
          <thead className="border-b border-rule bg-paper-sunk/60 text-xs font-medium whitespace-nowrap text-ink-faint">
            <tr>
              <th scope="col" className="px-4 py-2.5 text-left font-medium">Section</th>
              <th scope="col" className="hidden w-[34%] px-4 py-2.5 text-left font-medium md:table-cell">
                <span className="sr-only">Use of budget</span>
              </th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Budget</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Spent</th>
              <th scope="col" className="hidden px-4 py-2.5 text-right font-medium sm:table-cell">Committed</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Left</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {lines.map((line) => {
              const scale = Math.max(toNumber(line.budget), toNumber(line.forecast), 1);
              const width = (value: string) => `${String((toNumber(value) / scale) * 100)}%`;
              const over = toNumber(line.variance) < 0;
              return (
                <tr key={line.section_id}>
                  <th scope="row" className="px-4 py-3 text-left font-normal">
                    <span className="mr-2 font-mono text-xs text-ink-faint">{line.code}</span>
                    {line.name}
                  </th>
                  <td aria-hidden="true" className="hidden px-4 py-3 md:table-cell">
                    <div className="relative flex h-2.5 overflow-hidden rounded-full bg-paper-sunk">
                      <div className="h-full bg-signal-low" style={{ width: width(line.spent) }} />
                      <div className="h-full bg-accent-line" style={{ width: width(line.committed) }} />
                      <div className="h-full bg-rule-strong" style={{ width: width(line.approved) }} />
                      {over ? (
                        <span className="absolute inset-y-0 w-0.5 bg-signal-high" style={{ left: width(line.budget) }} />
                      ) : null}
                    </div>
                  </td>
                  <td className="tabular px-4 py-3 text-right whitespace-nowrap text-ink-soft">{formatCompactLKR(line.budget)}</td>
                  <td className="tabular px-4 py-3 text-right whitespace-nowrap text-ink">{formatCompactLKR(line.spent)}</td>
                  <td className="tabular hidden px-4 py-3 text-right whitespace-nowrap text-ink-soft sm:table-cell">
                    {formatCompactLKR(line.committed)}
                  </td>
                  <td className={`tabular px-4 py-3 text-right font-medium whitespace-nowrap ${over ? "text-signal-high" : "text-ink"}`}>
                    {over ? `${formatCompactLKR(Math.abs(toNumber(line.variance)))} over` : formatCompactLKR(line.variance)}
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
          <span>Left = budget less spent, committed and approved.</span>
        </p>
      </Sheet>
    </section>
  );
}
