import { NavLink } from "react-router";

import { useHealth } from "../../api/health";
import { useAuth } from "../../auth/context";
import { LogoMark } from "../ui/Logo";
import { isAvailable, navForPermissions, type NavItem } from "./navigation";

interface SidebarProps {
  onNavigate?: () => void;
}

function NavEntry({ item, onNavigate }: { item: NavItem; onNavigate?: (() => void) | undefined }) {
  const base =
    "group relative flex min-h-11 items-center gap-3 rounded-[var(--radius-sheet)] px-3 text-sm transition-colors";

  if (!isAvailable(item)) {
    return (
      <span aria-disabled="true" className={`${base} cursor-default text-asphalt-muted/70`}>
        <span className="font-mono text-[0.7rem] text-asphalt-muted/60">{item.code}</span>
        <span className="flex-1">{item.label}</span>
        <span className="font-mono text-[0.62rem] tracking-wider text-asphalt-muted">
          <span className="sr-only">Coming in phase </span>
          <span aria-hidden="true">P</span>
          {item.phase}
        </span>
      </span>
    );
  }

  return (
    <NavLink
      to={item.path}
      end={item.path === "/"}
      onClick={onNavigate}
      className={({ isActive }) =>
        `${base} ${
          isActive
            ? "bg-asphalt-raised font-semibold text-hivis before:absolute before:inset-y-2 before:-left-3 before:w-1 before:bg-hivis"
            : "text-asphalt-text hover:bg-asphalt-raised hover:text-paper"
        }`
      }
    >
      <span className="font-mono text-[0.7rem] opacity-70">{item.code}</span>
      <span className="flex-1">{item.label}</span>
    </NavLink>
  );
}

function ApiStatus() {
  const { data, isError, isPending } = useHealth();
  const label = isPending ? "Checking" : isError ? "Offline" : "Online";
  const dot = isPending ? "bg-asphalt-muted" : isError ? "bg-signal-high" : "bg-[#5fd08a] animate-pulse-dot";

  return (
    <div className="flex items-center justify-between gap-2 font-mono text-[0.7rem] text-asphalt-muted">
      <span className="flex items-center gap-2">
        <span aria-hidden="true" className={`size-2 rounded-full text-[#5fd08a] ${dot}`} />
        <span>
          API <span className="text-asphalt-text">{label}</span>
        </span>
      </span>
      {data ? <span className="tabular">{data.latencyMs} ms</span> : null}
    </div>
  );
}

export function SidebarContent({ onNavigate }: SidebarProps) {
  const { can } = useAuth();
  const groups = navForPermissions(can);

  return (
    <div className="on-asphalt flex h-full flex-col bg-asphalt text-asphalt-text">
      <div aria-hidden="true" className="hazard-band h-1.5 shrink-0" />

      <div className="flex items-center gap-3 px-6 pt-6 pb-8">
        <LogoMark className="size-9" />
        <div className="leading-none">
          <p className="font-wide text-base font-extrabold tracking-[0.18em] text-paper uppercase">SiteSense</p>
          <p className="mt-1.5 font-mono text-[0.62rem] tracking-[0.2em] text-asphalt-muted uppercase">
            Delay &amp; cost control
          </p>
        </div>
      </div>

      <nav aria-label="Main" className="flex-1 space-y-7 overflow-y-auto px-6">
        {groups.map((group) => (
          <div key={group.label}>
            <p className="font-wide mb-2 text-[0.62rem] font-bold tracking-[0.24em] text-asphalt-muted uppercase">
              {group.label}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <li key={item.path}>
                  <NavEntry item={item} onNavigate={onNavigate} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="space-y-2 border-t border-asphalt-line px-6 py-5">
        <ApiStatus />
        <p className="font-mono text-[0.62rem] text-asphalt-muted">
          Web <span className="text-asphalt-text">v{__APP_VERSION__}</span>
        </p>
      </div>
    </div>
  );
}
