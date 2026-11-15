/**
 * Registers the service worker (src/pwa/sw.ts, built to /sw.js) and tracks a waiting new version,
 * so the app can offer to reload into it (ADR 0018). Production builds only: the dev server has
 * no /sw.js and must never be cached.
 */

type Listener = () => void;

let waiting: ServiceWorker | null = null;
let reloadRequested = false;
const listeners = new Set<Listener>();

function setWaiting(worker: ServiceWorker | null): void {
  waiting = worker;
  for (const listener of listeners) listener();
}

/** A new version that has installed and is waiting for the person to reload (null if none). */
export function waitingWorker(): ServiceWorker | null {
  return waiting;
}

export function subscribeToUpdates(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Switches to the waiting version; the page reloads once it has taken over. */
export function applyUpdate(): void {
  if (!waiting) return;
  reloadRequested = true;
  waiting.postMessage({ type: "SKIP_WAITING" });
}

const HOUR = 60 * 60 * 1000;

export function registerServiceWorker(
  container: ServiceWorkerContainer,
  reload: () => void = () => {
    window.location.reload();
  },
): Promise<ServiceWorkerRegistration | null> {
  // Only after the person asked: the first install also changes the controller, and must not reload.
  container.addEventListener("controllerchange", () => {
    if (!reloadRequested) return;
    reloadRequested = false;
    reload();
  });

  return container
    .register("/sw.js", { scope: "/" })
    .then((registration) => {
      // A version that installed while the app was closed.
      if (registration.waiting && container.controller) setWaiting(registration.waiting);
      registration.addEventListener("updatefound", () => {
        const worker = registration.installing;
        worker?.addEventListener("statechange", () => {
          // With no controller this is the first install, not an update.
          if (worker.state === "installed" && container.controller) setWaiting(worker);
        });
      });
      // Long-lived tabs (an office screen left open) still notice a release.
      setInterval(() => {
        void registration.update().catch(() => undefined);
      }, HOUR);
      return registration;
    })
    .catch(() => null); // The app works without it, just not offline or installable.
}

/** For tests: forget any waiting version. */
export function resetUpdates(): void {
  reloadRequested = false;
  setWaiting(null);
}
