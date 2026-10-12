import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { safeInternalLink, useMarkAllRead, useMarkRead, useNotifications, type Notification } from "../../api/notifications";
import { timeAgo } from "../../lib/time";
import { Icon } from "../ui/icons";

/** Bell with an unread count; the panel lists the latest notifications (reminders, new reports). */
export function NotificationBell({ onDark = false }: { onDark?: boolean }) {
  const notifications = useNotifications();
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointer(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const unread = notifications.data?.unread ?? 0;
  const items = notifications.data?.items ?? [];

  function openItem(item: Notification) {
    if (!item.read_at) markRead.mutate(item.id);
    setOpen(false);
    const link = safeInternalLink(item.link);
    if (link) void navigate(link);
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={unread ? `Notifications, ${String(unread)} unread` : "Notifications"}
        onClick={() => {
          setOpen((v) => !v);
        }}
        className={`relative inline-flex size-10 items-center justify-center rounded-lg ${
          onDark ? "text-asphalt-text hover:bg-asphalt-raised hover:text-white" : "text-ink-soft hover:bg-paper-sunk hover:text-ink"
        }`}
      >
        <Icon name="bell" className="size-5" />
        {unread ? (
          <span
            aria-hidden="true"
            className="tabular absolute top-1 right-1 grid h-4 min-w-4 place-items-center rounded-full bg-signal-high px-1 text-[0.625rem] font-semibold text-white"
          >
            {unread > 9 ? "9+" : unread}
          </span>
        ) : null}
      </button>

      {open ? (
        <div
          id={panelId}
          role="region"
          aria-label="Notifications"
          className="animate-rise absolute right-0 z-30 mt-2 w-[min(24rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-rule bg-paper-raised shadow-[var(--shadow-pop)]"
        >
          <div className="flex items-center justify-between gap-3 border-b border-rule px-4 py-3">
            <p className="text-sm font-semibold text-ink">Notifications</p>
            {unread ? (
              <button
                type="button"
                onClick={() => {
                  markAll.mutate();
                }}
                className="text-sm font-medium text-survey hover:underline"
              >
                Mark all read
              </button>
            ) : null}
          </div>
          {notifications.isError ? <p className="px-4 py-6 text-sm text-ink-soft">Notifications could not be loaded.</p> : null}
          {notifications.data && items.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-ink-faint">You are all caught up.</p>
          ) : null}
          {items.length ? (
            <ul className="max-h-[60dvh] divide-y divide-rule overflow-y-auto">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => {
                      openItem(item);
                    }}
                    className={`flex w-full gap-3 px-4 py-3 text-left hover:bg-paper-sunk ${item.read_at ? "" : "bg-hivis/5"}`}
                  >
                    <span
                      aria-hidden="true"
                      className={`mt-1.5 size-2 shrink-0 rounded-full ${item.read_at ? "bg-transparent" : "bg-accent-line"}`}
                    />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-ink">
                        {item.title}
                        {item.read_at ? null : <span className="sr-only"> (unread)</span>}
                      </span>
                      <span className="block text-sm text-ink-soft">{item.body}</span>
                      <span className="mt-0.5 block text-xs text-ink-faint">{timeAgo(item.created_at)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
