import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { makeMe, mockApi, renderRoute, sessionApi } from "../../test/utils";
import { isAvailable, NAV_GROUPS } from "./navigation";

describe("AppLayout", () => {
  beforeEach(() => {
    mockApi(sessionApi(makeMe("project_manager")));
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

  it("links every module now that every phase's module is built", async () => {
    mockApi(sessionApi(makeMe("project_manager")));
    renderRoute("/");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).queryByText("Soon")).not.toBeInTheDocument();
  });

  it("would show a later module as unavailable (the gating rule)", () => {
    const item = { label: "Later", path: "/later", icon: "projects", phase: 15 } as const;
    expect(isAvailable(item)).toBe(false);
    expect(isAvailable(item, 15)).toBe(true);
    expect(NAV_GROUPS.flatMap((g) => g.items).every((i) => isAvailable(i))).toBe(true);
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
