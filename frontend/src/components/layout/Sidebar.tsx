import { NavLink } from 'react-router-dom'
import { navItems } from './navigation'

interface SidebarProps {
  isOpen: boolean
  onNavigate: () => void
}

export function Sidebar({ isOpen, onNavigate }: SidebarProps) {
  return (
    <aside
      id="sidebar"
      className={`${isOpen ? 'flex' : 'hidden'} fixed inset-y-0 left-0 z-20 w-64 flex-col bg-slate-900 text-slate-100 md:static md:flex`}
    >
      <div className="flex h-16 items-center px-6 text-xl font-bold tracking-tight">
        Site<span className="text-yellow-400">Sense</span>
      </div>
      <nav aria-label="Main" className="flex-1 space-y-1 px-3 py-4">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              `block rounded-md px-3 py-2.5 text-sm font-medium ${
                isActive ? 'bg-yellow-400 text-slate-900' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
