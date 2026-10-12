import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Role } from "../../api/auth";
import type { ProjectDetail, ProjectSummary } from "../../api/projects";
import type { Driver, ProjectRisk, RiskRanking } from "../../api/risk";
import { jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi } from "../../test/utils";
import { delayRangeText, delayText, driverEffect, overrunRangeText, overrunText, raisesRisk, scoreRangeText } from "./risk";

const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };
const PID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const PID2 = "1a1b1c1d-2e2f-4a3b-8c4d-5e6f7a8b9c0d";
const PID3 = "2b2c2d2e-3f3a-4b4c-9d5e-6f7a8b9c0d1e";

const SUMMARY: ProjectSummary = {
  id: PID, code: "HR-2026-01", name: "Havelock Residences", site: SITE, client_name: "Havelock Developers",
  project_type: "residential", status: "active", contract_value: "1114000000.00", start_date: "2026-03-02",
  planned_end: "2027-09-30", boq_total: "0.00", budget_total: "0.00", item_count: 0,
};
const DETAIL: ProjectDetail = {
  ...SUMMARY, description: null, planned_crew: 55, sections: [], team: [],
  created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
};

const driver = (over: Partial<Driver>): Driver => ({
  feature: "progress_gap_pct", label: "Progress against plan", kind: "signal", value: "8.0 points behind",
  delay_days: 22.4, overrun_pct: 0.6, ...over,
});

const RANGES = {
  delay_days: { low: 44.2, high: 103.9 }, overrun_pct: { low: 3.1, high: 14.6 }, score: { low: 53, high: 100 },
};

const RISK: ProjectRisk = {
  project_id: PID,
  latest: {
    score_date: "2026-10-10", score: 82, level: "high", delay_days: "71.6", overrun_pct: "8.75", ranges: RANGES,
    drivers: [
      driver({ feature: "planned_duration_days", label: "Planned duration", kind: "context", value: "83 weeks", delay_days: 9.8, overrun_pct: 0.3 }),
      driver({}),
      driver({ feature: "avg_lateness_days", label: "Delivery lateness", value: "3.8 days on average", delay_days: -3.6, overrun_pct: 0 }),
    ],
    notes: ["Only 4 forecast days cached: rain scaled to 14 days."],
    model_version: "2.0.0", scored_at: "2026-10-10T00:30:00+00:00",
  },
  history: [{ date: "2026-10-10", score: 82, level: "high", score_range: { low: 53, high: 100 } }],
};

const RANKING: RiskRanking = [
  { project_id: PID, code: "HR-2026-01", name: "Havelock Residences", site_code: "COL-07", status: "active", score: 82,
    level: "high", delay_days: "71.6", overrun_pct: "8.75", ranges: RANGES, top_driver: "Progress against plan: 8.0 points behind", score_date: "2026-10-10" },
  { project_id: PID2, code: "PRO-2026-02", name: "Peradeniya Road Offices", site_code: "KDY-02", status: "active", score: 32,
    level: "low", delay_days: "7.2", overrun_pct: "0.2", ranges: null, top_driver: null, score_date: "2026-10-10" },
  { project_id: PID3, code: "FVA-2026-03", name: "Fort View Apartments", site_code: "GAL-11", status: "planning", score: null,
    level: null, delay_days: null, overrun_pct: null, ranges: null, top_driver: null, score_date: null },
];  // fmt: skip

function riskApi(role: Role, extra: Record<string, () => Response> = {}) {
  return mockApi({
    ...sessionApi(makeMe(role)),
    "/api/v1/projects": () => jsonResponse([SUMMARY]),
    [`/api/v1/projects/${PID}`]: () => jsonResponse(DETAIL),
    "/api/v1/schedule/summary": () => jsonResponse([]),
    "/api/v1/reports/today": () => jsonResponse({ date: "2026-10-10", deadline: "2026-10-10T18:00:00+05:30", deadline_passed: false, projects: [] }),
    "/api/v1/risk/projects": () => jsonResponse(RANKING),
    [`/api/v1/projects/${PID}/risk`]: () => jsonResponse(RISK),
    ...extra,
  });
}

describe("Dashboard risk ranking", () => {
  it("ranks projects by risk with the band in words", async () => {
    riskApi("project_manager");
    renderRoute("/");

    const list = await screen.findByRole("list", { name: "Projects ranked by risk" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => within(r).getByRole("link").textContent)).toEqual([
      "Havelock Residences", "Peradeniya Road Offices", "Fort View Apartments",
    ]);  // fmt: skip
    expect(rows[0]).toHaveTextContent("High risk");
    // Every forecast comes with its likely range.
    expect(rows[0]).toHaveTextContent(
      "Forecast about 72 days late (likely 44 to 104 days late), 8.8% over budget (likely 3.1% to 14.6% over budget)",
    );
    expect(rows[0]).toHaveTextContent("53–100");
    expect(rows[0]).toHaveTextContent("Progress against plan: 8.0 points behind");
    expect(within(rows[0]!).getByRole("meter", { name: "Risk score" })).toHaveAttribute(
      "aria-valuetext",
      "82 out of 100, High risk, likely 53 to 100",
    );
    expect(within(rows[0]!).getByTestId("score-range")).toHaveStyle({ left: "53%", width: "47%" });
    expect(within(rows[0]!).getByRole("link")).toHaveAttribute("href", `/projects/${PID}`);
    expect(rows[1]).toHaveTextContent("Low risk");
    expect(rows[1]).toHaveTextContent("on budget");
    expect(rows[1]).toHaveTextContent("range from the next scoring"); // scored before risk model v2
    expect(rows[2]).toHaveTextContent("Not scored yet");
    expect(within(rows[2]!).queryByRole("meter")).not.toBeInTheDocument();
  });

  it("counts high-risk projects in the KPIs", async () => {
    riskApi("quantity_surveyor");
    renderRoute("/");

    const tile = await screen.findByRole("group", { name: "High risk" });
    expect(await within(tile).findByText("1")).toBeInTheDocument();
    expect(tile).toHaveTextContent("Risk score 70 or more (BR-10)");
  });

  it("says when nothing is at high risk", async () => {
    riskApi("project_manager", { "/api/v1/risk/projects": () => jsonResponse(RANKING.slice(1)) });
    renderRoute("/");

    const tile = await screen.findByRole("group", { name: "High risk" });
    expect(await within(tile).findByText("No project is at high risk")).toBeInTheDocument();
  });

  it("is not shown to roles without risk access", async () => {
    const fetchMock = riskApi("site_engineer");
    renderRoute("/");

    await screen.findByRole("group", { name: "Active projects" });
    expect(screen.queryByRole("heading", { name: "Projects by risk" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "High risk" })).not.toBeInTheDocument();
    expect(requestTo(fetchMock, "/risk/projects")).toBeUndefined();
    expect(requestTo(fetchMock, `/projects/${PID}/risk`)).toBeUndefined();
  });

  it("explains an empty portfolio", async () => {
    riskApi("project_manager", { "/api/v1/risk/projects": () => jsonResponse([]) });
    renderRoute("/");

    expect(await screen.findByText("No open projects on your sites.")).toBeInTheDocument();
  });
});

describe("Project risk panel", () => {
  it("shows the score, forecast, drivers and data gaps as an estimate", async () => {
    riskApi("project_manager");
    renderRoute(`/projects/${PID}`);

    const panel = (await screen.findByRole("heading", { name: "Delay and cost risk" })).closest("section")!;
    expect(await within(panel).findByText("82")).toBeInTheDocument();
    expect(panel).toHaveTextContent("High risk");
    expect(panel).toHaveTextContent("about 72 days late");
    expect(panel).toHaveTextContent("8.8% over budget");
    expect(panel).toHaveTextContent("likely 53 to 100");
    expect(panel).toHaveTextContent("likely 44 to 104 days late");
    expect(panel).toHaveTextContent("likely 3.1% to 14.6% over budget");
    expect(panel).toHaveTextContent("An estimate from risk model v2.0.0, trained on simulated projects");
    expect(panel).toHaveTextContent("Likely ranges hold 8 in 10 outcomes");
    expect(panel).toHaveTextContent("from the average project the model learnt from (SHAP values)");

    const drivers = within(within(panel).getByRole("list", { name: "What moved the forecast" })).getAllByRole("listitem");
    // Signals the site can act on come before context such as the project's length.
    expect(drivers.map((d) => d.textContent)).toEqual([
      expect.stringContaining("Progress against plan: 8.0 points behind"),
      expect.stringContaining("Delivery lateness"),
      expect.stringContaining("Planned duration: 83 weeks(context)"),
    ]);
    expect(drivers[0]).toHaveTextContent("Raises the forecast: adds 22.4 days, adds 0.6% cost");
    expect(drivers[1]).toHaveTextContent("Lowers the forecast: saves 3.6 days");
    expect(panel).toHaveTextContent("Gaps in the data");
    expect(panel).toHaveTextContent("Only 4 forecast days cached");
  });

  it("says when a project has not been scored yet", async () => {
    riskApi("quantity_surveyor", { [`/api/v1/projects/${PID}/risk`]: () => jsonResponse({ project_id: PID, latest: null, history: [] }) });
    renderRoute(`/projects/${PID}`);

    expect(await screen.findByText(/Not scored yet\. Every open project is scored each morning/)).toBeInTheDocument();
  });

  it("is not shown to site engineers", async () => {
    const strip = { ...DETAIL, contract_value: undefined, boq_total: undefined, budget_total: undefined };
    riskApi("site_engineer", { [`/api/v1/projects/${PID}`]: () => jsonResponse(strip) });
    renderRoute(`/projects/${PID}`);

    await screen.findByRole("heading", { level: 1, name: /Havelock Residences/ });
    expect(screen.queryByRole("heading", { name: "Delay and cost risk" })).not.toBeInTheDocument();
  });
});

describe("risk wording", () => {
  it.each([
    ["0", "on time"], ["2.4", "on time"], ["71.6", "about 72 days late"], ["-10", "about 10 days early"],
  ])("delay %s reads %s", (days, text) => {
    expect(delayText(days)).toBe(text);
  });

  it.each([
    ["0.2", "on budget"], ["8.75", "8.8% over budget"], ["-3", "3.0% under budget"],
  ])("overrun %s reads %s", (pct, text) => {
    expect(overrunText(pct)).toBe(text);
  });

  it.each([
    [{ low: 44.2, high: 103.9 }, "likely 44 to 104 days late"],
    [{ low: -12, high: -3 }, "likely 3 to 12 days early"],
    [{ low: -5.2, high: 30 }, "likely 5 days early to 30 days late"],
    [{ low: 0, high: 12 }, "likely on time to 12 days late"],
  ])("delay range %j reads %s", (range, text) => {
    expect(delayRangeText(range)).toBe(text);
  });

  it.each([
    [{ low: 3.1, high: 14.6 }, "likely 3.1% to 14.6% over budget"],
    [{ low: -4, high: -1 }, "likely 1.0% to 4.0% under budget"],
    [{ low: -2, high: 4.5 }, "likely 2.0% under budget to 4.5% over budget"],
    [{ low: 0, high: 3 }, "likely on budget to 3.0% over budget"],
  ])("overrun range %j reads %s", (range, text) => {
    expect(overrunRangeText(range)).toBe(text);
  });

  it("gives the score's range, or one number when both ends agree", () => {
    expect(scoreRangeText({ low: 53, high: 100 })).toBe("likely 53 to 100");
    expect(scoreRangeText({ low: 100, high: 100 })).toBe("likely 100");
  });

  it("describes what a driver did", () => {
    expect(driverEffect(driver({ delay_days: 0.2, overrun_pct: 0.05 }))).toBe("little effect");
    expect(driverEffect(driver({ delay_days: 0, overrun_pct: -0.4 }))).toBe("saves 0.4% cost");
    expect(raisesRisk(driver({ delay_days: -1, overrun_pct: 0.4 }))).toBe(true);  // 0.4% cost outweighs a day
    expect(raisesRisk(driver({ delay_days: -3, overrun_pct: 0.4 }))).toBe(false);
  });
});
