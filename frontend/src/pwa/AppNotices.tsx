import { useSyncExternalStore } from "react";

import { Button } from "../components/ui/Button";
import { applyUpdate, subscribeToUpdates, waitingWorker } from "./register";

function subscribeToConnection(listener: () => void): () => void {
  window.addEventListener("online", listener);
  window.addEventListener("offline", listener);
  return () => {
    window.removeEventListener("online", listener);
    window.removeEventListener("offline", listener);
  };
}

function isOnline(): boolean {
  return navigator.onLine;
}

/**
 * Notices from the installable app (ADR 0018), at the bottom of every screen:
 * - offline: SiteSense needs the server for every figure, so say so rather than show stale data;
 * - a new version is ready: reload when it suits (a form being filled in is never reloaded).
 */
export function AppNotices() {
  const online = useSyncExternalStore(subscribeToConnection, isOnline, () => true);
  const update = useSyncExternalStore(subscribeToUpdates, waitingWorker, () => null);

  if (online && !update) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 print:hidden">
      {!online ? (
        <p
          role="status"
          className="pointer-events-auto max-w-md rounded-lg border border-rule-strong bg-paper-raised px-4 py-3 text-sm text-ink shadow-[var(--shadow-sheet)]"
        >
          <strong className="font-semibold">You&apos;re offline.</strong> SiteSense needs a connection to load or save
          anything. Nothing you have not saved is lost: stay on this page until the signal is back.
        </p>
      ) : null}
      {update ? (
        <div
          role="status"
          className="pointer-events-auto flex max-w-md items-center gap-3 rounded-lg border border-rule-strong bg-paper-raised px-4 py-3 text-sm text-ink shadow-[var(--shadow-sheet)]"
        >
          <span>A new version of SiteSense is ready.</span>
          <Button variant="primary" onClick={applyUpdate}>
            Reload
          </Button>
        </div>
      ) : null}
    </div>
  );
}
