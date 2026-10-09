import { describe, expect, it } from "vitest";

import { findNavItem, isAvailable, NAV_GROUPS } from "../components/layout/navigation";
import { MILESTONES, PHASES, PROGRAMME_WEEKS, phaseStatus } from "./programme";
import { formatSiteClock, formatSiteDate } from "./time";

describe("programme", () => {
  it("has phases 0 to 14 in order, inside the programme window", () => {
    expect(PHASES.map((p) => p.number)).toEqual([...Array(15).keys()]);
    for (const phase of PHASES) {
      expect(phase.startWeek).toBeGreaterThanOrEqual(1);
      expect(phase.endWeek).toBeLessThanOrEqual(PROGRAMME_WEEKS);
      expect(phase.endWeek).toBeGreaterThanOrEqual(phase.startWeek);
    }
  });

  it("places the v0.1 release after phase 6, ending stage 1", () => {
    expect(MILESTONES.find((m) => m.label.startsWith("v0.1"))?.afterPhase).toBe(6);
    expect(PHASES.filter((p) => p.stage === 1).map((p) => p.number)).toEqual([0, 1, 2, 3, 4, 5, 6]);
  });

  it("derives status from the current phase", () => {
    expect(phaseStatus(0, 2)).toBe("done");
    expect(phaseStatus(2, 2)).toBe("active");
    expect(phaseStatus(3, 2)).toBe("planned");
  });
});

describe("navigation", () => {
  it("uses unique paths and codes", () => {
    const items = NAV_GROUPS.flatMap((g) => g.items);
    expect(new Set(items.map((i) => i.path)).size).toBe(items.length);
    expect(new Set(items.map((i) => i.code)).size).toBe(items.length);
  });

  it("only makes modules available once their phase is reached", () => {
    const projects = findNavItem("/projects");
    expect(projects).toBeDefined();
    expect(isAvailable(projects!, 1)).toBe(false);
    expect(isAvailable(projects!, 2)).toBe(true);
    expect(findNavItem("/nowhere")).toBeUndefined();
  });
});

describe("site time", () => {
  it("formats clocks in Colombo time regardless of the browser zone", () => {
    // 2026-10-09 09:15 UTC is 14:45 in Colombo (UTC+05:30).
    expect(formatSiteClock(new Date("2026-10-09T09:15:00Z"))).toBe("FRI, 09 OCT 2026 · 14:45");
    expect(formatSiteDate(new Date("2026-10-09T20:00:00Z"))).toBe("10 Oct 2026");
  });
});
