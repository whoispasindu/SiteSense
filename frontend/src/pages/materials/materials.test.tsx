import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Role } from "../../api/auth";
import type { PoDetail, RequestDetail, RequestSummary, RuleCheck, Supplier } from "../../api/materials";
import type { ProjectDetail, ProjectSummary } from "../../api/projects";
import { addDaysIso, siteTodayIso } from "../../lib/time";
import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi } from "../../test/utils";

const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };
const PID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const RID = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e";
const RID2 = "3c4d5e6f-7a8b-4c9d-8e0f-2a3b4c5d6e7f";
const ITEM = "4d5e6f7a-8b9c-4d0e-9f1a-3b4c5d6e7f8a";
const POID = "5e6f7a8b-9c0d-4e1f-8a2b-4c5d6e7f8a9b";
const SUP = "6f7a8b9c-0d1e-4f2a-9b3c-5d6e7f8a9b0c";
const ME = "6f0d3c1e-8a7b-4c2d-9e1f-0a1b2c3d4e5f"; // makeMe's id
const TODAY = siteTodayIso();

const PROJECT: ProjectSummary = {
  id: PID, code: "HR-2026-01", name: "Havelock Residences", site: SITE, client_name: "Havelock Developers",
  project_type: "residential", status: "active", contract_value: "1114000000.00", start_date: "2026-03-02",
  planned_end: "2027-09-30", boq_total: "5500000.00", budget_total: "4400000.00", item_count: 2,
};

const CHECK: RuleCheck = {
  approval_level: "qs", blocked: false, budget_rate: "2000.00", amount: "200000.00", routed_by: [],
  results: [
    { rule: "BR-02", severity: "pass", message: "100 of 1,000 requested so far for this item, including this one.", facts: {} },
    { rule: "BR-01", severity: "pass", message: "At or below the budgeted rate.", facts: {} },
    { rule: "BR-13", severity: "pass", message: "The section stays within its budget line.", facts: {} },
  ],
};

const SUMMARY: RequestSummary = {
  id: RID, number: "MR-0001", project: { id: PID, code: "HR-2026-01", name: "Havelock Residences", site_code: "COL-07" },
  boq_item: { id: ITEM, item_code: "A.1", description: "Cement, 50 kg bags", unit: "bag", section_code: "A" },
  quantity: "100.000", unit_price: "2000.00", amount: "200000.00", needed_by: addDaysIso(TODAY, 14), status: "requested",
  approval_level: "qs", requested_by: { id: "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d", full_name: "Kasun Perera" },
  submitted_at: "2026-10-10T03:00:00+00:00", updated_at: "2026-10-10T03:00:00+00:00",
};

const DETAIL: RequestDetail = {
  ...SUMMARY, notes: "For the level 4 slab.", boq_quantity: "1000.000", rules: CHECK, order: null,
  history: [{ action: "submit", from_status: null, to_status: "requested", comment: null, actor: SUMMARY.requested_by,
              created_at: "2026-10-10T03:00:00+00:00" }],
  actions: ["approve", "reject", "request_change"],
};

const SUPPLIER: Supplier = {
  id: SUP, name: "Kelani Building Supplies", contact_name: "Nimal", phone: "+94 11 234 5678", email: null,
  categories: "cement", is_active: true,
};

const PO: PoDetail = {
  id: POID, number: "PO-0001", project: SUMMARY.project, supplier: SUPPLIER, status: "issued", total: "195000.00",
  issued_at: "2026-10-10T04:00:00+00:00", expected_delivery: addDaysIso(TODAY, 7),
  issued_by: { id: ME, full_name: "Fathima Procurement" }, notes: null, deliveries: [],
  lines: [{ id: "7a8b9c0d-1e2f-4a3b-8c4d-6e7f8a9b0c1d", request_id: RID, request_number: "MR-0001", item_code: "A.1",
            description: "Cement, 50 kg bags", unit: "bag", quantity: "100.000", unit_price: "1950.00",
            amount: "195000.00", delivered_quantity: "40.000" }],
};

type Handler = (url: string, init?: RequestInit) => Response;

function materialsApi(role: Role, extra: Record<string, Handler> = {}) {
  return mockApi({
    ...sessionApi(makeMe(role)),
    "/api/v1/notifications": () => jsonResponse({ items: [], unread: 0 }),
    "/api/v1/projects": () => jsonResponse([PROJECT]),
    "/api/v1/material-requests": (_url, init) =>
      init?.method === "POST"
        ? jsonResponse(DETAIL, 201)
        : jsonResponse({
            items: [SUMMARY, { ...SUMMARY, id: RID2, number: "MR-0002", status: "approved" }],
            total: 2,
            counts: { requested: 1, pm_approval: 0, approved: 1, ordered: 0, delivered: 0, change_requested: 0, rejected: 0, cancelled: 0 },
          }),
    "/api/v1/material-requests/check": () => jsonResponse(CHECK),
    [`/api/v1/material-requests/${RID}`]: () => jsonResponse(DETAIL),
    [`/api/v1/material-requests/${RID}/decision`]: () => jsonResponse({ ...DETAIL, status: "approved", actions: [] }),
    [`/api/v1/projects/${PID}/boq-items`]: () =>
      jsonResponse([
        { id: ITEM, item_code: "A.1", description: "Cement, 50 kg bags", unit: "bag", section_code: "A", section_name: "Materials",
          boq_quantity: "1000.000", requested_quantity: "250.000", remaining_quantity: "750.000", budget_rate: "2000.00" },
        { id: "8b9c0d1e-2f3a-4b4c-9d5e-7f8a9b0c1d2e", item_code: "A.2", description: "Reinforcement steel", unit: "t",
          section_code: "A", section_name: "Materials", boq_quantity: "10.000", requested_quantity: "0.000", remaining_quantity: "10.000", budget_rate: "240000.00" },
      ]),
    "/api/v1/suppliers": (_url, init) => (init?.method === "POST" ? jsonResponse(SUPPLIER, 201) : jsonResponse([SUPPLIER])),
    [`/api/v1/suppliers/${SUP}`]: () => jsonResponse({ ...SUPPLIER, is_active: false }),
    "/api/v1/purchase-orders/ready": () => jsonResponse([{ ...SUMMARY, status: "approved" }]),
    "/api/v1/purchase-orders": (_url, init) =>
      init?.method === "POST"
        ? jsonResponse({ order: PO, returned: [] }, 201)
        : jsonResponse([{ ...PO, lines: undefined, deliveries: undefined, notes: undefined }]),
    [`/api/v1/purchase-orders/${POID}`]: () => jsonResponse(PO),
    [`/api/v1/purchase-orders/${POID}/deliveries`]: () =>
      jsonResponse({ ...PO, status: "part_delivered", deliveries: [{ id: "9c0d1e2f-3a4b-4c5d-8e6f-8a9b0c1d2e3f", quantity: "10.000",
        delivered_on: TODAY, notes: null, created_at: "2026-10-10T05:00:00+00:00", request_number: "MR-0001", unit: "bag" }] }, 201),
    ...extra,
  });
}

function urlOf(input: RequestInfo | URL): string {
  return input instanceof Request ? input.url : input instanceof URL ? input.href : input;
}

function bodyOf(init: RequestInit | undefined): Record<string, unknown> {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON request body");
  return JSON.parse(init.body) as Record<string, unknown>;
}

describe("Materials list", () => {
  it("shows the pipeline with counts and what is waiting for the QS", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("quantity_surveyor");
    renderRoute("/materials");

    const pipeline = await screen.findByRole("group", { name: "Filter by stage" });
    expect(await within(pipeline).findByRole("button", { name: /All\s*2/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(pipeline).getByRole("button", { name: /QS check\s*1/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1 request is waiting for you" })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Material requests" });
    expect(within(table).getByRole("link", { name: "MR-0001" })).toHaveAttribute("href", `/materials/${RID}`);
    expect(within(table).getByText("Ready to order")).toBeInTheDocument();

    await user.click(within(pipeline).getByRole("button", { name: /PM approval/ }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => urlOf(input).includes("status=pm_approval"))).toBe(true);
    });
  });

  it("offers a new request only to roles that can raise one", async () => {
    materialsApi("procurement_officer");
    renderRoute("/materials");

    await screen.findByRole("table", { name: "Material requests" });
    expect(screen.queryByRole("link", { name: /New request/ })).not.toBeInTheDocument();
  });
});

describe("New request form", () => {
  it("checks the rules live and submits the request", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("site_engineer");
    const { router } = renderRoute("/materials/new");

    await screen.findByRole("option", { name: /Havelock Residences/ });
    await user.selectOptions(screen.getByLabelText("Project"), PID);
    await user.click(await screen.findByRole("radio", { name: /Cement, 50 kg bags/ }));
    expect(screen.getByText(/750 of 1,000 bag left/)).toBeInTheDocument();
    // Site engineers do not see rates: no price field, the QS prices the request.
    expect(screen.queryByLabelText("Unit price (LKR)")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Quantity (bag)"), "100");

    expect(await screen.findByText(/100 of 1,000 requested so far/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Submit request" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/materials/${RID}`);
    });
    const post = fetchMock.mock.calls.find(([input, init]) => urlOf(input).endsWith("/material-requests") && init?.method === "POST");
    const sent = bodyOf(post?.[1]);
    expect(sent).toMatchObject({ project_id: PID, boq_item_id: ITEM, quantity: "100", notes: null });
    expect(sent).not.toHaveProperty("unit_price");
  });

  it("validates before sending and cannot submit a blocked request", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("site_engineer", {
      "/api/v1/material-requests/check": () =>
        jsonResponse({ ...CHECK, blocked: true, results: [{ rule: "BR-02", severity: "block", message: "An approved variation is needed first.", facts: {} }] }),
    });
    renderRoute("/materials/new");

    await user.click(await screen.findByRole("button", { name: "Submit request" }));
    expect(screen.getByText("Choose the project.")).toBeInTheDocument();
    expect(screen.getByText("Enter a quantity greater than zero.")).toBeInTheDocument();

    await screen.findByRole("option", { name: /Havelock Residences/ });
    await user.selectOptions(screen.getByLabelText("Project"), PID);
    await user.click(await screen.findByRole("radio", { name: /Cement/ }));
    await user.type(screen.getByLabelText("Quantity (bag)"), "5000");
    expect(await screen.findByText("An approved variation is needed first.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit request" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([input, init]) => urlOf(input).endsWith("/material-requests") && init?.method === "POST")).toBe(false);
  });

  it("filters BOQ items by search", async () => {
    const user = userEvent.setup();
    materialsApi("site_engineer");
    renderRoute(`/materials/new?project=${PID}`);

    await user.type(await screen.findByLabelText("Search BOQ items"), "steel");

    expect(screen.getByRole("radio", { name: /Reinforcement steel/ })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /Cement/ })).not.toBeInTheDocument();
  });
});

describe("Request detail", () => {
  it("lets the QS approve, with the rule results and history shown", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("quantity_surveyor");
    renderRoute(`/materials/${RID}`);

    expect(await screen.findByRole("heading", { level: 1, name: /MR-0001: Cement/ })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Rule checks" })).getAllByRole("listitem")).toHaveLength(3);
    expect(within(screen.getByRole("list", { name: "Request history" })).getByText(/Submitted/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", { name: "Approve this request" });
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(requestTo(fetchMock, `/material-requests/${RID}/decision`)).toBeDefined();
    });
    expect(bodyOf(requestTo(fetchMock, `/material-requests/${RID}/decision`))).toEqual({ decision: "approve", comment: null });
  });

  it("needs a comment to reject", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("quantity_surveyor");
    renderRoute(`/materials/${RID}`);

    await user.click(await screen.findByRole("button", { name: "Reject" }));
    const dialog = screen.getByRole("dialog", { name: "Reject this request" });
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));
    expect(within(dialog).getByText("Add a comment so the requester knows why.")).toBeInTheDocument();
    expect(requestTo(fetchMock, `/material-requests/${RID}/decision`)).toBeUndefined();

    await user.type(within(dialog).getByLabelText("Comment"), "Use the central store.");
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));
    await waitFor(() => {
      expect(bodyOf(requestTo(fetchMock, `/material-requests/${RID}/decision`))).toEqual({
        decision: "reject",
        comment: "Use the central store.",
      });
    });
  });

  it("explains a PM routing and shows refusals from the server", async () => {
    const user = userEvent.setup();
    materialsApi("quantity_surveyor", {
      [`/api/v1/material-requests/${RID}`]: () =>
        jsonResponse({ ...DETAIL, rules: { ...CHECK, approval_level: "pm", routed_by: ["BR-01"] } }),
      [`/api/v1/material-requests/${RID}/decision`]: () =>
        jsonResponse({ error: { code: "own_request", message: "You cannot approve or reject a request you raised yourself.", request_id: "r", details: [] } }, 403),
    });
    renderRoute(`/materials/${RID}`);

    await user.click(await screen.findByRole("button", { name: "Pass to PM" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/BR-01 sends this request to the project manager/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(await within(dialog).findByText("You cannot approve or reject a request you raised yourself.")).toBeInTheDocument();
  });

  it("lets the requester change and resubmit after a change request", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("site_engineer", {
      [`/api/v1/material-requests/${RID}`]: (_url, init) =>
        init?.method === "PATCH"
          ? jsonResponse({ ...DETAIL, status: "requested", actions: ["cancel"] })
          : jsonResponse({
              // As the API sends it to a site engineer: no price, no amount.
              ...DETAIL, unit_price: undefined, amount: undefined, status: "change_requested", actions: ["edit", "cancel"],
              history: [...DETAIL.history, { action: "request_change", from_status: "requested", to_status: "change_requested",
                comment: "Split by floor.", actor: { id: ME, full_name: "Shalini" }, created_at: "2026-10-10T04:00:00+00:00" }],
            }),
    });
    renderRoute(`/materials/${RID}`);

    expect(await screen.findByText("Split by floor.", { selector: "div *" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Change and resubmit" }));
    const dialog = screen.getByRole("dialog", { name: "Change and resubmit" });
    await user.clear(within(dialog).getByLabelText("Quantity (bag)"));
    await user.type(within(dialog).getByLabelText("Quantity (bag)"), "50");
    await user.click(within(dialog).getByRole("button", { name: "Resubmit" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(true);
    });
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH")?.[1];
    expect(bodyOf(patch)).toMatchObject({ quantity: "50" });
    expect(bodyOf(patch)).not.toHaveProperty("unit_price");
    expect(within(dialog).queryByLabelText("Unit price (LKR)")).not.toBeInTheDocument();
  });

  it("shows the order and delivery progress", async () => {
    materialsApi("site_engineer", {
      [`/api/v1/material-requests/${RID}`]: () =>
        jsonResponse({
          ...DETAIL, status: "ordered", actions: [],
          order: { id: POID, number: "PO-0001", supplier_name: "Kelani Building Supplies", unit_price: "1950.00", amount: "195000.00",
                   expected_delivery: addDaysIso(TODAY, 7), delivered_quantity: "40.000", deliveries: [] },
        }),
    });
    renderRoute(`/materials/${RID}`);

    expect(await screen.findByRole("link", { name: "PO-0001" })).toHaveAttribute("href", `/purchase-orders/${POID}`);
    expect(screen.getByText("40 of 100 bag delivered")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Request progress" })).toHaveTextContent("Ordered");
  });

  it("shows not found outside the user's sites", async () => {
    materialsApi("site_engineer", { [`/api/v1/material-requests/${RID}`]: () => errorResponse(404, "not_found") });
    renderRoute(`/materials/${RID}`);

    expect(await screen.findByRole("heading", { name: "Off the drawings." })).toBeInTheDocument();
  });
});

describe("Purchase orders", () => {
  it("creates an order from approved requests", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("procurement_officer");
    const { router } = renderRoute("/purchase-orders");

    await user.click(await screen.findByRole("checkbox", { name: "Select MR-0001" }));
    await user.click(screen.getByRole("button", { name: "Create purchase order (1)" }));
    const dialog = screen.getByRole("dialog", { name: "Create purchase order" });
    await user.click(within(dialog).getByRole("button", { name: "Issue order" }));
    expect(within(dialog).getByText("Choose the supplier.")).toBeInTheDocument();

    await user.selectOptions(within(dialog).getByLabelText("Supplier"), SUP);
    const price = within(dialog).getByLabelText("Unit price for MR-0001");
    await user.clear(price);
    await user.type(price, "0");
    await user.click(within(dialog).getByRole("button", { name: "Issue order" }));
    expect(within(dialog).getByText("MR-0001: enter the quoted unit price, greater than zero.")).toBeInTheDocument();
    await user.clear(price);
    await user.type(price, "2100");
    expect(within(dialog).getByText(/\+5\.0%/)).not.toHaveTextContent("goes back to the PM");
    await user.clear(price);
    await user.type(price, "2200");
    expect(within(dialog).getByText(/\+10\.0%: over 5%, goes back to the PM \(BR-14\)/)).toBeInTheDocument();

    await user.clear(price);
    await user.type(price, "1950");
    await user.click(within(dialog).getByRole("button", { name: "Issue order" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/purchase-orders/${POID}`);
    });
    const post = fetchMock.mock.calls.find(([input, init]) => urlOf(input).endsWith("/purchase-orders") && init?.method === "POST");
    expect(bodyOf(post?.[1])).toMatchObject({ supplier_id: SUP, lines: [{ request_id: RID, unit_price: "1950" }] });
  });

  it("lists orders for readers without the ordering tools", async () => {
    materialsApi("project_manager");
    renderRoute("/purchase-orders");

    expect(await screen.findByRole("link", { name: /PO-0001/ })).toHaveAttribute("href", `/purchase-orders/${POID}`);
    expect(screen.queryByRole("heading", { name: "Ready to order" })).not.toBeInTheDocument();
  });

  it("records a delivery within what is still due", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("procurement_officer");
    renderRoute(`/purchase-orders/${POID}`);

    const form = await screen.findByRole("form", { name: "Record a delivery" });
    expect(within(form).getByText("60 still to come")).toBeInTheDocument();
    await user.type(within(form).getByLabelText("Quantity received (bag)"), "61");
    await user.click(within(form).getByRole("button", { name: "Record delivery" }));
    expect(within(form).getByText("Enter a quantity between 0 and 60.")).toBeInTheDocument();

    await user.clear(within(form).getByLabelText("Quantity received (bag)"));
    await user.type(within(form).getByLabelText("Quantity received (bag)"), "10");
    await user.click(within(form).getByRole("button", { name: "Record delivery" }));
    await waitFor(() => {
      expect(bodyOf(requestTo(fetchMock, `/purchase-orders/${POID}/deliveries`))).toMatchObject({ request_id: RID, quantity: "10" });
    });
  });

  it("does not show the delivery form to readers", async () => {
    materialsApi("project_manager");
    renderRoute(`/purchase-orders/${POID}`);

    expect(await screen.findByRole("heading", { level: 1, name: /PO-0001/ })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Record a delivery" })).not.toBeInTheDocument();
  });
});

describe("Suppliers", () => {
  it("adds and deactivates suppliers", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("procurement_officer");
    renderRoute("/suppliers");

    await user.click(await screen.findByRole("button", { name: "Add supplier" }));
    const dialog = screen.getByRole("dialog", { name: "Add a supplier" });
    await user.type(within(dialog).getByLabelText("Phone (optional)"), "call me");
    await user.click(within(dialog).getByRole("button", { name: "Add supplier" }));
    expect(within(dialog).getByText("Enter the supplier's name.")).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Name"), "Southern Steel Traders");
    await user.click(within(dialog).getByRole("button", { name: "Add supplier" }));
    expect(within(dialog).getByText(/Enter a phone number/)).toBeInTheDocument();
    await user.clear(within(dialog).getByLabelText("Phone (optional)"));
    await user.click(within(dialog).getByRole("button", { name: "Add supplier" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, init]) => urlOf(input).endsWith("/suppliers") && init?.method === "POST")).toBe(true);
    });

    await user.click(screen.getByRole("button", { name: "Deactivate" }));
    await waitFor(() => {
      expect(requestTo(fetchMock, `/suppliers/${SUP}`)?.method).toBe("PATCH");
    });
  });
});

describe("Cost control on the BOQ tab", () => {
  const detail: ProjectDetail = {
    ...PROJECT, description: null, planned_crew: null, team: [], created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
    sections: [{ id: "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d", code: "A", name: "Materials", item_count: 2, amount: "5500000.00",
                 budget_line_id: "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e", budget_amount: "4400000.00" }],
  };
  const boq = {
    project_id: PID, item_count: 2, boq_total: "5500000.00", budget_total: "4400000.00",
    sections: [{ ...detail.sections[0]!, items: [] }],
  };
  const figures = { boq_amount: "5500000.00", budget: "4400000.00", approved: "100000.00", on_order: "117000.00", spent: "78000.00",
                    committed: "295000.00", remaining: "4105000.00" };

  function boqApi(role: Role) {
    return materialsApi(role, {
      [`/api/v1/projects/${PID}`]: () => jsonResponse(detail),
      [`/api/v1/projects/${PID}/boq`]: () => jsonResponse(boq),
      [`/api/v1/projects/${PID}/budget`]: () =>
        jsonResponse({ project_id: PID, lines: [{ section_id: detail.sections[0]!.id, code: "A", name: "Materials", ...figures }], totals: figures }),
    });
  }

  it("shows budget, spent, committed and what is left to cost readers", async () => {
    boqApi("quantity_surveyor");
    renderRoute(`/projects/${PID}/boq`);

    expect(await screen.findByRole("heading", { name: "Cost control" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Committed" })).toHaveTextContent("LKR 295 k");
    expect(screen.getByRole("group", { name: "Committed" })).toHaveTextContent("Spent + on order + approved");
    expect(screen.getByRole("group", { name: "Spent" })).toHaveTextContent("On order LKR 117 k");
    expect(screen.getByRole("group", { name: "Left in budget" })).toHaveTextContent("LKR 4.11 M");
    const table = screen.getByRole("table", { name: /Cost budget, spent/ });
    expect(within(table).getByRole("columnheader", { name: "On order" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Committed" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Cost budget, spent/ })).toHaveTextContent("Materials");
  });

  it("is hidden from roles without cost access", async () => {
    boqApi("site_engineer");
    renderRoute(`/projects/${PID}/boq`);

    await screen.findByRole("article", { name: /Section A/ });
    expect(screen.queryByRole("heading", { name: "Cost control" })).not.toBeInTheDocument();
  });
});

describe("Materials edge cases", () => {
  it("lets the requester cancel and checks edits before resubmitting", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("site_engineer", {
      [`/api/v1/material-requests/${RID}`]: () =>
        jsonResponse({ ...DETAIL, status: "change_requested", actions: ["edit", "cancel"] }),
      [`/api/v1/material-requests/${RID}/decision`]: () => jsonResponse({ ...DETAIL, status: "cancelled", actions: [] }),
    });
    renderRoute(`/materials/${RID}`);

    await user.click(await screen.findByRole("button", { name: "Change and resubmit" }));
    let dialog = screen.getByRole("dialog", { name: "Change and resubmit" });
    await user.clear(within(dialog).getByLabelText("Quantity (bag)"));
    await user.type(within(dialog).getByLabelText("Quantity (bag)"), "0");
    await user.click(within(dialog).getByRole("button", { name: "Resubmit" }));
    expect(within(dialog).getByText("Quantity and price must be greater than zero.")).toBeInTheDocument();
    await user.clear(within(dialog).getByLabelText("Quantity (bag)"));
    await user.type(within(dialog).getByLabelText("Quantity (bag)"), "5");
    await user.clear(within(dialog).getByLabelText("Needed by"));
    await user.type(within(dialog).getByLabelText("Needed by"), "2020-01-01");
    await user.click(within(dialog).getByRole("button", { name: "Resubmit" }));
    expect(within(dialog).getByText("The needed-by date cannot be in the past.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Back" }));

    await user.click(screen.getByRole("button", { name: "Cancel request" }));
    dialog = screen.getByRole("dialog", { name: "Cancel this request" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(bodyOf(requestTo(fetchMock, `/material-requests/${RID}/decision`))).toEqual({ decision: "cancel", comment: null });
    });
  });

  it("shows the PM step for requests routed above the limit", async () => {
    materialsApi("project_manager", {
      [`/api/v1/material-requests/${RID}`]: () =>
        jsonResponse({ ...DETAIL, status: "pm_approval", approval_level: "pm", rules: { ...CHECK, approval_level: "pm", routed_by: ["BR-13"] } }),
    });
    renderRoute(`/materials/${RID}`);

    const steps = await screen.findByRole("list", { name: "Request progress" });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(5);
    expect(within(steps).getByText("PM approval").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("Project manager")).toBeInTheDocument();
  });

  it("only lets one project go on a purchase order", async () => {
    const user = userEvent.setup();
    const other = { ...SUMMARY, id: RID2, number: "MR-0002", status: "approved" as const,
                    project: { ...SUMMARY.project, id: "1a1b1c1d-2e2f-4a3b-8c4d-5e6f7a8b9c0d", name: "Peradeniya Road" } };
    materialsApi("procurement_officer", {
      "/api/v1/purchase-orders/ready": () => jsonResponse([{ ...SUMMARY, status: "approved" }, other]),
    });
    renderRoute("/purchase-orders");

    await user.click(await screen.findByRole("checkbox", { name: "Select MR-0001" }));

    expect(screen.getByRole("checkbox", { name: "Select MR-0002" })).toBeDisabled();
  });

  it("filters orders by status", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("procurement_officer");
    renderRoute("/purchase-orders");

    const filters = await screen.findByRole("group", { name: "Filter by status" });
    await user.click(within(filters).getByRole("button", { name: "Delivered" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => urlOf(input).endsWith("/purchase-orders?status=delivered"))).toBe(true);
    });
  });

  it("says when an order is fully delivered", async () => {
    materialsApi("procurement_officer", {
      [`/api/v1/purchase-orders/${POID}`]: () =>
        jsonResponse({ ...PO, status: "delivered", lines: [{ ...PO.lines[0]!, delivered_quantity: "100.000" }] }),
    });
    renderRoute(`/purchase-orders/${POID}`);

    expect(await screen.findByText("Everything on this order has been delivered.")).toBeInTheDocument();
  });

  it("flags a section that will end over budget", async () => {
    const over = { boq_amount: "5500000.00", budget: "100000.00", approved: "0.00", on_order: "50000.00", spent: "80000.00",
                   committed: "130000.00", remaining: "-30000.00" };
    const detail: ProjectDetail = {
      ...PROJECT, description: null, planned_crew: null, team: [], created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
      sections: [{ id: "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d", code: "A", name: "Materials", item_count: 2, amount: "5500000.00",
                   budget_line_id: "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e", budget_amount: "100000.00" }],
    };
    materialsApi("project_manager", {
      [`/api/v1/projects/${PID}`]: () => jsonResponse(detail),
      [`/api/v1/projects/${PID}/boq`]: () =>
        jsonResponse({ project_id: PID, item_count: 2, boq_total: "5500000.00", budget_total: "100000.00", sections: [{ ...detail.sections[0]!, items: [] }] }),
      [`/api/v1/projects/${PID}/budget`]: () =>
        jsonResponse({ project_id: PID, lines: [{ section_id: detail.sections[0]!.id, code: "A", name: "Materials", ...over }], totals: over }),
    });
    renderRoute(`/projects/${PID}/boq`);

    expect(await screen.findByRole("group", { name: "Over budget" })).toHaveTextContent("LKR 30 k");
    expect(screen.getByRole("table", { name: /Cost budget, spent/ })).toHaveTextContent("LKR 30 k over");
  });
});


describe("Prices and routing", () => {
  const ENGINEER_DETAIL = {
    ...DETAIL, unit_price: undefined, amount: undefined, actions: ["cancel"],
    rules: { approval_level: "qs", blocked: false, routed_by: [], results: [CHECK.results[0]] },
  };

  it("shows a site engineer the request without any price or amount", async () => {
    materialsApi("site_engineer", { [`/api/v1/material-requests/${RID}`]: () => jsonResponse(ENGINEER_DETAIL) });
    renderRoute(`/materials/${RID}`);

    expect(await screen.findByRole("heading", { level: 1, name: /MR-0001/ })).toBeInTheDocument();
    expect(screen.queryByText("Unit price")).not.toBeInTheDocument();
    expect(screen.queryByText("Value")).not.toBeInTheDocument();
    expect(screen.queryByText("Request value")).not.toBeInTheDocument();
    expect(screen.queryByText(/LKR/)).not.toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Rule checks" })).getAllByRole("listitem")).toHaveLength(1);
  });

  it("lets the QS price the request when approving", async () => {
    const user = userEvent.setup();
    const fetchMock = materialsApi("quantity_surveyor");
    renderRoute(`/materials/${RID}`);

    await user.click(await screen.findByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", { name: "Approve this request" });
    const price = within(dialog).getByLabelText(/Quoted unit price \(LKR \/ bag\)/);
    expect(price).toHaveValue("2000.00");
    await user.clear(price);
    await user.type(price, "2120");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(bodyOf(requestTo(fetchMock, `/material-requests/${RID}/decision`))).toEqual({
        decision: "approve",
        comment: null,
        unit_price: "2120",
      });
    });
  });

  it("requires the quoted price for a pending request, with the budgeted rate beside the field", async () => {
    const user = userEvent.setup();
    const waiting = "Price pending: the QS enters the quoted price at the QS check.";
    const pending = {
      ...DETAIL, unit_price: null, amount: null,
      rules: { ...CHECK, amount: null, results: [CHECK.results[0]!,
        { rule: "BR-01", severity: "pending", message: waiting, facts: {} },
        { rule: "BR-13", severity: "pending", message: waiting, facts: {} }] },
    };
    const fetchMock = materialsApi("quantity_surveyor", { [`/api/v1/material-requests/${RID}`]: () => jsonResponse(pending) });
    renderRoute(`/materials/${RID}`);

    expect(await screen.findAllByText("Price pending")).toHaveLength(3); // unit price, value, request value
    expect(screen.getAllByText(waiting)).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", { name: "Approve this request" });
    expect(within(dialog).getByText(/price pending\./)).toBeInTheDocument();
    const reference = within(dialog).getByLabelText("Reference");
    expect(reference).toHaveTextContent("Budgeted rate");
    expect(reference).toHaveTextContent("LKR 2,000.00 / bag");
    const price = within(dialog).getByLabelText(/Quoted unit price/);
    expect(price).toHaveValue("");
    expect(price).toBeRequired();
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(within(dialog).getByText("Enter the quoted unit price before approving: the price is pending.")).toBeInTheDocument();
    expect(requestTo(fetchMock, `/material-requests/${RID}/decision`)).toBeUndefined();

    await user.type(price, "1980");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => {
      expect(bodyOf(requestTo(fetchMock, `/material-requests/${RID}/decision`))).toEqual({ decision: "approve", comment: null, unit_price: "1980" });
    });
  });

  it("shows price pending in the request list", async () => {
    materialsApi("quantity_surveyor", {
      "/api/v1/material-requests": () =>
        jsonResponse({ items: [{ ...SUMMARY, unit_price: null, amount: null }], total: 1, counts: { requested: 1 } }),
    });
    renderRoute("/materials");

    const row = (await screen.findByText("MR-0001")).closest("tr");
    expect(row).toHaveTextContent("Price pending");
  });

  it("explains a request sent back from ordering", async () => {
    const reason = "Sent back for project manager approval: the quoted price is more than 5% above the approved price (BR-14).";
    materialsApi("project_manager", {
      [`/api/v1/material-requests/${RID}`]: () =>
        jsonResponse({
          ...DETAIL, status: "pm_approval", approval_level: "pm", unit_price: "2200.00", amount: "220000.00",
          history: [...DETAIL.history, { action: "return_for_approval", from_status: "approved", to_status: "pm_approval",
            comment: reason, actor: { id: ME, full_name: "Fathima Procurement" }, created_at: "2026-10-10T05:00:00+00:00" }],
        }),
    });
    renderRoute(`/materials/${RID}`);

    const alert = (await screen.findByText("Sent back from ordering")).closest("[role]");
    expect(alert).toHaveTextContent(reason);
    expect(screen.getByText("Sent back for PM approval")).toBeInTheDocument();
  });

  it("lists requests sent back when issuing an order", async () => {
    const user = userEvent.setup();
    const br14 = { rule: "BR-14", severity: "warn",
                   message: "The order price is 10.0% above the approved price (limit 5%): sent back for project manager approval.", facts: {} };
    materialsApi("procurement_officer", {
      "/api/v1/purchase-orders": (_url, init) =>
        init?.method === "POST"
          ? jsonResponse({ order: null, returned: [{ request_id: RID, number: "MR-0001", unit_price: "2200.00", rules: [br14] }] })
          : jsonResponse([]),
    });
    const { router } = renderRoute("/purchase-orders");

    await user.click(await screen.findByRole("checkbox", { name: "Select MR-0001" }));
    await user.click(screen.getByRole("button", { name: "Create purchase order (1)" }));
    const form = screen.getByRole("dialog", { name: "Create purchase order" });
    await user.selectOptions(within(form).getByLabelText("Supplier"), SUP);
    await user.clear(within(form).getByLabelText("Unit price for MR-0001"));
    await user.type(within(form).getByLabelText("Unit price for MR-0001"), "2200");
    await user.click(within(form).getByRole("button", { name: "Issue order" }));

    const dialog = await screen.findByRole("dialog", { name: "Nothing ordered" });
    expect(within(dialog).getByText("1 request sent back for PM approval")).toBeInTheDocument();
    const sentBack = within(dialog).getByRole("list", { name: "Sent back" });
    expect(within(sentBack).getByRole("link", { name: "MR-0001" })).toHaveAttribute("href", `/materials/${RID}`);
    expect(sentBack).toHaveTextContent("BR-14");
    expect(sentBack).toHaveTextContent("LKR 2,200.00");
    expect(within(dialog).queryByRole("link", { name: /Open PO/ })).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/purchase-orders");
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("links the order when only some lines were sent back", async () => {
    const user = userEvent.setup();
    const br13 = { rule: "BR-13", severity: "warn", message: "Needs project manager approval: the section would go over.", facts: {} };
    materialsApi("procurement_officer", {
      "/api/v1/purchase-orders": (_url, init) =>
        init?.method === "POST"
          ? jsonResponse({ order: PO, returned: [{ request_id: RID2, number: "MR-0002", unit_price: "2060.00", rules: [br13] }] }, 201)
          : jsonResponse([]),
    });
    renderRoute("/purchase-orders");

    await user.click(await screen.findByRole("checkbox", { name: "Select MR-0001" }));
    await user.click(screen.getByRole("button", { name: "Create purchase order (1)" }));
    const form = screen.getByRole("dialog", { name: "Create purchase order" });
    await user.selectOptions(within(form).getByLabelText("Supplier"), SUP);
    await user.click(within(form).getByRole("button", { name: "Issue order" }));

    const dialog = await screen.findByRole("dialog", { name: "PO-0001 issued" });
    expect(within(dialog).getByRole("link", { name: "Open PO-0001" })).toHaveAttribute("href", `/purchase-orders/${POID}`);
    expect(within(dialog).getByRole("list", { name: "Sent back" })).toHaveTextContent("BR-13");
  });

  it("names the rule that sent a request to the PM", async () => {
    materialsApi("project_manager", {
      [`/api/v1/material-requests/${RID}`]: () =>
        jsonResponse({
          ...DETAIL, status: "pm_approval", approval_level: "pm",
          rules: {
            ...CHECK, approval_level: "pm", routed_by: ["BR-13"],
            results: [
              ...CHECK.results.filter((x) => x.rule !== "BR-13"),
              { rule: "BR-13", severity: "warn", message: "Needs project manager approval: the section would exceed its budget line.", facts: {} },
            ],
          },
        }),
    });
    renderRoute(`/materials/${RID}`);

    expect(await screen.findByText("Sent to the project manager by BR-13.")).toBeInTheDocument();
    const rule = screen.getByText("Section cost against its budget line").closest("li");
    expect(rule).toHaveTextContent("Sends to PM");
    expect(screen.getByText("Unit price against the budgeted rate").closest("li")).not.toHaveTextContent("Sends to PM");
  });

  it("shows a site engineer the BOQ with quantities only", async () => {
    const detail = {
      ...PROJECT, contract_value: undefined, boq_total: undefined, budget_total: undefined, description: null, planned_crew: null, team: [],
      created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
      sections: [{ id: "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d", code: "A", name: "Materials", item_count: 1 }],
    };
    const boq = {
      project_id: PID, item_count: 1,
      sections: [{ ...detail.sections[0], items: [{ id: ITEM, item_code: "A.1", description: "Cement, 50 kg bags", unit: "bag",
        quantity: "1000.000", requested_quantity: "250.000", remaining_quantity: "750.000" }] }],
    };
    const user = userEvent.setup();
    materialsApi("site_engineer", {
      [`/api/v1/projects/${PID}`]: () => jsonResponse(detail),
      [`/api/v1/projects/${PID}/boq`]: () => jsonResponse(boq),
    });
    renderRoute(`/projects/${PID}/boq`);

    const section = await screen.findByRole("article", { name: /Section A/ });
    await user.click(within(section).getByRole("button", { expanded: false }));
    const table = within(section).getByRole("table", { name: "Items in section A" });
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Item", "Description", "Unit", "BOQ qty", "Requested", "Remaining"]);
    expect(within(table).getByRole("row", { name: /A.1/ })).toHaveTextContent("1,000250750");
    expect(screen.queryByText(/LKR|Margin|BOQ value/)).not.toBeInTheDocument();
  });
});

describe("Engineer views without costs", () => {
  const card = { ...PROJECT, contract_value: undefined, boq_total: undefined, budget_total: undefined };
  const detail = {
    ...card, description: null, planned_crew: null, team: [], created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
    sections: [{ id: "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d", code: "A", name: "Materials", item_count: 2 }],
  };
  const engineerSummary = { ...SUMMARY, unit_price: undefined, amount: undefined };

  function engineerApi() {
    return materialsApi("site_engineer", {
      "/api/v1/projects": () => jsonResponse([card]),
      [`/api/v1/projects/${PID}`]: () => jsonResponse(detail),
      "/api/v1/material-requests": () =>
        jsonResponse({ items: [engineerSummary], total: 1, counts: { requested: 1 } }),
      [`/api/v1/purchase-orders/${POID}`]: () =>
        jsonResponse({ ...PO, total: undefined, lines: PO.lines.map((l) => ({ ...l, unit_price: undefined, amount: undefined })) }),
    });
  }

  it("lists projects without contract values", async () => {
    engineerApi();
    renderRoute("/projects");

    const list = await screen.findByRole("list", { name: "Projects" });
    expect(within(list).getByText("BOQ: 2 items")).toBeInTheDocument();
    expect(within(list).queryByText(/LKR/)).not.toBeInTheDocument();
  });

  it("shows the project overview with BOQ sections but no money", async () => {
    engineerApi();
    renderRoute(`/projects/${PID}`);

    expect(await screen.findByRole("group", { name: "BOQ items" })).toHaveTextContent("2");
    expect(screen.getByRole("list", { name: "BOQ sections" })).toHaveTextContent("Materials");
    expect(screen.queryByRole("group", { name: "Contract value" })).not.toBeInTheDocument();
    expect(screen.queryByText(/LKR/)).not.toBeInTheDocument();
  });

  it("lists requests without a value column", async () => {
    engineerApi();
    renderRoute("/materials");

    const table = await screen.findByRole("table", { name: "Material requests" });
    await within(table).findByRole("link", { name: "MR-0001" });
    expect(within(table).queryByRole("columnheader", { name: "Value" })).not.toBeInTheDocument();
    expect(within(table).queryByText(/LKR/)).not.toBeInTheDocument();
  });

  it("shows a purchase order without prices", async () => {
    engineerApi();
    renderRoute(`/purchase-orders/${POID}`);

    const table = await screen.findByRole("table", { name: "Order lines and delivered quantities" });
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Line", "Ordered", "Delivered"]);
    expect(screen.queryByText("Total")).not.toBeInTheDocument();
  });
});
