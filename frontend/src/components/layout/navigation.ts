import { CURRENT_PHASE } from "../../lib/programme";

export interface NavItem {
  /** Drawing-sheet style index shown beside the label. */
  code: string;
  label: string;
  path: string;
  /** The build phase that delivers this module; later modules render as "coming". */
  phase: number;
}

export interface NavGroup {
  label: string;
  items: readonly NavItem[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    label: "Site office",
    items: [
      { code: "01", label: "Dashboard", path: "/", phase: 0 },
      { code: "02", label: "Projects", path: "/projects", phase: 2 },
      { code: "03", label: "Schedule", path: "/schedule", phase: 3 },
      { code: "04", label: "Site reports", path: "/reports", phase: 4 },
      { code: "05", label: "Materials", path: "/materials", phase: 5 },
    ],
  },
  {
    label: "Control",
    items: [
      { code: "06", label: "Risk & what-if", path: "/risk", phase: 6 },
      { code: "07", label: "Cost & claims", path: "/cost", phase: 8 },
      { code: "08", label: "Client portal", path: "/client", phase: 12 },
    ],
  },
  {
    label: "Admin",
    items: [{ code: "09", label: "Users & sites", path: "/admin/users", phase: 1 }],
  },
];

export function isAvailable(item: NavItem, currentPhase: number = CURRENT_PHASE): boolean {
  return item.phase <= currentPhase;
}

export function findNavItem(pathname: string): NavItem | undefined {
  return NAV_GROUPS.flatMap((group) => group.items).find((item) => item.path === pathname);
}
