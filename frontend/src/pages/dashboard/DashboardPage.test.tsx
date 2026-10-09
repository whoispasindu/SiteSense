import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ProjectSummary } from "../../api/projects";
import { jsonResponse, makeMe, mockApi, renderRoute, sessionApi } from "../../test/utils";

const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };
const HAVELOCK: ProjectSummary = {
  id: "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d", code: "HR-2026-01", name: "Havelock Residences", site: SITE,
  client_name: "Havelock Developers", project_type: "residential", status: "active", contract_value: "1114000000.00",
  start_date: "2026-03-02", planned_end: "2027-09-30", boq_total: "0.00", budget_total: "0.00", item_count: 0,
};
const PERADENIYA: ProjectSummary = {
  ...HAVELOCK, id: "1a1b1c1d-2e2f-4a3b-8c4d-5e6f7a8b9c0d", code: "PRO-1", name: "Peradeniya Road",
  status: "planning", contract_value: "386000000.00",
};

function portfolioApi() {
  return mockApi({
    ...sessionApi(makeMe("project_manager", { full_name: "Ruwan Silva" })),
    "/api/v1/projects": () => jsonResponse([HAVELOCK, PERADENIYA]),
    "/api/v1/schedule/summary": () =>
      jsonResponse([
        { project: PERADENIYA, planned_percent: 34.4, actual_percent: 35.2, variance: 0.8, task_count: 5 },
        { project: HAVELOCK, planned_percent: 27.4, actual_percent: 23.0, variance: -4.4, task_count: 11 },
      ]),
  });
}

describe("DashboardPage", () => {
  it("greets the signed-in user by first name", async () => {
    portfolioApi();
    renderRoute("/");

    expect(await screen.findByRole("heading", { level: 1, name: /, Ruwan$/ })).toBeInTheDocument();
  });

  it("summarises the portfolio in KPIs", async () => {
    portfolioApi();
    renderRoute("/");

    const active = await screen.findByRole("group", { name: "Active projects" });
    expect(await within(active).findByText("1")).toBeInTheDocument();
    expect(active).toHaveTextContent("2 in total");
    expect(screen.getByRole("group", { name: "Contract value" })).toHaveTextContent("LKR 1.5 bn");
    const behind = screen.getByRole("group", { name: "Behind plan" });
    expect(await within(behind).findByText("1")).toBeInTheDocument();
    expect(behind).toHaveTextContent("more than 2 points behind");
  });

  it("lists schedule health furthest behind first, in words", async () => {
    portfolioApi();
    renderRoute("/");

    const list = await screen.findByRole("list", { name: "Schedule health by project" });
    const items = await within(list).findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Havelock Residences");
    expect(items[0]).toHaveTextContent("Behind 4.4 pts");
    expect(items[0]).toHaveTextContent("23.0% of 27.4%");
    expect(items[1]).toHaveTextContent("On plan");
  });

  it("describes the contract value chart for screen readers", async () => {
    portfolioApi();
    renderRoute("/");

    expect(await screen.findByRole("img", { name: /Havelock Residences: LKR 1.11 bn; Peradeniya Road/ })).toBeInTheDocument();
  });

  it("shows system status only to the company admin", async () => {
    portfolioApi();
    renderRoute("/");
    await screen.findByRole("group", { name: "Active projects" });
    expect(screen.queryByRole("heading", { name: /System status/ })).not.toBeInTheDocument();
  });

  it("shows live readings when the API and database are up", async () => {
    mockApi(sessionApi(makeMe("admin")));
    renderRoute("/");

    const api = await screen.findByRole("group", { name: "API" });
    expect(await within(api).findByText("Online")).toBeInTheDocument();
    expect(await within(api).findByText(/v0\.0\.1/)).toBeInTheDocument();
    const db = screen.getByRole("group", { name: "Database" });
    expect(await within(db).findByText("Ready")).toBeInTheDocument();
    expect(await screen.findByText("All systems are working.")).toBeInTheDocument();
  });

  it("reports a degraded database with a text label, not only colour", async () => {
    mockApi({
      ...sessionApi(makeMe("admin")),
      "/api/v1/health/ready": () => jsonResponse({ status: "degraded", checks: { database: "unavailable" } }, 503),
    });
    renderRoute("/");

    const db = await screen.findByRole("group", { name: "Database" });
    expect(await within(db).findByText("Unavailable")).toBeInTheDocument();
    expect(await screen.findByText("The API is up but cannot reach PostgreSQL.")).toBeInTheDocument();
  });

  it("explains what to do when the API is unreachable", async () => {
    const authOnly = Object.fromEntries(
      Object.entries(sessionApi(makeMe("admin"))).filter(([path]) => !path.startsWith("/api/v1/health")),
    );
    mockApi(authOnly);
    renderRoute("/");

    const api = await screen.findByRole("group", { name: "API" });
    expect(await within(api).findByText("Offline")).toBeInTheDocument();
    expect(await screen.findByText(/The API is not answering/)).toBeInTheDocument();
  });

  it("re-checks on demand", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(sessionApi(makeMe("admin")));
    renderRoute("/");
    const api = await screen.findByRole("group", { name: "API" });
    await within(api).findByText("Online");
    const before = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Re-check now" }));

    await screen.findByRole("button", { name: "Re-check now" });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before);
  });

  it("links the admin to the administration pages", async () => {
    mockApi(sessionApi(makeMe("admin")));
    renderRoute("/");

    const main = await screen.findByRole("main");
    expect(await within(main).findByRole("link", { name: /Accounts, roles and site access/ })).toHaveAttribute("href", "/admin/users");
    expect(within(main).getByRole("link", { name: /Sign-ins and changes/ })).toHaveAttribute("href", "/admin/audit");
  });
});
