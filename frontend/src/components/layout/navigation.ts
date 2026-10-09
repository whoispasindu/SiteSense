import { CURRENT_PHASE } from "../../lib/programme";

export interface NavItem {
  /** Drawing-sheet style index shown beside the label. */
  code: string;
  label: string;
  path: string;
  /** The build phase that delivers this module; later modules render as "coming". */
  phase: number;
  /** Permission needed to see the item. Omitted: every signed-in user. */
  permission?: string;
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
      { code: "02", label: "Projects", path: "/projects", phase: 2, permission: "projects:read" },
      { code: "03", label: "Schedule", path: "/schedule", phase: 3, permission: "schedule:read" },
      { code: "04", label: "Site reports", path: "/reports", phase: 4, permission: "reports:read" },
      { code: "05", label: "Materials", path: "/materials", phase: 5, permission: "materials:read" },
    ],
  },
  {
    label: "Control",
    items: [
      { code: "06", label: "Risk & what-if", path: "/risk", phase: 6, permission: "risk:read" },
      { code: "07", label: "Cost & claims", path: "/cost", phase: 8, permission: "cost:read" },
      { code: "08", label: "Client portal", path: "/client", phase: 12, permission: "client:portal" },
    ],
  },
  {
    label: "Admin",
    items: [
      { code: "09", label: "Users", path: "/admin/users", phase: 1, permission: "users:manage" },
      { code: "10", label: "Sites", path: "/admin/sites", phase: 1, permission: "sites:manage" },
      { code: "11", label: "Audit log", path: "/admin/audit", phase: 1, permission: "audit:read" },
    ],
  },
];

export function isAvailable(item: NavItem, currentPhase: number = CURRENT_PHASE): boolean {
  return item.phase <= currentPhase;
}

export function findNavItem(pathname: string): NavItem | undefined {
  return NAV_GROUPS.flatMap((group) => group.items).find((item) => item.path === pathname);
}

/** The menu a user sees: only groups and items their permissions allow. */
export function navForPermissions(can: (permission: string) => boolean): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => item.permission === undefined || can(item.permission)),
  })).filter((group) => group.items.length > 0);
}
