import { describe, expect, it } from "vitest";

import { findNavItem } from "../components/layout/navigation";
import { durationWeeks, formatDate, programmeProgress } from "../features/projects/dates";
import { configureLocale, DEFAULT_LOCALE } from "./locale";
import { formatAmount, formatCompactMoney, formatMoney, formatQuantity, percent, toNumber } from "./money";

describe("money", () => {
  it("formats exact amounts and quantities", () => {
    expect(formatAmount("1113985000.00")).toBe("1,113,985,000.00");
    expect(formatAmount("0")).toBe("0.00");
    expect(formatQuantity("2850.000")).toBe("2,850");
    expect(formatQuantity("1920.5")).toBe("1,920.5");
  });

  it("formats compact LKR for tiles", () => {
    expect(formatCompactMoney("1113985000.00")).toBe("LKR 1.11 bn");
    expect(formatCompactMoney("685000000")).toBe("LKR 685 M");
    expect(formatCompactMoney("42500")).toBe("LKR 42.5 k");
    expect(formatCompactMoney("950")).toBe("LKR 950");
  });

  it("uses the company's currency and number format", () => {
    try {
      configureLocale({ ...DEFAULT_LOCALE, currency: "EUR", number_locale: "de-DE" });
      expect(formatMoney("1250000.5")).toBe("EUR 1.250.000,50");
      expect(formatCompactMoney("685000000")).toBe("EUR 685 M");
      configureLocale({ ...DEFAULT_LOCALE, currency: "JPY", currency_decimals: 0, number_locale: "ja-JP" });
      expect(formatMoney("1250000")).toBe("JPY 1,250,000");
    } finally {
      configureLocale(DEFAULT_LOCALE);
    }
    expect(formatMoney("1250000.5")).toBe("LKR 1,250,000.50");
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
