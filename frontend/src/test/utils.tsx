import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { vi } from "vitest";

import { routes } from "../routes";

export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

/** Stubs global fetch; each test describes the backend it wants by URL suffix. */
export function mockApi(handlers: Record<string, Handler>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    const match = Object.entries(handlers).find(([suffix]) => url.endsWith(suffix));
    if (!match) return Promise.reject(new TypeError(`Unhandled request in test: ${url}`));
    return Promise.resolve(match[1](url, init));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export const healthyApi = {
  "/api/v1/health": () => jsonResponse({ status: "ok", version: "0.0.1" }),
  "/api/v1/health/ready": () => jsonResponse({ status: "ok", checks: { database: "ok" } }),
};

export function renderRoute(path = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...result, router, queryClient };
}
