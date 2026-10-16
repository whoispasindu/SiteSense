import { useState } from "react";

import { useWhatIf, type ActionId, type Forecast, type PlannedAction } from "../../api/risk";
import { Alert } from "../../components/ui/Alert";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../admin/adminUtils";
import { formatDate } from "../projects/dates";
import { RiskBadge } from "./RiskBits";
import { delayRangeText, delayText, overrunRangeText, overrunText, savedCostText, savedDaysText, scoreRangeText } from "./risk";

const MONEY = /^\d{1,13}(\.\d{1,2})?$/;
const lkr = new Intl.NumberFormat("en-LK", { maximumFractionDigits: 0 });

function ForecastBlock({ title, forecast }: { title: string; forecast: Forecast }) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium tracking-wide text-ink-faint uppercase">{title}</p>
      <div className="flex items-center gap-3">
        <span className="tabular text-2xl font-semibold text-ink">{forecast.score}</span>
        <RiskBadge level={forecast.level} />
        <span className="tabular text-xs text-ink-faint">{scoreRangeText(forecast.score_range)}</span>
      </div>
      <p className="text-sm text-ink">
        {delayText(forecast.delay_days)} <span className="text-ink-faint">({delayRangeText(forecast.delay_range)})</span>
      </p>
      <p className="text-sm text-ink">
        {overrunText(forecast.overrun_pct)} <span className="text-ink-faint">({overrunRangeText(forecast.overrun_range)})</span>
      </p>
    </div>
  );
}

/**
 * The what-if planner: tick recovery actions and see how today's forecast would change. Every effect
 * is a range (the action delivering half its planned change, to all of it) and a simulation
 * estimate. The PM's cost for each action is added to the cost forecast; a blank cost is said, never
 * treated as free. Nothing is saved.
 */
export function WhatIfPlanner({ projectId }: { projectId: string }) {
  const [selected, setSelected] = useState<ActionId[]>([]);
  const [drafts, setDrafts] = useState<Partial<Record<ActionId, string>>>({});
  const [costs, setCosts] = useState<Partial<Record<ActionId, string>>>({});
  const planned: PlannedAction[] = selected.map((id) => ({ id, cost: costs[id] ?? null }));
  const whatIf = useWhatIf(projectId, planned);
  const data = whatIf.data;

  function toggle(id: ActionId, on: boolean) {
    setSelected((current) => (on ? [...current, id] : current.filter((x) => x !== id)));
  }

  function commitCost(id: ActionId) {
    const text = (drafts[id] ?? "").replaceAll(",", "").trim();
    setCosts((current) => ({ ...current, [id]: MONEY.test(text) ? text : undefined }));
  }

  return (
    <section aria-labelledby="what-if-heading" className="space-y-4">
      <SectionHeading id="what-if-heading" annotation="simulation estimate">
        What-if planner
      </SectionHeading>
      <p className="max-w-3xl text-sm text-ink-soft">
        Tick recovery actions to see how today&apos;s forecast would change. Each effect runs from the action delivering
        half its planned change to all of it. The model only knows what it learnt from simulated projects, so treat these
        as estimates. Nothing is saved.
      </p>
      {whatIf.isError ? <Alert tone="error">{errorText(whatIf.error)}</Alert> : null}
      {whatIf.isPending ? <p className="text-sm text-ink-faint">Working out today&apos;s forecast…</p> : null}
      {data ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <ul aria-label="Recovery actions" className="space-y-3">
            {data.actions.map((a) => {
              const inputId = `cost-${a.id}`;
              const draft = drafts[a.id] ?? "";
              const badCost = draft.trim() !== "" && !MONEY.test(draft.replaceAll(",", "").trim());
              return (
                <li key={a.id}>
                  <Sheet className={`p-4 ${selected.includes(a.id) ? "ring-2 ring-accent-line" : ""}`}>
                    <div className="flex items-start gap-3">
                      <input
                        id={`action-${a.id}`}
                        type="checkbox"
                        checked={selected.includes(a.id)}
                        onChange={(e) => {
                          toggle(a.id, e.target.checked);
                        }}
                        className="mt-1 size-4 accent-[var(--color-survey)]"
                      />
                      <div className="min-w-0 flex-1">
                        <label htmlFor={`action-${a.id}`} className="block font-medium text-ink">
                          {a.label}
                        </label>
                        <p className="text-sm text-ink-soft">{a.description}</p>
                        <p className="mt-1 text-xs text-ink-faint">For this project: {a.change}</p>
                      </div>
                    </div>
                    <p className="mt-2 pl-7 text-sm text-ink">
                      {savedDaysText(a.delay_saved_days)}, {savedCostText(a.overrun_saved_pct)}
                      <span className="ml-1 text-xs text-ink-faint">(simulation estimate)</span>
                    </p>
                    {selected.includes(a.id) ? (
                      <div className="mt-3 flex flex-wrap items-end gap-3 pl-7">
                        <label htmlFor={inputId} className="text-sm">
                          <span className="mb-1 block font-medium text-ink">Estimated cost (LKR)</span>
                          <input
                            id={inputId}
                            inputMode="decimal"
                            value={draft}
                            placeholder="cost not entered"
                            aria-invalid={badCost}
                            onChange={(e) => {
                              setDrafts((d) => ({ ...d, [a.id]: e.target.value }));
                            }}
                            onBlur={() => {
                              commitCost(a.id);
                            }}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") commitCost(a.id);
                            }}
                            className="tabular w-48 rounded-md border border-field-line bg-paper px-3 py-2 text-ink"
                          />
                        </label>
                        <p className="pb-2 text-xs text-ink-faint">
                          {badCost
                            ? "Enter an amount in rupees, up to two decimals."
                            : a.cost === null
                              ? "Cost not entered: not counted in the cost forecast."
                              : a.cost_pct === null
                                ? `LKR ${lkr.format(Number(a.cost))}: no cost budget to compare with.`
                                : `LKR ${lkr.format(Number(a.cost))}, ${a.cost_pct.toFixed(1)}% of the cost budget.`}
                        </p>
                      </div>
                    ) : null}
                  </Sheet>
                </li>
              );
            })}
          </ul>

          <Sheet className="h-fit space-y-4 p-5" aria-live="polite">
            <ForecastBlock title={`Today, ${formatDate(data.as_of)}`} forecast={data.baseline} />
            {data.plan && data.plan_delay_saved_days && data.plan_overrun_saved_pct ? (
              <>
                <div className="border-t border-rule pt-4">
                  <ForecastBlock
                    title={`With ${String(selected.length)} action${selected.length === 1 ? "" : "s"}`}
                    forecast={data.plan}
                  />
                </div>
                <p className="rounded-lg bg-paper-sunk px-3 py-2 text-sm text-ink">
                  Together: {savedDaysText(data.plan_delay_saved_days)}, {savedCostText(data.plan_overrun_saved_pct)} (costs
                  entered included).
                </p>
              </>
            ) : (
              <p className="border-t border-rule pt-4 text-sm text-ink-faint">Tick an action to see the forecast with it.</p>
            )}
            {data.costs_not_entered.length > 0 ? (
              <Alert tone="warn" title="Cost not entered">
                {data.costs_not_entered.join(", ")}: the cost forecast leaves {data.costs_not_entered.length === 1 ? "it" : "them"}{" "}
                out, so it looks better than it will be.
              </Alert>
            ) : null}
            {data.notes.length > 0 ? (
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-ink-faint">
                {data.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            ) : null}
            <p className="text-xs text-ink-faint">Simulation estimate from risk model v{data.model_version}. It suggests; people decide.</p>
          </Sheet>
        </div>
      ) : null}
      {data && data.advice.length > 0 ? (
        <div>
          <p className="text-sm font-semibold text-ink">Also worth doing</p>
          <p className="mb-2 text-xs text-ink-faint">Advice only: these change no forecast here.</p>
          <ul aria-label="Advice" className="space-y-2">
            {data.advice.map((a) => (
              <li key={a.id} className="rounded-lg border border-rule px-3 py-2 text-sm">
                <span className="font-medium text-ink">{a.label}.</span> <span className="text-ink-soft">{a.text}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
