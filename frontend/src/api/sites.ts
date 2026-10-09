import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { siteSummarySchema } from "./auth";
import { apiRequest } from "./client";

/** Active sites the signed-in user may work on (assigned sites for site-scoped roles). */
export function useMySites() {
  return useQuery({
    queryKey: ["sites", "mine"],
    queryFn: ({ signal }) => apiRequest("/sites", z.array(siteSummarySchema), { signal }).then((r) => r.data),
  });
}
