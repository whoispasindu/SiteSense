import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { jsonResponse, makeMe, mockApi, renderRoute, sessionApi } from "../../test/utils";

describe("DashboardPage", () => {
  it("greets the signed-in user by first name", async () => {
    mockApi(sessionApi(makeMe("project_manager", { full_name: "Ruwan Silva" })));
    renderRoute("/");

    expect(await screen.findByRole("heading", { level: 1, name: /Ruwan\./ })).toBeInTheDocument();
  });

  it("shows live readings when the API and database are up", async () => {
    mockApi(sessionApi(makeMe("project_manager")));
    renderRoute("/");

    const api = await screen.findByRole("article", { name: "API · liveness" });
    expect(await within(api).findByText("Online")).toBeInTheDocument();
    expect(within(api).getByText("api v0.0.1")).toBeInTheDocument();

    const db = screen.getByRole("article", { name: "Database · readiness" });
    expect(await within(db).findByText("Ready")).toBeInTheDocument();
  });

  it("reports a degraded database with a text label, not only colour", async () => {
    mockApi({
      ...sessionApi(makeMe("project_manager")),
      "/api/v1/health/ready": () => jsonResponse({ status: "degraded", checks: { database: "unavailable" } }, 503),
    });
    renderRoute("/");

    const db = await screen.findByRole("article", { name: "Database · readiness" });
    expect(await within(db).findByText("Unavailable")).toBeInTheDocument();
    expect(await screen.findByText("The API is up but cannot reach PostgreSQL.")).toBeInTheDocument();
  });

  it("explains what to do when the API is unreachable", async () => {
    const authOnly = Object.fromEntries(
      Object.entries(sessionApi(makeMe("project_manager"))).filter(([path]) => !path.startsWith("/api/v1/health")),
    );
    mockApi(authOnly);
    renderRoute("/");

    const api = await screen.findByRole("article", { name: "API · liveness" });
    expect(await within(api).findByText("Offline")).toBeInTheDocument();
    expect(await screen.findByText(/The API is not answering/)).toBeInTheDocument();
  });

  it("re-checks on demand", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(sessionApi(makeMe("project_manager")));
    renderRoute("/");
    await screen.findAllByText("Online");
    const before = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Re-check now" }));

    await screen.findByRole("button", { name: "Re-check now" });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before);
  });

  it("lists every build phase with its status as text", async () => {
    mockApi(sessionApi(makeMe("project_manager")));
    renderRoute("/");

    const programme = await screen.findByRole("list", { name: "Build phases and releases" });
    const items = within(programme).getAllByRole("listitem");
    expect(items).toHaveLength(15 + 2); // 15 phases plus the v0.1 and v1.0 releases
    expect(within(programme).getByText("Setup and foundations").closest("li")).toHaveTextContent("Complete");
    expect(within(programme).getByText("Authentication, roles and users").closest("li")).toHaveTextContent(
      "In progress",
    );
    expect(within(programme).getByText("Client portal").closest("li")).toHaveTextContent("Planned");
    expect(within(programme).getByText(/Release v0.1 MVP/)).toBeInTheDocument();
  });
});
