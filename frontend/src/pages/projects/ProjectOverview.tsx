import { Link } from "react-router";

import { TYPE_LABELS } from "../../api/projects";
import { useAuth } from "../../auth/context";
import { DimensionHeading } from "../../components/ui/DimensionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { durationWeeks, formatDate } from "../../features/projects/dates";
import { KpiTile, ProgrammeBar } from "../../features/projects/ProjectBits";
import { formatAmount, formatCompactLKR, percent, toNumber } from "../../lib/money";
import { useCurrentProject } from "./projectContext";

export function ProjectOverview() {
  const p = useCurrentProject();
  const { can } = useAuth();
  const boq = toNumber(p.boq_total);
  const budget = toNumber(p.budget_total);
  const margin = boq > 0 ? ((boq - budget) / boq) * 100 : 0;
  const coverage = percent(p.boq_total, p.contract_value);
  const largest = Math.max(...p.sections.map((s) => toNumber(s.amount)), 1);

  const titleRows: [string, string][] = [
    ["Client", p.client_name],
    ["Site", `${p.site.code} · ${p.site.name}`],
    ["Type", TYPE_LABELS[p.project_type]],
    ["Start", formatDate(p.start_date)],
    ["Planned end", formatDate(p.planned_end)],
    ["Duration", `${String(durationWeeks(p.start_date, p.planned_end))} weeks`],
  ];

  return (
    <div className="space-y-12">
      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <Sheet as="div">
          <p className="font-wide border-b-2 border-ink px-4 py-2 text-[0.65rem] font-extrabold tracking-[0.24em] uppercase">
            Title block
          </p>
          <dl className="divide-y divide-rule text-sm">
            {titleRows.map(([term, value]) => (
              <div key={term} className="grid grid-cols-[7rem_1fr] gap-3 px-4 py-2.5">
                <dt className="font-mono text-[0.68rem] tracking-wider text-ink-faint uppercase">{term}</dt>
                <dd className="min-w-0 break-words">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="border-t border-rule px-4 py-4">
            <ProgrammeBar start={p.start_date} end={p.planned_end} />
            <p className="mt-2 text-xs text-ink-faint">Contract period, with today marked.</p>
          </div>
        </Sheet>

        <div className="grid content-start gap-4 sm:grid-cols-2">
          <KpiTile sheetCode="K-01" label="Contract value" value={formatCompactLKR(p.contract_value)} title={`LKR ${formatAmount(p.contract_value)}`} />
          <KpiTile
            sheetCode="K-02"
            label="BOQ total"
            value={p.item_count ? formatCompactLKR(p.boq_total) : "—"}
            title={`LKR ${formatAmount(p.boq_total)}`}
            note={p.item_count ? `${String(p.item_count)} items · ${coverage.toFixed(1)}% of contract value` : "No BOQ imported yet"}
          />
          <KpiTile
            sheetCode="K-03"
            label="Cost budget"
            value={p.item_count ? formatCompactLKR(p.budget_total) : "—"}
            title={`LKR ${formatAmount(p.budget_total)}`}
            note="Committed and spent cost arrive with materials (Phase 5)"
          />
          <KpiTile
            sheetCode="K-04"
            label="Planned margin"
            value={p.item_count ? `${margin.toFixed(1)} %` : "—"}
            note="BOQ value less cost budget"
          />
        </div>
      </div>

      <section aria-labelledby="sections-heading">
        <DimensionHeading id="sections-heading" annotation={p.sections.length ? `${String(p.sections.length)} sections` : undefined}>
          Cost by BOQ section
        </DimensionHeading>
        {p.sections.length === 0 ? (
          <Sheet className="px-6 py-10 text-center">
            <p className="font-semibold">No bill of quantities yet</p>
            <p className="mt-1 text-sm text-ink-soft">
              {can("boq:manage") ? "Import the BOQ from Excel or CSV to see budgets by section." : "The quantity surveyor imports the BOQ."}
            </p>
            {can("boq:manage") ? (
              <Link
                to={`/projects/${p.id}/boq/import`}
                className="font-wide mt-5 inline-flex min-h-11 items-center rounded-[var(--radius-sheet)] border-2 border-ink bg-hivis px-5 text-xs font-bold tracking-[0.12em] uppercase shadow-[3px_3px_0_0_var(--color-ink)] hover:bg-hivis-deep"
              >
                Import BOQ
              </Link>
            ) : null}
          </Sheet>
        ) : (
          <Sheet className="relative overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">BOQ value and cost budget by section, in LKR</caption>
              <thead className="border-b border-rule-strong bg-paper-sunk font-mono text-[0.65rem] tracking-[0.14em] text-ink-soft uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5 text-left font-normal">
                    Section
                  </th>
                  <th scope="col" className="hidden w-[38%] px-4 py-2.5 text-left font-normal md:table-cell">
                    <span className="sr-only">Share of BOQ</span>
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-normal">
                    BOQ value
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-normal">
                    Budget
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {p.sections.map((s) => {
                  const width = (toNumber(s.amount) / largest) * 100;
                  const budgetMark = percent(s.budget_amount, s.amount);
                  return (
                    <tr key={s.id}>
                      <th scope="row" className="px-4 py-3 text-left font-normal">
                        <span className="mr-2 font-mono text-xs text-ink-faint">{s.code}</span>
                        {s.name}
                      </th>
                      <td aria-hidden="true" className="hidden px-4 py-3 md:table-cell">
                        <div className="relative h-3 rounded-[2px] bg-paper-sunk">
                          <div className="h-full rounded-[2px] bg-ink" style={{ width: `${String(width)}%` }} />
                          <span
                            className="absolute -top-1 -bottom-1 w-0.5 bg-hivis"
                            style={{ left: `${String((width * Math.min(budgetMark, 100)) / 100)}%` }}
                          />
                        </div>
                      </td>
                      <td className="tabular px-4 py-3 text-right font-mono">{formatCompactLKR(s.amount)}</td>
                      <td className="tabular px-4 py-3 text-right font-mono text-ink-soft">{formatCompactLKR(s.budget_amount)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="border-t border-rule px-4 py-2.5 text-xs text-ink-faint">
              Black bar: BOQ value. Yellow mark: where the cost budget sits within it.
            </p>
          </Sheet>
        )}
      </section>

      <section aria-labelledby="team-heading">
        <DimensionHeading id="team-heading" annotation={`site ${p.site.code}`}>
          Team
        </DimensionHeading>
        {p.team.length === 0 ? (
          <p className="text-sm text-ink-soft">Nobody is assigned to this site yet. The company admin assigns people to sites.</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {p.team.map((m) => (
              <li key={m.id} className="flex items-center gap-3 rounded-[var(--radius-sheet)] border border-rule bg-paper-raised px-4 py-3">
                <span aria-hidden="true" className="font-wide grid size-9 shrink-0 place-items-center rounded-[2px] bg-asphalt text-xs font-bold text-hivis">
                  {m.full_name
                    .split(/\s+/)
                    .map((w) => w[0])
                    .slice(0, 2)
                    .join("")
                    .toUpperCase()}
                </span>
                <span className="min-w-0">
                  <span className="block truncate font-semibold">{m.full_name}</span>
                  <span className="block font-mono text-[0.65rem] tracking-wider text-ink-faint uppercase">{m.role_label}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
