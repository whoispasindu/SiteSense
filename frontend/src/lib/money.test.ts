import { describe, expect, it } from "vitest";

import { findNavItem } from "../components/layout/navigation";
import { durationWeeks, formatDate, programmeProgress } from "../features/projects/dates";
import { formatAmount, formatCompactLKR, formatQuantity, percent, toNumber } from "./money";

describe("money", () => {
  it("formats exact amounts and quantities", () => {
    expect(formatAmount("1113985000.00")).toBe("1,113,985,000.00");
    expect(formatAmount("0")).toBe("0.00");
    expect(formatQuantity("2850.000")).toBe("2,850");
    expect(formatQuantity("1920.5")).toBe("1,920.5");
  });

  it("formats compact LKR for tiles", () => {
    expect(formatCompactLKR("1113985000.00")).toBe("LKR 1.11 bn");
    expect(formatCompactLKR("685000000")).toBe("LKR 685 M");
    expect(formatCompactLKR("42500")).toBe("LKR 42.5 k");
    expect(formatCompactLKR("950")).toBe("LKR 950");
  });

  it("is safe with bad input", () => {
    expect(toNumber("not a number")).toBe(0);
    expect(percent("5", "0")).toBe(0);
    expect(percent("25", "100")).toBe(25);
  });
});

describe("project dates", () => {
  it("computes duration and progress through the contract period", () => {
    expect(durationWeeks("2026-03-02", "2027-09-30")).toBe(82);
    expect(programmeProgress("2026-01-01", "2026-12-31", new Date(2025, 5, 1))).toEqual({ elapsed: 0, state: "not_started" });
    expect(programmeProgress("2026-01-01", "2026-12-31", new Date(2027, 0, 5))).toEqual({ elapsed: 100, state: "overdue" });
    const mid = programmeProgress("2026-01-01", "2026-12-31", new Date(2026, 6, 2));
    expect(mid.state).toBe("running");
    expect(mid.elapsed).toBeCloseTo(50, 0);
    expect(formatDate("2026-03-02")).toBe("02 Mar 2026");
  });
});

describe("findNavItem", () => {
  it("matches nested project pages to the Projects item", () => {
    expect(findNavItem("/projects/abc/boq")?.label).toBe("Projects");
    expect(findNavItem("/")?.label).toBe("Dashboard");
    expect(findNavItem("/projectsx")).toBeUndefined();
  });
});
