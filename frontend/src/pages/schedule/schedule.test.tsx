import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Role } from "../../api/auth";
import type { ProjectDetail, ProjectSummary } from "../../api/projects";
import type { Progress, Task } from "../../api/schedule";
import { varianceLabel } from "../../features/schedule/variance";
import { jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi } from "../../test/utils";

const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };
const PID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const TID = "5e6f7a8b-9c0d-4e1f-8a2b-3c4d5e6f7a8b";

const SUMMARY: ProjectSummary = {
  id: PID, code: "HR-2026-01", name: "Havelock Residences", site: SITE, client_name: "Havelock Developers",
  project_type: "residential", status: "active", contract_value: "1114000000.00", start_date: "2026-03-02",
  planned_end: "2027-09-30", boq_total: "0.00", budget_total: "0.00", item_count: 0,
};
const DETAIL: ProjectDetail = {
  ...SUMMARY, description: null, planned_crew: null, sections: [], team: [],
  created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
};

const TASK: Task = {
  id: TID, project_id: PID, code: "T-040", name: "Frame: ground to level 4", boq_section_id: null,
  boq_section_code: null, planned_start: "2026-06-15", planned_end: "2026-10-30", weight: "17.10",
  percent_complete: "71.20", is_critical: true, position: 1, planned_percent_today: 84.8, state: "behind",
  progress_updated_at: null, is_concrete_pour: true, client_milestone: false, milestone_name: null, stopped: false, actual_start: "2026-06-15", actual_finish: null,
};

const PROGRESS: Progress = {
  as_of: "2026-10-09", planned_percent: 27.4, actual_percent: 23.0, variance: -4.4, weight_total: "17.10",
  task_count: 1, programme_start: "2026-03-02", programme_end: "2027-09-30", contract_end: "2027-09-30",
  points: [
    { date: "2026-03-02", planned: 0, actual: 0 },
    { date: "2026-10-09", planned: 27.4, actual: 23.0 },
    { date: "2027-09-30", planned: 100, actual: null },
  ],
};

function scheduleApi(role: Role, extra: Record<string, (url: string, init?: RequestInit) => Response> = {}) {
  return mockApi({
    ...sessionApi(makeMe(role)),
    [`/api/v1/projects/${PID}`]: () => jsonResponse(DETAIL),
    [`/api/v1/projects/${PID}/tasks`]: () => jsonResponse({ tasks: [TASK], weight_total: "17.10" }),
    [`/api/v1/projects/${PID}/progress`]: () => jsonResponse(PROGRESS),
    [`/api/v1/tasks/${TID}`]: () => jsonResponse(TASK),
    "/api/v1/schedule/summary": () =>
      jsonResponse([
        { project: SUMMARY, planned_percent: 27.4, actual_percent: 23.0, variance: -4.4, task_count: 11 },
        { project: { ...SUMMARY, id: "1a1b1c1d-2e2f-4a3b-8c4d-5e6f7a8b9c0d", code: "PRO-1", name: "Peradeniya Road" },
          planned_percent: 34.4, actual_percent: 35.2, variance: 0.8, task_count: 5 },
      ]),
    ...extra,
  });
}

describe("varianceLabel", () => {
  it("describes the gap in words and tone", () => {
    expect(varianceLabel(0.8)).toEqual({ tone: "ok", label: "On plan" });
    expect(varianceLabel(3.25)).toEqual({ tone: "ok", label: "Ahead 3.3 pts" });
    expect(varianceLabel(-4.4)).toEqual({ tone: "warn", label: "Behind 4.4 pts" });
    expect(varianceLabel(-12)).toEqual({ tone: "down", label: "Behind 12.0 pts" });
  });
});

describe("SchedulePage", () => {
  it("lists projects furthest behind first", async () => {
    scheduleApi("project_manager");
    renderRoute("/schedule");

    const list = await screen.findByRole("list", { name: "Projects by schedule variance" });
    const items = await within(list).findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Havelock Residences");
    expect(items[0]).toHaveTextContent("Behind 4.4 pts");
    expect(items[0]).toHaveTextContent("Actual 23.0%");
    expect(items[1]).toHaveTextContent("On plan");
    expect(within(items[0]!).getByRole("link")).toHaveAttribute("href", `/projects/${PID}/schedule`);
  });

  it("is hidden from roles without schedule access", async () => {
    scheduleApi("procurement_officer");
    renderRoute("/schedule");

    expect(await screen.findByRole("heading", { name: "Authorised personnel only." })).toBeInTheDocument();
  });
});

describe("Project schedule", () => {
  it("shows KPIs, an accessible S-curve and the programme", async () => {
    const user = userEvent.setup();
    scheduleApi("quantity_surveyor");
    renderRoute(`/projects/${PID}/schedule`);

    expect(await screen.findByRole("img", { name: /planned 27.4 percent and actual 23.0 percent/ })).toBeInTheDocument();
    expect(screen.getByText("-4.4 pts")).toBeInTheDocument();
    expect(screen.getByText("Behind 4.4 pts")).toBeInTheDocument();
    expect(screen.getByText(/Task weights add up to 17.10%/)).toBeInTheDocument();
    await user.click(screen.getByText("Show the numbers"));
    expect(screen.getByRole("table", { name: /Planned and actual progress by date/ })).toBeVisible();

    const tasks = screen.getByRole("table", { name: "Programme tasks" });
    const row = within(tasks).getByRole("row", { name: /Frame: ground to level 4/ });
    expect(row).toHaveTextContent("Critical");
    expect(row).toHaveTextContent("Behind");
    // QS: read-only.
    expect(within(row).queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add task" })).not.toBeInTheDocument();
  });

  it("lets a site engineer report decimal progress but not edit the plan", async () => {
    const user = userEvent.setup();
    const fetchMock = scheduleApi("site_engineer");
    renderRoute(`/projects/${PID}/schedule`);

    const input = await screen.findByRole("spinbutton", { name: "Percent complete for Frame: ground to level 4" });
    expect(screen.queryByRole("button", { name: "Add task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit Frame/ })).not.toBeInTheDocument();

    await user.clear(input);
    await user.type(input, "72.5{Enter}");

    await waitFor(() => {
      expect(requestTo(fetchMock, `/tasks/${TID}`)?.body).toBe('{"percent_complete":"72.5"}');
    });
  });

  it("lets the project manager add, edit and delete tasks", async () => {
    const user = userEvent.setup();
    const fetchMock = scheduleApi("project_manager", {
      [`/api/v1/projects/${PID}/tasks`]: (_url, init) =>
        init?.method === "POST" ? jsonResponse(TASK, 201) : jsonResponse({ tasks: [TASK], weight_total: "17.10" }),
      [`/api/v1/tasks/${TID}`]: (_url, init) => (init?.method === "DELETE" ? new Response(null, { status: 204 }) : jsonResponse(TASK)),
    });
    renderRoute(`/projects/${PID}/schedule`);

    await user.click(await screen.findByRole("button", { name: "Add task" }));
    const dialog = screen.getByRole("dialog", { name: "Add a task" });
    await user.click(within(dialog).getByRole("button", { name: "Add task" }));
    expect(within(dialog).getByText("Enter the task name.")).toBeInTheDocument();
    expect(within(dialog).getByText("A share between 0.01 and 100 %.")).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText("Task name"), "Piling");
    await user.type(within(dialog).getByLabelText("Planned start"), "2026-02-01");
    await user.type(within(dialog).getByLabelText("Planned end"), "2026-04-30");
    await user.type(within(dialog).getByLabelText("Weight (% of contract)"), "5.5");
    await user.click(within(dialog).getByRole("button", { name: "Add task" }));
    expect(within(dialog).getByText("A task cannot start before the project starts.")).toBeInTheDocument();

    await user.clear(within(dialog).getByLabelText("Planned start"));
    await user.type(within(dialog).getByLabelText("Planned start"), "2026-03-16");
    await user.click(within(dialog).getByRole("button", { name: "Add task" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Add a task" })).not.toBeInTheDocument();
    });
    const post = fetchMock.mock.calls.find(([url, init]) => (url as string).endsWith("/tasks") && init?.method === "POST");
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({
      code: null, name: "Piling", boq_section_id: null, planned_start: "2026-03-16", planned_end: "2026-04-30",
      weight: "5.5", is_concrete_pour: false, client_milestone: false, milestone_name: null,
    });

    await user.click(screen.getByRole("button", { name: "Delete Frame: ground to level 4" }));
    await user.click(screen.getByRole("button", { name: "Yes" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true);
    });
  });
});
