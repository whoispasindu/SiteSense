interface TopBarProps {
  isMenuOpen: boolean
  onMenuToggle: () => void
}

export function TopBar({ isMenuOpen, onMenuToggle }: TopBarProps) {
  return (
    <header className="flex h-16 items-center gap-4 border-b border-slate-200 bg-white px-4 md:px-8">
      {/* The menu button only shows on small screens, where the sidebar is hidden by default */}
      <button
        type="button"
        onClick={onMenuToggle}
        aria-controls="sidebar"
        aria-expanded={isMenuOpen}
        className="rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 md:hidden"
      >
        {isMenuOpen ? 'Close menu' : 'Menu'}
      </button>
      <div className="flex-1" />
      {/* Phase 1: signed-in user's name, role and a sign-out button go here */}
    </header>
  )
}
