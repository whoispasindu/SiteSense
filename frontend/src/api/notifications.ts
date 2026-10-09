import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiRequest } from "./client";

const notificationSchema = z.object({
  id: z.uuid(),
  kind: z.string(),
  title: z.string(),
  body: z.string(),
  link: z.string().nullable(),
  created_at: z.iso.datetime({ offset: true }),
  read_at: z.iso.datetime({ offset: true }).nullable(),
});
export type Notification = z.infer<typeof notificationSchema>;

const listSchema = z.object({ items: z.array(notificationSchema), unread: z.number().int() });

export const notificationKeys = { all: ["notifications"] as const };

/** In-app links only: a stored link that is not a same-origin path is ignored. */
export function safeInternalLink(link: string | null): string | null {
  return link?.startsWith("/") && !link.startsWith("//") ? link : null;
}

export function useNotifications() {
  return useQuery({
    queryKey: notificationKeys.all,
    queryFn: ({ signal }) => apiRequest("/notifications", listSchema, { signal }).then((r) => r.data),
    refetchInterval: 60_000,
  });
}

export function useMarkRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/notifications/${encodeURIComponent(id)}/read`, notificationSchema, { method: "POST" }).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}

export function useMarkAllRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest("/notifications/read-all", z.null(), { method: "POST" }).then(() => undefined),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}
