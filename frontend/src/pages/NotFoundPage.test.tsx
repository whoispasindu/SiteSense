import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { healthyApi, mockApi, renderRoute } from "../test/utils";

describe("NotFoundPage", () => {
  it("renders inside the shell for unknown routes and links home", async () => {
    mockApi(healthyApi);
    const user = userEvent.setup();
    const { router } = renderRoute("/no/such/sheet");

    expect(await screen.findByRole("heading", { level: 1, name: "Off the drawings." })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Back to the site office" }));
    expect(router.state.location.pathname).toBe("/");
  });

  it("treats not-yet-built modules as unknown routes", async () => {
    mockApi(healthyApi);
    renderRoute("/projects");

    expect(await screen.findByRole("heading", { name: "Off the drawings." })).toBeInTheDocument();
    expect(screen.getByRole("banner")).not.toHaveTextContent("Projects");
  });
});
