import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Role } from "../../api/auth";
import type { ProjectDetail } from "../../api/projects";
import type { ReportDetail, Weather } from "../../api/reports";
import type { Task } from "../../api/schedule";
import { isHeavyRain, summaryIcon, weatherIcon } from "../../features/reports/weather";
import { safeInternalLink } from "../../api/notifications";
import { addDaysIso, siteTodayIso, timeAgo } from "../../lib/time";
import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi } from "../../test/utils";

const SITE = { id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" };
const PID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const RID = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e";
const PHOTO = "3c4d5e6f-7a8b-4c9d-8e0f-2a3b4c5d6e7f";
const TID = "5e6f7a8b-9c0d-4e1f-8a2b-3c4d5e6f7a8b";
const TODAY = siteTodayIso();

const PROJECT: ProjectDetail = {
  id: PID, code: "HR-2026-01", name: "Havelock Residences", site: SITE, client_name: "Havelock Developers",
  project_type: "residential", status: "active", contract_value: "1114000000.00", start_date: "2026-03-02",
  planned_end: "2027-09-30", boq_total: "0.00", budget_total: "0.00", item_count: 0, description: null,
  sections: [], team: [], created_at: "2026-10-01T08:00:00+00:00", updated_at: "2026-10-01T08:00:00+00:00",
};

const TASK: Task = {
  id: TID, project_id: PID, code: "T-040", name: "Frame: ground to level 4", boq_section_id: null,
  boq_section_code: null, planned_start: "2026-06-15", planned_end: "2026-12-30", weight: "17.10",
  percent_complete: "71.20", is_critical: true, position: 1, planned_percent_today: 84.8, state: "behind",
  progress_updated_at: null,
};

const WEATHER: Weather = {
  site_code: "COL-07", available: true, stale: false, fetched_at: "2026-10-09T18:58:16+00:00", message: null,
  heavy_rain_threshold_mm: "10.0",
  days: [0, 1, 2, 3, 4].map((i) => ({
    date: addDaysIso(TODAY, i), summary: i === 0 ? "Thunderstorm" : "Partly cloudy", weather_code: i === 0 ? 95 : 2,
    temp_max_c: "29.6", temp_min_c: "23.6", rain_mm: i === 0 ? "19.7" : "0.0", rain_probability: i === 0 ? 100 : 10,
  })),
};

const REPORT: ReportDetail = {
  id: RID, project_id: PID, project_name: "Havelock Residences", report_date: TODAY,
  author: { id: "6f0d3c1e-8a7b-4c2d-9e1f-0a1b2c3d4e5f", full_name: "Kasun Perera" },
  weather_summary: "Thunderstorm", temp_max_c: "29.6", temp_min_c: "23.6", rain_mm: "19.7", weather_source: "forecast",
  crew_count: 47, work_done: "Level 4 slab reinforcement on grids A to F.", problems: "Cement delivery late again.",
  submitted_at: "2026-10-10T03:10:00+00:00", updated_at: "2026-10-10T03:10:00+00:00",
  photos: [{ id: PHOTO, caption: "Level 4 rebar", width: 1200, height: 800, size_bytes: 120000, created_at: "2026-10-10T03:11:00+00:00" }],
  progress: [{ task_id: TID, task_name: "Frame: ground to level 4", percent_before: "71.20", percent_after: "74.00" }],
  editable: true, photo_limit: 12,
};

const SUMMARY_ITEM = {
  id: RID, project_id: PID, report_date: TODAY, author: REPORT.author, weather_summary: "Thunderstorm", rain_mm: "19.7",
  crew_count: 47, work_done_preview: "Level 4 slab reinforcement", has_problems: true, photo_count: 1, progress_count: 1,
  submitted_at: REPORT.submitted_at,
};

type Handler = (url: string, init?: RequestInit) => Response;

function reportsApi(role: Role, extra: Record<string, Handler> = {}) {
  return mockApi({
    ...sessionApi(makeMe(role)),
    [`/api/v1/projects/${PID}`]: () => jsonResponse(PROJECT),
    [`/api/v1/projects/${PID}/weather`]: () => jsonResponse(WEATHER),
    [`/api/v1/projects/${PID}/tasks`]: () => jsonResponse({ tasks: [TASK], weight_total: "17.10" }),
    [`/api/v1/projects/${PID}/reports`]: (_url, init) =>
      init?.method === "POST" ? jsonResponse(REPORT, 201) : jsonResponse({ items: [], total: 0 }),
    [`/api/v1/reports/${RID}`]: () => jsonResponse(REPORT),
    [`/api/v1/reports/${RID}/photos`]: () => jsonResponse(REPORT.photos[0], 201),
    [`/api/v1/photos/${PHOTO}`]: () =>
      new Response(new Uint8Array([0xff, 0xd8, 0xff]), { headers: { "Content-Type": "image/jpeg" } }),
    "/api/v1/notifications": () => jsonResponse({ items: [], unread: 0 }),
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

describe("Project reports tab", () => {
  it("shows the five-day forecast with heavy rain called out", async () => {
    reportsApi("project_manager");
    renderRoute(`/projects/${PID}/reports`);

    // Wait on the forecast's own content with a text query, then check the list by role once. This page
    // loads through three chained requests; a findByRole here re-runs a whole-page role query on every
    // render while it loads, which made this test miss the 1 s default under coverage (issue #17).
    await screen.findByText("Thunderstorm");
    const strip = screen.getByRole("list", { name: "Five-day forecast for site COL-07" });
    const days = within(strip).getAllByRole("listitem");
    expect(days).toHaveLength(5);
    expect(days[0]).toHaveTextContent("Today");
    expect(days[0]).toHaveTextContent("Thunderstorm");
    expect(days[0]).toHaveTextContent("Heavy rain: check concrete pours");
    expect(days[1]).not.toHaveTextContent("Heavy rain");
  });

  it("warns and keeps the last forecast when the weather service is down (TC-08)", async () => {
    reportsApi("project_manager", {
      [`/api/v1/projects/${PID}/weather`]: () =>
        jsonResponse({ ...WEATHER, stale: true, message: "The weather service is unavailable. Showing the last saved forecast." }),
    });
    renderRoute(`/projects/${PID}/reports`);

    expect(await screen.findByText(/weather service is unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /Five-day forecast/ })).toBeInTheDocument();
  });

  it("lists reports and offers today's report only to site engineers", async () => {
    reportsApi("site_engineer");
    renderRoute(`/projects/${PID}/reports`);

    expect(await screen.findByRole("link", { name: /Write today's report/ })).toHaveAttribute(
      "href",
      `/projects/${PID}/reports/new`,
    );
  });

  it("hides the write button once today's report is filed, and lists it", async () => {
    reportsApi("site_engineer", {
      [`/api/v1/projects/${PID}/reports`]: () => jsonResponse({ items: [SUMMARY_ITEM], total: 1 }),
    });
    renderRoute(`/projects/${PID}/reports`);

    const list = await screen.findByRole("list", { name: "Daily reports, newest first" });
    expect(within(list).getByRole("link")).toHaveAttribute("href", `/reports/${RID}`);
    expect(within(list).getByText("Problems noted")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Write today's report/ })).not.toBeInTheDocument();
  });

  it("does not offer reports to project managers", async () => {
    reportsApi("project_manager");
    renderRoute(`/projects/${PID}/reports`);

    expect(await screen.findByText("No reports yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Write today's report/ })).not.toBeInTheDocument();
  });
});

describe("Daily report form", () => {
  beforeEach(() => {
    vi.stubGlobal("createImageBitmap", undefined);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("pre-fills the weather from the forecast", async () => {
    reportsApi("site_engineer");
    renderRoute(`/projects/${PID}/reports/new`);

    await waitFor(() => {
      expect(screen.getByLabelText("Conditions")).toHaveValue("Thunderstorm");
    });
    expect(screen.getByLabelText("Max °C")).toHaveValue("29.6");
    expect(screen.getByLabelText("Rainfall (mm)")).toHaveValue("19.7");
    expect(screen.getByText("Filled from the forecast")).toBeInTheDocument();
    expect(screen.getByLabelText("Report date")).toHaveValue(TODAY);
  });

  it("validates required fields before sending anything", async () => {
    const user = userEvent.setup();
    const fetchMock = reportsApi("site_engineer");
    renderRoute(`/projects/${PID}/reports/new`);

    await user.click(await screen.findByRole("button", { name: "Submit report" }));

    expect(await screen.findByText("Describe the work done (at least 10 characters).")).toBeInTheDocument();
    expect(screen.getByText("Enter the number of people on site (0 to 5000).")).toBeInTheDocument();
    expect(requestTo(fetchMock, `/projects/${PID}/reports`)?.method).not.toBe("POST");
  });

  it("submits the report with changed progress, uploads photos and opens the report", async () => {
    const user = userEvent.setup();
    const fetchMock = reportsApi("site_engineer");
    const { router } = renderRoute(`/projects/${PID}/reports/new`);

    await waitFor(() => {
      expect(screen.getByLabelText("Conditions")).toHaveValue("Thunderstorm");
    });
    await user.type(screen.getByLabelText("Crew on site"), "47");
    await user.type(screen.getByLabelText("Work done"), "Level 4 slab reinforcement on grids A to F.");
    await user.type(screen.getByLabelText("Problems (optional)"), "Cement late.");
    await user.type(screen.getByLabelText("Percent complete for Frame: ground to level 4"), "74");
    await user.upload(screen.getByLabelText(/Add photos/), new File([new Uint8Array([0xff, 0xd8, 0xff])], "rebar.jpg", { type: "image/jpeg" }));
    await user.type(screen.getByLabelText("Caption for photo 1"), "Rebar");

    await user.click(screen.getByRole("button", { name: "Submit report" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/reports/${RID}`);
    });
    const body = bodyOf(requestTo(fetchMock, `/projects/${PID}/reports`));
    expect(body).toMatchObject({
      report_date: TODAY, crew_count: 47, problems: "Cement late.", weather_summary: "Thunderstorm",
      rain_mm: "19.7", weather_source: "forecast", progress: [{ task_id: TID, percent_complete: "74" }],
    });
    const upload = requestTo(fetchMock, `/reports/${RID}/photos`);
    expect(upload?.body).toBeInstanceOf(FormData);
    expect((upload?.body as FormData).get("caption")).toBe("Rebar");
  });

  it("marks weather as entered by hand once it is edited", async () => {
    const user = userEvent.setup();
    const fetchMock = reportsApi("site_engineer");
    renderRoute(`/projects/${PID}/reports/new`);

    await waitFor(() => {
      expect(screen.getByLabelText("Conditions")).toHaveValue("Thunderstorm");
    });
    await user.clear(screen.getByLabelText("Conditions"));
    await user.type(screen.getByLabelText("Conditions"), "Dry morning, storm after 2 pm");
    await user.type(screen.getByLabelText("Crew on site"), "40");
    await user.type(screen.getByLabelText("Work done"), "Blockwork on level 2 continued.");
    await user.click(screen.getByRole("button", { name: "Submit report" }));

    await waitFor(() => {
      expect(requestTo(fetchMock, `/projects/${PID}/reports`)).toBeDefined();
    });
    expect(bodyOf(requestTo(fetchMock, `/projects/${PID}/reports`))).toMatchObject({
      weather_summary: "Dry morning, storm after 2 pm", temp_max_c: "29.6", weather_source: "manual", progress: [],
    });
  });

  it("links to the existing report when today's is already filed (TC-03)", async () => {
    const user = userEvent.setup();
    reportsApi("site_engineer", {
      [`/api/v1/projects/${PID}/reports`]: () =>
        jsonResponse(
          { error: { code: "conflict", message: "A report for 10 Oct 2026 already exists. Open it to make changes.",
                     request_id: "r", details: [{ field: "report_date", report_id: RID }] } },
          409,
        ),
    });
    renderRoute(`/projects/${PID}/reports/new`);

    await user.type(await screen.findByLabelText("Crew on site"), "40");
    await user.type(screen.getByLabelText("Work done"), "Blockwork on level 2 continued.");
    await user.click(screen.getByRole("button", { name: "Submit report" }));

    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the existing report" })).toHaveAttribute("href", `/reports/${RID}`);
    expect(screen.getByRole("button", { name: "Submit report" })).toBeEnabled();
  });

  it("is only for site engineers", async () => {
    reportsApi("project_manager");
    renderRoute(`/projects/${PID}/reports/new`);

    expect(await screen.findByRole("heading", { name: "Authorised personnel only." })).toBeInTheDocument();
  });
});

describe("Report detail", () => {
  it("shows the full report, progress and photos to the PM without editing", async () => {
    reportsApi("project_manager", {
      [`/api/v1/reports/${RID}`]: () => jsonResponse({ ...REPORT, editable: false }),
    });
    renderRoute(`/reports/${RID}`);

    expect(await screen.findByRole("heading", { level: 1, name: /Daily report/ })).toBeInTheDocument();
    expect(screen.getByText("Level 4 slab reinforcement on grids A to F.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Problems" })).toHaveTextContent("Cement delivery late again.");
    const progress = screen.getByRole("table", { name: "Task progress reported" });
    expect(within(progress).getByRole("row", { name: /Frame/ })).toHaveTextContent("71.2%74%+2.8 pts");
    expect(screen.getByText("19.7 mm")).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: "Level 4 rebar" })).toHaveAttribute("src", expect.stringMatching(/^data:image\/jpeg/));
    expect(screen.queryByRole("button", { name: /Correct report/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove photo/ })).not.toBeInTheDocument();
  });

  it("lets the author correct the report on the day", async () => {
    const user = userEvent.setup();
    const fetchMock = reportsApi("site_engineer", {
      [`/api/v1/reports/${RID}`]: (_url, init) =>
        jsonResponse(init?.method === "PATCH" ? { ...REPORT, crew_count: 50 } : REPORT),
    });
    renderRoute(`/reports/${RID}`);

    await user.click(await screen.findByRole("button", { name: /Correct report/ }));
    const dialog = screen.getByRole("dialog", { name: "Correct the report" });
    await user.clear(within(dialog).getByLabelText("Crew on site"));
    await user.type(within(dialog).getByLabelText("Crew on site"), "50");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(true);
    });
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH")?.[1];
    expect(bodyOf(patch)).toEqual({ crew_count: 50, work_done: REPORT.work_done, problems: REPORT.problems });
  });

  it("reports upload failures after saving", async () => {
    reportsApi("site_engineer");
    const { router } = renderRoute(`/reports/${RID}`);
    await screen.findByRole("heading", { level: 1 });

    await router.navigate(`/reports/${RID}`, { state: { uploadFailures: ["big.png: Photos can be at most 10 MB."] } });

    expect(await screen.findByText("The report was saved, but some photos were not")).toBeInTheDocument();
    expect(screen.getByText("big.png: Photos can be at most 10 MB.")).toBeInTheDocument();
  });

  it("shows not found for reports outside the user's sites", async () => {
    reportsApi("site_engineer", { [`/api/v1/reports/${RID}`]: () => errorResponse(404, "not_found") });
    renderRoute(`/reports/${RID}`);

    expect(await screen.findByRole("heading", { name: "Off the drawings." })).toBeInTheDocument();
  });
});

describe("Site reports page", () => {
  const status = (overrides: object = {}) => ({
    date: TODAY, deadline: `${TODAY}T18:00:00+05:30`, deadline_passed: false,
    projects: [
      { project_id: PID, project_code: "HR-2026-01", project_name: "Havelock Residences", site_code: "COL-07",
        report_id: RID, submitted_at: REPORT.submitted_at, author_name: "Kasun Perera" },
      { project_id: "1a1b1c1d-2e2f-4a3b-8c4d-5e6f7a8b9c0d", project_code: "PRO-1", project_name: "Peradeniya Road",
        site_code: "KDY-02", report_id: null, submitted_at: null, author_name: null },
    ],
    ...overrides,
  });

  it("shows which projects have filed and lets engineers write the missing one", async () => {
    reportsApi("site_engineer", { "/api/v1/reports/today": () => jsonResponse(status()) });
    renderRoute("/reports");

    expect(await screen.findByText("1 of 2 still to file.")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Today's reports" });
    const [filed, missing] = within(list).getAllByRole("listitem");
    expect(filed).toHaveTextContent("Filed by Kasun Perera");
    expect(within(filed!).getByRole("link", { name: "Open" })).toHaveAttribute("href", `/reports/${RID}`);
    expect(missing).toHaveTextContent("Not filed");
    expect(within(missing!).getByRole("link", { name: "Write report" })).toBeInTheDocument();
  });

  it("marks missing reports overdue after the deadline, without a write button for the PM", async () => {
    reportsApi("project_manager", { "/api/v1/reports/today": () => jsonResponse(status({ deadline_passed: true })) });
    renderRoute("/reports");

    expect(await screen.findByText("1 of 2 still to file, past the deadline.")).toBeInTheDocument();
    expect(screen.getByText("Overdue")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Write report" })).not.toBeInTheDocument();
  });
});

describe("Notifications", () => {
  const notes = {
    unread: 1,
    items: [
      { id: "8d9e0f1a-2b3c-4d5e-8f6a-7b8c9d0e1f2a", kind: "report_missing", title: "Daily report missing: Havelock",
        body: "Please submit it now.", link: `/projects/${PID}/reports/new`, created_at: new Date().toISOString(), read_at: null },
      { id: "9e0f1a2b-3c4d-4e5f-9a6b-8c9d0e1f2a3b", kind: "report_submitted", title: "Old one", body: "Read already.",
        link: "https://evil.example", created_at: "2026-10-01T08:00:00+00:00", read_at: "2026-10-01T09:00:00+00:00" },
    ],
  };

  it("shows the unread count and opens the linked page", async () => {
    const user = userEvent.setup();
    const fetchMock = reportsApi("site_engineer", {
      "/api/v1/notifications": () => jsonResponse(notes),
      "/read": () => jsonResponse({ ...notes.items[0], read_at: new Date().toISOString() }),
    });
    const { router } = renderRoute("/reports");

    await user.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
    const panel = screen.getByRole("region", { name: "Notifications" });
    expect(within(panel).getByText("just now")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: /Daily report missing/ }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/projects/${PID}/reports/new`);
    });
    expect(requestTo(fetchMock, `/notifications/${notes.items[0]!.id}/read`)?.method).toBe("POST");
  });

  it("never follows external links and can mark everything read", async () => {
    const user = userEvent.setup();
    const fetchMock = reportsApi("site_engineer", {
      "/api/v1/notifications": () => jsonResponse(notes),
      "/read-all": () => new Response(null, { status: 204 }),
    });
    const { router } = renderRoute("/reports");

    await user.click(await screen.findByRole("button", { name: /Notifications/ }));
    await user.click(screen.getByRole("button", { name: /Old one/ }));
    expect(router.state.location.pathname).toBe("/reports");

    await user.click(await screen.findByRole("button", { name: /Notifications/ }));
    await user.click(screen.getByRole("button", { name: "Mark all read" }));
    await waitFor(() => {
      expect(requestTo(fetchMock, "/notifications/read-all")?.method).toBe("POST");
    });
  });
});

describe("report helpers", () => {
  it("maps weather to pictures and flags heavy rain", () => {
    expect(weatherIcon(0)).toBe("sun");
    expect(weatherIcon(63)).toBe("rain");
    expect(weatherIcon(95)).toBe("storm");
    expect(weatherIcon(3)).toBe("cloud");
    expect(weatherIcon(null)).toBe("cloud");
    expect(summaryIcon("Light showers")).toBe("rain");
    expect(summaryIcon("Thunderstorm with hail")).toBe("storm");
    expect(summaryIcon("Clear sky")).toBe("sun");
    expect(isHeavyRain({ rain_mm: "10.1" }, "10.0")).toBe(true);
    expect(isHeavyRain({ rain_mm: "10.0" }, "10.0")).toBe(false);
    expect(isHeavyRain({ rain_mm: null }, "10.0")).toBe(false);
  });

  it("only allows in-app notification links", () => {
    expect(safeInternalLink("/reports/1")).toBe("/reports/1");
    expect(safeInternalLink("//evil.example")).toBeNull();
    expect(safeInternalLink("https://evil.example")).toBeNull();
    expect(safeInternalLink(null)).toBeNull();
  });

  it("does site-calendar arithmetic", () => {
    expect(siteTodayIso(new Date("2026-10-09T19:00:00Z"))).toBe("2026-10-10"); // after midnight in Colombo
    expect(addDaysIso("2026-12-30", 3)).toBe("2027-01-02");
    const now = new Date("2026-10-10T12:00:00Z");
    expect(timeAgo("2026-10-10T11:55:00Z", now)).toBe("5 min ago");
    expect(timeAgo("2026-10-10T09:00:00Z", now)).toBe("3 h ago");
    expect(timeAgo("2026-10-09T10:00:00Z", now)).toBe("yesterday");
    expect(timeAgo("2026-10-06T10:00:00Z", now)).toBe("4 days ago");
  });
});

describe("Report photos and corrections", () => {
  const PHOTO_2 = "4d5e6f7a-8b9c-4d0e-9f1a-3b4c5d6e7f8a";
  const twoPhotos: ReportDetail = {
    ...REPORT,
    photos: [...REPORT.photos, { ...REPORT.photos[0]!, id: PHOTO_2, caption: null }],
  };
  const jpeg = () => new Response(new Uint8Array([0xff, 0xd8, 0xff]), { headers: { "Content-Type": "image/jpeg" } });

  beforeEach(() => {
    vi.stubGlobal("createImageBitmap", undefined);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens photos in a viewer and steps through them", async () => {
    const user = userEvent.setup();
    reportsApi("project_manager", {
      [`/api/v1/reports/${RID}`]: () => jsonResponse({ ...twoPhotos, editable: false }),
      [`/api/v1/photos/${PHOTO_2}`]: jpeg,
    });
    renderRoute(`/reports/${RID}`);

    await user.click(await screen.findByRole("button", { name: "Open photo 1: Level 4 rebar" }));
    const viewer = screen.getByRole("dialog", { name: "Photo 1 of 2" });
    expect(within(viewer).getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(within(viewer).getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "Photo 2 of 2" })).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Next" })).toBeDisabled();
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Previous" }));
    expect(screen.getByRole("dialog", { name: "Photo 1 of 2" })).toBeInTheDocument();
  });

  it("says so when a photo cannot be loaded", async () => {
    reportsApi("project_manager", { [`/api/v1/photos/${PHOTO}`]: () => errorResponse(404, "not_found") });
    renderRoute(`/reports/${RID}`);

    expect(await screen.findByRole("img", { name: "Level 4 rebar (could not load)" })).toBeInTheDocument();
  });

  it("lets the author remove a photo", async () => {
    const user = userEvent.setup();
    const fetchMock = reportsApi("site_engineer", {
      [`/api/v1/photos/${PHOTO}`]: (_url, init) => (init?.method === "DELETE" ? new Response(null, { status: 204 }) : jpeg()),
    });
    renderRoute(`/reports/${RID}`);

    await user.click(await screen.findByRole("button", { name: "Remove photo 1" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true);
    });
  });

  it("lets the author add photos and reports the ones that fail", async () => {
    const user = userEvent.setup();
    let uploads = 0;
    const fetchMock = reportsApi("site_engineer", {
      [`/api/v1/reports/${RID}/photos`]: () => {
        uploads += 1;
        return uploads === 1
          ? jsonResponse(REPORT.photos[0], 201)
          : errorResponse(422, "photo_rejected", "Only JPEG, PNG or WebP photos can be uploaded.");
      },
    });
    renderRoute(`/reports/${RID}`);

    const picker = await screen.findByLabelText(/Add photos \(11 left\)/);
    await user.upload(picker, [
      new File([new Uint8Array([1])], "ok.jpg", { type: "image/jpeg" }),
      new File([new Uint8Array([2])], "bad.jpg", { type: "image/jpeg" }),
    ]);
    await user.click(screen.getByRole("button", { name: "Remove photo 2" }));
    await user.upload(screen.getByLabelText(/Add photos/), new File([new Uint8Array([2])], "bad.jpg", { type: "image/jpeg" }));
    await user.click(screen.getByRole("button", { name: "Upload 2 photos" }));

    expect(await screen.findByText("Some photos were not added")).toBeInTheDocument();
    expect(screen.getByText("bad.jpg: Only JPEG, PNG or WebP photos can be uploaded.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => urlOf(input).endsWith(`/reports/${RID}/photos`))).toHaveLength(2);
  });

  it("checks corrections before saving them", async () => {
    const user = userEvent.setup();
    const fetchMock = reportsApi("site_engineer");
    renderRoute(`/reports/${RID}`);

    await user.click(await screen.findByRole("button", { name: /Correct report/ }));
    const dialog = screen.getByRole("dialog", { name: "Correct the report" });
    const crew = within(dialog).getByLabelText("Crew on site");
    const save = within(dialog).getByRole("button", { name: "Save changes" });

    await user.clear(crew);
    await user.type(crew, "lots");
    await user.click(save);
    expect(within(dialog).getByText("Crew must be a whole number from 0 to 5000.")).toBeInTheDocument();

    await user.clear(crew);
    await user.type(crew, "40");
    await user.clear(within(dialog).getByLabelText("Work done"));
    await user.type(within(dialog).getByLabelText("Work done"), "Short");
    await user.click(save);
    expect(within(dialog).getByText("Describe the work done (at least 10 characters).")).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText("Work done"), " but now long enough.");
    await user.clear(within(dialog).getByLabelText("Rainfall (mm)"));
    await user.type(within(dialog).getByLabelText("Rainfall (mm)"), "-3");
    await user.click(save);
    expect(within(dialog).getByText("Rainfall must be a number from 0 to 2000 mm.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(false);

    await user.clear(within(dialog).getByLabelText("Rainfall (mm)"));
    await user.type(within(dialog).getByLabelText("Rainfall (mm)"), "4.5");
    await user.click(save);
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(true);
    });
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH")?.[1];
    expect(bodyOf(patch)).toMatchObject({ crew_count: 40, rain_mm: "4.5", weather_source: "manual" });
  });
});

describe("Reports tab edge cases", () => {
  it("explains when the site has no coordinates for weather", async () => {
    reportsApi("project_manager", {
      [`/api/v1/projects/${PID}/weather`]: () =>
        jsonResponse({ ...WEATHER, available: false, days: [], message: "Add the site's coordinates (Admin, Sites) to see its weather." }),
    });
    renderRoute(`/projects/${PID}/reports`);

    expect(await screen.findByText("Add the site's coordinates (Admin, Sites) to see its weather.")).toBeInTheDocument();
  });

  it("pages through a long report history", async () => {
    const user = userEvent.setup();
    const fetchMock = reportsApi("project_manager", {
      [`/api/v1/projects/${PID}/reports`]: () =>
        jsonResponse({ items: [{ ...SUMMARY_ITEM, report_date: addDaysIso(TODAY, -1) }], total: 45 }),
    });
    renderRoute(`/projects/${PID}/reports`);

    const newer = await screen.findByRole("button", { name: "Newer" });
    expect(newer).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Older" }));
    await user.click(screen.getByRole("button", { name: "Older" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Older" })).toBeDisabled();
    });
    await user.click(screen.getByRole("button", { name: "Newer" }));

    const offsets = fetchMock.mock.calls
      .map(([input]) => urlOf(input))
      .filter((url) => url.includes(`/projects/${PID}/reports?`))
      .map((url) => new URL(url, "http://x").searchParams.get("offset"));
    expect(offsets).toEqual(expect.arrayContaining(["0", "20", "40"]));
  });
});

describe("Weather strip values", () => {
  it("shows dashes for values the forecast does not have", async () => {
    reportsApi("project_manager", {
      [`/api/v1/projects/${PID}/weather`]: () =>
        jsonResponse({
          ...WEATHER,
          days: [{ ...WEATHER.days[1]!, temp_max_c: null, temp_min_c: null, rain_mm: null, rain_probability: null, weather_code: null }],
        }),
    });
    renderRoute(`/projects/${PID}/reports`);

    const day = within(await screen.findByRole("list", { name: /Five-day forecast/ })).getByRole("listitem");
    expect(day).toHaveTextContent("—");
    expect(day).toHaveTextContent("Rain —");
    expect(day).not.toHaveTextContent("%");
  });
});
