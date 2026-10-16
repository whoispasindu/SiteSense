import { useState } from "react";

import { AUDIT_PAGE_SIZE, useAuditLog, type AuditLogEntry } from "../../api/admin";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import type { Tone } from "../../components/ui/StatusBadge";
import { errorText, formatDateTime } from "../../features/admin/adminUtils";
import { ACTION_LABELS } from "../../features/admin/auditActions";

const DOT: Record<Tone, string> = {
  ok: "bg-signal-low",
  warn: "bg-signal-medium",
  down: "bg-signal-high",
  idle: "bg-rule-strong",
};

function summarise(entry: AuditLogEntry): string {
  const d = entry.details;
  const parts: string[] = [];
  if (typeof d.reason === "string") parts.push(d.reason.replace(/_/g, " "));
  if (typeof d.email === "string") parts.push(d.email);
  if (typeof d.role === "string") parts.push(`role ${d.role}`);
  if (typeof d.code === "string") parts.push(d.code);
  if (Array.isArray(d.to)) parts.push(`sites: ${d.to.join(", ") || "none"}`);
  if (typeof d.minutes === "number") parts.push(`${String(d.minutes)} min`);
  return parts.join(" · ");
}

export function AuditLogPage() {
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const log = useAuditLog(offset, action);
  const total = log.data?.total ?? 0;

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHeader
        title="Audit log"
        description="Sign-ins, failed attempts and every administrative change, newest first. Entries cannot be edited or deleted, even by the application itself."
      />

      <div className="flex flex-wrap items-end gap-4">
        <label className="block">
          <span className="block text-sm font-medium text-ink">Event</span>
          <select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setOffset(0);
            }}
            className="mt-1.5 min-h-10 rounded-lg border border-field-line bg-paper-raised px-3 text-sm text-ink focus:border-survey focus:ring-2 focus:ring-survey/25 focus:outline-none"
          >
            <option value="">All events</option>
            {Object.entries(ACTION_LABELS).map(([value, { label }]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <p className="tabular ml-auto text-sm text-ink-faint" aria-live="polite">
          {total === 0 ? "0 entries" : `${String(offset + 1)}–${String(Math.min(offset + AUDIT_PAGE_SIZE, total))} of ${String(total)}`}
        </p>
      </div>

      {log.isError ? <Alert tone="error">{errorText(log.error)}</Alert> : null}

      <Sheet className="overflow-hidden">
        <ol aria-label="Audit entries" className="divide-y divide-rule">
          {log.isPending ? <li className="px-5 py-10 text-center text-ink-faint">Loading…</li> : null}
          {log.data?.items.length === 0 ? <li className="px-5 py-10 text-center text-ink-faint">No entries.</li> : null}
          {log.data?.items.map((entry) => {
            const meta = ACTION_LABELS[entry.action] ?? { label: entry.action, tone: "idle" as Tone };
            const summary = summarise(entry);
            return (
              <li key={entry.id} className="grid gap-1 px-5 py-3.5 sm:grid-cols-[11rem_1fr_auto] sm:items-center sm:gap-6">
                <time dateTime={entry.occurred_at} className="tabular text-sm text-ink-faint">
                  {formatDateTime(entry.occurred_at)}
                </time>
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm font-medium text-ink">
                    <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${DOT[meta.tone]}`} />
                    {meta.label}
                    <span className="truncate font-normal text-ink-soft">· {entry.actor_name ?? "Unknown user"}</span>
                  </p>
                  {summary ? <p className="mt-0.5 truncate pl-4 text-xs text-ink-faint">{summary}</p> : null}
                </div>
                <span className="tabular text-xs text-ink-faint sm:text-right">{entry.ip_address ?? "—"}</span>
              </li>
            );
          })}
        </ol>
      </Sheet>

      <div className="flex justify-between gap-3">
        <Button
          disabled={offset === 0}
          onClick={() => {
            setOffset(Math.max(0, offset - AUDIT_PAGE_SIZE));
          }}
        >
          Newer
        </Button>
        <Button
          disabled={offset + AUDIT_PAGE_SIZE >= total}
          onClick={() => {
            setOffset(offset + AUDIT_PAGE_SIZE);
          }}
        >
          Older
        </Button>
      </div>
    </div>
  );
}
