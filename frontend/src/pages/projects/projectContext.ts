import { useOutletContext } from "react-router";

import type { ProjectDetail } from "../../api/projects";

/** The project loaded by ProjectLayout, available to its tab pages. */
export function useCurrentProject(): ProjectDetail {
  return useOutletContext<ProjectDetail>();
}
