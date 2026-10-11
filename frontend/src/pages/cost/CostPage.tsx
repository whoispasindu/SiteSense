import { Link } from "react-router";

import { useCostOverview, VARIATION_STATUS_LABELS, type VariationStatus } from "../../api/contract";
import { Alert } from "../../components/ui/Alert";
import { PageHeader } from "../../components/ui/PageHeader";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { errorText } from "../../features/admin/adminUtils";
import { formatAmount, formatCompactLKR, toNumber } from "../../lib/money";
import { timeAgo } from "../../lib/time";

/** Cost & claims across the PM's or QS's projects: forecast against budget, claims, what waits for them. */
export function CostPage() {
  const overview = useCostOverview();
  if (overview.isPending) return <p className="py-16 text-center text-ink-faint">Loading cost figures…</p>;
  if (overview.isError) return <Alert tone="error">{errorText(overview.error)}</Alert>;
  const { projects, waiting_for_you: waiting } = overview.data;

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHeader
        title="Cost & claims"
        description="Forecast final cost against budget, progress claims and variations on your projects."
      />

      <section aria-labelledby="waiting-heading" className="space-y-3">
        <SectionHeading id="waiting-heading" annotation="claims to approve, variations to price or decide">
          Waiting for you
        </SectionHeading>
        {waiting.length === 0 ? (
          <Sheet className="p-6 text-sm text-ink-faint">Nothing is waiting for you.</Sheet>
        ) : (
          <Sheet className="divide-y divide-rule">
            {waiting.map((w) => (
              <Link
                key={`${w.kind}-${w.id}`}
                to={w.kind === "claim" ? `/projects/${w.project_id}/claims` : `/variations/${w.id}`}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 hover:bg-paper-sunk"
              >
                <span className="font-mono text-sm text-ink-faint">{w.number}</span>
                <span className="min-w-0 flex-1 font-medium text-ink">{w.title}</span>
                <span className="text-sm text-ink-faint">
                  {w.project_code} · {timeAgo(w.since)}
                </span>
                <StatusBadge
                  tone="warn"
                  label={w.kind === "claim" ? "Claim to approve" : VARIATION_STATUS_LABELS[w.status as VariationStatus]}
                />
              </Link>
            ))}
          </Sheet>
        )}
      </section>

      <section aria-labelledby="projects-cost-heading" className="space-y-3">
        <SectionHeading id="projects-cost-heading" annotation="LKR; contract value includes approved variations">
          Projects
        </SectionHeading>
        <Sheet className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Contract, budget, forecast final cost, variance and claims by project</caption>
            <thead className="border-b border-rule bg-paper-sunk/60 text-xs whitespace-nowrap text-ink-faint">
              <tr>
                <th scope="col" className="px-4 py-2.5 text-left font-medium">Project</th>
                <th scope="col" className="hidden px-4 py-2.5 text-right font-medium md:table-cell">Contract</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Budget</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Forecast</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Variance</th>
                <th scope="col" className="hidden px-4 py-2.5 text-right font-medium lg:table-cell">Claimed</th>
                <th scope="col" className="hidden px-4 py-2.5 text-left font-medium xl:table-cell">Open</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {projects.map((p) => {
                const variance = toNumber(p.variance);
                const noBudget = toNumber(p.budget) === 0;
                return (
                  <tr key={p.project_id}>
                    <th scope="row" className="min-w-48 px-4 py-3 text-left font-normal">
                      <Link to={`/projects/${p.project_id}/boq`} className="font-medium text-ink hover:underline">
                        {p.name}
                      </Link>
                      <span className="block font-mono text-xs text-ink-faint">{p.code}</span>
                      {p.sections_over > 0 ? (
                        <span className="block text-xs text-signal-high">
                          {p.sections_over} section{p.sections_over === 1 ? "" : "s"} forecast more than 5% over
                        </span>
                      ) : null}
                    </th>
                    <td className="tabular hidden px-4 py-3 text-right whitespace-nowrap text-ink-soft md:table-cell" title={`LKR ${formatAmount(p.contract_value)}`}>
                      {formatCompactLKR(p.contract_value)}
                    </td>
                    {noBudget ? (
                      <td colSpan={3} className="px-4 py-3 text-right text-ink-faint">
                        No BOQ budget yet
                      </td>
                    ) : (
                      <>
                        <td className="tabular px-4 py-3 text-right whitespace-nowrap text-ink-soft">{formatCompactLKR(p.budget)}</td>
                        <td className="tabular px-4 py-3 text-right whitespace-nowrap text-ink">{formatCompactLKR(p.forecast_final)}</td>
                        <td
                          className={`tabular px-4 py-3 text-right font-medium whitespace-nowrap ${variance < 0 ? "text-signal-high" : "text-ink"}`}
                        >
                          {variance === 0 ? "On budget" : `${formatCompactLKR(Math.abs(variance))} ${variance < 0 ? "over" : "under"}`}
                        </td>
                      </>
                    )}
                    <td className="tabular hidden px-4 py-3 text-right whitespace-nowrap text-ink lg:table-cell">
                      <Link to={`/projects/${p.project_id}/claims`} className="hover:underline">
                        {formatCompactLKR(p.claimed_to_date)}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-3 text-ink-soft xl:table-cell">
                      {[p.open_claim ? `${p.open_claim} to approve` : null, p.variations_open > 0 ? `${String(p.variations_open)} variation${p.variations_open === 1 ? "" : "s"}` : null]
                        .filter(Boolean)
                        .join(" · ") || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Sheet>
      </section>
    </div>
  );
}
