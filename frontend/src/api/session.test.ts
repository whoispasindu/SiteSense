import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { errorResponse, jsonResponse, makeMe, mockApi, requestTo, tokenResponse } from "../test/utils";
import { resumeSession, signIn, signOut } from "./auth";
import { apiRequest, configureSession, getAccessToken, refreshSession, setAccessToken } from "./client";

const ok = z.object({ ok: z.literal(true) });

function authHeader(init: RequestInit | undefined): string | undefined {
  return (init?.headers as Record<string, string> | undefined)?.Authorization;
}

afterEach(() => {
  configureSession(null);
  setAccessToken(null);
});

describe("access token handling", () => {
  it("attaches the in-memory token and never stores it in web storage", async () => {
    const fetchMock = mockApi({ "/api/v1/thing": () => jsonResponse({ ok: true }) });
    setAccessToken("secret-token");

    await apiRequest("/thing", ok);

    expect(authHeader(requestTo(fetchMock, "/thing"))).toBe("Bearer secret-token");
    expect(JSON.stringify(localStorage)).not.toContain("secret-token");
    expect(JSON.stringify(sessionStorage)).not.toContain("secret-token");
  });

  it("does not attach the token when auth is off", async () => {
    const fetchMock = mockApi({ "/api/v1/auth/login": () => jsonResponse({ ok: true }) });
    setAccessToken("secret-token");

    await apiRequest("/auth/login", ok, { method: "POST", auth: false });

    expect(authHeader(requestTo(fetchMock, "/auth/login"))).toBeUndefined();
  });
});

describe("refresh on expiry", () => {
  it("refreshes once and retries the request with the new token", async () => {
    let calls = 0;
    const fetchMock = mockApi({
      "/api/v1/thing": () => {
        calls += 1;
        return calls === 1 ? errorResponse(401, "token_expired") : jsonResponse({ ok: true });
      },
    });
    const refresh = vi.fn(() => {
      setAccessToken("fresh-token");
      return Promise.resolve(true);
    });
    configureSession({ refresh, onExpired: vi.fn() });
    setAccessToken("stale-token");

    const result = await apiRequest("/thing", ok);

    expect(result.data.ok).toBe(true);
    expect(refresh).toHaveBeenCalledTimes(1);
    const authHeaders = fetchMock.mock.calls.map(([, init]) => authHeader(init));
    expect(authHeaders).toEqual(["Bearer stale-token", "Bearer fresh-token"]);
  });

  it("shares one refresh between concurrent requests", async () => {
    let refreshed = false;
    mockApi({
      "/api/v1/a": () => (refreshed ? jsonResponse({ ok: true }) : errorResponse(401, "token_expired")),
      "/api/v1/b": () => (refreshed ? jsonResponse({ ok: true }) : errorResponse(401, "token_expired")),
    });
    const refresh = vi.fn(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
      refreshed = true;
      return true;
    });
    configureSession({ refresh, onExpired: vi.fn() });

    await Promise.all([apiRequest("/a", ok), apiRequest("/b", ok)]);

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("reports an unrecoverable session", async () => {
    mockApi({ "/api/v1/thing": () => errorResponse(401, "session_expired") });
    const onExpired = vi.fn();
    configureSession({ refresh: () => Promise.resolve(false), onExpired });

    await expect(apiRequest("/thing", ok)).rejects.toMatchObject({ code: "session_expired" });
    expect(onExpired).toHaveBeenCalledTimes(1);
  });

  it("does not refresh on 403 or on business errors", async () => {
    mockApi({ "/api/v1/thing": () => errorResponse(403, "forbidden") });
    const refresh = vi.fn(() => Promise.resolve(true));
    configureSession({ refresh, onExpired: vi.fn() });

    await expect(apiRequest("/thing", ok)).rejects.toMatchObject({ status: 403 });
    expect(refresh).not.toHaveBeenCalled();
  });

  it("resolves false without session hooks", async () => {
    await expect(refreshSession()).resolves.toBe(false);
  });
});

describe("auth API", () => {
  it("signIn stores the token in memory only", async () => {
    mockApi({ "/api/v1/auth/login": () => tokenResponse(makeMe("admin"), "token-from-login") });

    const result = await signIn("admin@sitesense.example", "pw");

    expect(result.kind === "session" ? result.user.role : null).toBe("admin");
    expect(getAccessToken()).toBe("token-from-login");
  });

  it("signIn returns a challenge, and no token, when a code is due", async () => {
    mockApi({
      "/api/v1/auth/login": () => jsonResponse({ mfa_required: true, mfa_token: "challenge-token-0123456789", expires_in: 300 }),
    });

    const result = await signIn("pm@sitesense.example", "pw");

    expect(result).toEqual({ kind: "challenge", token: "challenge-token-0123456789" });
    expect(getAccessToken()).toBeNull();
  });

  it("resumeSession returns null when signed out", async () => {
    mockApi({ "/api/v1/auth/refresh": () => errorResponse(401, "session_expired") });

    await expect(resumeSession()).resolves.toBeNull();
  });

  it("resumeSession retries once when another tab just refreshed", async () => {
    let calls = 0;
    mockApi({
      "/api/v1/auth/refresh": () => {
        calls += 1;
        return calls === 1 ? errorResponse(401, "refresh_superseded") : tokenResponse(makeMe("project_manager"));
      },
    });

    const me = await resumeSession();

    expect(me?.role).toBe("project_manager");
    expect(calls).toBe(2);
  });

  it("resumeSession surfaces unexpected failures", async () => {
    mockApi({ "/api/v1/auth/refresh": () => errorResponse(500, "server_error") });

    await expect(resumeSession()).rejects.toMatchObject({ status: 500 });
  });

  it("signOut clears the token even if the server call fails", async () => {
    mockApi({ "/api/v1/auth/logout": () => errorResponse(500, "server_error") });
    setAccessToken("t");

    await expect(signOut()).rejects.toBeTruthy();
    expect(getAccessToken()).toBeNull();
  });
});
