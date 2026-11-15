import { NavLink } from "react-router";

import { useHealth } from "../../api/health";
import { useAuth } from "../../auth/context";
import { Icon } from "../ui/icons";
import { LogoMark } from "../ui/Logo";
import { isAvailable, navForPermissions, type NavItem } from "./navigation";

interface SidebarProps {
  onNavigate?: () => void;
}

const ITEM = "group relative flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm transition-colors";

function NavEntry({ item, onNavigate }: { item: NavItem; onNavigate?: (() => void) | undefined }) {
  if (!isAvailable(item)) {
    return (
      <span aria-disabled="true" className={`${ITEM} cursor-default text-asphalt-muted/70`}>
        <Icon name={item.icon} />
        <span className="flex-1">{item.label}</span>
        <span className="rounded-full border border-asphalt-line px-1.5 py-px text-[0.6875rem] text-asphalt-muted">
          <span className="sr-only">Coming in phase {item.phase}</span>
          <span aria-hidden="true">Soon</span>
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
        `${ITEM} ${
          isActive
            ? "bg-asphalt-raised font-medium text-white before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-full before:bg-hivis"
            : "text-asphalt-text/85 hover:bg-asphalt-raised hover:text-white"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <span className={isActive ? "text-hivis" : "text-asphalt-muted group-hover:text-asphalt-text"}>
            <Icon name={item.icon} />
          </span>
          <span className="flex-1">{item.label}</span>
        </>
      )}
    </NavLink>
  );
}

function ApiStatus() {
  const { data, isError, isPending } = useHealth();
  const label = isPending ? "Checking" : isError ? "Offline" : "Online";
  const dot = isPending ? "bg-asphalt-muted" : isError ? "bg-signal-high" : "bg-[#5fd08a] animate-pulse-dot";

  return (
    <div className="flex items-center justify-between gap-2 text-xs text-asphalt-muted">
      <span className="flex items-center gap-2">
        <span aria-hidden="true" className={`size-2 rounded-full text-[#5fd08a] ${dot}`} />
        <span>
          API <span className="text-asphalt-text">{label}</span>
        </span>
      </span>
      <span className="tabular">{data ? `${String(data.latencyMs)} ms · ` : ""}v{__APP_VERSION__}</span>
    </div>
  );
}

/** AGPL-3.0 section 13: where the source of this running version is. */
export function SourceLink({ className = "" }: { className?: string }) {
  return (
    <a href={__SOURCE_URL__} target="_blank" rel="noreferrer" className={`underline-offset-2 hover:underline ${className}`}>
      Source code (AGPL-3.0)
    </a>
  );
}

export function SidebarContent({ onNavigate }: SidebarProps) {
  const { can } = useAuth();
  const groups = navForPermissions(can);

  return (
    <div className="on-asphalt flex h-full flex-col bg-asphalt text-asphalt-text">
      <div aria-hidden="true" className="hazard-band h-1 shrink-0" />

      <div className="flex items-center gap-3 px-5 pt-5 pb-6">
        <LogoMark className="size-9" />
        <div className="leading-tight">
          <p className="text-[1.0625rem] font-semibold tracking-tight text-white">SiteSense</p>
          <p className="text-xs text-asphalt-muted">Delay &amp; cost control</p>
        </div>
      </div>

      <nav aria-label="Main" className="flex-1 space-y-6 overflow-y-auto px-3">
        {groups.map((group) => (
          <div key={group.label}>
            <p className="mb-1.5 px-3 text-[0.6875rem] font-semibold text-asphalt-muted uppercase">
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

      <div className="space-y-2 border-t border-asphalt-line px-5 py-4">
        <ApiStatus />
        <SourceLink className="block text-xs text-asphalt-muted" />
      </div>
    </div>
  );
}
