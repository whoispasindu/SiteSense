import { useState } from "react";
import { Link } from "react-router";

import {
  REQUEST_STATUS_LABELS,
  REQUESTS_PAGE_SIZE,
  useRequests,
  type RequestStatus,
} from "../../api/materials";
import { useProjects } from "../../api/projects";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button, primaryLinkClass } from "../../components/ui/Button";
import { Icon } from "../../components/ui/icons";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { formatDate } from "../../features/projects/dates";
import { RequestStatusBadge } from "../../features/materials/MaterialBits";
import { formatCompactLKR, formatQuantity } from "../../lib/money";

/** The happy path, left to right, then the side exits. */
const PIPELINE: RequestStatus[] = ["requested", "pm_approval", "approved", "ordered", "delivered"];
const SIDE: RequestStatus[] = ["change_requested", "rejected", "cancelled"];

export function MaterialsPage() {
  const { can } = useAuth();
  const [status, setStatus] = useState<RequestStatus | "">("");
  const [projectId, setProjectId] = useState("");
  const [mine, setMine] = useState(false);
  const [offset, setOffset] = useState(0);
  const requests = useRequests({ status, projectId, mine, offset });
  const projects = useProjects();
  const counts = requests.data?.counts ?? {};
  const total = requests.data?.total ?? 0;

  // What is waiting for this user, by role.
  const waiting: RequestStatus | null = can("materials:approve_qs")
    ? "requested"
    : can("materials:approve_pm")
      ? "pm_approval"
      : can("purchase_orders:manage")
        ? "approved"
        : null;

  function choose(next: RequestStatus | "") {
    setStatus(next);
    setOffset(0);
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Materials"
        description="Material requests from site to delivery: QS check, approval by the QS (or the project manager under BR-01 and BR-13), purchase order and delivery."
        action={
          can("materials:request") ? (
            <Link to="/materials/new" className={primaryLinkClass}>
              <Icon name="plus" className="size-4" />
              New request
            </Link>
          ) : undefined
        }
      />

      {waiting && counts[waiting] ? (
        <Alert tone="info">
          <button type="button" className="font-medium underline" onClick={() => { choose(waiting); }}>
            {counts[waiting]} {counts[waiting] === 1 ? "request is" : "requests are"} waiting for you
          </button>{" "}
          ({REQUEST_STATUS_LABELS[waiting]}).
        </Alert>
      ) : null}

      <div role="group" aria-label="Filter by stage" className="space-y-2">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <PipelineButton label="All" count={Object.values(counts).reduce((a, b) => a + b, 0)} active={status === ""} onClick={() => { choose(""); }} />
          {PIPELINE.map((s, index) => (
            <PipelineButton
              key={s}
              label={REQUEST_STATUS_LABELS[s]}
              count={counts[s] ?? 0}
              active={status === s}
              step={index + 1}
              onClick={() => {
                choose(s);
              }}
            />
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {SIDE.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={status === s}
              onClick={() => {
                choose(s);
              }}
              className={`min-h-9 rounded-full border px-3 text-sm font-medium ${
                status === s ? "border-ink bg-ink text-paper" : "border-rule-strong text-ink-soft hover:border-ink"
              }`}
            >
              {REQUEST_STATUS_LABELS[s]} <span className="tabular text-ink-faint">{counts[s] ?? 0}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <label className="block min-w-56">
          <span className="block text-sm font-medium text-ink">Project</span>
          <select
            value={projectId}
            onChange={(e) => {
              setProjectId(e.target.value);
              setOffset(0);
            }}
            className="mt-1.5 min-h-10 w-full rounded-lg border border-rule-strong bg-paper-raised px-3 text-sm text-ink focus:border-survey focus:ring-2 focus:ring-survey/25 focus:outline-none"
          >
            <option value="">All projects</option>
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        {can("materials:request") ? (
          <label className="flex min-h-10 items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={mine}
              onChange={(e) => {
                setMine(e.target.checked);
                setOffset(0);
              }}
              className="size-4 accent-[var(--color-accent-line)]"
            />
            Only my requests
          </label>
        ) : null}
      </div>

      {requests.isError ? <Alert tone="error">{errorText(requests.error)}</Alert> : null}

      <Sheet className="relative overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Material requests</caption>
          <thead className="border-b border-rule bg-paper-sunk/60 text-xs font-medium whitespace-nowrap text-ink-faint">
            <tr>
              <th scope="col" className="px-4 py-2.5 text-left font-medium">Request</th>
              <th scope="col" className="px-4 py-2.5 text-left font-medium">Item</th>
              <th scope="col" className="hidden px-4 py-2.5 text-right font-medium md:table-cell">Quantity</th>
              {can("rates:read") ? <th scope="col" className="px-4 py-2.5 text-right font-medium">Value</th> : null}
              <th scope="col" className="hidden px-4 py-2.5 text-left font-medium lg:table-cell">Needed by</th>
              <th scope="col" className="px-4 py-2.5 text-left font-medium">Stage</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {requests.isPending ? (
              <tr>
                <td colSpan={can("rates:read") ? 6 : 5} className="px-4 py-10 text-center text-ink-faint">Loading requests…</td>
              </tr>
            ) : requests.data?.items.length === 0 ? (
              <tr>
                <td colSpan={can("rates:read") ? 6 : 5} className="px-4 py-10 text-center text-ink-faint">No requests here.</td>
              </tr>
            ) : (
              requests.data?.items.map((r) => (
                <tr key={r.id} className="hover:bg-paper-sunk/50">
                  <td className="px-4 py-3 whitespace-nowrap">
                    <Link to={`/materials/${r.id}`} className="font-medium text-ink hover:text-survey hover:underline">
                      {r.number}
                    </Link>
                    <p className="text-xs text-ink-faint">{r.project.code}</p>
                  </td>
                  <td className="max-w-80 px-4 py-3">
                    <p className="truncate text-ink">
                      <span className="mr-1.5 font-mono text-xs text-ink-faint">{r.boq_item.item_code}</span>
                      {r.boq_item.description}
                    </p>
                    <p className="text-xs text-ink-faint">{r.requested_by.full_name}</p>
                  </td>
                  <td className="tabular hidden px-4 py-3 text-right whitespace-nowrap text-ink-soft md:table-cell">
                    {formatQuantity(r.quantity)} {r.boq_item.unit}
                  </td>
                  {r.amount !== undefined ? (
                    <td className="tabular px-4 py-3 text-right font-medium whitespace-nowrap text-ink">
                      {r.amount === null ? <span className="text-xs font-normal text-ink-faint italic">Price pending</span> : formatCompactLKR(r.amount)}
                    </td>
                  ) : null}
                  <td className="tabular hidden px-4 py-3 whitespace-nowrap text-ink-soft lg:table-cell">{formatDate(r.needed_by)}</td>
                  <td className="px-4 py-3">
                    <RequestStatusBadge status={r.status} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Sheet>

      {total > REQUESTS_PAGE_SIZE ? (
        <div className="flex justify-between gap-3">
          <Button disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - REQUESTS_PAGE_SIZE)); }}>
            Newer
          </Button>
          <Button disabled={offset + REQUESTS_PAGE_SIZE >= total} onClick={() => { setOffset(offset + REQUESTS_PAGE_SIZE); }}>
            Older
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function PipelineButton({
  label,
  count,
  active,
  step,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  step?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`flex min-h-16 flex-col justify-between rounded-[var(--radius-sheet)] border px-3 py-2.5 text-left transition ${
        active
          ? "border-accent-line bg-hivis/10 shadow-[var(--shadow-sheet)]"
          : "border-rule bg-paper-raised hover:border-rule-strong"
      }`}
    >
      <span className="text-xs font-medium text-ink-faint">
        {step ? <span className="mr-1 tabular">{step}.</span> : null}
        {label}
      </span>
      <span className="tabular text-xl font-semibold text-ink">{count}</span>
    </button>
  );
}
