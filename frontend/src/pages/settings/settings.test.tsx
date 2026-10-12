import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { NotificationPreferences } from "../../api/dashboard";
import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, sessionApi } from "../../test/utils";

const PM_PREFS: NotificationPreferences = {
  email_urgent: true,
  email_digest: true,
  weekly_report: true,
  weekly_report_available: true,
  stop_work_always: true,
  email_configured: false,
  digest_time: "18:30",
  weekly_time: "Monday 07:00",
};

function putBody(init: RequestInit | undefined): Record<string, unknown> {
  return JSON.parse(typeof init?.body === "string" ? init.body : "{}") as Record<string, unknown>;
}

function sentBody(fetchMock: ReturnType<typeof mockApi>): Record<string, unknown> {
  return putBody(fetchMock.mock.calls.find(([, init]) => init?.method === "PUT")?.[1]);
}

function prefsApi(role: "project_manager" | "site_engineer", prefs: NotificationPreferences, put?: () => Response) {
  return mockApi({
    ...sessionApi(makeMe(role)),
    "/api/v1/me/notification-preferences": (_url, init) =>
      init?.method === "PUT" ? (put?.() ?? jsonResponse({ ...prefs, ...putBody(init) })) : jsonResponse(prefs),
  });
}

describe("NotificationSettingsPage", () => {
  it("shows each choice, with stop-work locked on", async () => {
    prefsApi("project_manager", PM_PREFS);
    renderRoute("/settings/notifications");

    expect(await screen.findByRole("switch", { name: "Urgent alerts by email" })).toBeChecked();
    const stopWork = screen.getByRole("switch", { name: "Stop-work alerts" });
    expect(stopWork).toBeChecked();
    expect(stopWork).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Evening digest" })).toHaveAccessibleDescription(/18:30 site time/);
    expect(screen.getByRole("switch", { name: "Weekly report (PDF)" })).toHaveAccessibleDescription(/Monday 07:00/);
    expect(screen.getByText(/written to the server log/)).toBeInTheDocument();
  });

  it("saves only what changed, and only when something did", async () => {
    const user = userEvent.setup();
    const fetchMock = prefsApi("project_manager", PM_PREFS);
    renderRoute("/settings/notifications");

    const save = await screen.findByRole("button", { name: "Save choices" });
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("switch", { name: "Evening digest" }));
    await user.click(save);

    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(sentBody(fetchMock)).toEqual({ email_urgent: true, email_digest: false, weekly_report: true });
  });

  it("offers the weekly PDF only to cost roles, and never sends it for others", async () => {
    const user = userEvent.setup();
    const fetchMock = prefsApi("site_engineer", { ...PM_PREFS, weekly_report: false, weekly_report_available: false, email_configured: true });
    renderRoute("/settings/notifications");

    await user.click(await screen.findByRole("switch", { name: "Urgent alerts by email" }));
    expect(screen.queryByRole("switch", { name: "Weekly report (PDF)" })).not.toBeInTheDocument();
    expect(screen.queryByText(/written to the server log/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save choices" }));

    await screen.findByRole("status");
    expect(sentBody(fetchMock)).toEqual({ email_urgent: false, email_digest: true });
  });

  it("shows a save error", async () => {
    const user = userEvent.setup();
    prefsApi("project_manager", PM_PREFS, () => errorResponse(422, "business_rule", "The weekly report holds cost figures."));
    renderRoute("/settings/notifications");

    await user.click(await screen.findByRole("switch", { name: "Urgent alerts by email" }));
    await user.click(screen.getByRole("button", { name: "Save choices" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/cost figures/);
  });

  it("is reachable from the account menu", async () => {
    const user = userEvent.setup();
    mockApi({
      ...sessionApi(makeMe("project_manager")),
      "/api/v1/me/notification-preferences": () => jsonResponse(PM_PREFS),
      "/api/v1/projects": () => jsonResponse([]),
      "/api/v1/analytics/portfolio": () => errorResponse(500, "internal_error"),
      "/api/v1/briefing/today": () => errorResponse(500, "internal_error"),
      "/api/v1/notifications": () => jsonResponse({ unread: 0, items: [] }),
      "/api/v1/reports/today": () => jsonResponse({ date: "2026-10-12", deadline: "2026-10-12T18:00:00+05:30", deadline_passed: false, projects: [] }),
    });
    renderRoute("/");

    await user.click(await screen.findByRole("button", { name: /Kasun Perera/ }));
    await user.click(screen.getByRole("link", { name: "Email settings" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Email alerts" })).toBeInTheDocument();
  });
});
