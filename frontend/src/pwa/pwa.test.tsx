import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import manifest from "../../public/manifest.json";
import { AppNotices } from "./AppNotices";
import { applyUpdate, registerServiceWorker, resetUpdates, waitingWorker } from "./register";
import { assetCacheName, isStaleCache, isStorable, shellCacheName, strategyFor } from "./sw";
import swSource from "./sw.ts?raw";

const ORIGIN = "https://sitesense.example";
const PRECACHED = new Set(["/", "/manifest.json", "/icons/icon-192.png"]);
const ICONS = import.meta.glob("../../public/icons/*.png");

function request(path: string, over: Partial<{ method: string; mode: string; origin: string }> = {}) {
  return { url: `${over.origin ?? ORIGIN}${path}`, method: over.method ?? "GET", mode: over.mode ?? "cors" };
}

describe("the service worker's rules", () => {
  it("never stores anything from the API, whatever the request", () => {
    expect(strategyFor(request("/api/v1/projects"), ORIGIN, PRECACHED)).toBe("network");
    expect(strategyFor(request("/api/v1/reports/1/photos/2"), ORIGIN, PRECACHED)).toBe("network");
    expect(strategyFor(request("/api/v1/me", { mode: "navigate" }), ORIGIN, PRECACHED)).toBe("network");
    expect(strategyFor(request("/api"), ORIGIN, PRECACHED)).toBe("network");
  });

  it("leaves writes and other sites to the network", () => {
    expect(strategyFor(request("/assets/index-abc.js", { method: "POST" }), ORIGIN, PRECACHED)).toBe("network");
    expect(strategyFor(request("/assets/index-abc.js", { origin: "https://cdn.example" }), ORIGIN, PRECACHED)).toBe(
      "network",
    );
  });

  it("serves pages from the network first, and fingerprinted and shell files from the cache", () => {
    expect(strategyFor(request("/projects/7/reports", { mode: "navigate" }), ORIGIN, PRECACHED)).toBe("page");
    expect(strategyFor(request("/assets/ibm-plex-sans-latin-wght-normal-x1.woff2"), ORIGIN, PRECACHED)).toBe("cached");
    expect(strategyFor(request("/icons/icon-192.png"), ORIGIN, PRECACHED)).toBe("cached");
    expect(strategyFor(request("/icons/icon-192.png?v=2"), ORIGIN, PRECACHED)).toBe("network");
    expect(strategyFor(request("/boq-template.csv"), ORIGIN, PRECACHED)).toBe("network");
  });

  it("removes only its own caches from earlier releases", () => {
    expect(isStaleCache(shellCacheName("old"), "new")).toBe(true);
    expect(isStaleCache(assetCacheName("old"), "new")).toBe(true);
    expect(isStaleCache(shellCacheName("new"), "new")).toBe(false);
    expect(isStaleCache(assetCacheName("new"), "new")).toBe(false);
    expect(isStaleCache("someone-elses-cache", "new")).toBe(false);
  });

  it("stores only complete same-origin answers", () => {
    expect(isStorable({ ok: true, type: "basic" })).toBe(true);
    expect(isStorable({ ok: false, type: "basic" })).toBe(false);
    expect(isStorable({ ok: true, type: "opaque" })).toBe(false);
  });

  it("is a classic script: no imports, so the build can ship it as /sw.js", () => {
    expect(swSource).not.toMatch(/^\s*import\s/m);
    expect(swSource).toContain("declare const PRECACHE");
  });
});

describe("the manifest", () => {
  it("makes the app installable as SiteSense", () => {
    expect(manifest).toMatchObject({ name: "SiteSense", start_url: "/", scope: "/", display: "standalone" });
    const sizes = manifest.icons.map((i) => `${i.sizes} ${i.purpose}`);
    expect(sizes).toEqual(expect.arrayContaining(["192x192 any", "512x512 any", "512x512 maskable"]));
    for (const icon of manifest.icons) {
      expect(Object.keys(ICONS)).toContain(`../../public${icon.src}`);
    }
  });
});

// --- Registration and updates ------------------------------------------------------------------

class FakeWorker extends EventTarget {
  state = "installing";
  postMessage = vi.fn();
}

class FakeRegistration extends EventTarget {
  waiting: FakeWorker | null = null;
  installing: FakeWorker | null = null;
  update = vi.fn(() => Promise.resolve());
}

class FakeContainer extends EventTarget {
  controller: object | null;
  registration = new FakeRegistration();
  register = vi.fn(() => Promise.resolve(this.registration));
  constructor(controlled: boolean) {
    super();
    this.controller = controlled ? {} : null;
  }
}

function asContainer(fake: FakeContainer): ServiceWorkerContainer {
  return fake as unknown as ServiceWorkerContainer;
}

describe("registering the service worker", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    act(() => {
      resetUpdates();
    });
    vi.useRealTimers();
  });

  it("offers a version that installed while the app was closed, and reloads only when asked", async () => {
    const container = new FakeContainer(true);
    const waiting = new FakeWorker();
    container.registration.waiting = waiting;
    const reload = vi.fn();

    await registerServiceWorker(asContainer(container), reload);
    expect(container.register).toHaveBeenCalledWith("/sw.js", { scope: "/" });
    expect(waitingWorker()).toBe(waiting);

    container.dispatchEvent(new Event("controllerchange"));
    expect(reload).not.toHaveBeenCalled(); // nobody asked

    applyUpdate();
    expect(waiting.postMessage).toHaveBeenCalledWith({ type: "SKIP_WAITING" });
    container.dispatchEvent(new Event("controllerchange"));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("offers an update found while the app is open, but not the very first install", async () => {
    const reload = vi.fn();
    const first = new FakeContainer(false);
    await registerServiceWorker(asContainer(first), reload);
    const firstWorker = new FakeWorker();
    first.registration.installing = firstWorker;
    first.registration.dispatchEvent(new Event("updatefound"));
    firstWorker.state = "installed";
    firstWorker.dispatchEvent(new Event("statechange"));
    expect(waitingWorker()).toBeNull();
    first.dispatchEvent(new Event("controllerchange")); // the first install takes control
    expect(reload).not.toHaveBeenCalled();

    const later = new FakeContainer(true);
    await registerServiceWorker(asContainer(later), reload);
    const next = new FakeWorker();
    later.registration.installing = next;
    later.registration.dispatchEvent(new Event("updatefound"));
    next.state = "installed";
    next.dispatchEvent(new Event("statechange"));
    expect(waitingWorker()).toBe(next);
  });

  it("checks for a new release every hour", async () => {
    const container = new FakeContainer(true);
    await registerServiceWorker(asContainer(container), vi.fn());
    vi.advanceTimersByTime(60 * 60 * 1000);
    expect(container.registration.update).toHaveBeenCalledTimes(1);
  });

  it("keeps the app working when registration fails", async () => {
    const container = new FakeContainer(true);
    container.register.mockImplementationOnce(() => Promise.reject(new Error("blocked")));
    await expect(registerServiceWorker(asContainer(container), vi.fn())).resolves.toBeNull();
  });
});

describe("app notices", () => {
  afterEach(() => {
    act(() => {
      resetUpdates();
    });
  });

  it("says when the connection is gone, and goes when it is back", () => {
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    render(<AppNotices />);
    expect(screen.getByRole("status")).toHaveTextContent(/You're offline\. SiteSense needs a connection/);

    online.mockReturnValue(true);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("offers a ready new version and switches to it on Reload", async () => {
    const user = userEvent.setup();
    const container = new FakeContainer(true);
    const waiting = new FakeWorker();
    container.registration.waiting = waiting;
    render(<AppNotices />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    await act(async () => {
      await registerServiceWorker(asContainer(container), vi.fn());
    });
    expect(screen.getByRole("status")).toHaveTextContent("A new version of SiteSense is ready.");
    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(waiting.postMessage).toHaveBeenCalledWith({ type: "SKIP_WAITING" });
  });
});
