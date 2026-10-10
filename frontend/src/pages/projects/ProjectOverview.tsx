import { Link } from "react-router";

import { TYPE_LABELS } from "../../api/projects";
import { useBudget } from "../../api/materials";
import { useAuth } from "../../auth/context";
import { primaryLinkClass } from "../../components/ui/Button";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { durationWeeks, formatDate } from "../../features/projects/dates";
import { KpiTile, ProgrammeBar } from "../../features/projects/ProjectBits";
import { StopWorkBanner } from "../../features/reports/StopWorkBanner";
import { ProjectRiskPanel } from "../../features/risk/ProjectRiskPanel";
import { formatAmount, formatCompactLKR, percent, toNumber } from "../../lib/money";
import { useCurrentProject } from "./projectContext";

export function ProjectOverview() {
  const p = useCurrentProject();
  const { can } = useAuth();
  const costs = useBudget(p.id, can("cost:read") && p.item_count > 0);
  // Rates and amounts arrive only for roles with "rates:read"; site engineers get none of them.
  const priced = p.contract_value !== undefined;
  const boq = toNumber(p.boq_total ?? 0);
  const budget = toNumber(p.budget_total ?? 0);
  const margin = boq > 0 ? ((boq - budget) / boq) * 100 : 0;
  const coverage = percent(p.boq_total ?? 0, p.contract_value ?? 0);
  const largest = Math.max(...p.sections.map((s) => toNumber(s.amount ?? 0)), 1);

  const titleRows: [string, string][] = [
    ["Client", p.client_name],
    ["Site", `${p.site.code} · ${p.site.name}`],
    ["Type", TYPE_LABELS[p.project_type]],
    ["Start", formatDate(p.start_date)],
    ["Planned end", formatDate(p.planned_end)],
    ["Duration", `${String(durationWeeks(p.start_date, p.planned_end))} weeks`],
  ];

  return (
    <div className="space-y-10">
      {can("reports:read") ? <StopWorkBanner projectId={p.id} /> : null}
      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <Sheet as="div">
          <p className="border-b border-rule px-4 py-3 text-sm font-semibold text-ink">Project details</p>
          <dl className="divide-y divide-rule text-sm">
            {titleRows.map(([term, value]) => (
              <div key={term} className="grid grid-cols-[7rem_1fr] gap-3 px-4 py-2.5">
                <dt className="text-ink-faint">{term}</dt>
                <dd className="min-w-0 font-medium break-words text-ink">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="border-t border-rule px-4 py-4">
            <ProgrammeBar start={p.start_date} end={p.planned_end} />
            <p className="mt-2 text-xs text-ink-faint">Contract period, with today marked.</p>
          </div>
        </Sheet>

        {priced ? (
        <div className="grid content-start gap-4 sm:grid-cols-2">
          <KpiTile icon="cost" label="Contract value" value={formatCompactLKR(p.contract_value ?? 0)} title={`LKR ${formatAmount(p.contract_value ?? 0)}`} />
          <KpiTile
            icon="projects"
            label="BOQ total"
            value={p.item_count ? formatCompactLKR(p.boq_total ?? 0) : "—"}
            title={`LKR ${formatAmount(p.boq_total ?? 0)}`}
            note={p.item_count ? `${String(p.item_count)} items · ${coverage.toFixed(1)}% of contract value` : "No BOQ imported yet"}
          />
          <KpiTile
            icon="materials"
            label="Cost budget"
            value={p.item_count ? formatCompactLKR(p.budget_total ?? 0) : "—"}
            title={`LKR ${formatAmount(p.budget_total ?? 0)}`}
            note={
              costs.data
                ? `Committed ${formatCompactLKR(costs.data.totals.committed)} · spent ${formatCompactLKR(costs.data.totals.spent)}`
                : "Cost to date is on the BOQ & budget tab"
            }
          />
          <KpiTile
            icon="risk"
            label="Planned margin"
            value={p.item_count ? `${margin.toFixed(1)}%` : "—"}
            tone={p.item_count ? (margin < 0 ? "down" : margin < 5 ? "warn" : "ok") : "idle"}
            note="BOQ value less cost budget"
          />
        </div>
        ) : (
          <div className="grid content-start gap-4 sm:grid-cols-2">
            <KpiTile
              icon="projects"
              label="BOQ items"
              value={String(p.item_count)}
              note={p.sections.length ? `In ${String(p.sections.length)} sections` : "No BOQ imported yet"}
            />
          </div>
        )}
      </div>

      {can("risk:read") ? <ProjectRiskPanel projectId={p.id} /> : null}

      <section aria-labelledby="sections-heading">
        <SectionHeading id="sections-heading" annotation={p.sections.length ? `${String(p.sections.length)} sections` : undefined}>
          {priced ? "Cost by BOQ section" : "BOQ sections"}
        </SectionHeading>
        {p.sections.length === 0 ? (
          <Sheet className="px-6 py-10 text-center">
            <p className="font-semibold">No bill of quantities yet</p>
            <p className="mt-1 text-sm text-ink-soft">
              {can("boq:manage") ? "Import the BOQ from Excel or CSV to see budgets by section." : "The quantity surveyor imports the BOQ."}
            </p>
            {can("boq:manage") ? (
              <Link
                to={`/projects/${p.id}/boq/import`}
                className={`mt-5 ${primaryLinkClass}`}
              >
                Import BOQ
              </Link>
            ) : null}
          </Sheet>
        ) : !priced ? (
          <Sheet>
            <ul aria-label="BOQ sections" className="divide-y divide-rule">
              {p.sections.map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                  <span>
                    <span className="mr-2 font-mono text-xs text-ink-faint">{s.code}</span>
                    {s.name}
                  </span>
                  <span className="text-ink-faint">{s.item_count} items</span>
                </li>
              ))}
            </ul>
          </Sheet>
        ) : (
          <Sheet className="relative overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">BOQ value and cost budget by section, in LKR</caption>
              <thead className="border-b border-rule bg-paper-sunk/60 text-xs text-ink-faint">
                <tr>
                  <th scope="col" className="px-4 py-2.5 text-left font-medium">
                    Section
                  </th>
                  <th scope="col" className="hidden w-[38%] px-4 py-2.5 text-left font-medium md:table-cell">
                    <span className="sr-only">Share of BOQ</span>
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    BOQ value
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    Budget
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {p.sections.map((s) => {
                  const width = (toNumber(s.amount ?? 0) / largest) * 100;
                  const budgetMark = percent(s.budget_amount ?? 0, s.amount ?? 0);
                  return (
                    <tr key={s.id}>
                      <th scope="row" className="px-4 py-3 text-left font-normal">
                        <span className="mr-2 font-mono text-xs text-ink-faint">{s.code}</span>
                        {s.name}
                      </th>
                      <td aria-hidden="true" className="hidden px-4 py-3 md:table-cell">
                        <div className="relative h-2.5 rounded-full bg-paper-sunk">
                          <div className="h-full rounded-full bg-accent-line" style={{ width: `${String(width)}%` }} />
                          <span
                            className="absolute -top-1 -bottom-1 w-[3px] -translate-x-1/2 rounded-full bg-ink"
                            style={{ left: `${String((width * Math.min(budgetMark, 100)) / 100)}%` }}
                          />
                        </div>
                      </td>
                      <td className="tabular px-4 py-3 text-right font-medium text-ink">{formatCompactLKR(s.amount ?? 0)}</td>
                      <td className="tabular px-4 py-3 text-right text-ink-soft">{formatCompactLKR(s.budget_amount ?? 0)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="border-t border-rule px-4 py-2.5 text-xs text-ink-faint">
              Bar: BOQ value, relative to the largest section. Dark mark: where the cost budget sits within it.
            </p>
          </Sheet>
        )}
      </section>

      <section aria-labelledby="team-heading">
        <SectionHeading id="team-heading" annotation={`site ${p.site.code}`}>
          Team
        </SectionHeading>
        {p.team.length === 0 ? (
          <p className="text-sm text-ink-soft">Nobody is assigned to this site yet. The company admin assigns people to sites.</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {p.team.map((m) => (
              <li key={m.id} className="flex items-center gap-3 rounded-[var(--radius-sheet)] border border-rule bg-paper-raised px-4 py-3 shadow-[var(--shadow-sheet)]">
                <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-full bg-asphalt text-xs font-semibold text-hivis">
                  {m.full_name
                    .split(/\s+/)
                    .map((w) => w[0])
                    .slice(0, 2)
                    .join("")
                    .toUpperCase()}
                </span>
                <span className="min-w-0">
                  <span className="block truncate font-medium text-ink">{m.full_name}</span>
                  <span className="block text-sm text-ink-faint">{m.role_label}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
