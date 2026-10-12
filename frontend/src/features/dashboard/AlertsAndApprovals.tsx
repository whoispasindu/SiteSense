import { Link, useNavigate } from "react-router";

import type { ApprovalItem } from "../../api/dashboard";
import { safeInternalLink, useMarkRead, useNotifications, type Notification } from "../../api/notifications";
import { Alert } from "../../components/ui/Alert";
import { Icon } from "../../components/ui/icons";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { timeAgo } from "../../lib/time";
import { errorText } from "../admin/adminUtils";
import { APPROVAL_LABELS } from "./dashboard";

/** The same kinds the server emails at once (``alerts.URGENT_KINDS``). */
const URGENT_KINDS = new Set([
  "risk_high",
  "stop_work",
  "pour_rain",
  "issue_high",
  "request_pending",
  "claim_submitted",
  "variation_for_pm",
  "variation_for_client",
]);
const ALERT_LIMIT = 6;

/** What is waiting for this reader to act on, oldest first. */
export function ApprovalQueue({ items, total }: { items: ApprovalItem[]; total: number }) {
  return (
    <Sheet className="p-5">
      <SectionHeading annotation={total > items.length ? `oldest ${String(items.length)} of ${String(total)}` : "oldest first"}>
        Waiting for you
      </SectionHeading>
      {items.length === 0 ? (
        <p className="flex items-center gap-2 py-4 text-sm text-ink-soft">
          <Icon name="audit" className="size-4 text-signal-low" /> Nothing is waiting for your approval.
        </p>
      ) : (
        <ul aria-label="Approval queue" className="divide-y divide-rule">
          {items.map((item) => (
            <li key={`${item.kind}-${item.id}`}>
              <Link to={item.link} className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-3">
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-x-2 text-xs text-ink-faint">
                    <span className="font-medium tracking-wide uppercase">{APPROVAL_LABELS[item.kind]}</span>
                    <span className="font-mono">
                      {item.number} · {item.project_code}
                    </span>
                  </span>
                  <span className="mt-0.5 block truncate font-medium text-ink group-hover:underline">{item.title}</span>
                </span>
                <span className="flex items-center gap-2 text-xs text-ink-faint">
                  {timeAgo(item.since)}
                  <Icon name="chevron" className="size-4" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  );
}

/** The latest alerts (in-app notifications), urgent ones marked. The bell holds the full list. */
export function AlertsList() {
  const notifications = useNotifications();
  const markRead = useMarkRead();
  const navigate = useNavigate();
  const items = (notifications.data?.items ?? []).slice(0, ALERT_LIMIT);
  const unread = notifications.data?.unread ?? 0;

  function open(item: Notification) {
    if (!item.read_at) markRead.mutate(item.id);
    const link = safeInternalLink(item.link);
    if (link) void navigate(link);
  }

  return (
    <Sheet className="p-5">
      <SectionHeading
        annotation={unread ? `${String(unread)} unread` : "all read"}
        action={
          <Link to="/settings/notifications" className="text-sm font-medium text-survey hover:underline">
            Email settings
          </Link>
        }
      >
        Alerts
      </SectionHeading>
      {notifications.isPending ? <p className="py-4 text-sm text-ink-faint">Loading…</p> : null}
      {notifications.isError ? <Alert tone="error">{errorText(notifications.error)}</Alert> : null}
      {notifications.isSuccess && items.length === 0 ? <p className="py-4 text-sm text-ink-soft">No alerts yet.</p> : null}
      <ul aria-label="Latest alerts" className="divide-y divide-rule">
        {items.map((item) => {
          const urgent = URGENT_KINDS.has(item.kind);
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => {
                  open(item);
                }}
                className="grid w-full grid-cols-[0.75rem_minmax(0,1fr)] gap-x-3 py-3 text-left"
              >
                <span
                  aria-hidden="true"
                  className={`mt-1.5 size-2 rounded-full ${item.read_at ? "bg-transparent" : urgent ? "bg-signal-high" : "bg-survey"}`}
                />
                <span className="min-w-0">
                  <span className="flex items-baseline justify-between gap-3">
                    <span className={`truncate text-sm ${item.read_at ? "text-ink-soft" : "font-medium text-ink"}`}>{item.title}</span>
                    <span className="shrink-0 text-xs text-ink-faint">{timeAgo(item.created_at)}</span>
                  </span>
                  <span className="mt-0.5 line-clamp-1 block text-xs text-ink-faint">
                    {urgent ? <span className="font-medium text-signal-high">Urgent · </span> : null}
                    {item.body}
                  </span>
                  {!item.read_at ? <span className="sr-only">Unread.</span> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Sheet>
  );
}
