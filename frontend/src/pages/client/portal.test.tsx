import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ClientClaims, ClientProject, ClientProjectCard } from "../../api/portal";
import type { ProjectDetail } from "../../api/projects";
import type { Task } from "../../api/schedule";
import { againstContract, guessTask } from "../../features/client/portal";
import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, sessionApi } from "../../test/utils";

const PID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const PID2 = "1a1b1c1d-2e2f-4a3b-8c4d-5e6f7a8b9c0d";
const PHOTO = "5a5a5a5a-1111-4111-8111-111111111111";
const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };

const CARD: ClientProjectCard = {
  id: PID, code: "HR-2026-01", name: "Havelock Residences", location: "Colombo 05", status: "active",
  planned_percent: 28.3, actual_percent: 25.6, handover_date: "2027-10-12", handover_published: true, variations_waiting: 1,
};  // fmt: skip

const PROJECT: ClientProject = {
  ...CARD,
  start_date: "2026-03-02",
  handover: {
    contract_end: "2027-09-30", published_date: "2027-10-12", reason: "Heavy October rain held up the frame.",
    published_at: "2026-10-13T00:55:00+00:00",
    history: [{ handover_date: "2027-09-30", reason: "The contract date.", published_at: "2026-05-16T00:00:00+00:00" }],
  },  // fmt: skip
  progress: [
    { date: "2026-03-02", planned: 0, actual: 0 },
    { date: "2026-10-12", planned: 28.3, actual: 25.6 },
    { date: "2027-09-30", planned: 100, actual: null },
  ],
  milestones: [
    { name: "Foundations complete", planned_date: "2026-05-29", expected_date: "2026-06-12", completed_on: "2026-06-12", percent_complete: 100, status: "done" },
    { name: "Handover", planned_date: "2027-09-30", expected_date: "2027-10-12", completed_on: null, percent_complete: 0, status: "late" },
  ],  // fmt: skip
  photos: [{ id: PHOTO, caption: "Level 4 columns", taken_on: "2026-10-09", width: 1200, height: 800 }],
};

const CLAIMS: ClientClaims = {
  project_id: PID, original_contract_value: "1114000000.00", approved_variations: "850000.00",
  contract_value: "1114850000.00", claimed_to_date: "189710948.15", paid_to_date: "189710948.15",
  retention_held: "9984786.75",
  retention_note: "Retention is held back from each claim and released at the end of the defects period after handover.",
  claims: [
    { number: "PC-0001", status: "paid", certified_pct: "17.93", certified_value: "199695734.90", retention: "9984786.75",
      previous_claims: "0.00", amount: "189710948.15", approved_on: "2026-10-12", paid_on: "2026-10-13" },
  ],
};  // fmt: skip

function clientApi(cards: ClientProjectCard[] = [CARD], project: ClientProject | Response = PROJECT) {
  return mockApi({
    ...sessionApi(makeMe("client", { full_name: "Mr. Jayawardena" })),
    "/api/v1/client/projects": () => jsonResponse(cards),
    [`/api/v1/client/projects/${PID}`]: () => (project instanceof Response ? project : jsonResponse(project)),
    [`/api/v1/client/projects/${PID}/claims`]: () => jsonResponse(CLAIMS),
    [`/api/v1/client/photos/${PHOTO}`]: () => new Response(new Blob(["jpeg"], { type: "image/jpeg" }), { status: 200 }),
    "/api/v1/notifications": () => jsonResponse({ unread: 0, items: [] }),
  });
}

describe("The client portal", () => {
  it("opens the client's only project straight away, under a top navigation", async () => {
    clientApi();
    const { router } = renderRoute("/");

    expect(await screen.findByRole("heading", { level: 1, name: "Havelock Residences" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/client/projects/${PID}`);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link").map((l) => l.textContent)).toEqual(["Your projects", "Variations"]);
    expect(screen.queryByText("Site office")).not.toBeInTheDocument(); // no staff sidebar
  });

  it("lists several projects with progress and the handover date", async () => {
    const second: ClientProjectCard = { ...CARD, id: PID2, code: "HR-2", name: "Havelock Towers", handover_published: false, handover_date: "2027-12-31", variations_waiting: 0 };
    clientApi([CARD, second]);
    renderRoute("/");

    expect(await screen.findByRole("heading", { level: 1, name: "Your projects" })).toBeInTheDocument();
    const towers = screen.getByRole("link", { name: /Havelock Towers/ });
    expect(towers).toHaveTextContent("Contract handover 31 Dec 2027");
    expect(screen.getByRole("link", { name: /Havelock Residences/ })).toHaveTextContent("1 variation waiting for your decision");
  });

  it("shows the published handover date with its reason and the earlier dates", async () => {
    clientApi();
    renderRoute(`/client/projects/${PID}`);

    const card = await screen.findByRole("region", { name: "Expected handover" });
    expect(card).toHaveTextContent("12 Oct 2027");
    expect(card).toHaveTextContent("12 days after the contract date (30 Sept 2027)");
    expect(card).toHaveTextContent("Heavy October rain held up the frame.");
    expect(within(card).getByText("Earlier dates (1)")).toBeInTheDocument();
  });

  it("says the contract date is shown until one is published", async () => {
    clientApi([CARD], { ...PROJECT, handover: { contract_end: "2027-09-30", published_date: null, reason: null, published_at: null, history: [] } });
    renderRoute(`/client/projects/${PID}`);

    const card = await screen.findByRole("region", { name: "Contract handover" });
    expect(card).toHaveTextContent("30 Sept 2027");
    expect(card).toHaveTextContent("Your project manager will publish an expected date");
  });

  it("lists milestones with their status in words", async () => {
    clientApi();
    renderRoute(`/client/projects/${PID}`);

    const list = await screen.findByRole("list", { name: "Milestones" });
    const [done, late] = within(list).getAllByRole("listitem");
    expect(done).toHaveTextContent("Foundations complete");
    expect(done).toHaveTextContent("Done");
    expect(done).toHaveTextContent("Completed 12 Jun 2026");
    expect(late).toHaveTextContent("Running late");
    expect(late).toHaveTextContent("Expected 12 Oct 2027 · planned 30 Sept 2027");
  });

  it("shows shared photos and opens one larger", async () => {
    const user = userEvent.setup();
    clientApi();
    renderRoute(`/client/projects/${PID}`);

    const gallery = await screen.findByRole("list", { name: "Site photos" });
    const thumb = await within(gallery).findByRole("img", { name: "Level 4 columns" });
    expect(thumb.getAttribute("src")).toMatch(/^data:/);
    await user.click(within(gallery).getByRole("button"));
    expect(await screen.findByRole("dialog", { name: "Level 4 columns, 09 Oct 2026" })).toBeInTheDocument();
  });

  it("shows approved claims, the contract value and the retention held", async () => {
    clientApi();
    renderRoute(`/client/projects/${PID}`);

    const table = await screen.findByRole("table", { name: /Approved progress claims/ });
    expect(within(table).getByRole("rowheader")).toHaveTextContent("PC-0001");
    expect(table).toHaveTextContent("17.93%");
    expect(table).toHaveTextContent("Paid 13 Oct 2026");
    expect(screen.getByText(/released at the end of the defects period/)).toBeInTheDocument();
    expect(screen.getByText(/plus LKR 850 k of approved variations/)).toBeInTheDocument();
  });

  it("treats a project the client is not linked to as not found", async () => {
    clientApi([CARD], errorResponse(404, "not_found", "Project not found."));
    renderRoute(`/client/projects/${PID}`);
    expect(await screen.findByRole("heading", { name: "Off the drawings." })).toBeInTheDocument();
  });

  it("points to variations waiting for a decision", async () => {
    clientApi();
    renderRoute(`/client/projects/${PID}`);
    expect(await screen.findByRole("link", { name: /1 variation is waiting for your decision/ })).toHaveAttribute("href", "/client/variations");
  });
});

// --- The project manager's side -------------------------------------------------------------------------

const DETAIL: ProjectDetail = {
  id: PID, code: "HR-2026-01", name: "Havelock Residences", site: SITE, client_name: "Havelock Developers",
  project_type: "residential", status: "active", contract_value: "1114000000.00", start_date: "2026-03-02",
  planned_end: "2027-09-30", boq_total: "0.00", budget_total: "0.00", item_count: 0, description: null,
  planned_crew: null, sections: [], team: [], created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
};  // fmt: skip

const task = (id: string, name: string, end: string, over: Partial<Task> = {}): Task => ({
  id, project_id: PID, code: null, name, boq_section_id: null, boq_section_code: null, planned_start: "2026-03-02",
  planned_end: end, weight: "10.00", percent_complete: "0.00", is_critical: false, is_concrete_pour: false,
  client_milestone: false, milestone_name: null, stopped: false, actual_start: null, actual_finish: null, position: 1,
  planned_percent_today: 0, state: "not_started", progress_updated_at: null, ...over,
});  // fmt: skip

const TASKS = [
  task("a1a1a1a1-1111-4111-8111-111111111111", "Piling and pile caps", "2026-05-29"),
  task("a2a2a2a2-1111-4111-8111-111111111111", "Frame: ground to level 4", "2026-10-30"),
  task("a3a3a3a3-1111-4111-8111-111111111111", "Frame: level 5 to roof", "2027-02-26"),
  task("a4a4a4a4-1111-4111-8111-111111111111", "External works and handover", "2027-09-30", {
    client_milestone: true, milestone_name: "Handover",
  }),
];

const HANDOVER = {
  project_id: PID,
  current: { kind: "published", handover_date: "2027-09-30", reason: "The contract date.", programme_forecast: "2027-10-12", published_by: "Ruwan PM", published_at: "2026-08-01T00:00:00+00:00" },
  published: { kind: "published", handover_date: "2027-09-30", reason: "The contract date.", programme_forecast: "2027-10-12", published_by: "Ruwan PM", published_at: "2026-08-01T00:00:00+00:00" },
  history: [{ kind: "published", handover_date: "2027-09-30", reason: "The contract date.", programme_forecast: "2027-10-12", published_by: "Ruwan PM", published_at: "2026-08-01T00:00:00+00:00" }],
  suggestions: { contract_end: "2027-09-30", programme_forecast: "2027-10-12", risk_range: { start: "2027-10-27", end: "2028-02-07" } },
  reminder: { reasons: ["The programme now forecasts 12 Oct 2027, 9 working days after the published date.", "Not reviewed for 73 days."], forecast_gap_days: 9, days_since_review: 73 },
  can_publish: true,
};  // fmt: skip

const PHOTOS = {
  items: [
    { id: PHOTO, report_id: "6b6b6b6b-1111-4111-8111-111111111111", report_date: "2026-10-09", caption: "Level 4 columns", width: 1200, height: 800, shared_with_client: false, shared_at: null },
  ],
  total: 1,
  shared: 0,
};  // fmt: skip

function pmApi() {
  return mockApi({
    ...sessionApi(makeMe("project_manager")),
    [`/api/v1/projects/${PID}`]: () => jsonResponse(DETAIL),
    [`/api/v1/projects/${PID}/handover`]: () => jsonResponse(HANDOVER),
    [`/api/v1/projects/${PID}/handover/confirm`]: () => jsonResponse({ ...HANDOVER, reminder: null }),
    [`/api/v1/projects/${PID}/tasks`]: () => jsonResponse({ tasks: TASKS, weight_total: "40.00" }),
    [`/api/v1/tasks/${TASKS[2]?.id ?? ""}`]: (_url, init) => jsonResponse({ ...TASKS[2], ...(JSON.parse(typeof init?.body === "string" ? init.body : "{}") as object) }),
    [`/api/v1/projects/${PID}/photos`]: () => jsonResponse(PHOTOS),
    [`/api/v1/projects/${PID}/photos/client-share`]: () => jsonResponse({ ...PHOTOS, shared: 1, items: [{ ...PHOTOS.items[0], shared_with_client: true }] }),
    [`/api/v1/photos/${PHOTO}`]: () => new Response(new Blob(["jpeg"], { type: "image/jpeg" }), { status: 200 }),
  });
}

function urlOf(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}

function bodyOf(fetchMock: ReturnType<typeof mockApi>, suffix: string): unknown {
  const call = fetchMock.mock.calls.find(([url, init]) => urlOf(url).split("?")[0]?.endsWith(suffix) && init?.method && init.method !== "GET");
  const body = call?.[1]?.body;
  return typeof body === "string" ? JSON.parse(body) : undefined;
}

describe("The project manager's client view", () => {
  it("reminds the PM, suggests dates and publishes a new one with a reason", async () => {
    const user = userEvent.setup();
    const fetchMock = pmApi();
    renderRoute(`/projects/${PID}/client`);

    expect(await screen.findByText("This date may be out of date")).toBeInTheDocument();
    expect(screen.getByText(/9 working days after the published date/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Programme, at current rates/ }));
    expect(screen.getByLabelText("Handover date")).toHaveValue("2027-10-12");
    await user.type(screen.getByLabelText("Reason, for the client"), "October rain held up the frame.");
    await user.click(screen.getByRole("button", { name: "Publish to the client" }));

    await waitFor(() => {
      expect(bodyOf(fetchMock, `/projects/${PID}/handover`)).toEqual({ handover_date: "2027-10-12", reason: "October rain held up the frame." });
    });
  });

  it("asks for a reason before publishing", async () => {
    const user = userEvent.setup();
    pmApi();
    renderRoute(`/projects/${PID}/client`);
    await user.click(await screen.findByRole("button", { name: /Contract end/ }));
    await user.click(screen.getByRole("button", { name: "Publish to the client" }));
    expect(await screen.findByText("Write a short reason for the client.")).toHaveAttribute("role", "alert");
  });

  it("confirms an unchanged date", async () => {
    const user = userEvent.setup();
    const fetchMock = pmApi();
    renderRoute(`/projects/${PID}/client`);
    await user.click(await screen.findByRole("button", { name: "Confirm unchanged" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url, init]) => urlOf(url).endsWith("/handover/confirm") && init?.method === "POST")).toBe(true);
    });
    await waitFor(() => {
      expect(screen.queryByText("This date may be out of date")).not.toBeInTheDocument();
    });
  });

  it("maps a suggested milestone to the task the keywords point at", async () => {
    const user = userEvent.setup();
    const fetchMock = pmApi();
    renderRoute(`/projects/${PID}/client`);

    const flagged = await screen.findByRole("list", { name: "Client milestones" });
    expect(flagged).toHaveTextContent("Handover");
    const suggestions = screen.getByRole("list", { name: "Suggested milestones" });
    expect(within(suggestions).queryByText("Handover")).not.toBeInTheDocument(); // already used
    const structure = within(suggestions).getByLabelText("Structure complete");
    expect(structure).toHaveValue(TASKS[2]?.id); // the last frame task
    const row = structure.closest("li") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Add" }));
    await waitFor(() => {
      expect(bodyOf(fetchMock, `/tasks/${TASKS[2]?.id ?? ""}`)).toEqual({ client_milestone: true, milestone_name: "Structure complete" });
    });
  });

  it("shares selected photos", async () => {
    const user = userEvent.setup();
    const fetchMock = pmApi();
    renderRoute(`/projects/${PID}/client`);

    const share = await screen.findByRole("button", { name: "Share selected" });
    expect(share).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /Select Level 4 columns/ }));
    await user.click(share);
    await waitFor(() => {
      expect(bodyOf(fetchMock, `/projects/${PID}/photos/client-share`)).toEqual({ photo_ids: [PHOTO], shared: true });
    });
    expect(await screen.findByText("Shared with client")).toBeInTheDocument();
  });

  it("is read-only for roles that cannot publish", async () => {
    mockApi({
      ...sessionApi(makeMe("quantity_surveyor")),
      [`/api/v1/projects/${PID}`]: () => jsonResponse(DETAIL),
      [`/api/v1/projects/${PID}/handover`]: () => jsonResponse({ ...HANDOVER, can_publish: false }),
      [`/api/v1/projects/${PID}/tasks`]: () => jsonResponse({ tasks: TASKS, weight_total: "40.00" }),
      [`/api/v1/projects/${PID}/photos`]: () => jsonResponse(PHOTOS),
      [`/api/v1/photos/${PHOTO}`]: () => new Response(new Blob(["jpeg"]), { status: 200 }),
    });
    renderRoute(`/projects/${PID}/client`);
    await screen.findByRole("list", { name: "Client milestones" });
    expect(screen.queryByRole("button", { name: "Publish to the client" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm unchanged" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Share selected" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Suggested milestones" })).not.toBeInTheDocument();
  });
});

describe("Portal helpers", () => {
  it("describes a date against the contract", () => {
    expect(againstContract("2027-09-30", "2027-09-30")).toBe("on the contract date");
    expect(againstContract("2027-10-01", "2027-09-30")).toBe("1 day after the contract date");
    expect(againstContract("2027-10-28", "2027-09-30")).toBe("4 weeks after the contract date");
    expect(againstContract("2027-09-25", "2027-09-30")).toBe("5 days before the contract date");
  });

  it("guesses the last task with a keyword", () => {
    expect(guessTask(TASKS, ["frame"])?.name).toBe("Frame: level 5 to roof");
    expect(guessTask(TASKS, ["lift"])).toBeUndefined();
  });
});
