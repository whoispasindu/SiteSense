import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// Parallel test files on a cold start (and slower CI machines) can exceed the 1 s default.
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
});
