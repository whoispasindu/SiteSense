import { describe, expect, it } from "vitest";

import { ApiError } from "./client";
import { createQueryClient, shouldRetry } from "./queryClient";

const error = (status: number) => new ApiError({ status, code: "x", message: "x" });

describe("shouldRetry", () => {
  it("retries network failures and server errors", () => {
    expect(shouldRetry(0, error(0))).toBe(true);
    expect(shouldRetry(1, error(503))).toBe(true);
  });

  it("never retries client errors", () => {
    expect(shouldRetry(0, error(400))).toBe(false);
    expect(shouldRetry(0, error(403))).toBe(false);
    expect(shouldRetry(0, error(422))).toBe(false);
  });

  it("stops after two attempts", () => {
    expect(shouldRetry(2, error(503))).toBe(false);
  });

  it("retries unknown errors", () => {
    expect(shouldRetry(0, new Error("boom"))).toBe(true);
  });
});

describe("createQueryClient", () => {
  it("applies the retry policy to queries and never retries mutations", () => {
    const client = createQueryClient();
    const defaults = client.getDefaultOptions();

    expect(defaults.queries?.retry).toBe(shouldRetry);
    expect(defaults.mutations?.retry).toBe(false);
    const delay = defaults.queries?.retryDelay as (attempt: number) => number;
    expect(delay(1)).toBe(2000);
    expect(delay(10)).toBe(8000);
  });
});
