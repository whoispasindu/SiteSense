import { Link } from "react-router";

import { useBriefing } from "../../api/dashboard";
import { Alert } from "../../components/ui/Alert";
import { Icon } from "../../components/ui/icons";
import { errorText } from "../admin/adminUtils";
import { siteClock, sourceText } from "./dashboard";

/**
 * Today's briefing: 3 to 5 bullets on what needs attention. Always labelled "AI-written" or
 * "Rule-based" so the reader knows which they are reading; each bullet names the records it rests on.
 */
export function BriefingCard({ projectIds }: { projectIds: Map<string, string> }) {
  const briefing = useBriefing();
  const data = briefing.data;
  const ai = data?.source === "ai";

  return (
    <section
      aria-labelledby="briefing-title"
      className="relative overflow-hidden rounded-[var(--radius-sheet)] border border-rule bg-paper-raised shadow-[var(--shadow-sheet)]"
    >
      {/* The hi-vis edge: the one place on the page that says "read this first". */}
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1.5 bg-hivis" />
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule py-3 pr-5 pl-6">
        <div className="flex items-center gap-3">
          <h2 id="briefing-title" className="text-base font-semibold tracking-tight text-ink">
            Today&rsquo;s briefing
          </h2>
          {data ? (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${
                ai ? "border-survey/30 bg-survey/10 text-survey" : "border-rule-strong bg-paper-sunk text-ink-soft"
              }`}
              title={ai && data.model ? `Written by ${data.model} from the facts below` : "Written by fixed rules from the facts below"}
            >
              <Icon name={ai ? "spark" : "rules"} className="size-3.5" />
              {data.label}
            </span>
          ) : null}
        </div>
        {data ? (
          <p className="font-mono text-xs text-ink-faint">
            written {siteClock(data.generated_at)} · counts from SiteSense records
          </p>
        ) : null}
      </div>

      <div className="py-4 pr-5 pl-6">
        {briefing.isPending ? (
          <div role="status" aria-busy="true" aria-label="Writing today's briefing" className="space-y-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-4 animate-pulse rounded bg-paper-sunk" style={{ width: `${String(88 - i * 14)}%` }} />
            ))}
          </div>
        ) : null}
        {briefing.isError ? <Alert tone="error">{errorText(briefing.error)}</Alert> : null}
        {data ? (
          <>
            <ol aria-label="Briefing points" className="space-y-3">
              {data.bullets.map((bullet, index) => (
                <li key={`${String(index)}-${bullet.text.slice(0, 24)}`} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-2">
                  <span aria-hidden="true" className="tabular pt-0.5 font-mono text-xs text-ink-faint">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <p className="text-[0.9375rem] leading-relaxed text-ink">{bullet.text}</p>
                    {bullet.projects.length > 0 || bullet.sources.length > 0 ? (
                      <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-faint">
                        {bullet.projects.map((code) => {
                          const id = projectIds.get(code);
                          return id ? (
                            <Link key={code} to={`/projects/${id}`} className="font-mono font-medium text-ink-soft underline-offset-2 hover:underline">
                              {code}
                            </Link>
                          ) : (
                            <span key={code} className="font-mono">
                              {code}
                            </span>
                          );
                        })}
                        {bullet.sources.length > 0 ? (
                          <span>from {bullet.sources.map((s) => sourceText(s.kind, s.count)).join(" · ")}</span>
                        ) : null}
                      </p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
            {data.note ? <p className="mt-4 text-sm text-ink-soft">{data.note}</p> : null}
          </>
        ) : null}
      </div>
    </section>
  );
}
