import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { errorResponse, makeMe, mockApi, renderRoute, requestTo, sessionApi, tokenResponse } from "../../test/utils";
import { passwordChecks } from "./passwordRules";

describe("passwordChecks", () => {
  it("mirrors the server rules", () => {
    const result = (pw: string, confirm = pw) =>
      passwordChecks(pw, confirm, "kasun.perera@site.lk").map((c) => c.ok);

    expect(result("short")).toEqual([false, true, true, true]);
    expect(result("kasun.perera-is-me-2026")).toEqual([true, false, true, true]);
    expect(result("aaaaaaaaaaaaaaab")).toEqual([true, true, false, true]);
    expect(result("Monsoon-Slab-Pour-42", "different")).toEqual([true, true, true, false]);
    expect(result("Monsoon-Slab-Pour-42")).toEqual([true, true, true, true]);
  });
});

describe("ChangePasswordPage", () => {
  it("replaces a temporary password and continues into the app", async () => {
    const temp = makeMe("admin", { must_change_password: true });
    const fetchMock = mockApi({
      ...sessionApi(temp),
      "/api/v1/auth/change-password": () => tokenResponse({ ...temp, must_change_password: false }, "access-token-2"),
    });
    const user = userEvent.setup();
    const { router } = renderRoute("/change-password");

    const save = await screen.findByRole("button", { name: "Save password" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Temporary password"), "kQ7rd-2xPmA-9fT3c-Lw8nB");
    await user.type(screen.getByLabelText("New password"), "Monsoon-Slab-Pour-42");
    await user.type(screen.getByLabelText("Repeat new password"), "Monsoon-Slab-Pour-42");
    expect(save).toBeEnabled();
    await user.click(save);

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    const call = requestTo(fetchMock, "/auth/change-password");
    expect((call?.headers as Record<string, string>).Authorization).toBe("Bearer access-token-1");
  });

  it("shows the server's reason when the change is refused", async () => {
    mockApi({
      ...sessionApi(makeMe("admin", { must_change_password: true })),
      "/api/v1/auth/change-password": () =>
        errorResponse(422, "invalid_current_password", "Your current password is incorrect."),
    });
    const user = userEvent.setup();
    renderRoute("/change-password");

    await user.type(await screen.findByLabelText("Temporary password"), "wrong-temporary");
    await user.type(screen.getByLabelText("New password"), "Monsoon-Slab-Pour-42");
    await user.type(screen.getByLabelText("Repeat new password"), "Monsoon-Slab-Pour-42");
    await user.click(screen.getByRole("button", { name: "Save password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Your current password is incorrect.");
  });
});
