import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { AdminUser } from "../../api/admin";
import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, sessionApi, tokenResponse } from "../../test/utils";

const CHALLENGE = { mfa_required: true, mfa_token: "challenge-token-0123456789abcdef", expires_in: 300 };
const QR = "data:image/png;base64,iVBORw0KGgo=";
const CODES = ["abcde-fghjk", "mnpqr-stuvw", "xyz23-45678", "9abcd-efghj", "kmnpq-rstuv", "wxyz2-34567", "89abc-defgh", "jkmnp-qrstu", "vwxyz-23456", "789ab-cdefg"];

function bodyOf(fetchMock: ReturnType<typeof mockApi>, suffix: string): unknown {
  const call = fetchMock.mock.calls.find(([input]) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    return url.split("?")[0]?.endsWith(suffix);
  });
  const body = call?.[1]?.body;
  return typeof body === "string" ? JSON.parse(body) : undefined;
}

async function signInWithPassword(email = "pm@sitesense.example") {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), "Correct-Horse-9");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return user;
}

describe("Two-step sign-in at sign-in", () => {
  it("asks for the app code after the password, then signs in", async () => {
    const fetchMock = mockApi({
      ...sessionApi(null),
      "/api/v1/auth/login": () => jsonResponse(CHALLENGE),
      "/api/v1/auth/mfa/verify": () => tokenResponse(makeMe("site_engineer", { mfa_enabled: true })),
      "/api/v1/reports/today": () => jsonResponse({ date: "2026-10-16", deadline: "2026-10-16T18:00:00+05:30", deadline_passed: false, projects: [] }),
      "/api/v1/projects": () => jsonResponse([]),
      "/api/v1/analytics/portfolio": () => errorResponse(500, "internal_error"),
      "/api/v1/briefing/today": () => errorResponse(500, "internal_error"),
      "/api/v1/notifications": () => jsonResponse({ unread: 0, items: [] }),
      "/api/v1/schedule/summary": () => jsonResponse([]),
    });
    const { router } = renderRoute("/sign-in");
    const user = await signInWithPassword();

    expect(await screen.findByRole("heading", { name: "Two-step sign-in" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(bodyOf(fetchMock, "/auth/mfa/verify")).toEqual({ mfa_token: CHALLENGE.mfa_token, code: "123456" });
  });

  it("takes a recovery code instead, and says when a code is wrong", async () => {
    const fetchMock = mockApi({
      ...sessionApi(null),
      "/api/v1/auth/login": () => jsonResponse(CHALLENGE),
      "/api/v1/auth/mfa/verify": () => errorResponse(401, "invalid_mfa_code", "That code is not right."),
    });
    renderRoute("/sign-in");
    const user = await signInWithPassword();

    await user.click(await screen.findByRole("button", { name: /Use a recovery code/ }));
    await user.type(screen.getByLabelText("Recovery code"), "abcde-fghjk");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText(/That code is not right/)).toBeInTheDocument();
    expect(bodyOf(fetchMock, "/auth/mfa/verify")).toEqual({ mfa_token: CHALLENGE.mfa_token, recovery_code: "abcde-fghjk" });
  });

  it("checks the code's shape before sending, and can start again", async () => {
    mockApi({ ...sessionApi(null), "/api/v1/auth/login": () => jsonResponse(CHALLENGE) });
    renderRoute("/sign-in");
    const user = await signInWithPassword();

    await user.type(await screen.findByLabelText("Code"), "12a");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText("Enter the 6-digit code.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start again" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("sends the user back to the password when the challenge has expired", async () => {
    mockApi({
      ...sessionApi(null),
      "/api/v1/auth/login": () => jsonResponse(CHALLENGE),
      "/api/v1/auth/mfa/verify": () => errorResponse(401, "mfa_challenge_expired", "Too slow."),
    });
    renderRoute("/sign-in");
    const user = await signInWithPassword();
    await user.type(await screen.findByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("Setting up two-step sign-in", () => {
  function setupApi(me = makeMe("project_manager", { mfa_setup_required: true })) {
    return mockApi({
      ...sessionApi(me),
      "/api/v1/auth/mfa/setup": () => jsonResponse({ secret: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/SiteSense:pm", qr_png: QR }),
      "/api/v1/auth/mfa/enable": () => jsonResponse({ codes: CODES }),
      "/api/v1/me": () => jsonResponse(makeMe("project_manager", { mfa_enabled: true })),
      "/api/v1/projects": () => jsonResponse([]),
      "/api/v1/analytics/portfolio": () => errorResponse(500, "internal_error"),
      "/api/v1/briefing/today": () => errorResponse(500, "internal_error"),
      "/api/v1/notifications": () => jsonResponse({ unread: 0, items: [] }),
      "/api/v1/reports/today": () => jsonResponse({ date: "2026-10-16", deadline: "2026-10-16T18:00:00+05:30", deadline_passed: false, projects: [] }),
      "/api/v1/schedule/summary": () => jsonResponse([]),
      "/api/v1/risk/projects": () => jsonResponse([]),
    });
  }

  it("sends roles that need it to the set-up page first, then on into the app", async () => {
    const fetchMock = setupApi();
    const { router } = renderRoute("/projects");
    const user = userEvent.setup();

    expect(await screen.findByRole("heading", { name: "Set up two-step sign-in" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/two-step-setup");

    await user.click(screen.getByRole("button", { name: "Show the QR code" }));
    expect(await screen.findByRole("img", { name: /QR code/ })).toHaveAttribute("src", QR);
    expect(screen.getByLabelText("Setup key")).toHaveTextContent("JBSW Y3DP EHPK 3PXP");
    await user.type(screen.getByLabelText("6-digit code from the app"), "654321");
    await user.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    expect(bodyOf(fetchMock, "/auth/mfa/enable")).toEqual({ code: "654321" });

    const list = await screen.findByRole("list", { name: "Recovery codes" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(10);
    const done = screen.getByRole("button", { name: "Continue to SiteSense" });
    expect(done).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /saved these codes/ }));
    await user.click(done);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
  });

  it("shows a wrong code and lets the user try again", async () => {
    mockApi({
      ...sessionApi(makeMe("project_manager", { mfa_setup_required: true })),
      "/api/v1/auth/mfa/setup": () => jsonResponse({ secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/SiteSense:pm", qr_png: QR }),
      "/api/v1/auth/mfa/enable": () => errorResponse(401, "invalid_mfa_code", "That code is not right."),
    });
    renderRoute("/two-step-setup");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Show the QR code" }));
    await user.type(await screen.findByLabelText("6-digit code from the app"), "000000");
    await user.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    expect(await screen.findByText(/Check the time on your phone/)).toBeInTheDocument();
    expect(screen.getByLabelText("6-digit code from the app")).toHaveValue("");
  });
});

describe("Two-step sign-in settings", () => {
  it("renews recovery codes for a required role, and offers no switch-off", async () => {
    const fetchMock = mockApi({
      ...sessionApi(makeMe("project_manager", { mfa_enabled: true })),
      "/api/v1/auth/mfa": () => jsonResponse({ enabled: true, required: true, enabled_at: "2026-10-16T02:00:00+00:00", recovery_codes_left: 2 }),
      "/api/v1/auth/mfa/recovery-codes": () => jsonResponse({ codes: CODES }),
    });
    renderRoute("/settings/security");
    const user = userEvent.setup();

    expect(await screen.findByText(/running out of recovery codes/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Turn off two-step sign-in" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Renew recovery codes" }));
    await user.type(screen.getByLabelText("6-digit code from the app"), "111222");
    await user.click(screen.getAllByRole("button", { name: "Renew recovery codes" }).at(-1) as HTMLElement);
    expect(await screen.findByRole("list", { name: "Recovery codes" })).toBeInTheDocument();
    expect(bodyOf(fetchMock, "/auth/mfa/recovery-codes")).toEqual({ code: "111222" });
  });

  it("lets a site engineer turn it on and off", async () => {
    let enabled = false;
    mockApi({
      ...sessionApi(makeMe("site_engineer")),
      "/api/v1/auth/mfa": () => jsonResponse({ enabled, required: false, enabled_at: enabled ? "2026-10-16T02:00:00+00:00" : null, recovery_codes_left: enabled ? 10 : 0 }),
      "/api/v1/auth/mfa/disable": () => {
        enabled = false;
        return new Response(null, { status: 204 });
      },
      "/api/v1/me": () => jsonResponse(makeMe("site_engineer", { mfa_enabled: enabled })),
    });
    enabled = true;
    renderRoute("/settings/security");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Turn off two-step sign-in" }));
    await user.type(screen.getByLabelText("6-digit code from the app"), "333444");
    await user.click(screen.getAllByRole("button", { name: "Turn off two-step sign-in" }).at(-1) as HTMLElement);
    expect(await screen.findByRole("button", { name: "Set up two-step sign-in" })).toBeInTheDocument();
  });
});

describe("The Company Admin's reset", () => {
  const PM: AdminUser = {
    id: "33333333-3333-4333-8333-333333333333", email: "pm@site.lk", full_name: "Ruwan Silva", role: "project_manager",
    role_label: "Project Manager", is_active: true, is_locked: false, must_change_password: false,
    last_login_at: null, created_at: "2026-10-01T08:00:00+00:00", sites: [], projects: [], mfa_enabled: true,
  };  // fmt: skip

  it("resets two-step sign-in only after a warning", async () => {
    const fetchMock = mockApi({
      ...sessionApi(makeMe("admin")),
      "/api/v1/admin/users": () => jsonResponse({ items: [PM], total: 1, limit: 100, offset: 0 }),
      "/api/v1/admin/sites": () => jsonResponse([]),
      [`/api/v1/admin/users/${PM.id}/mfa/reset`]: () => jsonResponse({ ...PM, mfa_enabled: false }),
    });
    renderRoute("/admin/users");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Manage Ruwan Silva" }));
    const dialog = screen.getByRole("dialog", { name: "Ruwan Silva" });
    await user.click(within(dialog).getByRole("button", { name: "Reset two-step sign-in" }));
    expect(within(dialog).getByText(/recorded in the audit log/)).toBeInTheDocument();
    await user.click(within(dialog).getAllByRole("button", { name: "Reset two-step sign-in" }).at(-1) as HTMLElement);
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, init]) => String(input instanceof Request ? input.url : input).endsWith("/mfa/reset") && init?.method === "POST")).toBe(true);
    });
  });
});

describe("Demo mode", () => {
  it("shows the demo banner when the server runs the demo", async () => {
    mockApi({
      ...sessionApi(makeMe("client", { demo_mode: true })),
      "/api/v1/client/projects": () => jsonResponse([]),
      "/api/v1/notifications": () => jsonResponse({ unread: 0, items: [] }),
    });
    renderRoute("/");
    expect(await screen.findByRole("complementary", { name: "Demo notice" })).toHaveTextContent(
      "Demo data, not real projects.",
    );
  });
});
