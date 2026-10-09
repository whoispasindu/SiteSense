import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { applyTheme, readPreference, useTheme } from "./theme";

function stubDarkSystem(dark: boolean) {
  const listeners = new Set<() => void>();
  const query = {
    matches: dark,
    addEventListener: vi.fn((_type: string, listener: () => void) => listeners.add(listener)),
    removeEventListener: vi.fn((_type: string, listener: () => void) => listeners.delete(listener)),
  };
  vi.stubGlobal("matchMedia", vi.fn(() => query));
  return {
    query,
    change(next: boolean) {
      query.matches = next;
      listeners.forEach((listener) => {
        listener();
      });
    },
  };
}

const theme = () => document.documentElement.getAttribute("data-theme");

describe("theme", () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("follows the system setting by default, live", () => {
    const system = stubDarkSystem(true);
    const { result, unmount } = renderHook(() => useTheme());

    expect(result.current[0]).toBe("system");
    expect(theme()).toBe("dark");
    act(() => {
      system.change(false);
    });
    expect(theme()).toBe("light");
    unmount();
    expect(system.query.removeEventListener).toHaveBeenCalled();
  });

  it("remembers an explicit choice and forgets it for system", () => {
    stubDarkSystem(false);
    const { result } = renderHook(() => useTheme());

    act(() => {
      result.current[1]("dark");
    });
    expect(theme()).toBe("dark");
    expect(localStorage.getItem("sitesense-theme")).toBe("dark");
    expect(readPreference()).toBe("dark");

    act(() => {
      result.current[1]("system");
    });
    expect(localStorage.getItem("sitesense-theme")).toBeNull();
    expect(theme()).toBe("light");
  });

  it("ignores unknown stored values and blocked storage", () => {
    localStorage.setItem("sitesense-theme", "purple");
    expect(readPreference()).toBe("system");

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readPreference()).toBe("system");
    stubDarkSystem(false);
    const { result } = renderHook(() => useTheme());
    act(() => {
      result.current[1]("dark");
    });
    expect(theme()).toBe("dark"); // still applied for this page view
  });

  it("treats a browser without matchMedia as light", () => {
    vi.stubGlobal("matchMedia", undefined);

    applyTheme("system");

    expect(theme()).toBe("light");
  });
});
