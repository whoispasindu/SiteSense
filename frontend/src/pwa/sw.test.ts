import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { assetCacheName, shellCacheName, start, type WorkerScope } from "./sw";

const ORIGIN = "https://sitesense.example";
const PRECACHE = { version: "v2", files: ["/", "/assets/index-a1.js", "/manifest.json"] };

/** In-memory CacheStorage: enough of it for the worker. */
class FakeCaches {
  stores = new Map<string, Map<string, Response>>();
  matchOptions: ({ cacheName?: string; ignoreVary?: boolean } | undefined)[] = [];

  open(name: string) {
    const store = this.stores.get(name) ?? new Map<string, Response>();
    this.stores.set(name, store);
    return Promise.resolve({
      addAll: (urls: string[]) => {
        for (const url of urls) store.set(new URL(url, ORIGIN).href, new Response(`stored ${url}`));
        return Promise.resolve();
      },
      put: (request: Request, response: Response) => {
        store.set(request.url, response);
        return Promise.resolve();
      },
    });
  }

  match(request: Request | string, options?: { cacheName?: string; ignoreVary?: boolean }) {
    this.matchOptions.push(options);
    const key = new URL(typeof request === "string" ? request : request.url, ORIGIN).href;
    const names = options?.cacheName ? [options.cacheName] : [...this.stores.keys()];
    for (const name of names) {
      const hit = this.stores.get(name)?.get(key);
      if (hit) return Promise.resolve(hit.clone());
    }
    return Promise.resolve(undefined);
  }

  keys() {
    return Promise.resolve([...this.stores.keys()]);
  }

  delete(name: string) {
    return Promise.resolve(this.stores.delete(name));
  }
}

type Handler = (event: Event) => void;

class FakeScope {
  handlers = new Map<string, Handler>();
  location = new URL(ORIGIN) as unknown as Location;
  skipWaiting = vi.fn(() => Promise.resolve());
  clients = { claim: vi.fn(() => Promise.resolve()) };
  addEventListener(type: string, listener: Handler) {
    this.handlers.set(type, listener);
  }

  /** Fires an extendable event and waits for whatever it asked to wait for. */
  async extendable(type: "install" | "activate") {
    let pending: Promise<unknown> = Promise.resolve();
    this.handlers.get(type)?.(Object.assign(new Event(type), { waitUntil: (p: Promise<unknown>) => (pending = p) }));
    await pending;
  }

  /** Fires a fetch; returns the worker's answer, or null when it left the request to the browser. */
  async fetch(path: string, init: { method?: string; mode?: "navigate" } = {}) {
    const request = new Request(new URL(path, ORIGIN), { method: init.method ?? "GET" });
    if (init.mode) Object.defineProperty(request, "mode", { value: init.mode });
    let answer = null as Promise<Response> | null;
    this.handlers.get("fetch")?.(
      Object.assign(new Event("fetch"), {
        request,
        waitUntil: () => undefined,
        respondWith: (response: Promise<Response>) => (answer = response),
      }),
    );
    return answer ? await answer : null;
  }
}

/** A response as a same-origin fetch gives it (type "basic"; a constructed Response is "default"). */
function sameOrigin(body: string, init?: ResponseInit): Response {
  const response = new Response(body, init);
  Object.defineProperty(response, "type", { value: "basic" });
  return response;
}

/** Lets the worker finish what it does after answering (storing a copy). */
function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

let caches: FakeCaches;
let network: ReturnType<typeof vi.fn<(request: Request) => Promise<Response>>>;
let scope: FakeScope;

beforeEach(async () => {
  caches = new FakeCaches();
  network = vi.fn((request: Request) => Promise.resolve(sameOrigin(`network ${new URL(request.url).pathname}`)));
  vi.stubGlobal("caches", caches);
  vi.stubGlobal("fetch", network);
  scope = new FakeScope();
  start(scope as unknown as WorkerScope, PRECACHE);
  await scope.extendable("install");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the service worker", () => {
  it("stores the app shell on install", () => {
    expect([...(caches.stores.get(shellCacheName("v2"))?.keys() ?? [])]).toEqual([
      `${ORIGIN}/`,
      `${ORIGIN}/assets/index-a1.js`,
      `${ORIGIN}/manifest.json`,
    ]);
  });

  it("never answers or stores API requests", async () => {
    expect(await scope.fetch("/api/v1/projects")).toBeNull();
    expect(await scope.fetch("/api/v1/me", { mode: "navigate" })).toBeNull();
    expect(await scope.fetch("/api/v1/reports", { method: "POST" })).toBeNull();
    const everything = [...caches.stores.values()].flatMap((store) => [...store.keys()]);
    expect(everything.filter((url) => url.includes("/api"))).toEqual([]);
  });

  it("loads pages from the network, and the stored shell when offline", async () => {
    expect(await (await scope.fetch("/projects/7", { mode: "navigate" }))?.text()).toBe("network /projects/7");
    network.mockRejectedValueOnce(new TypeError("offline"));
    expect(await (await scope.fetch("/projects/7", { mode: "navigate" }))?.text()).toBe("stored /");
  });

  it("serves stored files without the network, and stores fingerprinted ones on first use", async () => {
    expect(await (await scope.fetch("/assets/index-a1.js"))?.text()).toBe("stored /assets/index-a1.js");
    expect(network).not.toHaveBeenCalled();

    expect(await (await scope.fetch("/assets/plex-sans-latin.woff2"))?.text()).toBe("network /assets/plex-sans-latin.woff2");
    await settle(); // the copy is stored after the answer
    expect(caches.stores.get(assetCacheName("v2"))?.has(`${ORIGIN}/assets/plex-sans-latin.woff2`)).toBe(true);
    expect(await (await scope.fetch("/assets/plex-sans-latin.woff2"))?.text()).toBe("network /assets/plex-sans-latin.woff2");
    expect(network).toHaveBeenCalledTimes(1);
  });

  it("finds stored files whatever the server's Vary header says", async () => {
    await scope.fetch("/assets/index-a1.js");
    network.mockRejectedValueOnce(new TypeError("offline"));
    await scope.fetch("/reports", { mode: "navigate" });
    expect(caches.matchOptions).toHaveLength(2);
    expect(caches.matchOptions.every((options) => options?.ignoreVary === true)).toBe(true);
  });

  it("does not store error answers", async () => {
    network.mockResolvedValueOnce(sameOrigin("gone", { status: 404 }));
    await scope.fetch("/assets/missing-x9.js");
    await settle();
    expect(caches.stores.get(assetCacheName("v2"))?.has(`${ORIGIN}/assets/missing-x9.js`)).toBeFalsy();
  });

  it("clears earlier releases' caches when it takes over, and keeps everything else", async () => {
    caches.stores.set(shellCacheName("v1"), new Map());
    caches.stores.set(assetCacheName("v1"), new Map());
    caches.stores.set("another-apps-cache", new Map());
    await scope.extendable("activate");
    expect([...caches.stores.keys()].sort()).toEqual(["another-apps-cache", shellCacheName("v2")].sort());
    expect(scope.clients.claim).toHaveBeenCalled();
  });

  it("switches to the new version only when the app asks", () => {
    scope.handlers.get("message")?.(new MessageEvent("message", { data: { type: "hello" } }));
    expect(scope.skipWaiting).not.toHaveBeenCalled();
    scope.handlers.get("message")?.(new MessageEvent("message", { data: { type: "SKIP_WAITING" } }));
    expect(scope.skipWaiting).toHaveBeenCalled();
  });
});
