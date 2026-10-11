import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Role } from "../api/auth";
import type { Claim, ClaimsOverview, ClientVariation, Variation, VariationList } from "../api/contract";
import type { ProjectDetail } from "../api/projects";
import { siteTodayIso } from "../lib/time";
import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi } from "../test/utils";

const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };
const PID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const SA = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d";
const SB = "b1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5e";
const C1 = "c1c1c1c1-1111-4111-8111-111111111111";
const V1 = "d1d1d1d1-1111-4111-8111-111111111111";
const TASK = "e1e1e1e1-1111-4111-8111-111111111111";

const PROJECT: ProjectDetail = {
  id: PID, code: "HR-2026-01", name: "Havelock Residences", site: SITE, client_name: "Havelock Developers",
  project_type: "residential", status: "active", contract_value: "10000000.00", start_date: "2026-03-02",
  planned_end: "2027-09-30", boq_total: "10000000.00", budget_total: "8000000.00", item_count: 2,
  description: null, planned_crew: null, team: [], created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
  sections: [
    { id: SA, code: "A", name: "Substructure", item_count: 1, amount: "4000000.00", budget_line_id: SA, budget_amount: "3200000.00" },
    { id: SB, code: "B", name: "Superstructure", item_count: 1, amount: "6000000.00", budget_line_id: SB, budget_amount: "4800000.00" },
  ],
};  // fmt: skip

const FIGURES = {
  contract_value: "10000000.00", certified_pct: "40.00", certified_value: "4000000.00", retention: "200000.00",
  retention_rate: "0.05", previous_claims: "0.00", amount: "3800000.00",
};  // fmt: skip

const claim = (over: Partial<Claim>): Claim => ({
  id: C1, number: "PC-0001", project_id: PID, status: "submitted", figures: FIGURES, notes: null,
  submitted_by: "Shalini QS", submitted_at: "2026-10-11T04:00:00+00:00", decided_by: null, decided_at: null,
  decision_comment: null, paid_on: null, actions: [],
  lines: [
    { section_id: SA, code: "A", name: "Substructure", section_value: "4000000.00", previous_pct: "0.00", certified_pct: "70.00" },
    { section_id: SB, code: "B", name: "Superstructure", section_value: "6000000.00", previous_pct: "0.00", certified_pct: "20.00" },
  ],
  ...over,
});  // fmt: skip

const overview = (over: Partial<ClaimsOverview>): ClaimsOverview => ({
  claims: [], claimed_to_date: "0.00", retention_held: "0.00", paid_to_date: "0.00", can_create: true,
  sections: [
    { section_id: SA, code: "A", name: "Substructure", section_value: "4000000.00", previous_pct: "30.00" },
    { section_id: SB, code: "B", name: "Superstructure", section_value: "6000000.00", previous_pct: "10.00" },
  ],
  ...over,
});  // fmt: skip

const variation = (over: Partial<Variation>): Variation => ({
  id: V1, number: "VO-0001", project_id: PID, project_code: "HR-2026-01", title: "Extra waterproofing",
  description: "Second membrane layer.", section_id: SA, section: "A Substructure", boq_item_id: null, boq_item: null,
  quantity_change: null, task_id: null, task: null, time_impact_days: 0, contract_change: null, budget_change: null,
  status: "awaiting_pricing", approver: null, limit: "100000.00", limit_applied: null, needs_client: null,
  raised_by: "Ruwan PM", raised_by_role: "pm", raised_at: "2026-10-11T04:00:00+00:00", priced_by: null, decided_at: null,
  events: [{ action: "raised", actor: "Ruwan PM", from_status: null, to_status: "awaiting_pricing", comment: null, at: "2026-10-11T04:00:00+00:00" }],
  actions: [],
  ...over,
});  // fmt: skip

const LIST: VariationList = {
  variations: [variation({ status: "approved", contract_change: "850000.00", budget_change: "680000.00", approver: "pm" })],
  limit: "100000.00",
  approved_contract_change: "850000.00",
  approved_time_impact_days: 0,
};

const clientVariation = (over: Partial<ClientVariation>): ClientVariation => ({
  id: V1, number: "VO-0002", project_id: PID, project_code: "HR-2026-01", project_name: "Havelock Residences",
  title: "Roof plant room", description: "A plant room on the roof.", contract_change: "4200000.00", time_impact_days: 10,
  status: "awaiting_client", limit: "100000.00", reason_for_client: "It changes the completion date by 10 days.",
  raised_at: "2026-10-11T04:00:00+00:00", can_decide: true,
  events: [{ action: "priced", actor: "Contractor", from_status: "awaiting_pricing", to_status: "awaiting_client", comment: null, at: "2026-10-11T04:05:00+00:00" }],
  ...over,
});  // fmt: skip

function urlOf(input: RequestInfo | URL): string {
  return input instanceof Request ? input.url : input instanceof URL ? input.href : input;
}

function body(init: RequestInit | undefined): Record<string, unknown> {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON request body");
  return JSON.parse(init.body) as Record<string, unknown>;
}

function projectApi(role: Role, extra: Record<string, (url: string, init?: RequestInit) => Response>) {
  return mockApi({
    ...sessionApi(makeMe(role)),
    [`/api/v1/projects/${PID}`]: () => jsonResponse(PROJECT),
    ...extra,
  });
}

describe("Cost & claims overview", () => {
  it("lists what waits for the PM and each project's forecast", async () => {
    mockApi({
      ...sessionApi(makeMe("project_manager")),
      "/api/v1/cost/overview": () =>
        jsonResponse({
          waiting_for_you: [
            { kind: "claim", id: C1, number: "PC-0002", project_id: PID, project_code: "HR-2026-01", title: "Claim of LKR 74,834,894.06", status: "submitted", since: "2026-10-11T04:00:00+00:00" },
            { kind: "variation", id: V1, number: "VO-0003", project_id: PID, project_code: "HR-2026-01", title: "Granite lobby", status: "awaiting_pm", since: "2026-10-11T05:00:00+00:00" },
          ],
          projects: [
            { project_id: PID, code: "HR-2026-01", name: "Havelock Residences", status: "active", contract_value: "1119050000.00",
              approved_variations: "5050000.00", budget: "982000000.00", committed: "28000000.00", forecast_final: "987790000.00",
              variance: "-5790000.00", variance_pct: "-0.6", sections_over: 1, claimed_to_date: "175000000.00", open_claim: "PC-0002", variations_open: 2 },
            { project_id: SA, code: "FVA-2026-03", name: "Fort View", status: "planning", contract_value: "742500000.00",
              approved_variations: "0.00", budget: "0.00", committed: "0.00", forecast_final: "0.00", variance: "0.00",
              variance_pct: null, sections_over: 0, claimed_to_date: "0.00", open_claim: null, variations_open: 0 },
          ],
        }),
    });  // fmt: skip
    renderRoute("/cost");

    const waiting = await screen.findByRole("link", { name: /PC-0002/ });
    expect(waiting).toHaveAttribute("href", `/projects/${PID}/claims`);
    expect(waiting).toHaveTextContent("Claim to approve");
    expect(screen.getByRole("link", { name: /VO-0003/ })).toHaveTextContent("Waiting for the PM");
    const table = screen.getByRole("table", { name: /forecast final cost/ });
    expect(table).toHaveTextContent("LKR 5.79 M over");
    expect(table).toHaveTextContent("1 section forecast more than 5% over");
    expect(table).toHaveTextContent("No BOQ budget yet");
  });

  it("is not in the menu for site engineers", async () => {
    mockApi({ ...sessionApi(makeMe("site_engineer")), "/api/v1/reports/today": () => jsonResponse({ date: siteTodayIso(), deadline: "2026-10-11T18:00:00+05:30", deadline_passed: false, projects: [] }) });
    renderRoute("/");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).queryByText("Cost & claims")).not.toBeInTheDocument();
  });
});

describe("Progress claims (BR-08)", () => {
  it("lets the QS certify progress, see the calculation and submit", async () => {
    const user = userEvent.setup();
    const fetchMock = projectApi("quantity_surveyor", {
      [`/api/v1/projects/${PID}/claims`]: (_url, init) =>
        init?.method === "POST" ? jsonResponse(claim({}), 201) : jsonResponse(overview({})),
      [`/api/v1/projects/${PID}/claims/check`]: () => jsonResponse({ figures: FIGURES, problems: [] }),
    });
    renderRoute(`/projects/${PID}/claims`);

    await user.click(await screen.findByRole("button", { name: "New claim" }));
    const a = screen.getByRole("textbox", { name: "Certified % for A Substructure" });
    expect(a).toHaveValue("30.00"); // starts at the last approved figure
    await user.clear(a);
    await user.type(a, "70");
    const sheet = await screen.findByRole("table", { name: "The claim as it will be submitted" });
    expect(sheet).toHaveTextContent("LKR 3,800,000.00");
    expect(sheet).toHaveTextContent("Less retention (5%)");
    await user.click(screen.getByRole("button", { name: "Submit to the PM" }));

    const posted = await waitFor(() => {
      const call = fetchMock.mock.calls.find(([input, init]) => urlOf(input).endsWith(`/projects/${PID}/claims`) && init?.method === "POST");
      expect(call).toBeDefined();
      return call;
    });
    expect(body(posted?.[1])).toEqual({
      sections: [
        { section_id: SA, certified_pct: "70" },
        { section_id: SB, certified_pct: "10.00" },
      ],
      notes: null,
    });
  });

  it("will not submit a claim that BR-08 refuses, or an impossible percentage", async () => {
    const user = userEvent.setup();
    projectApi("quantity_surveyor", {
      [`/api/v1/projects/${PID}/claims`]: () => jsonResponse(overview({})),
      [`/api/v1/projects/${PID}/claims/check`]: () =>
        jsonResponse({
          figures: { ...FIGURES, amount: "0.00" },
          problems: [{ rule: "BR-08", severity: "block", message: "Nothing to claim: certified progress less retention does not exceed the previous claims.", facts: {} }],
        }),
    });
    renderRoute(`/projects/${PID}/claims`);

    await user.click(await screen.findByRole("button", { name: "New claim" }));
    expect(await screen.findByText(/Nothing to claim/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit to the PM" })).toBeDisabled();
    const a = screen.getByRole("textbox", { name: "Certified % for A Substructure" });
    await user.clear(a);
    await user.type(a, "120");
    expect(screen.getByText("Each section needs a percentage from 0 to 100, up to two decimals.")).toBeInTheDocument();
    expect(a).toHaveAttribute("aria-invalid", "true");
  });

  it("lets the PM approve, or return with a comment", async () => {
    const user = userEvent.setup();
    const fetchMock = projectApi("project_manager", {
      [`/api/v1/projects/${PID}/claims`]: () =>
        jsonResponse(overview({ can_create: false, claims: [claim({ actions: ["approve", "return"] })] })),
      [`/api/v1/claims/${C1}/decision`]: () => jsonResponse(claim({ status: "returned" })),
    });
    renderRoute(`/projects/${PID}/claims`);

    const card = await screen.findByRole("article", { name: /PC-0001/ });
    expect(within(card).getByRole("table", { name: "Calculation of PC-0001" })).toHaveTextContent("LKR 3,800,000.00");
    await user.click(within(card).getByRole("button", { name: "Return…" }));
    const send = within(card).getByRole("button", { name: "Return to the QS" });
    expect(send).toBeDisabled();
    await user.type(within(card).getByRole("textbox", { name: "What should the QS change?" }), "Use 35% for B");
    await user.click(send);

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/claims/${C1}/decision`))).toEqual({ decision: "return", comment: "Use 35% for B" });
    });
  });

  it("lets the QS record a payment on an approved claim", async () => {
    const user = userEvent.setup();
    const fetchMock = projectApi("quantity_surveyor", {
      [`/api/v1/projects/${PID}/claims`]: () =>
        jsonResponse(
          overview({
            can_create: true,
            claimed_to_date: "3800000.00",
            retention_held: "200000.00",
            claims: [claim({ status: "approved", decided_by: "Ruwan PM", decided_at: "2026-10-11T05:00:00+00:00", actions: ["record_payment"] })],
          }),
        ),
      [`/api/v1/claims/${C1}/payment`]: () => jsonResponse(claim({ status: "paid", paid_on: siteTodayIso() })),
    });
    renderRoute(`/projects/${PID}/claims`);

    expect(await screen.findByRole("group", { name: "Retention held" })).toHaveTextContent("LKR 200 k");
    await user.click(screen.getByRole("button", { name: "Record payment…" }));
    await user.click(screen.getByRole("button", { name: "Record payment" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/claims/${C1}/payment`))).toEqual({ paid_on: siteTodayIso() });
    });
  });
});

describe("Variation orders (BR-09)", () => {
  function variationApi(role: Role, detail: Variation, extra: Record<string, (url: string, init?: RequestInit) => Response> = {}) {
    return projectApi(role, {
      [`/api/v1/projects/${PID}/variations`]: (_url, init) =>
        init?.method === "POST" ? jsonResponse(detail, 201) : jsonResponse(LIST),
      [`/api/v1/variations/${V1}`]: () => jsonResponse(detail),
      [`/api/v1/projects/${PID}/boq`]: () =>
        jsonResponse({
          project_id: PID, item_count: 1, boq_total: "10000000.00", budget_total: "8000000.00",
          sections: [{ ...PROJECT.sections[0]!, items: [{ id: SB, item_code: "A.1", description: "Concrete", unit: "m3", quantity: "100.000", requested_quantity: "0.000", remaining_quantity: "100.000" }] }],
        }),
      [`/api/v1/projects/${PID}/tasks`]: () =>
        jsonResponse({
          weight_total: "100.00",
          tasks: [{ id: TASK, project_id: PID, code: "T1", name: "Basement slab", boq_section_id: SA, boq_section_code: "A",
                    planned_start: "2026-09-01", planned_end: "2026-11-30", weight: "100.00", percent_complete: "40.00",
                    is_critical: false, position: 1, planned_percent_today: 50, state: "behind", progress_updated_at: null,
                    is_concrete_pour: false, stopped: false, actual_start: "2026-09-01", actual_finish: null }],
        }),
      ...extra,
    });  // fmt: skip
  }

  it("shows the list and lets the QS raise a priced variation with a time impact", async () => {
    const user = userEvent.setup();
    const fetchMock = variationApi("quantity_surveyor", variation({ raised_by_role: "qs" }));
    renderRoute(`/projects/${PID}/variations`);

    expect(await screen.findByRole("group", { name: "Client approval limit" })).toHaveTextContent("LKR 100 k");
    expect(screen.getByRole("group", { name: "Approved changes" })).toHaveTextContent("+ LKR 850 k");
    await user.click(screen.getByRole("button", { name: "Raise a variation" }));
    const dialog = await screen.findByRole("dialog", { name: "Raise a variation" });
    await user.type(within(dialog).getByRole("textbox", { name: "Title" }), "Deeper footings");
    await user.type(within(dialog).getByRole("textbox", { name: "What changes, and why" }), "Soft ground at grid C.");
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "BOQ section" }), SA);
    await user.selectOptions(within(dialog).getByRole("combobox", { name: /Extra quantity on an item/ }), SB);
    await user.type(within(dialog).getByRole("textbox", { name: "Extra quantity" }), "12.5");
    const days = within(dialog).getByRole("textbox", { name: /Time impact/ });
    await user.clear(days);
    await user.type(days, "7");
    expect(within(dialog).getByRole("button", { name: "Raise variation" })).toBeDisabled(); // needs the task
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Task it delays" }), TASK);
    await user.type(within(dialog).getByRole("textbox", { name: /Contract change/ }), "45000");
    await user.type(within(dialog).getByRole("textbox", { name: /Cost budget change/ }), "36000");
    expect(within(dialog).getByText("This one will go to the client.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Raise variation" }));

    await waitFor(() => {
      const posted = fetchMock.mock.calls.find(([input, init]) => urlOf(input).endsWith(`/projects/${PID}/variations`) && init?.method === "POST");
      expect(body(posted?.[1])).toEqual({
        title: "Deeper footings", description: "Soft ground at grid C.", section_id: SA, boq_item_id: SB, quantity_change: "12.5",
        task_id: TASK, time_impact_days: 7, contract_change: "45000", budget_change: "36000", comment: null,
      });
    });  // fmt: skip
    expect(await screen.findByRole("heading", { name: "Extra waterproofing" })).toBeInTheDocument();
  });

  it("lets a PM describe a change without pricing it", async () => {
    const user = userEvent.setup();
    const fetchMock = variationApi("project_manager", variation({}));
    renderRoute(`/projects/${PID}/variations`);

    await user.click(await screen.findByRole("button", { name: "Raise a variation" }));
    const dialog = await screen.findByRole("dialog", { name: "Raise a variation" });
    expect(within(dialog).queryByRole("textbox", { name: /Contract change/ })).not.toBeInTheDocument();
    expect(within(dialog).getByText(/The quantity surveyor prices it next/)).toBeInTheDocument();
    await user.type(within(dialog).getByRole("textbox", { name: "Title" }), "Granite lobby");
    await user.type(within(dialog).getByRole("textbox", { name: "What changes, and why" }), "Upgrade the finish.");
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "BOQ section" }), SA);
    await user.click(within(dialog).getByRole("button", { name: "Raise variation" }));

    await waitFor(() => {
      const posted = fetchMock.mock.calls.find(([input, init]) => urlOf(input).endsWith(`/projects/${PID}/variations`) && init?.method === "POST");
      expect(body(posted?.[1])).not.toHaveProperty("contract_change");
    });
  });

  it("lets the QS price a variation, and explains where it goes", async () => {
    const user = userEvent.setup();
    const fetchMock = variationApi("quantity_surveyor", variation({ actions: ["price"] }), {
      [`/api/v1/variations/${V1}/price`]: () =>
        jsonResponse(variation({ status: "awaiting_client", approver: "client", contract_change: "2350000.00", budget_change: "1900000.00", limit_applied: "100000.00", needs_client: true })),
    });
    renderRoute(`/variations/${V1}`);

    expect(await screen.findByText("The quantity surveyor prices it next.")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: /Contract change/ }), "2350000");
    await user.clear(screen.getByRole("textbox", { name: /Cost budget change/ }));
    await user.type(screen.getByRole("textbox", { name: /Cost budget change/ }), "1900000");
    await user.click(screen.getByRole("button", { name: "Price and send on" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/variations/${V1}/price`))).toEqual({ contract_change: "2350000", budget_change: "1900000", comment: null });
    });
  });

  it("lets the PM approve or query a variation routed to them", async () => {
    const user = userEvent.setup();
    const routed = variation({ status: "awaiting_pm", approver: "pm", raised_by_role: "qs", contract_change: "90000.00", budget_change: "72000.00", limit_applied: "100000.00", needs_client: false, actions: ["approve", "query", "reject"] });
    const fetchMock = variationApi("project_manager", routed, {
      [`/api/v1/variations/${V1}/decision`]: () => jsonResponse({ ...routed, status: "queried", actions: [] }),
    });
    renderRoute(`/variations/${V1}`);

    expect(await screen.findByText(/A project manager approves it: within the limit/)).toBeInTheDocument();
    expect(screen.getByText("+ LKR 90,000.00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Query…" }));
    await user.type(screen.getByRole("textbox", { name: /Your question/ }), "Which drawing?");
    await user.click(screen.getByRole("button", { name: "Send query" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/variations/${V1}/decision`))).toEqual({ decision: "query", comment: "Which drawing?" });
    });
  });

  it("shows an error when a step is refused", async () => {
    const user = userEvent.setup();
    variationApi("project_manager", variation({ actions: ["withdraw"] }), {
      [`/api/v1/variations/${V1}/withdraw`]: () => errorResponse(409, "conflict", "This variation is already closed."),
    });
    renderRoute(`/variations/${V1}`);

    await user.click(await screen.findByRole("button", { name: "Withdraw" }));
    expect(await screen.findByText("This variation is already closed.")).toBeInTheDocument();
  });
});

describe("The client's variations", () => {
  it("lists what was sent and lets the client approve, without internal costs", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      ...sessionApi(makeMe("client")),
      "/api/v1/client/variations": () => jsonResponse([clientVariation({})]),
      [`/api/v1/client/variations/${V1}`]: () => jsonResponse(clientVariation({})),
      [`/api/v1/variations/${V1}/client-decision`]: () => jsonResponse(clientVariation({ status: "approved", can_decide: false })),
    });
    renderRoute("/client/variations");

    await user.click(await screen.findByRole("link", { name: "Roof plant room" }));
    expect(await screen.findByText(/It changes the completion date by 10 days/)).toBeInTheDocument();
    expect(screen.getByText(/Changes above LKR 100,000.00/)).toBeInTheDocument();
    expect(screen.queryByText(/budget/i)).not.toBeInTheDocument();
    expect(screen.getByText("Sent to you for approval")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve this variation" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/variations/${V1}/client-decision`))).toEqual({ decision: "approve" });
    });
  });

  it("lets the client ask a question instead", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      ...sessionApi(makeMe("client")),
      [`/api/v1/client/variations/${V1}`]: () => jsonResponse(clientVariation({})),
      [`/api/v1/variations/${V1}/client-decision`]: () => jsonResponse(clientVariation({ status: "queried", can_decide: false })),
    });
    renderRoute(`/client/variations/${V1}`);

    await user.click(await screen.findByRole("button", { name: "Ask a question…" }));
    await user.type(screen.getByRole("textbox", { name: "Your question for the contractor" }), "Why 10 days?");
    await user.click(screen.getByRole("button", { name: "Send question" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/variations/${V1}/client-decision`))).toEqual({ decision: "query", comment: "Why 10 days?" });
    });
  });

  it("answers an unknown variation with the not-found page", async () => {
    mockApi({
      ...sessionApi(makeMe("client")),
      [`/api/v1/client/variations/${V1}`]: () => errorResponse(404, "not_found", "Variation not found."),
    });
    renderRoute(`/client/variations/${V1}`);

    expect(await screen.findByRole("heading", { name: "Off the drawings." })).toBeInTheDocument();
  });
});

describe("Variation limits (Company Admin)", () => {
  it("changes a limit with a reason", async () => {
    const user = userEvent.setup();
    const row = { project_id: PID, code: "HR-2026-01", name: "Havelock Residences", site_code: "COL-07", status: "active", variation_limit: "11140000.00" };
    const fetchMock = mockApi({
      ...sessionApi(makeMe("admin")),
      "/api/v1/admin/variation-limits": () => jsonResponse([row]),
      [`/api/v1/admin/projects/${PID}/variation-limit`]: () => jsonResponse({ ...row, variation_limit: "15000000.00" }),
    });
    renderRoute("/admin/variation-limits");

    expect(await screen.findByRole("table", { name: /Variation limit by project/ })).toHaveTextContent("11,140,000.00");
    await user.click(screen.getByRole("button", { name: /Change the limit for HR-2026-01/ }));
    const dialog = await screen.findByRole("dialog", { name: "Variation limit for HR-2026-01" });
    const limit = within(dialog).getByRole("textbox", { name: "Limit, LKR" });
    await user.clear(limit);
    await user.type(limit, "15,000,000");
    expect(within(dialog).getByRole("button", { name: "Save limit" })).toBeDisabled(); // needs a reason
    await user.type(within(dialog).getByRole("textbox", { name: /Reason/ }), "Clause 13.4");
    await user.click(within(dialog).getByRole("button", { name: "Save limit" }));

    await waitFor(() => {
      expect(body(requestTo(fetchMock, `/admin/projects/${PID}/variation-limit`))).toEqual({ variation_limit: "15000000", reason: "Clause 13.4" });
    });
  });
});

describe("Contract fields after the project starts", () => {
  it("are read-only in the edit dialog and say how they change", async () => {
    const user = userEvent.setup();
    mockApi({
      ...sessionApi(makeMe("project_manager")),
      [`/api/v1/projects/${PID}`]: () => jsonResponse({ ...PROJECT, contract_locked: true }),
      "/api/v1/sites": () => jsonResponse([SITE]),
    });
    renderRoute(`/projects/${PID}`);

    await user.click(await screen.findByRole("button", { name: "Edit project" }));
    const dialog = await screen.findByRole("dialog");
    const value = within(dialog).getByRole("textbox", { name: "Contract value (LKR)" });
    expect(value).toHaveAttribute("readonly");
    expect(within(dialog).getByText("Changes through approved variations now that the project is under way.")).toBeInTheDocument();
    expect(within(dialog).getByText("Moves with approved variations' time impact.")).toBeInTheDocument();
  });
});
