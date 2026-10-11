import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Role } from "../../api/auth";
import type { Issue, ReportAction, ReportIssues } from "../../api/issues";
import type { ProjectDetail } from "../../api/projects";
import type { ReportDetail } from "../../api/reports";
import { siteTodayIso } from "../../lib/time";
import { jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi } from "../../test/utils";

const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };
const PID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const RID = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e";
const ME = "6f0d3c1e-8a7b-4c2d-9e1f-0a1b2c3d4e5f"; // makeMe's id
const I1 = "11111111-1111-4111-8111-111111111111";
const I2 = "22222222-2222-4222-8222-222222222222";
const A1 = "33333333-3333-4333-8333-333333333333";

const REPORT: ReportDetail = {
  id: RID, project_id: PID, project_name: "Havelock Residences", report_date: siteTodayIso(),
  author: { id: ME, full_name: "Kasun Perera" }, weather_summary: "Rain", temp_max_c: null, temp_min_c: null, rain_mm: null,
  weather_source: "manual", crew_count: 40, work_done: "Slab reinforcement.", problems: "Cement not delivered again. Thing with stuff.",
  submitted_at: "2026-10-11T03:10:00+00:00", updated_at: "2026-10-11T03:10:00+00:00", photos: [], progress: [],
  editable: true, photo_limit: 12,
};  // fmt: skip

const issue = (over: Partial<Issue>): Issue => ({
  id: I1, snippet: "Cement not delivered again", category: "material_delay", severity: "high", status: "suggested",
  source: "ai", confidence: 0.91, low_confidence: false, ai_category: "material_delay", ai_severity: "high",
  edited: false, confirmed_at: null, ...over,
});  // fmt: skip

const SUGGESTED: ReportIssues = {
  report_id: RID, confirmed: false, can_confirm: true, model_version: "1.0.0", low_confidence_below: 0.6,
  issues: [issue({}), issue({ id: I2, snippet: "Thing with stuff", category: "other", severity: "low", confidence: 0.41, low_confidence: true, ai_category: "other", ai_severity: "low" })],
  actions: [],
};  // fmt: skip

const action = (over: Partial<ReportAction>): ReportAction => ({
  id: A1, report_id: RID, kind: "material_request", status: "open", summary: "Cement not delivered again",
  created_at: "2026-10-11T03:20:00+00:00", closed_at: null, request_id: null, can_close: true, ...over,
});  // fmt: skip

const CONFIRMED: ReportIssues = {
  ...SUGGESTED, confirmed: true, can_confirm: false,
  issues: [issue({ status: "confirmed" }), issue({ id: I2, snippet: "Thing with stuff", status: "removed" })],
  actions: [action({}), action({ id: "44444444-4444-4444-8444-444444444444", kind: "stop_work", summary: "Helper fell", can_close: false })],
};  // fmt: skip

function reportApi(role: Role, issues: () => Response, extra: Record<string, (url: string, init?: RequestInit) => Response> = {}) {
  return mockApi({
    ...sessionApi(makeMe(role)),
    [`/api/v1/reports/${RID}`]: () => jsonResponse(REPORT),
    [`/api/v1/reports/${RID}/issues`]: issues,
    [`/api/v1/reports/${RID}/analyze`]: () => jsonResponse(SUGGESTED),
    [`/api/v1/reports/${RID}/issues/confirm`]: () => jsonResponse(CONFIRMED),
    ...extra,
  });
}

function body(init: RequestInit | undefined): Record<string, unknown> {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON request body");
  return JSON.parse(init.body) as Record<string, unknown>;
}

describe("AI check on a daily report", () => {
  it("reads the problems once after filing and lets the author edit, remove, add and confirm", async () => {
    const user = userEvent.setup();
    const empty = { ...SUGGESTED, issues: [] };
    const fetchMock = reportApi("site_engineer", () => jsonResponse(empty));
    renderRoute(`/reports/${RID}`);

    const list = await screen.findByRole("list", { name: "Suggested tags" });
    expect(requestTo(fetchMock, `/reports/${RID}/analyze`)?.method).toBe("POST");
    expect(fetchMock.mock.calls.filter(([input]) => (input instanceof Request ? input.url : input.toString()).endsWith("/analyze"))).toHaveLength(1);
    const [cement, unclear] = within(list).getAllByRole("listitem");
    expect(cement).toHaveTextContent("91% sure");
    expect(unclear).toHaveTextContent("Check this: the model is unsure (41%)");

    // Follow-ups are only possible when a kept tag justifies them.
    const stopWork = screen.getByRole("checkbox", { name: /Flag stop-work/ });
    expect(stopWork).toBeDisabled();
    expect(screen.getByText("Needs a safety issue among the kept tags.")).toBeInTheDocument();

    await user.selectOptions(within(cement!).getByRole("combobox", { name: /Severity for/ }), "medium");
    await user.click(within(unclear!).getByRole("checkbox", { name: /Keep the tag/ }));
    const form = screen.getByRole("form", { name: "Add a tag" });
    await user.click(within(form).getByRole("button", { name: "Add" }));
    expect(within(form).getByText("Write a few words about the issue you are adding.")).toBeInTheDocument();
    await user.type(within(form).getByRole("textbox"), "A helper slipped on the stairs");
    await user.selectOptions(within(form).getByRole("combobox", { name: "Category for the new tag" }), "safety");
    await user.selectOptions(within(form).getByRole("combobox", { name: "Severity for the new tag" }), "high");
    await user.click(within(form).getByRole("button", { name: "Add" }));
    expect(stopWork).toBeEnabled();
    await user.click(stopWork);
    await user.click(screen.getByRole("checkbox", { name: /Draft a material request/ }));
    await user.click(screen.getByRole("button", { name: "Confirm 2 tags" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/reports/${RID}/issues/confirm`))).toEqual({
        issues: [
          { suggestion_id: I1, category: "material_delay", severity: "medium" },
          { category: "safety", severity: "high", snippet: "A helper slipped on the stairs" },
        ],
        actions: { material_request: true, pm_alert: false, stop_work: true },
      });
    });
    expect(await screen.findByRole("list", { name: "Confirmed issues" })).toHaveTextContent("Material delay");
  });

  it("does not send a follow-up whose tag was removed", async () => {
    const user = userEvent.setup();
    const fetchMock = reportApi("site_engineer", () => jsonResponse(SUGGESTED));
    renderRoute(`/reports/${RID}`);

    const material = await screen.findByRole("checkbox", { name: /Draft a material request/ });
    await user.click(material);
    const [cement] = within(screen.getByRole("list", { name: "Suggested tags" })).getAllByRole("listitem");
    await user.click(within(cement!).getByRole("checkbox", { name: /Keep the tag/ }));
    expect(material).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Confirm 1 tag" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/reports/${RID}/issues/confirm`)).actions).toEqual({ material_request: false, pm_alert: false, stop_work: false });
    });
    expect(requestTo(fetchMock, `/reports/${RID}/analyze`)).toBeUndefined(); // suggestions already there
  });

  it("shows the confirmed tags and follow-ups to readers", async () => {
    reportApi("project_manager", () => jsonResponse({ ...CONFIRMED, actions: [CONFIRMED.actions[0]!, { ...CONFIRMED.actions[1]!, can_close: true }] }));
    renderRoute(`/reports/${RID}`);

    const confirmed = await screen.findByRole("list", { name: "Confirmed issues" });
    expect(confirmed).toHaveTextContent("High severity");
    expect(screen.getByText("1 suggestion was removed by the author.")).toBeInTheDocument();
    const raise = screen.getByRole("link", { name: "Raise the request" });
    expect(raise.getAttribute("href")).toBe(`/materials/new?project=${PID}&action=${A1}&notes=Cement+not+delivered+again`);
    expect(screen.getByText(/Stop-work flagged: waiting for the project manager/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear stop-work" })).toBeInTheDocument();
  });

  it("tells other readers when the author has not confirmed yet", async () => {
    const fetchMock = reportApi("quantity_surveyor", () => jsonResponse({ ...SUGGESTED, can_confirm: false }));
    renderRoute(`/reports/${RID}`);

    expect(await screen.findByText("Waiting for the report's author to confirm 2 suggested tags.")).toBeInTheDocument();
    expect(requestTo(fetchMock, `/reports/${RID}/analyze`)).toBeUndefined();
  });

  it("dismisses a material follow-up", async () => {
    const user = userEvent.setup();
    const fetchMock = reportApi("site_engineer", () => jsonResponse({ ...CONFIRMED, actions: [CONFIRMED.actions[0]!] }), {
      [`/api/v1/report-actions/${A1}/close`]: () => jsonResponse({ ...CONFIRMED.actions[0]!, status: "dismissed", can_close: false }),
    });
    renderRoute(`/reports/${RID}`);

    await user.click(await screen.findByRole("button", { name: "Dismiss" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/report-actions/${A1}/close`))).toEqual({ resolution: "dismissed" });
    });
  });
});

describe("Follow-ups elsewhere", () => {
  it("raises a material request from a report's follow-up", async () => {
    mockApi({
      ...sessionApi(makeMe("site_engineer")),
      "/api/v1/projects": () => jsonResponse([]),
    });
    renderRoute(`/materials/new?project=${PID}&action=${A1}&notes=Cement+not+delivered+again`);

    expect(await screen.findByText(/Raising the material request from a daily report/)).toBeInTheDocument();
    expect(screen.getByLabelText("Notes (optional)")).toHaveValue("Cement not delivered again");
  });

  it("shows open stop-work flags on the project and lets the project manager clear them", async () => {
    const user = userEvent.setup();
    const project: ProjectDetail = {
      id: PID, code: "HR-2026-01", name: "Havelock Residences", site: SITE, client_name: "Client", project_type: "residential",
      status: "active", contract_value: "1000.00", start_date: "2026-03-02", planned_end: "2027-09-30", boq_total: "0.00",
      budget_total: "0.00", item_count: 0, description: null, planned_crew: null, sections: [], team: [],
      created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
    };  // fmt: skip
    const flag = action({ kind: "stop_work", summary: "Helper fell from the scaffold" });
    const fetchMock = mockApi({
      ...sessionApi(makeMe("project_manager")),
      [`/api/v1/projects/${PID}`]: () => jsonResponse(project),
      [`/api/v1/projects/${PID}/report-actions`]: () => jsonResponse([flag]),
      [`/api/v1/projects/${PID}/risk`]: () => jsonResponse({ project_id: PID, latest: null, history: [] }),
      [`/api/v1/report-actions/${A1}/close`]: () => jsonResponse({ ...flag, status: "done", can_close: false }),
    });
    renderRoute(`/projects/${PID}`);

    const banner = (await screen.findByText("Stop-work flagged")).closest("[role]")!;
    expect(banner).toHaveTextContent("Helper fell from the scaffold");
    expect(within(banner as HTMLElement).getByRole("link", { name: "See the report" })).toHaveAttribute("href", `/reports/${RID}`);
    await user.click(within(banner as HTMLElement).getByRole("button", { name: "Clear stop-work" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/report-actions/${A1}/close`))).toEqual({ resolution: "done" });
    });
  });

  it("tells others that only the project manager can clear stop-work", async () => {
    const project = { id: PID, code: "HR", name: "Havelock", site: SITE, client_name: "C", project_type: "residential", status: "active",
      start_date: "2026-03-02", planned_end: "2027-09-30", item_count: 0, description: null, planned_crew: null, sections: [], team: [],
      created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00" };  // fmt: skip
    mockApi({
      ...sessionApi(makeMe("site_engineer")),
      [`/api/v1/projects/${PID}`]: () => jsonResponse(project),
      [`/api/v1/projects/${PID}/report-actions`]: () => jsonResponse([action({ kind: "stop_work", can_close: false }), action({ id: I2 })]),
    });
    renderRoute(`/projects/${PID}`);

    expect(await screen.findByText("Only the project manager can clear it.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear stop-work" })).not.toBeInTheDocument();
  });
});
