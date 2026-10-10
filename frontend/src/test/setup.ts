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

// Parallel test files on a cold start, under coverage instrumentation or on a slow CI machine, can
// take more than 3 s to render a route the first time; 5 s keeps the suite reliable.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
});
