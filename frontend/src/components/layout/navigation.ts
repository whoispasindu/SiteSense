import { CURRENT_PHASE } from "../../lib/programme";
import type { IconName } from "../ui/icons";

export interface NavItem {
  label: string;
  path: string;
  icon: IconName;
  /** The build phase that delivers this module; later modules render as "Soon". */
  phase: number;
  /** Permission needed to see the item. Omitted: every signed-in user. */
  permission?: string;
  /** Other path prefixes that belong to this item (for the page title), e.g. /variations under Cost. */
  aliases?: readonly string[];
}

export interface NavGroup {
  label: string;
  items: readonly NavItem[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    label: "Site office",
    items: [
      { label: "Dashboard", path: "/", icon: "dashboard", phase: 0 },
      { label: "Projects", path: "/projects", icon: "projects", phase: 2, permission: "projects:read" },
      { label: "Schedule", path: "/schedule", icon: "schedule", phase: 3, permission: "schedule:read" },
      { label: "Site reports", path: "/reports", icon: "reports", phase: 4, permission: "reports:read" },
      { label: "Materials", path: "/materials", icon: "materials", phase: 5, permission: "materials:read" },
      { label: "Purchase orders", path: "/purchase-orders", icon: "cost", phase: 5, permission: "materials:read" },
      { label: "Suppliers", path: "/suppliers", icon: "client", phase: 5, permission: "suppliers:manage" },
    ],
  },
  {
    label: "Control",
    items: [
      // Every project by risk; each project's Risk tab holds its trend and the what-if planner (Phase 10).
      { label: "Risk & what-if", path: "/risk", icon: "risk", phase: 10, permission: "risk:read" },
      { label: "Cost & claims", path: "/cost", icon: "cost", phase: 8, permission: "cost:read", aliases: ["/variations"] },
      { label: "Variations", path: "/client/variations", icon: "cost", phase: 8, permission: "client:portal" },
      { label: "Client portal", path: "/client", icon: "client", phase: 12, permission: "client:portal" },
    ],
  },
  {
    label: "Admin",
    items: [
      { label: "Users", path: "/admin/users", icon: "users", phase: 1, permission: "users:manage" },
      { label: "Sites", path: "/admin/sites", icon: "sites", phase: 1, permission: "sites:manage" },
      { label: "Holidays", path: "/admin/holidays", icon: "schedule", phase: 9, permission: "holidays:manage" },
      { label: "Variation limits", path: "/admin/variation-limits", icon: "cost", phase: 8, permission: "variation_limits:manage" },
      { label: "Audit log", path: "/admin/audit", icon: "audit", phase: 1, permission: "audit:read" },
    ],
  },
];

export function isAvailable(item: NavItem, currentPhase: number = CURRENT_PHASE): boolean {
  return item.phase <= currentPhase;
}

/** The menu item for a path, including nested pages such as /projects/:id/boq. */
export function findNavItem(pathname: string): NavItem | undefined {
  const items = NAV_GROUPS.flatMap((group) => group.items);
  return (
    items.find((item) => item.path === pathname) ??
    items.find((item) => item.path !== "/" && pathname.startsWith(`${item.path}/`)) ??
    items.find((item) => item.aliases?.some((alias) => pathname === alias || pathname.startsWith(`${alias}/`)))
  );
}

/** The menu a user sees: only groups and items their permissions allow. */
export function navForPermissions(can: (permission: string) => boolean): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => item.permission === undefined || can(item.permission)),
  })).filter((group) => group.items.length > 0);
}
