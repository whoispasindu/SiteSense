import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Role } from "../api/auth";
import { errorResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi, tokenResponse } from "../test/utils";
import { safeNextPath } from "./context";

describe("safeNextPath", () => {
  it.each([
    ["/admin/users", "/admin/users"],
    ["/admin/users?tab=2", "/admin/users?tab=2"],
    [null, "/"],
    ["", "/"],
    ["https://evil.example", "/"],
    ["//evil.example/phish", "/"],
    ["/\\evil.example", "/"],
    ["javascript:alert(1)", "/"],
    ["/sign-in", "/"],
  ])("maps %s to %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });
});

describe("route guards", () => {
  it("sends signed-out visitors to sign-in and remembers where they were going", async () => {
    mockApi(sessionApi(null));
    const { router } = renderRoute("/admin/users");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(router.state.location.search).toBe("?next=%2Fadmin%2Fusers");
  });

  it("forces a password change before anything else", async () => {
    mockApi(sessionApi(makeMe("admin", { must_change_password: true })));
    const { router } = renderRoute("/admin/users");

    expect(await screen.findByRole("heading", { name: "Set your own password" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/change-password");
  });

  it("shows the restricted-area page when a role opens a page it may not use", async () => {
    mockApi(sessionApi(makeMe("site_engineer")));
    renderRoute("/admin/users");

    expect(await screen.findByRole("heading", { name: "Authorised personnel only." })).toBeInTheDocument();
    expect(screen.getByRole("banner")).not.toHaveTextContent("Users");
  });

  it("keeps signed-in users away from the sign-in page", async () => {
    mockApi(sessionApi(makeMe("project_manager")));
    const { router } = renderRoute("/sign-in");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
  });
});

const MENU: Record<Role, { visible: string[]; hidden: string[] }> = {
  admin: {
    visible: ["Dashboard", "Users", "Sites", "Audit log"],
    hidden: ["Projects", "Materials", "Client portal"],
  },
  project_manager: {
    visible: ["Dashboard", "Projects", "Risk & what-if", "Cost & claims"],
    hidden: ["Users", "Audit log", "Client portal"],
  },
  quantity_surveyor: {
    visible: ["Projects", "Materials", "Cost & claims"],
    hidden: ["Users", "Sites", "Client portal"],
  },
  site_engineer: {
    visible: ["Dashboard", "Site reports", "Materials"],
    hidden: ["Users", "Risk & what-if", "Cost & claims"],
  },
  procurement_officer: {
    visible: ["Dashboard", "Materials"],
    hidden: ["Users", "Site reports", "Cost & claims"],
  },
  client: {
    visible: ["Client portal"],
    hidden: ["Projects", "Materials", "Users", "Cost & claims", "Risk & what-if"],
  },
};

describe("role-based menu (Phase 1 'Done when')", () => {
  it.each(Object.entries(MENU))("%s sees only its own menu", async (role, { visible, hidden }) => {
    mockApi(sessionApi(makeMe(role as Role)));
    renderRoute("/");

    const nav = await screen.findByRole("navigation", { name: "Main" });
    for (const label of visible) expect(within(nav).getByText(label)).toBeInTheDocument();
    for (const label of hidden) expect(within(nav).queryByText(label)).not.toBeInTheDocument();
  });

  it("gives clients their own home instead of the internal dashboard", async () => {
    mockApi(sessionApi(makeMe("client", { full_name: "Mr. Jayawardena" })));
    renderRoute("/");

    expect(await screen.findByRole("heading", { name: "Welcome, Mr. Jayawardena." })).toBeInTheDocument();
    expect(screen.queryByText("System readings")).not.toBeInTheDocument();
  });
});

describe("session lifecycle", () => {
  it("signs out and returns to the sign-in page", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(sessionApi(makeMe("project_manager")));
    const { router } = renderRoute("/");

    await user.click(await screen.findByRole("button", { name: /Kasun Perera/ }));
    await user.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/sign-in");
      expect(router.state.location.search).toBe("");
    });
    expect(requestTo(fetchMock, "/auth/logout") !== undefined).toBe(true);
  });

  it("returns to sign-in when the session can no longer be refreshed", async () => {
    let refreshes = 0;
    mockApi({
      ...sessionApi(makeMe("admin")),
      "/api/v1/auth/refresh": () => {
        refreshes += 1;
        return refreshes === 1 ? tokenResponse(makeMe("admin")) : errorResponse(401, "session_expired");
      },
      "/api/v1/admin/users": () => errorResponse(401, "token_expired"),
      "/api/v1/admin/sites": () => errorResponse(401, "token_expired"),
    });
    const { router } = renderRoute("/admin/users");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/sign-in");
    });
  });
});
