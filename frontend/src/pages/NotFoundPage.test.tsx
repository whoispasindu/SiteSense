import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeMe, mockApi, renderRoute, sessionApi } from "../test/utils";

describe("NotFoundPage", () => {
  it("renders inside the shell for unknown routes and links home", async () => {
    mockApi(sessionApi(makeMe("project_manager")));
    const user = userEvent.setup();
    const { router } = renderRoute("/no/such/sheet");

    expect(await screen.findByRole("heading", { level: 1, name: "Off the drawings." })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Back to the dashboard" }));
    expect(router.state.location.pathname).toBe("/");
  });

});
