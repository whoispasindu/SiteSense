import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Role } from "../../api/auth";
import type { ProjectDetail } from "../../api/projects";
import type { ActionId, Forecast, ProjectRisk, WhatIf } from "../../api/risk";
import { jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi } from "../../test/utils";
import { savedCostText, savedDaysText } from "./risk";

const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };
const PID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";

const DETAIL: ProjectDetail = {
  id: PID, code: "HR-2026-01", name: "Havelock Residences", site: SITE, client_name: "Havelock Developers",
  project_type: "residential", status: "active", contract_value: "1114000000.00", start_date: "2026-03-02",
  planned_end: "2027-09-30", boq_total: "0.00", budget_total: "0.00", item_count: 0, description: null,
  planned_crew: 55, working_week: "123456", sections: [], team: [],
  created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
};  // fmt: skip

const RISK: ProjectRisk = {
  project_id: PID,
  latest: {
    score_date: "2026-10-12", score: 46, level: "medium", delay_days: "66.9", overrun_pct: "6.25",
    ranges: { delay_days: { low: 25.5, high: 127.9 }, overrun_pct: { low: -1.87, high: 14.63 }, score: { low: 18, high: 89 } },
    drivers: [], notes: [], model_version: "2.0.0", scored_at: "2026-10-12T00:30:00+00:00",
  },
  history: [
    { date: "2026-10-10", score: 30, level: "low", score_range: null },
    { date: "2026-10-11", score: 48, level: "medium", score_range: { low: 20, high: 90 } },
    { date: "2026-10-12", score: 46, level: "medium", score_range: { low: 18, high: 89 } },
  ],
};  // fmt: skip

const BASE: Forecast = {
  delay_days: 66.9, delay_range: { low: 25.5, high: 127.9 }, overrun_pct: 6.25, overrun_range: { low: -1.87, high: 14.63 },
  score: 46, score_range: { low: 18, high: 89 }, level: "medium",
};  // fmt: skip

const action = (id: ActionId, label: string, selected: boolean, cost: string | null = null) => ({
  id, label, description: `${label} description.`, change: `${label} change`, selected,
  delay_saved_days: { low: 4.2, high: 9.4 }, overrun_saved_pct: { low: 0.1, high: 0.3 },
  cost, cost_pct: cost ? 1.0 : null,
});  // fmt: skip

function whatIf(chosen: { id: ActionId; cost: string | null }[]): WhatIf {
  const ids = chosen.map((c) => c.id);
  const cost = (id: ActionId) => chosen.find((c) => c.id === id)?.cost ?? null;
  const labels: [ActionId, string][] = [
    ["add_crew", "Add a crew"], ["work_sundays", "Work Sundays"],
    ["expedite_materials", "Expedite late materials"], ["weather_protection", "Weather protection"],
  ];  // fmt: skip
  return {
    project_id: PID, as_of: "2026-10-12", model_version: "2.0.0", baseline: BASE,
    actions: labels.map(([id, label]) => action(id, label, ids.includes(id), cost(id))),
    plan: ids.length ? { ...BASE, delay_days: 36.0, delay_range: { low: -5.6, high: 97.0 }, score: 27, score_range: { low: 0, high: 69 }, level: "low" } : null,
    plan_delay_saved_days: ids.length ? { low: 12.1, high: 30.9 } : null,
    plan_overrun_saved_pct: ids.length ? { low: -0.6, high: -0.2 } : null,
    costs_not_entered: chosen.filter((c) => c.cost === null).map((c) => labels.find(([i]) => i === c.id)?.[1] ?? c.id),
    advice: [{ id: "file_reports", label: "File every daily report", text: "4 working days in the last 14 had no report." }],
    notes: ["Only 13 forecast days cached: rain scaled to 14 days."],
  };  // fmt: skip
}

/** The bodies of every what-if request so far, in order. */
function whatIfBodies(fetchMock: ReturnType<typeof mockApi>): unknown[] {
  return fetchMock.mock.calls
    .filter(([input]) => (input instanceof Request ? input.url : input instanceof URL ? input.href : input).endsWith("/risk/what-if"))
    .map(([, init]) => (typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : null));
}

function riskApi(role: Role) {
  return mockApi({
    ...sessionApi(makeMe(role)),
    [`/api/v1/projects/${PID}`]: () => jsonResponse(DETAIL),
    [`/api/v1/projects/${PID}/risk`]: () => jsonResponse(RISK),
    [`/api/v1/projects/${PID}/risk/what-if`]: (_url, init) => {
      const body = JSON.parse(typeof init?.body === "string" ? init.body : "{}") as { actions: { id: ActionId; cost: string | null }[] };
      return jsonResponse(whatIf(body.actions));
    },
    "/api/v1/projects": () => jsonResponse([]),
    "/api/v1/risk/projects": () => jsonResponse([]),
  });
}

describe("Project Risk tab (Phase 10)", () => {
  it("shows the trend with its ranges, and tests recovery actions with costs", async () => {
    const user = userEvent.setup();
    const fetchMock = riskApi("project_manager");
    renderRoute(`/projects/${PID}/risk`);

    // Today, with its range, before anything is ticked.
    const result = await screen.findByText(/^Today, /);
    const panel = result.closest("[aria-live]") as HTMLElement;
    expect(panel).toHaveTextContent("likely 18 to 89");
    expect(panel).toHaveTextContent("about 67 days late (likely 26 to 128 days late)");
    expect(panel).toHaveTextContent("Tick an action to see the forecast with it.");

    // Each action's effect is a range, labelled as a simulation estimate.
    const actions = screen.getByRole("list", { name: "Recovery actions" });
    expect(within(actions).getAllByText(/saves 4 to 9 days, saves 0.1% to 0.3% of cost/)).toHaveLength(4);
    expect(within(actions).getAllByText("(simulation estimate)")).toHaveLength(4);

    await user.click(screen.getByRole("checkbox", { name: "Add a crew" }));
    expect(await within(panel).findByText("With 1 action")).toBeInTheDocument();
    expect(panel).toHaveTextContent("about 36 days late (likely 6 days early to 97 days late)");
    expect(panel).toHaveTextContent("Together: saves 12 to 31 days, adds 0.2% to 0.6% to cost (costs entered included).");
    expect(within(panel).getByText("Cost not entered")).toBeInTheDocument(); // blank is never free
    expect(panel).toHaveTextContent("Add a crew: the cost forecast leaves it out");

    const cost = screen.getByLabelText("Estimated cost (LKR)");
    await user.type(cost, "9,800,000");
    fireEvent.blur(cost);
    await waitFor(() => {
      expect(within(panel).queryByText("Cost not entered")).not.toBeInTheDocument();
    });
    expect(screen.getByText("LKR 9,800,000, 1.0% of the cost budget.")).toBeInTheDocument();
    const posts = whatIfBodies(fetchMock);
    expect(posts.at(-1)).toEqual({ actions: [{ id: "add_crew", cost: "9800000" }] });

    // Advice changes no forecast; the trend has its numbers in a table.
    expect(screen.getByRole("list", { name: "Advice" })).toHaveTextContent("File every daily report.");
    expect(screen.getByText("Up 16 points over the period.")).toBeInTheDocument();
    const trend = screen.getByRole("table", { name: /Risk score by day/ });
    expect(within(trend).getAllByRole("row")[1]).toHaveTextContent("30—Low");
    expect(within(trend).getAllByRole("row")[3]).toHaveTextContent("4618 to 89Medium");
  });

  it("refuses a malformed cost and keeps it out of the plan", async () => {
    const user = userEvent.setup();
    const fetchMock = riskApi("project_manager");
    renderRoute(`/projects/${PID}/risk`);

    await user.click(await screen.findByRole("checkbox", { name: "Weather protection" }));
    const cost = await screen.findByLabelText("Estimated cost (LKR)");
    await user.type(cost, "12.345");

    expect(screen.getByText("Enter an amount in rupees, up to two decimals.")).toBeInTheDocument();
    expect(cost).toHaveAttribute("aria-invalid", "true");
    fireEvent.blur(cost);
    expect(whatIfBodies(fetchMock).every((b) => !JSON.stringify(b).includes("12.345"))).toBe(true);
  });

  it("lets quantity surveyors read risk but not plan", async () => {
    const fetchMock = riskApi("quantity_surveyor");
    renderRoute(`/projects/${PID}/risk`);

    expect(await screen.findByText("The project manager tests recovery actions in the what-if planner.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Risk" })).toHaveAttribute("href", `/projects/${PID}/risk`);
    expect(requestTo(fetchMock, "/risk/what-if")).toBeUndefined();
  });

  it("lists every project by risk on the Risk & what-if page", async () => {
    riskApi("project_manager");
    renderRoute("/risk");

    expect(await screen.findByRole("heading", { level: 1, name: "Risk & what-if" })).toBeInTheDocument();
    expect(await screen.findByText("No open projects on your sites.")).toBeInTheDocument();
  });
});

describe("saving wording", () => {
  it.each([
    [{ low: 0.1, high: 0.4 }, "little effect on handover"],
    [{ low: 4.2, high: 9.4 }, "saves 4 to 9 days"],
    [{ low: 6.4, high: 6.2 }, "saves about 6 days"],
  ])("days %j read %s", (effect, text) => {
    expect(savedDaysText(effect)).toBe(text);
  });

  it.each([
    [{ low: 0.01, high: 0.02 }, "little effect on cost"],
    [{ low: 0.1, high: 0.3 }, "saves 0.1% to 0.3% of cost"],
    [{ low: -0.6, high: -0.2 }, "adds 0.2% to 0.6% to cost"],
    [{ low: -0.4, high: 0.6 }, "between adding 0.4% and saving 0.6% of cost"],
  ])("cost %j reads %s", (effect, text) => {
    expect(savedCostText(effect)).toBe(text);
  });
});
