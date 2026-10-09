import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { apiRequest } from "./client";

export const healthSchema = z.object({
  status: z.literal("ok"),
  version: z.string(),
});

export const readinessSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  checks: z.record(z.string(), z.enum(["ok", "unavailable"])),
});

export type Health = z.infer<typeof healthSchema>;
export type Readiness = z.infer<typeof readinessSchema>;

export interface Timed<T> {
  data: T;
  latencyMs: number;
}

async function timed<T>(run: () => Promise<{ data: T }>): Promise<Timed<T>> {
  const started = performance.now();
  const { data } = await run();
  return { data, latencyMs: Math.round(performance.now() - started) };
}

const REFRESH_MS = 30_000;

export function useHealth() {
  return useQuery({
    queryKey: ["health", "live"],
    queryFn: ({ signal }) => timed(() => apiRequest("/health", healthSchema, { signal })),
    refetchInterval: REFRESH_MS,
  });
}

export function useReadiness() {
  return useQuery({
    queryKey: ["health", "ready"],
    // 503 is an expected answer here ("degraded"), not a failure of the request itself.
    queryFn: ({ signal }) =>
      timed(() => apiRequest("/health/ready", readinessSchema, { signal, acceptStatuses: [503] })),
    refetchInterval: REFRESH_MS,
  });
}
