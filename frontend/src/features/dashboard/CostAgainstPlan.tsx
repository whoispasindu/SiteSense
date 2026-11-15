import { Link } from "react-router";

import type { CostAgainstPlan as Cost, CostPoint } from "../../api/dashboard";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { formatCompactMoney, toNumber } from "../../lib/money";
import { currencyCode } from "../../lib/locale";

function pct(value: number, max: number): string {
  return `${String(Math.max(0, Math.min(100, (value / max) * 100)))}%`;
}

function Ruler({ point, max }: { point: CostPoint; max: number }) {
  const budget = toNumber(point.budget);
  const committed = toNumber(point.committed);
  const final = toNumber(point.forecast_final);
  const range = point.model_final_range;
  const low = range ? toNumber(range.low) : null;
  const high = range ? toNumber(range.high) : null;
  const over = final > budget;

  if (budget <= 0) {
    return (
      <li className="flex flex-wrap items-baseline justify-between gap-3 py-3.5">
        <Link to={`/projects/${point.project_id}`} className="min-w-0 truncate font-medium text-ink hover:underline">
          {point.name} <span className="font-mono text-xs font-normal text-ink-faint">{point.code}</span>
        </Link>
        <span className="text-sm text-ink-faint">No budget yet: the quantity surveyor sets it from the BOQ.</span>
      </li>
    );
  }

  return (
    <li className="py-3.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <Link to={`/projects/${point.project_id}`} className="min-w-0 truncate font-medium text-ink hover:underline">
          {point.name} <span className="font-mono text-xs font-normal text-ink-faint">{point.code}</span>
        </Link>
        <span className="tabular text-xs text-ink-faint">budget {formatCompactMoney(budget)}</span>
      </div>
      {/* The ruler: committed so far (solid), the risk model's likely final cost (hatched band),
          the forecast at current rates (diamond) and the budget (the tall tick). */}
      <div aria-hidden="true" className="relative mt-2.5 h-6">
        <div className="absolute inset-x-0 top-2.5 h-1 rounded-full bg-paper-sunk" />
        <div className="absolute top-2 left-0 h-2 rounded-r-[4px] bg-accent-line" style={{ width: pct(committed, max) }} />
        {low !== null && high !== null ? (
          <div
            className="cost-range absolute top-0.5 h-5 rounded-[3px] border border-survey/50"
            style={{ left: pct(low, max), width: `calc(${pct(high - low, max)} + 2px)` }}
          />
        ) : null}
        <div className="absolute -top-0.5 h-7 w-0.5 bg-ink" style={{ left: pct(budget, max) }} />
        <div
          className="absolute top-1 size-3.5 rotate-45 rounded-[2px] border-2 border-paper-raised bg-ink"
          style={{ left: `calc(${pct(final, max)} - 7px)` }}
        />
      </div>
      <p className="tabular mt-1.5 text-sm text-ink-soft">
        Committed {formatCompactMoney(committed)} · at current rates {formatCompactMoney(final)}
        {over ? <span className="font-medium text-signal-high"> (over budget)</span> : null}
        {low !== null && high !== null ? (
          <> · risk model, likely {formatCompactMoney(low)} to {formatCompactMoney(high)}</>
        ) : (
          <span className="text-ink-faint"> · risk model range from the next scoring</span>
        )}
      </p>
    </li>
  );
}

/** Budget against what is committed and where each project is heading, at current rates and per the risk model. */
export function CostAgainstPlan({ cost }: { cost: Cost }) {
  const values = cost.projects.flatMap((p) => [
    toNumber(p.budget),
    toNumber(p.committed),
    toNumber(p.forecast_final),
    p.model_final_range ? toNumber(p.model_final_range.high) : 0,
  ]);
  const max = Math.max(1, ...values) * 1.05;
  const t = cost.totals;

  return (
    <Sheet className="p-5">
      <SectionHeading annotation={`${currencyCode()}, cost roles only`}>Cost against plan</SectionHeading>
      <dl className="grid grid-cols-2 gap-3 border-b border-rule pb-4 sm:grid-cols-4">
        {[
          ["Budget", formatCompactMoney(t.budget)],
          ["Committed", formatCompactMoney(t.committed)],
          ["At current rates", formatCompactMoney(t.forecast_final)],
          ["Over budget", `${String(t.over_budget)} of ${String(cost.projects.length)}`],
        ].map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-ink-faint">{label}</dt>
            <dd className="tabular text-lg font-semibold text-ink">{value}</dd>
          </div>
        ))}
      </dl>
      {cost.projects.length === 0 ? <p className="py-6 text-sm text-ink-soft">No open projects with a budget yet.</p> : null}
      <ul aria-label="Cost against plan by project" className="divide-y divide-rule">
        {cost.projects.map((p) => (
          <Ruler key={p.project_id} point={p} max={max} />
        ))}
      </ul>
      <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-ink-faint">
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-2 w-4 rounded-r-[3px] bg-accent-line" /> Committed
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-0.5 bg-ink" /> Budget
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block size-2.5 rotate-45 rounded-[1px] bg-ink" /> At current rates
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="cost-range inline-block h-3 w-5 rounded-[2px] border border-survey/50" /> Risk model, likely range
        </span>
      </p>
    </Sheet>
  );
}
