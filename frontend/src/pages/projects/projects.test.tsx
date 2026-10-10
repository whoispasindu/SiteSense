import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Boq, ImportReport, ProjectDetail, ProjectSummary } from "../../api/projects";
import type { Role } from "../../api/auth";
import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi } from "../../test/utils";

const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };
const PID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const LINE = "8b2c3d4e-5f6a-4b7c-9d8e-0f1a2b3c4d5e";

const SUMMARY: ProjectSummary = {
  id: PID,
  code: "HR-2026-01",
  name: "Havelock Residences",
  site: SITE,
  client_name: "Havelock Developers (Pvt) Ltd",
  project_type: "residential",
  status: "active",
  contract_value: "1114000000.00",
  start_date: "2026-03-02",
  planned_end: "2027-09-30",
  boq_total: "1113985000.00",
  budget_total: "981742500.00",
  item_count: 40,
};

const SECTION = {
  id: "9c3d4e5f-6a7b-4c8d-8e9f-1a2b3c4d5e6f",
  code: "B",
  name: "Substructure",
  item_count: 2,
  amount: "91490000.00",
  budget_line_id: LINE,
  budget_amount: "80583500.00",
};

const DETAIL: ProjectDetail = {
  ...SUMMARY,
  description: null,
  planned_crew: null,
  sections: [SECTION],
  team: [{ id: "1d2e3f4a-5b6c-4d7e-8f9a-0b1c2d3e4f5a", full_name: "Kasun Perera", role: "site_engineer", role_label: "Site Engineer" }],
  created_at: "2026-10-01T08:00:00+00:00",
  updated_at: "2026-10-01T08:00:00+00:00",
};

const BOQ: Boq = {
  project_id: PID,
  boq_total: "91490000.00",
  budget_total: "80583500.00",
  item_count: 2,
  sections: [
    {
      ...SECTION,
      items: [
        { id: "2e3f4a5b-6c7d-4e8f-9a0b-1c2d3e4f5a6b", item_code: "B.01", description: "Excavation for pile caps", unit: "m3", quantity: "2850.000", requested_quantity: "850.000", remaining_quantity: "2000.000", rate: "1450.00", amount: "4132500.00" },
        { id: "3f4a5b6c-7d8e-4f9a-8b1c-2d3e4f5a6b7c", item_code: "B.02", description: "Bored piles 600 mm", unit: "m", quantity: "1920.000", requested_quantity: "0.000", remaining_quantity: "1920.000", rate: "18500.00", amount: "35520000.00" },
      ],
    },
  ],
};

function projectApi(role: Role, extra: Record<string, (url: string, init?: RequestInit) => Response> = {}) {
  return mockApi({
    ...sessionApi(makeMe(role)),
    "/api/v1/projects": () => jsonResponse([SUMMARY]),
    [`/api/v1/projects/${PID}`]: () => jsonResponse(DETAIL),
    [`/api/v1/projects/${PID}/boq`]: () => jsonResponse(BOQ),
    "/api/v1/sites": () => jsonResponse([SITE]),
    ...extra,
  });
}

describe("ProjectsPage", () => {
  it("lists projects with value, BOQ coverage and dates", async () => {
    projectApi("site_engineer");
    renderRoute("/projects");

    const list = await screen.findByRole("list", { name: "Projects" });
    const row = within(list).getByRole("link", { name: /Havelock Residences/ });
    expect(row).toHaveAttribute("href", `/projects/${PID}`);
    expect(row).toHaveTextContent("LKR 1.11 bn");
    expect(row).toHaveTextContent("BOQ 40 items · 100.0% of contract");
    expect(row).toHaveTextContent("02 Mar 2026");
    expect(row).toHaveTextContent("Active");
    expect(screen.queryByRole("button", { name: "New project" })).not.toBeInTheDocument();
  });

  it("filters by status through the API", async () => {
    const user = userEvent.setup();
    const fetchMock = projectApi("project_manager");
    renderRoute("/projects");
    await screen.findByRole("list", { name: "Projects" });

    await user.click(screen.getByRole("button", { name: "On hold" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => (url as string).includes("status=on_hold"))).toBe(true);
    });
  });

  it("lets a project manager create a project and opens it", async () => {
    const user = userEvent.setup();
    const fetchMock = projectApi("project_manager", {
      "/api/v1/projects": (_url, init) => (init?.method === "POST" ? jsonResponse(DETAIL, 201) : jsonResponse([])),
    });
    const { router } = renderRoute("/projects");

    await user.click(await screen.findByRole("button", { name: "New project" }));
    const dialog = screen.getByRole("dialog", { name: "New project" });
    await user.click(within(dialog).getByRole("button", { name: "Create project" }));
    expect(within(dialog).getByText(/2–24 letters/)).toBeInTheDocument();
    expect(within(dialog).getByText("Choose a site.")).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText("Code"), "hr-2026-01");
    await user.selectOptions(within(dialog).getByLabelText("Site"), SITE.id);
    await user.type(within(dialog).getByLabelText("Project name"), "Havelock Residences");
    await user.type(within(dialog).getByLabelText("Client"), "Havelock Developers");
    await user.type(within(dialog).getByLabelText("Contract value (LKR)"), "1,114,000,000.00");
    await user.type(within(dialog).getByLabelText("Start date"), "2026-03-02");
    await user.type(within(dialog).getByLabelText("Planned end"), "2025-01-01");
    await user.click(within(dialog).getByRole("button", { name: "Create project" }));
    expect(within(dialog).getByText("The planned end must be on or after the start date.")).toBeInTheDocument();

    await user.clear(within(dialog).getByLabelText("Planned end"));
    await user.type(within(dialog).getByLabelText("Planned end"), "2027-09-30");
    await user.type(within(dialog).getByLabelText("Planned crew (optional)"), "0");
    await user.click(within(dialog).getByRole("button", { name: "Create project" }));
    expect(within(dialog).getByText("Enter a whole number of people, 1 to 5000.")).toBeInTheDocument();
    await user.clear(within(dialog).getByLabelText("Planned crew (optional)"));
    await user.type(within(dialog).getByLabelText("Planned crew (optional)"), "55");
    await user.click(within(dialog).getByRole("button", { name: "Create project" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/projects/${PID}`);
    });
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST" && typeof init.body === "string" && init.body.includes("code"));
    expect(JSON.parse(post?.[1]?.body as string)).toMatchObject({
      code: "HR-2026-01",
      site_id: SITE.id,
      contract_value: "1114000000.00",
      status: "planning",
      description: null,
      planned_crew: 55,
    });
  });
});

describe("Project overview", () => {
  it("shows the project details, KPIs, section costs and team", async () => {
    projectApi("project_manager");
    renderRoute(`/projects/${PID}`);

    expect(await screen.findByRole("heading", { level: 1, name: "Havelock Residences" })).toBeInTheDocument();
    expect(screen.getByText("COL-07 · Havelock Residences")).toBeInTheDocument();
    expect(screen.getByText("82 weeks")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Contract value" })).toHaveTextContent("LKR 1.11 bn");
    expect(screen.getByText("11.9%")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /by section/ });
    expect(within(table).getByRole("rowheader", { name: /Substructure/ })).toBeInTheDocument();
    const team = screen.getByRole("region", { name: "Team" });
    expect(within(team).getByText("Kasun Perera")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit project" })).toBeInTheDocument();
  });

  it("shows not-found for projects outside the user's sites", async () => {
    projectApi("site_engineer", { [`/api/v1/projects/${PID}`]: () => errorResponse(404, "not_found") });
    renderRoute(`/projects/${PID}`);

    expect(await screen.findByRole("heading", { name: "Off the drawings." })).toBeInTheDocument();
  });

  it("keeps clients out of projects", async () => {
    projectApi("client");
    renderRoute("/projects");

    expect(await screen.findByRole("heading", { name: "Authorised personnel only." })).toBeInTheDocument();
  });
});

describe("BOQ page", () => {
  it("expands sections into items and lets the QS adjust a budget", async () => {
    const user = userEvent.setup();
    const fetchMock = projectApi("quantity_surveyor", {
      [`/api/v1/projects/${PID}/budget-lines/${LINE}`]: () => jsonResponse({ ...SECTION, budget_amount: "82000000.00" }),
    });
    renderRoute(`/projects/${PID}/boq`);

    const section = await screen.findByRole("article", { name: "Section B: Substructure" });
    const toggle = within(section).getByRole("button", { name: /Substructure/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(section).getByText("Bored piles 600 mm")).toBeVisible();
    expect(within(section).getByText("35,520,000.00")).toBeInTheDocument();

    await user.click(within(section).getByRole("button", { name: "Edit budget for section B" }));
    const input = within(section).getByLabelText(/Budget for section B/);
    await user.clear(input);
    await user.type(input, "abc");
    expect(within(section).getByRole("button", { name: "Save" })).toBeDisabled();
    await user.clear(input);
    await user.type(input, "82,000,000.00");
    await user.click(within(section).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(requestTo(fetchMock, `/budget-lines/${LINE}`)?.body).toBe('{"budget_amount":"82000000.00"}');
    });
    expect(screen.getByRole("link", { name: "Re-import BOQ" })).toBeInTheDocument();
  });

  it("is read-only for other roles", async () => {
    projectApi("site_engineer");
    renderRoute(`/projects/${PID}/boq`);

    const section = await screen.findByRole("article", { name: "Section B: Substructure" });
    expect(within(section).queryByRole("button", { name: /Edit budget/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Import BOQ/ })).not.toBeInTheDocument();
  });
});

const REPORT: ImportReport = {
  file_name: "boq.csv",
  imported: false,
  dry_run: true,
  total_rows: 3,
  ok_rows: 1,
  error_rows: 1,
  skipped_rows: 1,
  has_budget_rates: false,
  replaces_items: 2,
  boq_total: "4132500.00",
  budget_total: "4132500.00",
  sections: [{ code: "B", name: "Substructure", items: 1, amount: "4132500.00", budget: "4132500.00" }],
  rows: [
    { row: 2, status: "skipped", section_code: "B", item_code: null, description: "SUBSTRUCTURE", errors: [] },
    { row: 3, status: "ok", section_code: "B", item_code: "B.01", description: "Excavation", errors: [] },
    { row: 4, status: "error", section_code: "B", item_code: "B.02", description: "Piles", errors: [{ column: "quantity", message: "Must be greater than zero." }] },
  ],
};

describe("BOQ import", () => {
  const csv = () => new File(["Section Code,Section Name\n"], "boq.csv", { type: "text/csv" });

  it("checks a file and shows each bad row with its column", async () => {
    const user = userEvent.setup();
    const fetchMock = projectApi("quantity_surveyor", { [`/api/v1/projects/${PID}/boq/import`]: () => jsonResponse(REPORT) });
    renderRoute(`/projects/${PID}/boq/import`);

    await user.upload(await screen.findByLabelText(/Drop the BOQ here/), csv());
    await user.click(screen.getByRole("button", { name: "Check file" }));

    const errors = await screen.findByRole("list", { name: "Rows with errors" });
    expect(within(errors).getByText("Row 4")).toBeInTheDocument();
    expect(within(errors).getByText("Quantity:")).toBeInTheDocument();
    expect(screen.getByText("1 row needs fixing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import 1 item" })).toBeDisabled();
    const call = fetchMock.mock.calls.find(([url]) => (url as string).includes("/boq/import"));
    expect(call?.[0]).toContain("dry_run=true");
    expect(call?.[1]?.body).toBeInstanceOf(FormData);
    expect((call?.[1]?.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("imports a clean file and returns to the BOQ", async () => {
    const user = userEvent.setup();
    const clean = { ...REPORT, error_rows: 0, rows: REPORT.rows.slice(0, 2) };
    projectApi("quantity_surveyor", {
      [`/api/v1/projects/${PID}/boq/import`]: (url) =>
        jsonResponse(url.includes("dry_run=false") ? { ...clean, imported: true, dry_run: false } : clean),
    });
    const { router } = renderRoute(`/projects/${PID}/boq/import`);

    await user.upload(await screen.findByLabelText(/Drop the BOQ here/), csv());
    await user.click(screen.getByRole("button", { name: "Check file" }));
    expect(await screen.findByText("This replaces the current BOQ")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Import 1 item" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/projects/${PID}/boq`);
    });
    expect(await screen.findByText(/BOQ imported: 1 item\./)).toBeInTheDocument();
  });

  it("refuses the wrong file type before uploading", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const fetchMock = projectApi("quantity_surveyor");
    renderRoute(`/projects/${PID}/boq/import`);

    await user.upload(await screen.findByLabelText(/Drop the BOQ here/), new File(["%PDF"], "boq.pdf"));

    expect(screen.getByRole("alert")).toHaveTextContent("Choose an .xlsx or .csv file.");
    expect(screen.getByRole("button", { name: "Check file" })).toBeDisabled();
    expect(requestTo(fetchMock, "/boq/import")).toBeUndefined();
  });

  it("is only for quantity surveyors", async () => {
    projectApi("project_manager");
    renderRoute(`/projects/${PID}/boq/import`);

    expect(await screen.findByRole("heading", { name: "Authorised personnel only." })).toBeInTheDocument();
  });
});
