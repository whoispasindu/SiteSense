import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { errorResponse, jsonResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi, tokenResponse } from "../../test/utils";

async function fillAndSubmit(email: string, password: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Enter site office" }));
  return user;
}

const emptyPage = () => jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });

describe("SignInPage", () => {
  it("signs in and continues to the page the user asked for", async () => {
    const fetchMock = mockApi({
      ...sessionApi(null),
      "/api/v1/auth/login": () => tokenResponse(makeMe("admin")),
      "/api/v1/admin/users": emptyPage,
      "/api/v1/admin/sites": () => jsonResponse([]),
    });
    const { router } = renderRoute("/sign-in?next=%2Fadmin%2Fusers");

    await fillAndSubmit("admin@sitesense.example", "Correct-Horse-9");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/admin/users");
    });
    const login = requestTo(fetchMock, "/auth/login");
    expect(JSON.parse(login?.body as string)).toEqual({
      email: "admin@sitesense.example",
      password: "Correct-Horse-9",
    });
  });

  it("never follows an off-site next parameter", async () => {
    mockApi({ ...sessionApi(null), "/api/v1/auth/login": () => tokenResponse(makeMe("project_manager")) });
    const { router } = renderRoute("/sign-in?next=%2F%2Fevil.example%2Fphish");

    await fillAndSubmit("pm@sitesense.example", "Correct-Horse-9");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
  });

  it("sends users with a temporary password to change it", async () => {
    mockApi({
      ...sessionApi(null),
      "/api/v1/auth/login": () => tokenResponse(makeMe("site_engineer", { must_change_password: true })),
    });
    const { router } = renderRoute("/sign-in");

    await fillAndSubmit("se@sitesense.example", "kQ7rd-2xPmA-9fT3c-Lw8nB");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/change-password");
    });
  });

  it("shows one generic message for wrong credentials", async () => {
    mockApi({ ...sessionApi(null), "/api/v1/auth/login": () => errorResponse(401, "invalid_credentials") });
    renderRoute("/sign-in");

    await fillAndSubmit("someone@site.lk", "wrong-password");

    expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is incorrect.");
    expect(screen.getByRole("button", { name: "Enter site office" })).toBeEnabled();
  });

  it("explains a locked account", async () => {
    mockApi({
      ...sessionApi(null),
      "/api/v1/auth/login": () =>
        errorResponse(423, "account_locked", "Too many failed sign-in attempts. Try again in 15 minutes."),
    });
    renderRoute("/sign-in");

    await fillAndSubmit("target@site.lk", "wrong-password");

    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 15 minutes.");
  });

  it("explains rate limiting and network failures", async () => {
    mockApi({ ...sessionApi(null), "/api/v1/auth/login": () => errorResponse(429, "rate_limited") });
    renderRoute("/sign-in");

    await fillAndSubmit("a@site.lk", "x");

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts from this device");
  });

  it("validates fields before calling the server", async () => {
    const fetchMock = mockApi(sessionApi(null));
    const user = userEvent.setup();
    renderRoute("/sign-in");

    await user.click(await screen.findByRole("button", { name: "Enter site office" }));

    expect(screen.getByText("Enter the email address you use for SiteSense.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(requestTo(fetchMock, "/auth/login") !== undefined).toBe(false);
  });

  it("can reveal the password", async () => {
    mockApi(sessionApi(null));
    const user = userEvent.setup();
    renderRoute("/sign-in");

    const field = await screen.findByLabelText("Password");
    expect(field).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show" }));
    expect(field).toHaveAttribute("type", "text");
  });
});
