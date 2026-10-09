import { render, screen } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { describe, expect, it, vi } from "vitest";

import { RouteErrorPage } from "./RouteErrorPage";

function Boom(): never {
  throw new Error("SELECT * FROM users -- secret internal detail");
}

describe("RouteErrorPage", () => {
  it("shows a safe message and never the error details", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const router = createMemoryRouter([{ path: "/", element: <Boom />, errorElement: <RouteErrorPage /> }]);

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Work stopped on this screen.");
    expect(document.body).not.toHaveTextContent("secret internal detail");
    expect(screen.getByRole("link", { name: "Return to the dashboard" })).toHaveAttribute("href", "/");
  });

  it("renders the not-found page for 404 route errors", async () => {
    const router = createMemoryRouter([{ path: "/", element: <p>home</p>, errorElement: <RouteErrorPage /> }], {
      initialEntries: ["/missing"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "Off the drawings." })).toBeInTheDocument();
  });
});
