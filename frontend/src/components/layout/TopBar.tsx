import { useEffect, useState } from "react";
import { useLocation } from "react-router";

import { useAuth } from "../../auth/context";
import { formatSiteClock } from "../../lib/time";
import { Icon } from "../ui/icons";
import { findNavItem, isAvailable } from "./navigation";
import { NotificationBell } from "./NotificationBell";
import { UserMenu } from "./UserMenu";

function SiteClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(new Date());
    }, 30_000);
    return () => {
      window.clearInterval(id);
    };
  }, []);

  return (
    <time dateTime={now.toISOString()} className="tabular hidden text-sm text-ink-faint md:block">
      {formatSiteClock(now)}
    </time>
  );
}

interface TopBarProps {
  onOpenMenu: () => void;
}

export function TopBar({ onOpenMenu }: TopBarProps) {
  const { pathname } = useLocation();
  const { can } = useAuth();
  const match = findNavItem(pathname);
  // Only name pages the user can actually open: unbuilt modules show 404, forbidden ones 403.
  const allowed = match && isAvailable(match) && (match.permission === undefined || can(match.permission));
  const current = allowed ? match : undefined;

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-rule bg-paper/85 px-4 backdrop-blur-md sm:px-8">
      <button
        type="button"
        onClick={onOpenMenu}
        className="-ml-2 inline-flex size-10 items-center justify-center rounded-lg text-ink-soft hover:bg-paper-sunk hover:text-ink lg:hidden"
        aria-label="Open navigation"
      >
        <Icon name="menu" className="size-5" />
      </button>

      <p className="min-w-0 truncate text-sm font-medium text-ink">{current?.label ?? "SiteSense"}</p>

      <div className="ml-auto flex items-center gap-2 sm:gap-4">
        <SiteClock />
        {import.meta.env.MODE === "production" ? null : (
          <span className="hidden rounded-full bg-paper-sunk px-2.5 py-0.5 text-xs text-ink-faint lg:inline">
            Development
          </span>
        )}
        <NotificationBell />
        <UserMenu />
      </div>
    </header>
  );
}
