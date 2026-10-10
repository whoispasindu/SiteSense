import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { vi } from "vitest";

import { ROLE_LABELS, type Me, type Role } from "../api/auth";
import { setAccessToken } from "../api/client";
import { AuthProvider } from "../auth/AuthProvider";
import { isAvailable, NAV_GROUPS, type NavItem } from "../components/layout/navigation";
import { CURRENT_PHASE, PHASES } from "../lib/programme";
import { routes } from "../routes";

export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function errorResponse(status: number, code: string, message = "Error"): Response {
  return jsonResponse({ error: { code, message, request_id: "req-test-0001", details: [] } }, status);
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

/** Stubs global fetch; each test describes the backend it wants by URL suffix (longest match wins). */
export function mockApi(handlers: Record<string, Handler>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    const path = url.split("?")[0] ?? url;
    const match = Object.entries(handlers)
      .filter(([suffix]) => path.endsWith(suffix) || url.endsWith(suffix))
      .sort(([a], [b]) => b.length - a.length)[0];
    if (!match) return Promise.reject(new TypeError(`Unhandled request in test: ${url}`));
    return Promise.resolve(match[1](url, init));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

type FetchMock = ReturnType<typeof mockApi>;

/** The RequestInit of the first call whose URL ends with ``suffix`` (undefined if none). */
export function requestTo(fetchMock: FetchMock, suffix: string): RequestInit | undefined {
  const call = fetchMock.mock.calls.find(([input]) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    return url.split("?")[0]?.endsWith(suffix);
  });
  return call ? (call[1] ?? {}) : undefined;
}

export const healthyApi: Record<string, Handler> = {
  "/api/v1/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
  "/api/v1/health/ready": () => jsonResponse({ status: "ok", checks: { database: "ok" } }),
};

/** Mirrors app/core/permissions.py for the permissions the UI uses. */
export const ROLE_PERMISSIONS: Record<Role, string[]> = {
  admin: ["users:manage", "sites:manage", "audit:read", "dashboard:view"],
  project_manager: [
    "dashboard:view", "projects:read", "projects:manage", "schedule:read", "schedule:manage", "schedule:progress",
    "reports:read", "materials:read", "materials:request", "materials:approve_pm", "risk:read", "risk:what_if",
    "cost:read", "rates:read", "claims:approve", "variations:manage",
  ],
  quantity_surveyor: [
    "dashboard:view", "projects:read", "boq:manage", "schedule:read", "reports:read", "materials:read",
    "materials:request", "materials:approve_qs", "risk:read", "cost:read", "rates:read", "claims:manage",
    "variations:manage",
  ],
  site_engineer: [
    "dashboard:view", "projects:read", "schedule:read", "schedule:progress", "reports:create", "reports:read",
    "materials:request", "materials:read",
  ],
  procurement_officer: [
    "dashboard:view", "projects:read", "materials:read", "purchase_orders:manage", "suppliers:manage", "rates:read",
  ],
  client: ["client:portal", "variations:client_decide"],
};

export function makeMe(role: Role = "site_engineer", overrides: Partial<Me> = {}): Me {
  return {
    id: "6f0d3c1e-8a7b-4c2d-9e1f-0a1b2c3d4e5f",
    email: `${role}@sitesense.example`,
    full_name: "Kasun Perera",
    role,
    role_label: ROLE_LABELS[role],
    permissions: ROLE_PERMISSIONS[role],
    site_scoped: ["project_manager", "quantity_surveyor", "site_engineer", "client"].includes(role),
    sites: [{ id: "0b6c2f4e-1d3a-4e5f-8a9b-1c2d3e4f5a6b", code: "COL-07", name: "Havelock Residences" }],
    must_change_password: false,
    ...overrides,
  };
}

export function tokenResponse(user: Me, token = "access-token-1"): Response {
  return jsonResponse({ access_token: token, token_type: "bearer", expires_in: 900, user });
}

/** Backend for a browser that already holds a refresh cookie for ``user`` (or none). */
export function sessionApi(user: Me | null): Record<string, Handler> {
  return {
    ...healthyApi,
    "/api/v1/auth/refresh": () => (user ? tokenResponse(user) : errorResponse(401, "session_expired")),
    "/api/v1/auth/logout": () => new Response(null, { status: 204 }),
  };
}

export function renderRoute(path = "/") {
  setAccessToken(null);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { ...result, router, queryClient };
}

/** The first menu module a project manager can see that is not built yet (changes every phase). */
export function nextUnbuiltModule(): NavItem {
  const pm = new Set(ROLE_PERMISSIONS.project_manager);
  const item = NAV_GROUPS.flatMap((g) => g.items).find(
    (i) => !isAvailable(i) && (i.permission === undefined || pm.has(i.permission)),
  );
  if (!item) throw new Error("Every module is built: update the tests that rely on an unbuilt one.");
  return item;
}

export const currentPhaseName = (): string => PHASES[CURRENT_PHASE]?.name ?? "";
export const previousPhaseName = (): string => PHASES[CURRENT_PHASE - 1]?.name ?? "";
