import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Role } from "../api/auth";
import type { ReportAction } from "../api/issues";
import type { ProjectDetail } from "../api/projects";
import type { ProjectRisk } from "../api/risk";
import type { Network, Progress, Task, TaskTiming } from "../api/schedule";
import { slipText } from "../features/schedule/network";
import { DEFAULT_LOCALE } from "../lib/locale";
import { siteTodayIso } from "../lib/time";
import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi } from "../test/utils";

const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };
const PID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const T1 = "11111111-1111-4111-8111-111111111111";
const T2 = "22222222-2222-4222-8222-222222222222";
const T3 = "33333333-3333-4333-8333-333333333333";
const DEP = "44444444-4444-4444-8444-444444444444";
const ACT = "55555555-5555-4555-8555-555555555555";
const RID = "66666666-6666-4666-8666-666666666666";

const DETAIL: ProjectDetail = {
  id: PID, code: "HR-2026-01", name: "Havelock Residences", site: SITE, client_name: "Havelock Developers",
  project_type: "residential", status: "active", contract_value: "1114000000.00", start_date: "2026-03-02",
  planned_end: "2027-09-30", boq_total: "0.00", budget_total: "0.00", item_count: 0, description: null,
  planned_crew: null, working_week: "123456", sections: [], team: [],
  created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
};  // fmt: skip

const task = (id: string, code: string, pct: string, over: Partial<Task> = {}): Task => ({
  id, project_id: PID, code, name: `Task ${code}`, boq_section_id: null, boq_section_code: null,
  planned_start: "2026-09-01", planned_end: "2026-11-30", weight: "10.00", percent_complete: pct, is_critical: false,
  is_concrete_pour: false, client_milestone: false, milestone_name: null, stopped: false, actual_start: pct === "0.00" ? null : "2026-09-01", actual_finish: null,
  position: 1, planned_percent_today: 40, state: "on_track", progress_updated_at: null, ...over,
});  // fmt: skip

const TASKS = [
  task(T1, "T-040", "40.00", { is_critical: true }),
  task(T2, "T-050", "0.00", { is_concrete_pour: true }),
  task(T3, "T-060", "0.00"),
];

const timing = (id: string, code: string, over: Partial<TaskTiming> = {}): TaskTiming => ({
  task_id: id, code, name: `Task ${code}`, percent_complete: "0.00", planned_start: "2026-09-01",
  planned_end: "2026-11-30", planned_duration: 78, forecast_start: "2026-09-01", forecast_finish: "2026-11-30",
  slip_days: 0, total_float: 12, is_critical: false, is_done: false, stopped: false, stopped_days: 0,
  is_concrete_pour: false, rain_days: [], predecessors: [], ...over,
});  // fmt: skip

const NETWORK: Network = {
  project_id: PID, as_of: "2026-10-11", working_week: "123456", planned_end: "2027-09-30",
  network_end: "2027-09-30", forecast_end: "2027-10-14", slip_days: 12,
  tasks: [
    timing(T1, "T-040", { percent_complete: "40.00", forecast_finish: "2026-12-14", slip_days: 12, total_float: 0, is_critical: true, stopped: true, stopped_days: 3 }),
    timing(T2, "T-050", { is_concrete_pour: true, rain_days: ["2026-10-13"], predecessors: [T1] }),
    timing(T3, "T-060"),
  ],
  dependencies: [{ id: DEP, predecessor_id: T1, successor_id: T2, lag_days: 0 }],
  stop_work: [{ action_id: ACT, report_id: RID, summary: "Helper fell", scope: "tasks", task_ids: [T1], since: "2026-10-08T03:00:00+00:00" }],
  warnings: ["No holidays are entered for 2027: its public holidays count as working days. The Company Admin can add them."],
};  // fmt: skip

const PROGRESS: Progress = {
  as_of: "2026-10-11", planned_percent: 27.4, actual_percent: 23.0, variance: -4.4, weight_total: "30.00",
  task_count: 3, programme_start: "2026-03-02", programme_end: "2027-09-30", contract_end: "2027-09-30",
  points: [{ date: "2026-03-02", planned: 0, actual: 0 }, { date: "2027-09-30", planned: 100, actual: null }],
};  // fmt: skip

/** A risk forecast whose likely delay is ``low`` to ``high`` days past the planned end (30 Sept 2027). */
const riskWith = (low: number, high: number): ProjectRisk => ({
  project_id: PID,
  latest: {
    score_date: "2026-10-11", score: 48, level: "medium", delay_days: String((low + high) / 2), overrun_pct: "4.00",
    ranges: { delay_days: { low, high }, overrun_pct: { low: 1, high: 9 }, score: { low: 30, high: 66 } },
    drivers: [], notes: [], model_version: "2.0.0", scored_at: "2026-10-11T00:30:00+00:00",
  },
  history: [],
});  // fmt: skip

function urlOf(input: RequestInfo | URL): string {
  return input instanceof Request ? input.url : input instanceof URL ? input.href : input;
}

function body(init: RequestInit | undefined): Record<string, unknown> {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON request body");
  return JSON.parse(init.body) as Record<string, unknown>;
}

function scheduleApi(role: Role, extra: Record<string, (url: string, init?: RequestInit) => Response> = {}) {
  return mockApi({
    ...sessionApi(makeMe(role)),
    [`/api/v1/projects/${PID}`]: () => jsonResponse(DETAIL),
    [`/api/v1/projects/${PID}/tasks`]: () => jsonResponse({ tasks: TASKS, weight_total: "30.00" }),
    [`/api/v1/projects/${PID}/progress`]: () => jsonResponse(PROGRESS),
    [`/api/v1/projects/${PID}/network`]: () => jsonResponse(NETWORK),
    [`/api/v1/projects/${PID}/risk`]: () => jsonResponse(riskWith(30, 70)),
    ...extra,
  });
}

describe("slipText", () => {
  it("says slip in working days, in words", () => {
    expect(slipText(0)).toBe("on time");
    expect(slipText(1)).toBe("1 working day late");
    expect(slipText(-3)).toBe("3 working days early");
  });
});

describe("Forecast handover, two ways (Phase 10)", () => {
  it("says nothing more when the programme date falls inside the model's range", async () => {
    scheduleApi("quantity_surveyor", { [`/api/v1/projects/${PID}/risk`]: () => jsonResponse(riskWith(-5, 40)) });
    renderRoute(`/projects/${PID}/schedule`);

    const handover = await screen.findByRole("group", { name: "Forecast handover" });
    expect(await within(handover).findByText("25 Sept 2027 to 09 Nov 2027")).toBeInTheDocument();
    expect(handover).not.toHaveTextContent("later finish");
  });

  it("points out a programme running later than the model expects", async () => {
    scheduleApi("project_manager", { [`/api/v1/projects/${PID}/risk`]: () => jsonResponse(riskWith(-20, 5)) });
    renderRoute(`/projects/${PID}/schedule`);

    const handover = await screen.findByRole("group", { name: "Forecast handover" });
    expect(await within(handover).findByText(/The current pace points to a later finish than the risk model expects/)).toBeInTheDocument();
  });

  it("waits for the next scoring when there is no range yet", async () => {
    const unscored = { project_id: PID, latest: null, history: [] };
    scheduleApi("project_manager", { [`/api/v1/projects/${PID}/risk`]: () => jsonResponse(unscored) });
    renderRoute(`/projects/${PID}/schedule`);

    const handover = await screen.findByRole("group", { name: "Forecast handover" });
    expect(await within(handover).findByText("from the next scoring")).toBeInTheDocument();
  });

  it("shows engineers only the programme's date (risk is for PMs and QSs)", async () => {
    const fetchMock = scheduleApi("site_engineer");
    renderRoute(`/projects/${PID}/schedule`);

    const handover = await screen.findByRole("group", { name: "Forecast handover" });
    expect(handover).toHaveTextContent("At current rates14 Oct 2027");
    expect(handover).not.toHaveTextContent("Risk model");
    expect(requestTo(fetchMock, `/projects/${PID}/risk`)).toBeUndefined();
  });
});

describe("Gantt and forecast (Phase 9)", () => {
  it("shows the forecast handover, warnings, critical path, stop-work and rain on a pour", async () => {
    scheduleApi("project_manager");
    renderRoute(`/projects/${PID}/schedule`);

    const handover = await screen.findByRole("group", { name: "Forecast handover" });
    expect(handover).toHaveTextContent("At current rates14 Oct 2027");
    expect(handover).toHaveTextContent("12 working days late against 30 Sept 2027");
    // The risk model's likely range, labelled, and the disagreement spelt out: the programme says
    // 14 October, the model expects 30 October to 9 December.
    expect(await within(handover).findByText("30 Oct 2027 to 09 Dec 2027")).toBeInTheDocument();
    expect(handover).toHaveTextContent("Risk model, likely range");
    expect(handover).toHaveTextContent("The risk model expects a later finish than the current pace suggests.");
    expect(screen.getByText(/No holidays are entered for 2027/)).toBeInTheDocument();
    expect(screen.getByText(/working days, Mon–Sat/)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /planned and forecast dates/ });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("critical · 12 working days late · stopped by stop-work");
    expect(rows[2]).toHaveTextContent("12 working days of float · heavy rain forecast 13 Oct 2026");
    expect(rows[3]).toHaveTextContent("12 working days of float");
  });

  it("lets the PM mark a pour and link tasks; a loop is explained", async () => {
    const user = userEvent.setup();
    const fetchMock = scheduleApi("project_manager", {
      [`/api/v1/projects/${PID}/dependencies`]: () =>
        errorResponse(422, "dependency_loop", "That would make a loop: the second task already leads back to the first."),
      [`/api/v1/dependencies/${DEP}`]: () => new Response(null, { status: 204 }),
    });
    renderRoute(`/projects/${PID}/schedule`);

    await user.click(await screen.findByRole("button", { name: "Edit Task T-050" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("checkbox", { name: /Concrete pour/ })).toBeChecked();
    const predecessors = within(dialog).getByRole("list", { name: "Predecessors" });
    expect(predecessors).toHaveTextContent("T-040 Task T-040");
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Add a predecessor" }), T3);
    await user.click(within(dialog).getByRole("button", { name: "Add link" }));
    expect(await within(dialog).findByText(/would make a loop/)).toBeInTheDocument();
    expect(body(requestTo(fetchMock, `/projects/${PID}/dependencies`))).toEqual({ predecessor_id: T3, successor_id: T2, lag_days: 0 });
    await user.click(within(dialog).getByRole("button", { name: "Remove the link to T-040 Task T-040" }));
    await waitFor(() => {
      expect(requestTo(fetchMock, `/dependencies/${DEP}`)?.method).toBe("DELETE");
    });
  });
});

describe("Stop-work scope (BR-11)", () => {
  const flag: ReportAction = {
    id: ACT, report_id: RID, kind: "stop_work", status: "open", summary: "Helper fell", created_at: "2026-10-08T03:00:00+00:00",
    closed_at: null, request_id: null, can_close: true, stop_scope: "tasks", stop_task_ids: [T1], can_edit_scope: true,
  };  // fmt: skip

  it("says what a flag stops and lets the PM change it to the whole project", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      ...sessionApi(makeMe("project_manager")),
      [`/api/v1/projects/${PID}`]: () => jsonResponse(DETAIL),
      [`/api/v1/projects/${PID}/tasks`]: () => jsonResponse({ tasks: TASKS, weight_total: "30.00" }),
      [`/api/v1/projects/${PID}/report-actions`]: () => jsonResponse([flag]),
      [`/api/v1/report-actions/${ACT}/stop-scope`]: () => jsonResponse({ ...flag, stop_scope: "project", stop_task_ids: [] }),
    });
    renderRoute(`/projects/${PID}`);

    expect(await screen.findByText("Stops T-040.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Change what it stops" }));
    const dialog = await screen.findByRole("dialog", { name: "What does this stop-work stop?" });
    expect(within(dialog).getByRole("checkbox", { name: /T-040/ })).toBeChecked();
    await user.click(within(dialog).getByRole("checkbox", { name: /T-040/ }));
    expect(within(dialog).getByRole("button", { name: "Save" })).toBeDisabled(); // nothing chosen
    await user.click(within(dialog).getByRole("radio", { name: /The whole project/ }));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/report-actions/${ACT}/stop-scope`))).toEqual({ scope: "project", task_ids: [] });
    });
  });
});

describe("Holidays (Company Admin)", () => {
  it("lists holidays by year, warns about next year and adds one", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      ...sessionApi(makeMe("admin")),
      "/api/v1/admin/holidays": (_url, init) =>
        init?.method === "POST"
          ? jsonResponse({ id: DEP, holiday_date: "2027-01-03", name: "Duruthu Full Moon Poya Day" }, 201)
          : jsonResponse({
              holidays: [{ id: T1, holiday_date: "2026-01-03", name: "Duruthu Full Moon Poya Day" }],
              years: [2026],
              missing_next_year: true,
            }),
    });
    renderRoute("/admin/holidays");

    expect(await screen.findByText(/No holidays entered for \d{4} yet/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /2026/ })).toHaveTextContent("1 days");
    const form = screen.getByRole("form", { name: "Add a holiday" });
    // Date inputs take a value, not keystrokes, in the test DOM.
    fireEvent.change(within(form).getByLabelText(/Date/), { target: { value: "2027-01-03" } });
    await user.type(within(form).getByRole("textbox", { name: "Name" }), "Duruthu Full Moon Poya Day");
    await user.click(within(form).getByRole("button", { name: "Add holiday" }));

    await waitFor(() => {
      const posted = fetchMock.mock.calls.find(([input, init]) => urlOf(input).endsWith("/admin/holidays") && init?.method === "POST");
      expect(body(posted?.[1])).toEqual({ holiday_date: "2027-01-03", name: "Duruthu Full Moon Poya Day" });
    });
  });
});

describe("Holiday import (Company Admin)", () => {
  it("imports the company's country's public holidays for next year by default", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      ...sessionApi(makeMe("admin", { company: { ...DEFAULT_LOCALE, country: "GB", currency: "GBP", number_locale: "en-GB" } })),
      "/api/v1/admin/holidays": () => jsonResponse({ holidays: [], years: [], missing_next_year: true }),
      "/api/v1/admin/holidays/countries": () => jsonResponse({ countries: ["GB", "LK", "US"], default: "GB" }),
      "/api/v1/admin/holidays/import": () =>
        jsonResponse({
          country: "GB",
          year: 2027,
          added: [{ id: T1, holiday_date: "2027-12-25", name: "Christmas Day" }],
          already_entered: 0,
          message: "Added 1 public holidays for 2027. Check them, and add any other days your sites do not work.",
        }),
    });
    renderRoute("/admin/holidays");

    const form = await screen.findByRole("form", { name: "Import public holidays" });
    const country = within(form).getByRole("combobox", { name: "Country" });
    await waitFor(() => {
      expect(country).toHaveValue("GB");
    });
    expect(within(country).getByRole("option", { name: "United Kingdom" })).toBeInTheDocument();
    const year = within(form).getByRole("textbox", { name: "Year" });
    const nextYear = Number(siteTodayIso().slice(0, 4)) + 1;
    expect(year).toHaveValue(String(nextYear));
    await user.clear(year);
    await user.type(year, "2027");
    await user.click(within(form).getByRole("button", { name: "Import public holidays" }));

    expect(await screen.findByText(/Added 1 public holidays for 2027/)).toBeInTheDocument();
    expect(body(requestTo(fetchMock, "/admin/holidays/import"))).toEqual({ country: "GB", year: 2027 });
  });
});

describe("Working week", () => {
  it("is part of the project form and must have a day", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      ...sessionApi(makeMe("project_manager")),
      [`/api/v1/projects/${PID}`]: (_url, init) => jsonResponse(init?.method === "PATCH" ? { ...DETAIL, working_week: "12345" } : DETAIL),
      "/api/v1/sites": () => jsonResponse([SITE]),
    });
    renderRoute(`/projects/${PID}`);

    await user.click(await screen.findByRole("button", { name: "Edit project" }));
    const dialog = await screen.findByRole("dialog");
    const week = within(dialog).getByRole("group", { name: "Working week" });
    expect(within(week).getByRole("checkbox", { name: "Sat" })).toBeChecked();
    expect(within(week).getByRole("checkbox", { name: "Sun" })).not.toBeChecked();
    await user.click(within(week).getByRole("checkbox", { name: "Sat" }));
    await user.click(within(dialog).getByRole("button", { name: /Save/ }));

    await waitFor(() => {
      const patched = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
      expect(body(patched?.[1]).working_week).toBe("12345");
    });
  });
});
