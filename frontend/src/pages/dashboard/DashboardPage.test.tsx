import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Briefing, Portfolio } from "../../api/dashboard";
import type { ProjectSummary } from "../../api/projects";
import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, sessionApi } from "../../test/utils";

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

const WEEKS = ["2026-08-24", "2026-08-31", "2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05", "2026-10-12"];
const EMPTY = { material_delay: 0, labour: 0, weather: 0, equipment: 0, safety: 0, design: 0, quality: 0, other: 0 };

function portfolio(overrides: Partial<Portfolio> = {}): Portfolio {
  return {
    as_of: "2026-10-12",
    kpis: {
      active_projects: 1, total_projects: 2, average_actual_pct: 23.0, average_planned_pct: 27.4, behind_plan: 1,
      reports_due_today: 2, reports_filed_today: 1, issues_this_week: 3, stop_work_open: 1, waiting_for_you: 2,
      high_risk: 1,
    },
    cost: {
      totals: { budget: "900000000.00", committed: "120000000.00", forecast_final: "950000000.00", over_budget: 1 },
      projects: [
        {
          project_id: HAVELOCK.id, code: HAVELOCK.code, name: HAVELOCK.name, budget: "900000000.00",
          committed: "120000000.00", forecast_final: "950000000.00",
          model_final_range: { low: "910000000.00", high: "1010000000.00" },
        },
        {
          project_id: PERADENIYA.id, code: PERADENIYA.code, name: PERADENIYA.name, budget: "0.00", committed: "0.00",
          forecast_final: "0.00", model_final_range: null,
        },
      ],
    },
    risk: [],
    issue_trend: WEEKS.map((week, i) => ({
      week_start: week,
      total: i === 7 ? 3 : i === 6 ? 1 : 0,
      by_category: i === 7 ? { ...EMPTY, safety: 2, labour: 1 } : i === 6 ? { ...EMPTY, weather: 1 } : EMPTY,
    })),
    weather: [
      {
        site_code: "COL-07", site_name: "Havelock Residences", available: true, stale: true,
        fetched_at: "2026-10-10T00:00:00Z",
        days: [{ date: "2026-10-12", summary: "Rain", weather_code: 61, temp_max_c: "30.0", temp_min_c: "24.0", rain_mm: "14.0", rain_probability: 80 }],
        heavy_rain_threshold_mm: "10.0",
      },
    ],
    approvals: [
      {
        kind: "material_request", id: "11111111-1111-4111-8111-111111111111", number: "MR-0004", project_id: HAVELOCK.id,
        project_code: HAVELOCK.code, title: "Formwork to soffits", status: "pm_approval", since: "2026-10-12T02:00:00Z",
        link: "/materials/11111111-1111-4111-8111-111111111111",
      },
      {
        kind: "claim", id: "22222222-2222-4222-8222-222222222222", number: "PC-0002", project_id: HAVELOCK.id,
        project_code: HAVELOCK.code, title: "Progress claim PC-0002", status: "submitted", since: "2026-10-12T03:00:00Z",
        link: `/projects/${HAVELOCK.id}/claims`,
      },
    ],
    ...overrides,
  };
}

function briefing(overrides: Partial<Briefing> = {}): Briefing {
  return {
    date: "2026-10-12", source: "ai", label: "AI-written", model: "claude-haiku-5-5",
    generated_at: "2026-10-12T02:15:00Z",
    bullets: [
      { text: "Stop-work is in force on HR-2026-01 (BR-11).", projects: ["HR-2026-01"], sources: [{ kind: "stop_work", count: 1 }] },
      { text: "HR-2026-01 is at high risk: score 78, likely 71 to 84.", projects: ["HR-2026-01", "ZZ-9"], sources: [{ kind: "risk", count: 1 }] },
      { text: "2 items are waiting for you.", projects: [], sources: [{ kind: "approvals", count: 2 }, { kind: "issues", count: 3 }] },
    ],
    note: null,
    ...overrides,
  };
}

const NOTIFICATIONS = {
  unread: 2,
  items: [
    { id: "33333333-3333-4333-8333-333333333333", kind: "stop_work", title: "Stop-work flagged on HR-2026-01", body: "Scaffold", link: "/reports/x", created_at: "2026-10-12T03:00:00Z", read_at: null },
    { id: "44444444-4444-4444-8444-444444444444", kind: "report_submitted", title: "Daily report: Havelock", body: "Filed", link: null, created_at: "2026-10-12T02:00:00Z", read_at: null },
    { id: "55555555-5555-4555-8555-555555555555", kind: "request_approved", title: "MR-0001 approved", body: "Done", link: "https://evil.example", created_at: "2026-10-11T02:00:00Z", read_at: "2026-10-11T03:00:00Z" },
  ],
};

function api(role: "project_manager" | "site_engineer" = "project_manager", data: { portfolio?: Portfolio; briefing?: Briefing | Response } = {}) {
  return mockApi({
    ...sessionApi(makeMe(role, { full_name: "Ruwan Silva" })),
    "/api/v1/projects": () => jsonResponse([HAVELOCK, PERADENIYA]),
    "/api/v1/schedule/summary": () =>
      jsonResponse([
        { project: PERADENIYA, planned_percent: 34.4, actual_percent: 35.2, variance: 0.8, task_count: 5 },
        { project: HAVELOCK, planned_percent: 27.4, actual_percent: 23.0, variance: -4.4, task_count: 11 },
      ]),
    "/api/v1/analytics/portfolio": () => jsonResponse(data.portfolio ?? portfolio()),
    "/api/v1/briefing/today": () => (data.briefing instanceof Response ? data.briefing : jsonResponse(data.briefing ?? briefing())),
    "/api/v1/notifications": () => jsonResponse(NOTIFICATIONS),
    "/api/v1/risk/projects": () => jsonResponse([]),
    "/api/v1/reports/today": () => jsonResponse({ date: "2026-10-12", deadline: "2026-10-12T18:00:00+05:30", deadline_passed: false, projects: [] }),
    "/api/v1/reports/weekly.pdf": () => new Response(new Blob(["%PDF-1.4"], { type: "application/pdf" }), { status: 200 }),
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DashboardPage", () => {
  it("greets the signed-in user by first name", async () => {
    api();
    renderRoute("/");

    expect(await screen.findByRole("heading", { level: 1, name: /, Ruwan$/ })).toBeInTheDocument();
  });

  it("shows the briefing labelled AI-written, with project links and server-counted sources", async () => {
    api();
    renderRoute("/");

    const card = await screen.findByRole("region", { name: "Today’s briefing" });
    expect(await within(card).findByText("AI-written")).toBeInTheDocument();
    const points = within(card).getByRole("list", { name: "Briefing points" });
    const items = within(points).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Stop-work is in force on HR-2026-01 (BR-11).");
    expect(items[0]).toHaveTextContent("from 1 stop-work flag");
    await waitFor(() => {
      expect(within(items[1] as HTMLElement).getByRole("link", { name: "HR-2026-01" })).toHaveAttribute("href", `/projects/${HAVELOCK.id}`);
    });
    // A code the reader has no project for stays plain text.
    expect(within(items[1] as HTMLElement).queryByRole("link", { name: "ZZ-9" })).not.toBeInTheDocument();
    expect(items[2]).toHaveTextContent("from 2 items waiting · 3 issues");
  });

  it("labels the rule-based briefing and says why it is shown", async () => {
    api("project_manager", {
      briefing: briefing({ source: "rules", label: "Rule-based", model: null, note: "The AI briefing is unavailable just now, so this one is written by fixed rules." }),
    });
    renderRoute("/");

    const card = await screen.findByRole("region", { name: "Today’s briefing" });
    expect(await within(card).findByText("Rule-based")).toBeInTheDocument();
    expect(within(card).getByText(/written by fixed rules/)).toBeInTheDocument();
  });

  it("says so when the briefing cannot load", async () => {
    api("project_manager", { briefing: errorResponse(500, "internal_error", "Something went wrong.") });
    renderRoute("/");

    const card = await screen.findByRole("region", { name: "Today’s briefing" });
    expect(await within(card).findByRole("alert")).toBeInTheDocument();
  });

  it("summarises the portfolio in KPIs from the analytics endpoint", async () => {
    api();
    renderRoute("/");

    const active = await screen.findByRole("group", { name: "Active projects" });
    expect(active).toHaveTextContent("1");
    expect(active).toHaveTextContent("2 on your sites");
    expect(screen.getByRole("group", { name: "Average progress" })).toHaveTextContent("Planned 27.4% · 1 behind plan");
    expect(screen.getByRole("group", { name: "Reports today" })).toHaveTextContent("1 still to file (BR-07)");
    expect(screen.getByRole("group", { name: "Stop-work open" })).toHaveTextContent("Waiting for the project manager (BR-11)");
    expect(screen.getByRole("group", { name: "High risk" })).toHaveTextContent("Risk score 70 or more (BR-10)");
    expect(screen.getByRole("group", { name: "Waiting for you" })).toHaveTextContent("2");
  });

  it("asks the PM to review a published handover date that looks out of date", async () => {
    api("project_manager", {
      portfolio: portfolio({
        handover_reminders: [
          { project_id: HAVELOCK.id, code: HAVELOCK.code, name: HAVELOCK.name, published_date: "2027-09-30",
            reminder: { reasons: ["Not reviewed for 31 days."], forecast_gap_days: 2, days_since_review: 31 } },
        ],
      }),
    });  // fmt: skip
    renderRoute("/");

    const list = await screen.findByRole("list", { name: "Handover dates to review" });
    expect(list).toHaveTextContent("Published 30 Sept 2027. Not reviewed for 31 days.");
    expect(within(list).getByRole("link", { name: "Review the date" })).toHaveAttribute("href", `/projects/${HAVELOCK.id}/client`);
  });

  it("lists the approval queue with links", async () => {
    api();
    renderRoute("/");

    const queue = await screen.findByRole("list", { name: "Approval queue" });
    const links = within(queue).getAllByRole("link");
    expect(links[0]).toHaveAttribute("href", "/materials/11111111-1111-4111-8111-111111111111");
    expect(links[0]).toHaveTextContent("Material request");
    expect(links[1]).toHaveTextContent("Progress claim PC-0002");
  });

  it("marks urgent alerts and opens only in-app links", async () => {
    const user = userEvent.setup();
    const fetchMock = api();
    renderRoute("/");

    const list = await screen.findByRole("list", { name: "Latest alerts" });
    const buttons = await within(list).findAllByRole("button");
    expect(buttons[0]).toHaveTextContent("Urgent ·");
    expect(buttons[1]).not.toHaveTextContent("Urgent");
    expect(buttons[0]).toHaveTextContent("Unread.");

    await user.click(buttons[2] as HTMLElement); // an outside link is ignored
    expect(screen.getByRole("heading", { level: 1, name: /Ruwan/ })).toBeInTheDocument();
    await user.click(buttons[0] as HTMLElement);
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => (typeof url === "string" ? url : url instanceof URL ? url.href : url.url).includes("/notifications/33333333-3333-4333-8333-333333333333/read"))).toBe(true);
    });
  });

  it("draws cost against plan with the risk model's likely range", async () => {
    api();
    renderRoute("/");

    const list = await screen.findByRole("list", { name: "Cost against plan by project" });
    const [havelock, peradeniya] = within(list).getAllByRole("listitem");
    expect(havelock).toHaveTextContent("Committed LKR 120 M · at current rates LKR 950 M (over budget)");
    expect(havelock).toHaveTextContent("risk model, likely LKR 910 M to LKR 1.01 bn");
    expect(peradeniya).toHaveTextContent("No budget yet");
  });

  it("charts issues per week and ranks the last four weeks by kind", async () => {
    api();
    renderRoute("/");

    expect(await screen.findByRole("img", { name: /Confirmed issues per week.*week of Mon 12 Oct: 3/ })).toBeInTheDocument();
    const kinds = screen.getByRole("list", { name: "Issues in the last four weeks by kind" });
    const rows = within(kinds).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual(["Safety2", "Labour1", "Weather1"]);
  });

  it("shows each site's saved forecast and warns when it is old", async () => {
    api();
    renderRoute("/");

    expect(await screen.findByRole("list", { name: "Five-day forecast for site COL-07" })).toBeInTheDocument();
    expect(screen.getByText(/weather refresh did not run/)).toBeInTheDocument();
  });

  it("downloads the weekly PDF for cost roles", async () => {
    const user = userEvent.setup();
    const createUrl = vi.fn(() => "blob:weekly");
    const revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: revoke }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    api();
    renderRoute("/");

    await user.click(await screen.findByRole("button", { name: "Weekly report (PDF)" }));

    await waitFor(() => {
      expect(click).toHaveBeenCalled();
    });
    expect(createUrl).toHaveBeenCalled();
  });

  it("says so when the weekly PDF fails", async () => {
    const user = userEvent.setup();
    mockApi({
      ...sessionApi(makeMe("project_manager")),
      "/api/v1/projects": () => jsonResponse([]),
      "/api/v1/analytics/portfolio": () => jsonResponse(portfolio()),
      "/api/v1/briefing/today": () => jsonResponse(briefing()),
      "/api/v1/notifications": () => jsonResponse({ unread: 0, items: [] }),
      "/api/v1/risk/projects": () => jsonResponse([]),
      "/api/v1/schedule/summary": () => jsonResponse([]),
      "/api/v1/reports/today": () => jsonResponse({ date: "2026-10-12", deadline: "2026-10-12T18:00:00+05:30", deadline_passed: false, projects: [] }),
      "/api/v1/reports/weekly.pdf": () => errorResponse(500, "internal_error"),
    });
    renderRoute("/");

    await user.click(await screen.findByRole("button", { name: "Weekly report (PDF)" }));
    expect(await screen.findByText("Could not prepare the report. Try again.")).toBeInTheDocument();
  });

  it("shows a site engineer no costs, no PDF and no approval queue", async () => {
    const engineerView = portfolio({ cost: null, risk: null, approvals: [], kpis: { ...portfolio().kpis, high_risk: null, waiting_for_you: 0 } });
    api("site_engineer", { portfolio: engineerView });
    renderRoute("/");

    expect(await screen.findByRole("group", { name: "Active projects" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Weekly report (PDF)" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Cost against plan/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "High risk" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Waiting for you" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Approval queue" })).not.toBeInTheDocument();
    expect(screen.queryByText(/LKR/)).not.toBeInTheDocument();
  });

  it("lists schedule health furthest behind first, in words", async () => {
    api();
    renderRoute("/");

    const list = await screen.findByRole("list", { name: "Schedule health by project" });
    const items = await within(list).findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Havelock Residences");
    expect(items[0]).toHaveTextContent("Behind 4.4 pts");
    expect(items[1]).toHaveTextContent("On plan");
  });

  it("explains a portfolio that will not load", async () => {
    mockApi({
      ...sessionApi(makeMe("project_manager")),
      "/api/v1/projects": () => jsonResponse([]),
      "/api/v1/analytics/portfolio": () => errorResponse(500, "internal_error", "Something went wrong."),
      "/api/v1/briefing/today": () => jsonResponse(briefing()),
      "/api/v1/reports/today": () => jsonResponse({ date: "2026-10-12", deadline: "2026-10-12T18:00:00+05:30", deadline_passed: false, projects: [] }),
    });
    renderRoute("/");

    expect(await screen.findByText(/Something went wrong/)).toBeInTheDocument();
  });

  it("shows system status only to the company admin", async () => {
    api();
    renderRoute("/");
    await screen.findByRole("group", { name: "Active projects" });
    expect(screen.queryByRole("heading", { name: /System status/ })).not.toBeInTheDocument();
  });

  it("shows live readings when the API and database are up", async () => {
    mockApi(sessionApi(makeMe("admin")));
    renderRoute("/");

    const status = await screen.findByRole("group", { name: "API" });
    expect(await within(status).findByText("Online")).toBeInTheDocument();
    expect(await within(status).findByText(/v1\.0\.0/)).toBeInTheDocument();
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

    const status = await screen.findByRole("group", { name: "API" });
    expect(await within(status).findByText("Offline")).toBeInTheDocument();
    expect(await screen.findByText(/The API is not answering/)).toBeInTheDocument();
  });

  it("re-checks on demand", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(sessionApi(makeMe("admin")));
    renderRoute("/");
    const status = await screen.findByRole("group", { name: "API" });
    await within(status).findByText("Online");
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
