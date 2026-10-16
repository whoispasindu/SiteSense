import { useEffect, useRef, useState, type SubmitEvent } from "react";
import { Link } from "react-router";

import {
  allowedActions,
  CATEGORY_LABELS,
  ISSUE_CATEGORIES,
  SEVERITIES,
  SEVERITY_LABELS,
  useAnalyze,
  useCloseAction,
  useConfirmIssues,
  useReportIssues,
  type Issue,
  type IssueCategory,
  type IssueSeverity,
  type ReportAction,
  type ReportIssues,
} from "../../api/issues";
import { useTasks } from "../../api/schedule";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge, type Tone } from "../../components/ui/StatusBadge";
import { errorText } from "../admin/adminUtils";
import { stopScopeValid, tasksInProgress, type StopScopeValue } from "./stopScope";
import { StopScopeFields } from "./StopScopeFields";

const SEVERITY_TONES: Record<IssueSeverity, Tone> = { low: "idle", medium: "warn", high: "down" };
const selectClass =
  "min-h-9 rounded-lg border border-field-line bg-paper-raised px-2 text-sm text-ink focus:border-survey focus:ring-2 focus:ring-survey/25 focus:outline-none";

interface Row {
  key: string;
  suggestionId?: string;
  snippet: string;
  category: IssueCategory;
  severity: IssueSeverity;
  keep: boolean;
  confidence: number | null;
  low: boolean;
}

function rowsFrom(issues: Issue[]): Row[] {
  return issues.map((i) => ({
    key: i.id,
    suggestionId: i.id,
    snippet: i.snippet,
    category: i.category,
    severity: i.severity,
    keep: true,
    confidence: i.confidence,
    low: i.low_confidence,
  }));
}

const FOLLOW_UPS = [
  { key: "material_request", label: "Draft a material request", needs: "a material delay", hint: "Opens a request form filled in from this report." },
  { key: "pm_alert", label: "Alert the project manager", needs: "a high-severity issue", hint: "The site's project managers are notified now." },
  { key: "stop_work", label: "Flag stop-work", needs: "a safety issue", hint: "Stays open until the project manager clears it (BR-11)." },
] as const;

/** The author's check: keep, edit or remove each AI tag, add missing ones, tick follow-ups, confirm. */
function Editor({ data, reportId, projectId }: { data: ReportIssues; reportId: string; projectId: string }) {
  const confirm = useConfirmIssues(reportId, projectId);
  const [rows, setRows] = useState<Row[]>(() => rowsFrom(data.issues.filter((i) => i.status === "suggested")));
  const [actions, setActions] = useState({ material_request: false, pm_alert: false, stop_work: false });
  const [adding, setAdding] = useState({ snippet: "", category: "other" as IssueCategory, severity: "medium" as IssueSeverity });
  const [error, setError] = useState<string | null>(null);
  const kept = rows.filter((r) => r.keep);
  const allowed = allowedActions(kept);
  const tasks = useTasks(projectId);
  const [stopScope, setStopScope] = useState<StopScopeValue | null>(null);
  const programme = tasks.data?.tasks ?? [];
  // Pre-ticked: the tasks under way, until the author changes the choice (BR-11).
  const scope = stopScope ?? { scope: "tasks" as const, taskIds: tasksInProgress(programme) };
  const stopping = actions.stop_work && allowed.stop_work;

  function update(key: string, change: Partial<Row>) {
    setRows((current) => current.map((r) => (r.key === key ? { ...r, ...change } : r)));
  }

  function add(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const snippet = adding.snippet.trim();
    if (snippet.length < 3) {
      setError("Write a few words about the issue you are adding.");
      return;
    }
    setError(null);
    setRows((current) => [
      ...current,
      { key: `new-${String(current.length)}`, snippet, category: adding.category, severity: adding.severity, keep: true, confidence: null, low: false },
    ]);
    setAdding({ snippet: "", category: "other", severity: "medium" });
  }

  function submit() {
    confirm.mutate({
      issues: kept.map((r) =>
        r.suggestionId
          ? { suggestion_id: r.suggestionId, category: r.category, severity: r.severity }
          : { category: r.category, severity: r.severity, snippet: r.snippet },
      ),
      actions: {
        material_request: actions.material_request && allowed.material_request,
        pm_alert: actions.pm_alert && allowed.pm_alert,
        stop_work: stopping,
        ...(stopping ? { stop_work_scope: scope.scope, stop_work_task_ids: scope.scope === "tasks" ? scope.taskIds : [] } : {}),
      },
    });
  }

  return (
    <div className="space-y-5">
      {confirm.isError ? <Alert tone="error">{errorText(confirm.error)}</Alert> : null}
      {rows.length === 0 ? <p className="text-sm text-ink-soft">No issues found in the problems text. Add one below if something was missed.</p> : null}
      <ul aria-label="Suggested tags" className="space-y-3">
        {rows.map((r) => (
          <li
            key={r.key}
            className={`rounded-lg border p-3 ${r.low && r.keep ? "border-signal-medium bg-signal-medium-tint/40" : "border-rule bg-paper-raised"} ${r.keep ? "" : "opacity-60"}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <p className={`min-w-0 flex-1 text-sm text-ink ${r.keep ? "" : "line-through"}`}>“{r.snippet}”</p>
              <label className="flex items-center gap-2 text-sm text-ink-soft">
                <input
                  type="checkbox"
                  checked={r.keep}
                  onChange={(e) => {
                    update(r.key, { keep: e.target.checked });
                  }}
                  aria-label={`Keep the tag for “${r.snippet}”`}
                  className="size-4 accent-[var(--color-survey)]"
                />
                Keep
              </label>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <select
                aria-label={`Category for “${r.snippet}”`}
                value={r.category}
                disabled={!r.keep}
                onChange={(e) => {
                  update(r.key, { category: e.target.value as IssueCategory });
                }}
                className={selectClass}
              >
                {ISSUE_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY_LABELS[c]}
                  </option>
                ))}
              </select>
              <select
                aria-label={`Severity for “${r.snippet}”`}
                value={r.severity}
                disabled={!r.keep}
                onChange={(e) => {
                  update(r.key, { severity: e.target.value as IssueSeverity });
                }}
                className={selectClass}
              >
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {SEVERITY_LABELS[s]} severity
                  </option>
                ))}
              </select>
              {r.confidence === null ? (
                <span className="text-xs text-ink-faint">Added by you</span>
              ) : r.low ? (
                <span className="text-xs font-medium text-signal-medium">Check this: the model is unsure ({Math.round(r.confidence * 100)}%)</span>
              ) : (
                <span className="text-xs text-ink-faint">{Math.round(r.confidence * 100)}% sure</span>
              )}
            </div>
          </li>
        ))}
      </ul>

      <form noValidate onSubmit={add} aria-label="Add a tag" className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-rule-strong p-3">
        <label className="min-w-48 flex-1 text-sm">
          <span className="mb-1 block font-medium text-ink">Add a missed issue</span>
          <input
            value={adding.snippet}
            maxLength={300}
            onChange={(e) => {
              setAdding((a) => ({ ...a, snippet: e.target.value }));
            }}
            placeholder="e.g. two masons absent"
            className="min-h-9 w-full rounded-lg border border-field-line bg-paper-raised px-2 text-sm text-ink focus:border-survey focus:outline-none"
          />
        </label>
        <select aria-label="Category for the new tag" value={adding.category} onChange={(e) => { setAdding((a) => ({ ...a, category: e.target.value as IssueCategory })); }} className={selectClass}>
          {ISSUE_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABELS[c]}
            </option>
          ))}
        </select>
        <select aria-label="Severity for the new tag" value={adding.severity} onChange={(e) => { setAdding((a) => ({ ...a, severity: e.target.value as IssueSeverity })); }} className={selectClass}>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {SEVERITY_LABELS[s]}
            </option>
          ))}
        </select>
        <Button type="submit">Add</Button>
        {error ? <p className="w-full text-sm text-signal-high">{error}</p> : null}
      </form>

      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-semibold text-ink">Follow-ups</legend>
        {FOLLOW_UPS.map((f) => (
          <label key={f.key} className={`flex items-start gap-3 rounded-lg px-1 py-1 text-sm ${allowed[f.key] ? "" : "text-ink-faint"}`}>
            <input
              type="checkbox"
              checked={actions[f.key] && allowed[f.key]}
              disabled={!allowed[f.key]}
              onChange={(e) => {
                setActions((a) => ({ ...a, [f.key]: e.target.checked }));
              }}
              className="mt-0.5 size-4 accent-[var(--color-survey)]"
            />
            <span className="font-medium text-ink">
              {f.label}
              <span className="block text-xs font-normal text-ink-faint">{allowed[f.key] ? f.hint : `Needs ${f.needs} among the kept tags.`}</span>
            </span>
          </label>
        ))}
        {stopping ? <StopScopeFields tasks={programme} value={scope} onChange={setStopScope} idPrefix={`stop-${reportId}`} /> : null}
      </fieldset>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-rule pt-4">
        <p className="text-xs text-ink-faint">Suggestions only: nothing is saved until you confirm. Confirmed issues feed the project's risk score.</p>
        <Button variant="primary" onClick={submit} disabled={confirm.isPending || (stopping && !stopScopeValid(scope))}>
          {confirm.isPending ? "Confirming…" : `Confirm ${String(kept.length)} ${kept.length === 1 ? "tag" : "tags"}`}
        </Button>
      </div>
    </div>
  );
}

function ActionLine({ action, projectId }: { action: ReportAction; projectId: string }) {
  const close = useCloseAction();
  const open = action.status === "open";
  if (action.kind === "pm_alert") {
    return <p className="text-sm text-ink-soft">Project manager alerted.</p>;
  }
  if (action.kind === "material_request") {
    const params = new URLSearchParams({ project: projectId, action: action.id, notes: action.summary });
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="text-ink-soft">
          {open ? "Material request to raise" : action.status === "done" ? "Material request raised" : "Material request dismissed"}
          {action.request_id ? (
            <>
              {": "}
              <Link to={`/materials/${action.request_id}`} className="font-medium text-survey hover:underline">
                open it
              </Link>
            </>
          ) : null}
        </span>
        {open ? (
          <span className="flex gap-2">
            <Link to={`/materials/new?${params.toString()}`} className="font-medium text-survey hover:underline">
              Raise the request
            </Link>
            {action.can_close ? (
              <button type="button" className="text-ink-faint hover:text-ink hover:underline" onClick={() => { close.mutate({ id: action.id, resolution: "dismissed" }); }}>
                Dismiss
              </button>
            ) : null}
          </span>
        ) : null}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <span className={open ? "font-medium text-signal-high" : "text-ink-soft"}>
        {open ? "Stop-work flagged: waiting for the project manager to clear it" : "Stop-work cleared"}
      </span>
      {action.can_close ? (
        <Button variant="danger" onClick={() => { close.mutate({ id: action.id, resolution: "done" }); }} disabled={close.isPending}>
          Clear stop-work
        </Button>
      ) : null}
    </div>
  );
}

function Confirmed({ data, projectId }: { data: ReportIssues; projectId: string }) {
  const confirmed = data.issues.filter((i) => i.status === "confirmed");
  const removed = data.issues.filter((i) => i.status === "removed").length;
  return (
    <div className="space-y-4">
      {confirmed.length === 0 ? <p className="text-sm text-ink-soft">No issues confirmed for this report.</p> : null}
      <ul aria-label="Confirmed issues" className="space-y-2">
        {confirmed.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="rounded-full bg-paper-sunk px-2.5 py-0.5 text-xs font-medium text-ink">{CATEGORY_LABELS[i.category]}</span>
            <StatusBadge tone={SEVERITY_TONES[i.severity]} label={`${SEVERITY_LABELS[i.severity]} severity`} />
            <span className="min-w-0 text-ink-soft">“{i.snippet}”</span>
            {i.source === "manual" ? <span className="text-xs text-ink-faint">(added by hand)</span> : i.edited ? <span className="text-xs text-ink-faint">(edited)</span> : null}
          </li>
        ))}
      </ul>
      {removed ? <p className="text-xs text-ink-faint">{removed} {removed === 1 ? "suggestion was" : "suggestions were"} removed by the author.</p> : null}
      {data.actions.length ? (
        <div className="space-y-2 border-t border-rule pt-3">
          {data.actions.map((a) => (
            <ActionLine key={a.id} action={a} projectId={projectId} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** AI check on a daily report: suggestions for the author, the confirmed result for everyone. */
export function AiCheck({ reportId, projectId, hasProblems }: { reportId: string; projectId: string; hasProblems: boolean }) {
  const issues = useReportIssues(reportId);
  const analyze = useAnalyze(reportId);
  const asked = useRef(false);
  const data = issues.data;
  const needsAnalysis = Boolean(data?.can_confirm && !data.confirmed && data.issues.length === 0 && hasProblems);

  useEffect(() => {
    if (needsAnalysis && !asked.current) {
      asked.current = true; // read the problems once, straight after the report is filed
      analyze.mutate();
    }
  }, [needsAnalysis, analyze]);

  if (!data || (!data.confirmed && !data.can_confirm && data.issues.length === 0)) return null;
  // Until the first analysis has answered, show that the problems are being read (not an empty list).
  const analysing = needsAnalysis && !analyze.isSuccess && !analyze.isError;
  return (
    <Sheet className="p-5">
      <SectionHeading annotation={data.confirmed ? "confirmed by the author" : "suggestions: you decide"}>AI check</SectionHeading>
      {analysing ? <p className="text-sm text-ink-faint">Reading the problems…</p> : null}
      {analyze.isError ? <Alert tone="error">{errorText(analyze.error)}</Alert> : null}
      {data.confirmed ? (
        <Confirmed data={data} projectId={projectId} />
      ) : data.can_confirm && !analysing ? (
        <Editor key={data.issues.map((i) => i.id).join()} data={data} reportId={reportId} projectId={projectId} />
      ) : !data.can_confirm ? (
        <p className="text-sm text-ink-soft">Waiting for the report's author to confirm {data.issues.length} suggested {data.issues.length === 1 ? "tag" : "tags"}.</p>
      ) : null}
      {data.model_version ? <p className="mt-3 text-xs text-ink-faint">Tags suggested by report classifier v{data.model_version}.</p> : null}
    </Sheet>
  );
}
