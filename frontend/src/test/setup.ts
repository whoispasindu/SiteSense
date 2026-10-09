import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no layout engine: give Recharts' ResponsiveContainer an observer to attach to.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!("ResizeObserver" in globalThis)) {
  Object.defineProperty(globalThis, "ResizeObserver", { value: ResizeObserverStub, writable: true });
}

// Parallel test files on a cold start (and slower CI machines) can exceed the 1 s default.
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
});
