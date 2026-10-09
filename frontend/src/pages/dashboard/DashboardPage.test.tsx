import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { healthyApi, jsonResponse, mockApi, renderRoute } from "../../test/utils";

describe("DashboardPage", () => {
  it("shows live readings when the API and database are up", async () => {
    mockApi(healthyApi);
    renderRoute("/");

    const api = await screen.findByRole("article", { name: "API · liveness" });
    expect(await within(api).findByText("Online")).toBeInTheDocument();
    expect(within(api).getByText("api v0.0.1")).toBeInTheDocument();

    const db = screen.getByRole("article", { name: "Database · readiness" });
    expect(await within(db).findByText("Ready")).toBeInTheDocument();
  });

  it("reports a degraded database with a text label, not only colour", async () => {
    mockApi({
      ...healthyApi,
      "/api/v1/health/ready": () => jsonResponse({ status: "degraded", checks: { database: "unavailable" } }, 503),
    });
    renderRoute("/");

    const db = await screen.findByRole("article", { name: "Database · readiness" });
    expect(await within(db).findByText("Unavailable")).toBeInTheDocument();
    expect(await screen.findByText("The API is up but cannot reach PostgreSQL.")).toBeInTheDocument();
  });

  it("explains what to do when the API is unreachable", async () => {
    mockApi({});
    renderRoute("/");

    const api = await screen.findByRole("article", { name: "API · liveness" });
    expect(await within(api).findByText("Offline")).toBeInTheDocument();
    expect(await screen.findByText(/The API is not answering/)).toBeInTheDocument();
  });

  it("re-checks on demand", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(healthyApi);
    renderRoute("/");
    await screen.findAllByText("Online");
    const before = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Re-check now" }));

    await screen.findByRole("button", { name: "Re-check now" });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before);
  });

  it("lists every build phase with its status as text", async () => {
    mockApi(healthyApi);
    renderRoute("/");

    const programme = await screen.findByRole("list", { name: "Build phases and releases" });
    const items = within(programme).getAllByRole("listitem");
    expect(items).toHaveLength(15 + 2); // 15 phases plus the v0.1 and v1.0 releases
    expect(within(programme).getByText("Setup and foundations").closest("li")).toHaveTextContent("In progress");
    expect(within(programme).getByText("Client portal").closest("li")).toHaveTextContent("Planned");
    expect(within(programme).getByText(/Release v0.1 MVP/)).toBeInTheDocument();
  });
});
