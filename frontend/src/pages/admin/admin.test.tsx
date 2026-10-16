import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { AdminUser, AuditLogEntry, Site } from "../../api/admin";
import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi } from "../../test/utils";

const ADMIN = makeMe("admin", { id: "00000000-0000-4000-8000-000000000001", full_name: "Dilani Admin", sites: [] });

const SITE_A: Site = {
  id: "11111111-1111-4111-8111-111111111111",
  code: "COL-07",
  name: "Havelock Residences",
  location: "Colombo 05",
  latitude: 6.8836,
  longitude: 79.865,
  is_active: true,
  created_at: "2026-10-01T08:00:00+00:00",
};
const SITE_B: Site = { ...SITE_A, id: "22222222-2222-4222-8222-222222222222", code: "KDY-02", name: "Peradeniya Road Offices", location: "Kandy", latitude: null, longitude: null };

function makeUser(overrides: Partial<AdminUser>): AdminUser {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    email: "kasun@site.lk",
    full_name: "Kasun Perera",
    role: "site_engineer",
    role_label: "Site Engineer",
    is_active: true,
    is_locked: false,
    must_change_password: false,
    last_login_at: "2026-10-09T03:30:00+00:00",
    created_at: "2026-10-01T08:00:00+00:00",
    sites: [{ id: SITE_A.id, code: SITE_A.code, name: SITE_A.name }],
    projects: [],
    mfa_enabled: false,
    ...overrides,
  };
}

const KASUN = makeUser({});
const FATHIMA = makeUser({
  id: "44444444-4444-4444-8444-444444444444",
  email: "fathima@site.lk",
  full_name: "Fathima Rizvi",
  role: "procurement_officer",
  role_label: "Procurement Officer",
  sites: [],
  is_locked: true,
});
const SELF: AdminUser = makeUser({ id: ADMIN.id, email: ADMIN.email, full_name: ADMIN.full_name, role: "admin", role_label: "Company Admin", sites: [] });

function page(items: unknown[]) {
  return jsonResponse({ items, total: items.length, limit: 100, offset: 0 });
}

function adminApi(overrides: Record<string, (url: string, init?: RequestInit) => Response> = {}) {
  return mockApi({
    ...sessionApi(ADMIN),
    "/api/v1/admin/users": () => page([KASUN, FATHIMA, SELF]),
    "/api/v1/admin/sites": () => jsonResponse([SITE_A, SITE_B]),
    ...overrides,
  });
}

describe("UsersPage", () => {
  it("lists users with role, sites and a text status", async () => {
    adminApi();
    renderRoute("/admin/users");

    const table = await screen.findByRole("table", { name: "Company users" });
    const kasun = (await within(table).findByText("Kasun Perera")).closest("tr")!;
    expect(kasun).toHaveTextContent("COL-07");
    expect(kasun).toHaveTextContent("Active");
    const fathima = within(table).getByText("Fathima Rizvi").closest("tr")!;
    expect(fathima).toHaveTextContent("All sites");
    expect(fathima).toHaveTextContent("Locked");
  });

  it("filters by search text and role", async () => {
    const user = userEvent.setup();
    adminApi();
    renderRoute("/admin/users");
    const table = await screen.findByRole("table", { name: "Company users" });
    await within(table).findByText("Kasun Perera");

    await user.type(screen.getByRole("searchbox", { name: "Search users" }), "fathima");
    expect(within(table).queryByText("Kasun Perera")).not.toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox", { name: "Search users" }));
    await user.click(screen.getByRole("button", { name: "Site Engineer" }));
    expect(within(table).queryByText("Fathima Rizvi")).not.toBeInTheDocument();
    expect(within(table).getByText("Kasun Perera")).toBeInTheDocument();
  });

  it("creates a user and shows the temporary password exactly once", async () => {
    const user = userEvent.setup();
    const created = makeUser({ id: "55555555-5555-4555-8555-555555555555", full_name: "Nuwan Silva", email: "nuwan@site.lk", must_change_password: true });
    const fetchMock = adminApi({
      "/api/v1/admin/users": (_url, init) =>
        init?.method === "POST"
          ? jsonResponse({ user: created, temporary_password: "kQ7rd-2xPmA-9fT3c-Lw8nB" }, 201)
          : page([KASUN]),
    });
    renderRoute("/admin/users");

    await user.click(await screen.findByRole("button", { name: "Add user" }));
    const dialog = screen.getByRole("dialog", { name: "Add a user" });
    await user.type(within(dialog).getByLabelText("Full name"), "Nuwan Silva");
    await user.type(within(dialog).getByLabelText("Email"), "nuwan@site.lk");
    await user.click(within(dialog).getByRole("checkbox", { name: /KDY-02/ }));
    await user.click(within(dialog).getByRole("button", { name: "Create account" }));

    const result = await screen.findByRole("dialog", { name: "Account created" });
    expect(within(result).getByTestId("temporary-password")).toHaveTextContent("kQ7rd-2xPmA-9fT3c-Lw8nB");
    expect(within(result).getByText(/Shown once/)).toBeInTheDocument();
    await user.click(within(result).getByRole("button", { name: "Copy password" }));
    await waitFor(async () => {
      expect(await navigator.clipboard.readText()).toBe("kQ7rd-2xPmA-9fT3c-Lw8nB");
    });

    const body = JSON.parse(findPostBody(fetchMock)) as Record<string, unknown>;
    expect(body).toEqual({ email: "nuwan@site.lk", full_name: "Nuwan Silva", role: "site_engineer", site_ids: [SITE_B.id] });

    await user.click(within(result).getByRole("button", { name: "Done" }));
    expect(screen.queryByText("kQ7rd-2xPmA-9fT3c-Lw8nB")).not.toBeInTheDocument();
  });

  it("validates the new-user form and shows server errors", async () => {
    const user = userEvent.setup();
    adminApi({
      "/api/v1/admin/users": (_url, init) =>
        init?.method === "POST" ? errorResponse(409, "conflict", "A user with this email already exists.") : page([]),
    });
    renderRoute("/admin/users");

    await user.click(await screen.findByRole("button", { name: "Add user" }));
    const dialog = screen.getByRole("dialog", { name: "Add a user" });
    await user.click(within(dialog).getByRole("button", { name: "Create account" }));
    expect(within(dialog).getByText("Enter the person's full name.")).toBeInTheDocument();
    expect(within(dialog).getByText("Enter a valid email address.")).toBeInTheDocument();

    await user.selectOptions(within(dialog).getByLabelText("Role"), "procurement_officer");
    expect(within(dialog).queryByRole("checkbox")).not.toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Full name"), "Copy Cat");
    await user.type(within(dialog).getByLabelText("Email"), "taken@site.lk");
    await user.click(within(dialog).getByRole("button", { name: "Create account" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("A user with this email already exists.");
  });

  it("deactivates a user only after confirmation", async () => {
    const user = userEvent.setup();
    const fetchMock = adminApi({
      [`/api/v1/admin/users/${KASUN.id}`]: () => jsonResponse({ ...KASUN, is_active: false }),
    });
    renderRoute("/admin/users");

    await user.click(await screen.findByRole("button", { name: "Manage Kasun Perera" }));
    const dialog = screen.getByRole("dialog", { name: "Kasun Perera" });
    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(requestTo(fetchMock, `/admin/users/${KASUN.id}`)).toBeUndefined();
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Deactivate this account?");
    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    await waitFor(() => {
      expect(requestTo(fetchMock, `/admin/users/${KASUN.id}`)?.body).toBe('{"is_active":false}');
    });
  });

  it("changes sites and role, and resets a password", async () => {
    const user = userEvent.setup();
    const fetchMock = adminApi({
      [`/api/v1/admin/users/${KASUN.id}/sites`]: () => jsonResponse(KASUN),
      [`/api/v1/admin/users/${KASUN.id}/reset-password`]: () => jsonResponse({ temporary_password: "Zz9yy-Xx8ww-Vv7uu-Tt6ss" }),
      [`/api/v1/admin/users/${KASUN.id}`]: () => jsonResponse(KASUN),
    });
    renderRoute("/admin/users");

    await user.click(await screen.findByRole("button", { name: "Manage Kasun Perera" }));
    let dialog = screen.getByRole("dialog", { name: "Kasun Perera" });
    await user.click(within(dialog).getByRole("checkbox", { name: /KDY-02/ }));
    await user.click(within(dialog).getByRole("button", { name: "Save sites" }));
    await waitFor(() => {
      expect(requestTo(fetchMock, `/admin/users/${KASUN.id}/sites`)?.body).toBe(
        JSON.stringify({ site_ids: [SITE_A.id, SITE_B.id] }),
      );
    });

    await user.click(await screen.findByRole("button", { name: "Manage Kasun Perera" }));
    dialog = screen.getByRole("dialog", { name: "Kasun Perera" });
    await user.selectOptions(within(dialog).getByLabelText("Role"), "quantity_surveyor");
    await user.click(within(dialog).getByRole("button", { name: "Save role" }));
    await waitFor(() => {
      expect(requestTo(fetchMock, `/admin/users/${KASUN.id}`)?.body).toBe('{"role":"quantity_surveyor"}');
    });

    await user.click(await screen.findByRole("button", { name: "Manage Kasun Perera" }));
    dialog = screen.getByRole("dialog", { name: "Kasun Perera" });
    await user.click(within(dialog).getByRole("button", { name: "Reset password" }));
    await user.click(within(dialog).getByRole("button", { name: "Reset password" }));
    expect(await screen.findByTestId("temporary-password")).toHaveTextContent("Zz9yy-Xx8ww-Vv7uu-Tt6ss");
  });

  it("links a client account to the projects it may see", async () => {
    const user = userEvent.setup();
    const CLIENT = makeUser({
      id: "55555555-5555-4555-8555-555555555555", email: "owner@client.lk", full_name: "Mr. Jayawardena",
      role: "client", role_label: "Client", projects: [],
    });  // fmt: skip
    const projects = [
      { id: "66666666-6666-4666-8666-666666666666", code: "HR-2026-01", name: "Havelock Residences", site_code: "COL-07", status: "active", client_name: "Havelock Developers", clients: 0 },
      { id: "77777777-7777-4777-8777-777777777777", code: "HR-2", name: "Havelock Towers", site_code: "COL-07", status: "active", client_name: "Other Holdings", clients: 1 },
    ];  // fmt: skip
    const fetchMock = adminApi({
      "/api/v1/admin/users": () => page([CLIENT, SELF]),
      "/api/v1/admin/projects": () => jsonResponse(projects),
      [`/api/v1/admin/users/${CLIENT.id}/projects`]: () => jsonResponse({ ...CLIENT, projects: [projects[0]] }),
    });
    renderRoute("/admin/users");

    await user.click(await screen.findByRole("button", { name: "Manage Mr. Jayawardena" }));
    const dialog = screen.getByRole("dialog", { name: "Mr. Jayawardena" });
    expect(within(dialog).getByText(/Never anything on another project, even on the same site/)).toBeInTheDocument();
    const towers = await within(dialog).findByRole("checkbox", { name: /Havelock Towers/ });
    expect(towers.closest("label")).toHaveTextContent("Other Holdings · site COL-07");
    await user.click(within(dialog).getByRole("checkbox", { name: /HR-2026-01/ }));
    await user.click(within(dialog).getByRole("button", { name: "Save projects" }));
    await waitFor(() => {
      expect(requestTo(fetchMock, `/admin/users/${CLIENT.id}/projects`)?.body).toBe(
        JSON.stringify({ project_ids: [projects[0]?.id] }),
      );
    });
  });

  it("shows no project picker for staff", async () => {
    const user = userEvent.setup();
    adminApi();
    renderRoute("/admin/users");
    await user.click(await screen.findByRole("button", { name: "Manage Kasun Perera" }));
    expect(screen.queryByRole("button", { name: "Save projects" })).not.toBeInTheDocument();
  });

  it("does not let admins change their own role or deactivate themselves", async () => {
    const user = userEvent.setup();
    adminApi();
    renderRoute("/admin/users");

    await user.click(await screen.findByRole("button", { name: "Manage Dilani Admin" }));
    const dialog = screen.getByRole("dialog", { name: "Dilani Admin" });
    expect(within(dialog).getByLabelText("Role")).toBeDisabled();
    expect(within(dialog).queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
  });
});

function findPostBody(fetchMock: ReturnType<typeof mockApi>): string {
  const call = fetchMock.mock.calls.find(([, init]) => init?.method === "POST" && init.body);
  return call?.[1]?.body as string;
}

describe("SitesPage", () => {
  it("lists sites and toggles one closed", async () => {
    const user = userEvent.setup();
    const fetchMock = adminApi({ [`/api/v1/admin/sites/${SITE_A.id}`]: () => jsonResponse({ ...SITE_A, is_active: false }) });
    renderRoute("/admin/sites");

    const card = (await screen.findByText("Havelock Residences")).closest("article")!;
    expect(card).toHaveTextContent("6.8836°, 79.8650°");
    expect(screen.getByText("Peradeniya Road Offices").closest("article")).toHaveTextContent("No coordinates");

    await user.click(within(card).getByRole("button", { name: "Close site" }));
    await waitFor(() => {
      expect(requestTo(fetchMock, `/admin/sites/${SITE_A.id}`)?.body).toBe('{"is_active":false}');
    });
  });

  it("adds a site with client-side validation", async () => {
    const user = userEvent.setup();
    const fetchMock = adminApi({
      "/api/v1/admin/sites": (_url, init) => (init?.method === "POST" ? jsonResponse(SITE_B, 201) : jsonResponse([])),
    });
    renderRoute("/admin/sites");

    expect(await screen.findByText("No sites yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add site" }));
    const dialog = screen.getByRole("dialog", { name: "Add a site" });
    await user.type(within(dialog).getByLabelText("Code"), "bad code!");
    await user.type(within(dialog).getByLabelText("Latitude"), "120");
    await user.click(within(dialog).getByRole("button", { name: "Add site" }));
    expect(within(dialog).getByText(/2–16 letters/)).toBeInTheDocument();
    expect(within(dialog).getByText("Latitude must be between -90 and 90.")).toBeInTheDocument();
    expect(within(dialog).getByText("Enter the site name.")).toBeInTheDocument();

    await user.clear(within(dialog).getByLabelText("Code"));
    await user.type(within(dialog).getByLabelText("Code"), "kdy-02");
    await user.clear(within(dialog).getByLabelText("Latitude"));
    await user.type(within(dialog).getByLabelText("Site name"), "Peradeniya Road Offices");
    await user.type(within(dialog).getByLabelText("Location"), "Kandy");
    await user.click(within(dialog).getByRole("button", { name: "Add site" }));

    await waitFor(() => {
      expect(JSON.parse(findPostBody(fetchMock))).toEqual({
        code: "KDY-02",
        name: "Peradeniya Road Offices",
        location: "Kandy",
        latitude: null,
        longitude: null,
      });
    });
  });
});

describe("AuditLogPage", () => {
  const entry = (n: number, action = "auth.login_succeeded"): AuditLogEntry => ({
    id: `66666666-6666-4666-8666-${String(n).padStart(12, "0")}`,
    occurred_at: "2026-10-09T05:00:00+00:00",
    action,
    actor_id: ADMIN.id,
    actor_name: "Dilani Admin",
    target_type: "user",
    target_id: ADMIN.id,
    ip_address: "10.0.0.7",
    details: action === "auth.login_failed" ? { reason: "bad_password" } : { to: ["COL-07"] },
  });

  it("shows readable events, filters and pages", async () => {
    const user = userEvent.setup();
    const fetchMock = adminApi({
      "/api/v1/admin/audit-logs": (url) => {
        const params = new URL(url, "http://x").searchParams;
        if (params.get("action") === "auth.login_failed") {
          return jsonResponse({ items: [entry(99, "auth.login_failed")], total: 1, limit: 25, offset: 0 });
        }
        const offset = Number(params.get("offset"));
        const items = Array.from({ length: offset === 0 ? 25 : 5 }, (_, i) => entry(offset + i, "user.sites_assigned"));
        return jsonResponse({ items, total: 30, limit: 25, offset });
      },
    });
    renderRoute("/admin/audit");

    const list = await screen.findByRole("list", { name: "Audit entries" });
    expect(await within(list).findAllByText("Sites assigned")).toHaveLength(25);
    expect(screen.getByText("1–25 of 30")).toBeInTheDocument();
    expect(within(list).getAllByText("sites: COL-07")[0]).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Older" }));
    expect(await screen.findByText("26–30 of 30")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Older" })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText("Event"), "auth.login_failed");
    expect(await screen.findByText("bad password")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => (url as string).includes("action=auth.login_failed"))).toBe(true);
  });
});
