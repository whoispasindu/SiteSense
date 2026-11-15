import { afterEach, describe, expect, it } from "vitest";

import { configureLocale, DEFAULT_LOCALE } from "./locale";
import { formatCompactMoney } from "./money";
import { formatSiteDateTime, siteTodayIso } from "./time";

// Every source file, to check nothing still assumes Sri Lanka.
const SOURCES = import.meta.glob<string>(["../**/*.{ts,tsx}", "!../**/*.test.{ts,tsx}", "!../test/**"], {
  query: "?raw",
  import: "default",
  eager: true,
});

/** Code lines only: comments may still say "LKR" when they give an example. */
function codeLines(source: string): string[] {
  return source.split("\n").filter((line) => !/^\s*(\/\/|\*|\/\*\*)/.test(line));
}

describe("the company's locale", () => {
  afterEach(() => {
    configureLocale(DEFAULT_LOCALE);
  });

  it("has no Sri Lankan currency or time zone written into the screens", () => {
    const allowed = new Set(["./locale.ts"]); // the defaults, until the session says otherwise
    const offenders = Object.entries(SOURCES)
      .filter(([path]) => !allowed.has(path))
      .flatMap(([path, source]) =>
        codeLines(source)
          .filter((line) => /\bLKR\b|Asia\/Colombo|en-LK/.test(line))
          .map((line) => `${path}: ${line.trim()}`),
      );
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
    expect(offenders).toEqual([]);
  });

  it("moves site dates and times to the company's time zone", () => {
    const lateEvening = new Date("2026-11-14T23:30:00Z");
    expect(siteTodayIso(lateEvening)).toBe("2026-11-15"); // Colombo is already on the 15th
    configureLocale({ ...DEFAULT_LOCALE, time_zone: "America/Chicago" });
    expect(siteTodayIso(lateEvening)).toBe("2026-11-14");
    expect(formatSiteDateTime("2026-11-14T23:30:00Z")).toBe("14 Nov 2026, 17:30");
  });

  it("labels compact amounts with the company's currency", () => {
    configureLocale({ ...DEFAULT_LOCALE, currency: "AED", number_locale: "en-AE" });
    expect(formatCompactMoney("1250000")).toBe("AED 1.25 M");
  });
});
