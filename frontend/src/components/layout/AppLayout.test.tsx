import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { healthyApi, mockApi, renderRoute } from "../../test/utils";

describe("AppLayout", () => {
  beforeEach(() => {
    mockApi(healthyApi);
  });

  it("renders landmarks and a skip link to the main content", async () => {
    renderRoute("/");

    expect(await screen.findByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });

  it("marks the current page in the navigation", async () => {
    renderRoute("/");

    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: /Dashboard/ })).toHaveAttribute("aria-current", "page");
  });

  it("shows later modules as unavailable instead of linking to them", async () => {
    renderRoute("/");

    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: /Projects/ })).not.toBeInTheDocument();
    const projects = within(nav).getByText("Projects").closest("[aria-disabled]");
    expect(projects).toHaveAttribute("aria-disabled", "true");
    expect(projects).toHaveTextContent(/Coming in phase\s*P?2/);
  });

  it("opens and closes the mobile navigation", async () => {
    const user = userEvent.setup();
    renderRoute("/");

    await user.click(await screen.findByRole("button", { name: "Open navigation" }));
    const dialog = screen.getByRole("dialog", { name: "Navigation", hidden: true });
    expect(dialog).toHaveAttribute("open");

    await user.click(within(dialog).getByRole("button", { name: "Close navigation", hidden: true }));
    expect(dialog).not.toHaveAttribute("open");
  });

  it("shows the API status in the sidebar", async () => {
    renderRoute("/");

    const nav = await screen.findAllByText("Online");
    expect(nav.length).toBeGreaterThan(0);
  });
});
