/**
 * SiteSense's service worker: what makes the web app installable and lets it open with no signal
 * (ADR 0018). The build turns this file into /sw.js (the plugin in vite.config.ts): it strips the
 * types and the `export` keywords, and puts `PRECACHE` ({ version, files }) in front.
 *
 * - The app shell (the page, its scripts and styles, the icons and the manifest) is stored on
 *   install, so the app opens offline and starts fast.
 * - Pages come from the network first, so a new release shows at once; offline, the stored shell.
 * - Fingerprinted files under /assets/ (their names change with their content) are stored the
 *   first time they are used, such as fonts.
 * - **Nothing under /api/ is ever stored**: projects, costs, reports and photos always come from the
 *   server, so nothing about a company is left on a shared phone, and a client never sees cached
 *   internal figures. Only GET requests to this origin are handled at all.
 * - A new version waits until the person chooses to reload (the "New version" prompt), so a form
 *   being filled in is never reloaded under them.
 *
 * It is a classic script: no imports.
 */

declare const PRECACHE: { version: string; files: string[] };

export type Strategy = "network" | "page" | "cached";

export const CACHE_PREFIX = "sitesense-";

export function shellCacheName(version: string): string {
  return `${CACHE_PREFIX}shell-${version}`;
}

/** Fingerprinted files fetched while the app runs (fonts…), kept until the next release. */
export function assetCacheName(version: string): string {
  return `${CACHE_PREFIX}assets-${version}`;
}

/** How a request is answered. Anything not listed goes to the network untouched. */
export function strategyFor(
  request: { url: string; method: string; mode: string },
  origin: string,
  precached: ReadonlySet<string>,
): Strategy {
  if (request.method !== "GET") return "network";
  const url = new URL(request.url);
  if (url.origin !== origin) return "network";
  if (url.pathname === "/api" || url.pathname.startsWith("/api/")) return "network";
  if (request.mode === "navigate") return "page";
  if (url.pathname.startsWith("/assets/") || (precached.has(url.pathname) && url.search === "")) return "cached";
  return "network";
}

/** Caches this worker made for an earlier release: removed once it takes over. */
export function isStaleCache(name: string, version: string): boolean {
  return name.startsWith(CACHE_PREFIX) && name !== shellCacheName(version) && name !== assetCacheName(version);
}

/** Only complete same-origin answers are stored (never an error page or an opaque response). */
export function isStorable(response: { ok: boolean; type: string }): boolean {
  return response.ok && response.type === "basic";
}

interface ExtendableEventLike extends Event {
  waitUntil(promise: Promise<unknown>): void;
}

interface FetchEventLike extends ExtendableEventLike {
  request: Request;
  respondWith(response: Promise<Response>): void;
}

export interface WorkerScope {
  location: Location;
  addEventListener(type: "install" | "activate", listener: (event: ExtendableEventLike) => void): void;
  addEventListener(type: "fetch", listener: (event: FetchEventLike) => void): void;
  addEventListener(type: "message", listener: (event: MessageEvent) => void): void;
  skipWaiting(): Promise<void>;
  clients: { claim(): Promise<void> };
}

export function start(scope: WorkerScope, precache: { version: string; files: string[] }): void {
  const shell = shellCacheName(precache.version);
  const assets = assetCacheName(precache.version);
  const precached = new Set(precache.files);

  scope.addEventListener("install", (event) => {
    event.waitUntil(caches.open(shell).then((cache) => cache.addAll(precache.files)));
  });

  scope.addEventListener("activate", (event) => {
    event.waitUntil(
      caches
        .keys()
        .then((names) => Promise.all(names.filter((n) => isStaleCache(n, precache.version)).map((n) => caches.delete(n))))
        .then(() => scope.clients.claim()),
    );
  });

  scope.addEventListener("message", (event) => {
    if ((event.data as { type?: string } | null)?.type === "SKIP_WAITING") void scope.skipWaiting();
  });

  async function page(request: Request): Promise<Response> {
    try {
      return await fetch(request);
    } catch {
      // Offline: the stored shell. The app then says it cannot reach the server.
      return (await caches.match("/", { cacheName: shell, ignoreVary: true })) ?? Response.error();
    }
  }

  async function cached(request: Request): Promise<Response> {
    // ignoreVary: the server's Vary (Origin, Accept-Encoding) would otherwise make the stored copy
    // miss, since the install requests and the page's own requests carry different headers. Safe
    // here: these files are fingerprinted or part of this release's shell.
    const hit = await caches.match(request, { ignoreVary: true });
    if (hit) return hit;
    const response = await fetch(request);
    if (isStorable(response) && new URL(request.url).pathname.startsWith("/assets/")) {
      const copy = response.clone();
      void caches.open(assets).then((cache) => cache.put(request, copy));
    }
    return response;
  }

  scope.addEventListener("fetch", (event) => {
    const strategy = strategyFor(event.request, scope.location.origin, precached);
    if (strategy === "page") event.respondWith(page(event.request));
    else if (strategy === "cached") event.respondWith(cached(event.request));
    // "network": not handled, so the browser fetches it as if there were no service worker.
  });
}

// Only inside a real service worker (not when the tests import this file).
if (typeof (globalThis as { ServiceWorkerGlobalScope?: unknown }).ServiceWorkerGlobalScope !== "undefined") {
  start(self as unknown as WorkerScope, PRECACHE);
}
