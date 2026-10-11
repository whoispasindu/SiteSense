import { Link } from "react-router";

import { useRiskRanking } from "../../api/risk";
import { Alert } from "../../components/ui/Alert";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../admin/adminUtils";
import { RiskBadge, ScoreScale } from "./RiskBits";
import { delayRangeText, delayText, NO_RANGE_TEXT, overrunRangeText, overrunText, scoreRangeText } from "./risk";

/** The dashboard's ranking: every open project on the user's sites, highest risk first. */
export function RiskRankingPanel() {
  const ranking = useRiskRanking();

  return (
    <Sheet className="p-5">
      <SectionHeading annotation="model estimate, scored daily">Projects by risk</SectionHeading>
      {ranking.isPending ? <p className="py-6 text-sm text-ink-faint">Loading risk scores…</p> : null}
      {ranking.isError ? <Alert tone="error">{errorText(ranking.error)}</Alert> : null}
      {ranking.data?.length === 0 ? <p className="py-6 text-sm text-ink-soft">No open projects on your sites.</p> : null}
      {ranking.data && ranking.data.length > 0 ? (
        <ol aria-label="Projects ranked by risk" className="divide-y divide-rule">
          {ranking.data.map((r, index) => (
            <li key={r.project_id} className="grid grid-cols-[1.75rem_1fr] gap-x-3 gap-y-2 py-3.5 sm:grid-cols-[1.75rem_minmax(0,1fr)_11rem]">
              <span aria-hidden="true" className="tabular pt-0.5 font-mono text-xs text-ink-faint">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <Link to={`/projects/${r.project_id}`} className="truncate font-medium text-ink hover:underline">
                    {r.name}
                  </Link>
                  <span className="font-mono text-xs text-ink-faint">
                    {r.code} · {r.site_code}
                  </span>
                </div>
                {r.score !== null && r.delay_days !== null && r.overrun_pct !== null ? (
                  <p className="mt-0.5 text-sm text-ink-soft">
                    Forecast {delayText(r.delay_days)} ({r.ranges ? delayRangeText(r.ranges.delay_days) : NO_RANGE_TEXT}),{" "}
                    {overrunText(r.overrun_pct)} ({r.ranges ? overrunRangeText(r.ranges.overrun_pct) : NO_RANGE_TEXT})
                    {r.top_driver ? <span className="block text-xs text-ink-faint sm:inline sm:before:content-['_·_']">{r.top_driver}</span> : null}
                  </p>
                ) : (
                  <p className="mt-0.5 text-sm text-ink-faint">Not scored yet: scores are worked out every morning.</p>
                )}
              </div>
              {r.score !== null && r.level !== null ? (
                <div className="col-start-2 flex items-center gap-3 sm:col-start-3">
                  <span className="w-10 text-right">
                    <span className="tabular block text-lg leading-tight font-semibold text-ink">{r.score}</span>
                    {r.ranges ? (
                      <span className="tabular block text-[0.6875rem] leading-tight text-ink-faint" title={scoreRangeText(r.ranges.score)}>
                        {r.ranges.score.low}–{r.ranges.score.high}
                      </span>
                    ) : null}
                  </span>
                  <div className="flex-1 space-y-1.5">
                    <RiskBadge level={r.level} />
                    <ScoreScale score={r.score} level={r.level} range={r.ranges?.score} compact />
                  </div>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
      <p className="mt-3 text-xs text-ink-faint">
        Score 0 to 100: the worse of schedule and cost. 70 or more is High and alerts the project manager (BR-10); 40 to 69 is Medium.
      </p>
    </Sheet>
  );
}
