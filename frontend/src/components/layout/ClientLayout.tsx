import { NavLink, Outlet } from "react-router";

import { LogoMark } from "../ui/Logo";
import { DemoBanner } from "./DemoBanner";
import { NotificationBell } from "./NotificationBell";
import { UserMenu } from "./UserMenu";

const LINK = "relative flex h-14 items-center px-1 text-sm transition-colors";

function TopLink({ to, end, children }: { to: string; end?: boolean; children: string }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `${LINK} ${
          isActive
            ? "font-medium text-white after:absolute after:inset-x-0 after:bottom-0 after:h-[3px] after:rounded-t-full after:bg-hivis"
            : "text-asphalt-text/80 hover:text-white"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

/**
 * The client's shell (Phase 12): a simpler top navigation instead of the staff sidebar. Two places to
 * go, their projects and the variations sent to them; alerts and the account menu sit on the right.
 */
export function ClientLayout() {
  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-hivis px-4 py-2.5 text-sm font-semibold text-asphalt focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <DemoBanner />
      <header className="on-asphalt sticky top-0 z-20 bg-asphalt text-asphalt-text">
        <div aria-hidden="true" className="hazard-band h-1" />
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 sm:gap-8 sm:px-8">
          <NavLink to="/" className="flex shrink-0 items-center gap-2.5" aria-label="SiteSense, your projects">
            <LogoMark className="size-8" />
            <span className="hidden text-[1.0625rem] font-semibold tracking-tight text-white sm:inline">SiteSense</span>
          </NavLink>
          <nav aria-label="Main" className="flex min-w-0 items-center gap-5 overflow-x-auto [scrollbar-width:none]">
            <TopLink to="/" end>
              Your projects
            </TopLink>
            <TopLink to="/client/variations">Variations</TopLink>
          </nav>
          <div className="ml-auto flex items-center gap-1 sm:gap-3">
            <NotificationBell onDark />
            <UserMenu onDark />
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto max-w-6xl px-4 py-6 outline-none sm:px-8 lg:py-10">
        <Outlet />
      </main>
    </div>
  );
}
