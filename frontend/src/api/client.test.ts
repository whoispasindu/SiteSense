import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { jsonResponse, mockApi } from "../test/utils";
import { ApiError, apiRequest } from "./client";

const schema = z.object({ status: z.literal("ok"), version: z.string() });

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected the request to fail");
}

describe("apiRequest", () => {
  it("returns validated data and the request id", async () => {
    const fetchMock = mockApi({
      "/api/v1/health": () => jsonResponse({ status: "ok", version: "1.2.3" }, 200, { "X-Request-ID": "req-12345678" }),
    });

    const result = await apiRequest("/health", schema);

    expect(result).toEqual({ data: { status: "ok", version: "1.2.3" }, status: 200, requestId: "req-12345678" });
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.credentials).toBe("same-origin");
    expect(init?.redirect).toBe("error");
  });

  it("sends JSON bodies with a content type", async () => {
    const fetchMock = mockApi({ "/api/v1/things": () => jsonResponse({ status: "ok", version: "1" }) });

    await apiRequest("/things", schema, { method: "POST", body: { name: "Slab pour" } });

    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe('{"name":"Slab pour"}');
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("turns the backend error envelope into an ApiError", async () => {
    mockApi({
      "/api/v1/health": () =>
        jsonResponse(
          {
            error: {
              code: "forbidden",
              message: "You do not have permission to perform this action.",
              request_id: "abc12345",
              details: [],
            },
          },
          403,
        ),
    });

    const error = await captureError(apiRequest("/health", schema));

    expect(error.status).toBe(403);
    expect(error.code).toBe("forbidden");
    expect(error.message).toBe("You do not have permission to perform this action.");
    expect(error.requestId).toBe("abc12345");
    expect(error.isRetryable).toBe(false);
  });

  it("handles non-envelope error bodies without exposing them", async () => {
    mockApi({ "/api/v1/health": () => new Response("<html>proxy error: upstream 10.0.0.4</html>", { status: 502 }) });

    const error = await captureError(apiRequest("/health", schema));

    expect(error.code).toBe("http_error");
    expect(error.message).not.toContain("10.0.0.4");
    expect(error.isRetryable).toBe(true);
  });

  it("rejects responses that break the contract", async () => {
    mockApi({ "/api/v1/health": () => jsonResponse({ status: "ok", version: 42 }) });

    const error = await captureError(apiRequest("/health", schema));

    expect(error.code).toBe("invalid_response");
    expect(error.details[0]).toMatchObject({ path: "version" });
  });

  it("accepts listed non-2xx statuses as data", async () => {
    const degraded = z.object({ status: z.literal("degraded") });
    mockApi({ "/api/v1/health/ready": () => jsonResponse({ status: "degraded" }, 503) });

    const result = await apiRequest("/health/ready", degraded, { acceptStatuses: [503] });

    expect(result.status).toBe(503);
    expect(result.data.status).toBe("degraded");
  });

  it("reports network failures as retryable", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));

    const error = await captureError(apiRequest("/health", schema));

    expect(error.code).toBe("network_error");
    expect(error.status).toBe(0);
    expect(error.isRetryable).toBe(true);
  });

  it("reports a timeout distinctly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => {
              reject(new DOMException("aborted", "AbortError"));
            });
          }),
      ),
    );

    const error = await captureError(apiRequest("/health", schema, { timeoutMs: 10 }));

    expect(error.code).toBe("timeout");
  });

  it("reports caller cancellation distinctly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new DOMException("aborted", "AbortError"))),
    );
    const controller = new AbortController();
    controller.abort();

    const error = await captureError(apiRequest("/health", schema, { signal: controller.signal }));

    expect(error.code).toBe("aborted");
  });

  it.each(["health", "//evil.example/steal", "https://evil.example"])(
    "refuses path %s that is not same-origin and absolute",
    async (path) => {
      const fetchMock = mockApi({});

      await expect(apiRequest(path, schema)).rejects.toThrow(/same-origin/);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );
});
