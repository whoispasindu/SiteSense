export interface NavItem {
  label: string
  to: string
}

// Each phase adds its screens here (Projects in Phase 2, Daily reports in Phase 4, ...).
// Phase 1 adds the roles allowed to see each item, so every role gets its own menu.
export const navItems: NavItem[] = [{ label: 'Dashboard', to: '/' }]
