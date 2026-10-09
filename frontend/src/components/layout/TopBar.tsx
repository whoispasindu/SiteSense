import { useEffect, useState } from "react";
import { useLocation } from "react-router";

import { formatSiteClock } from "../../lib/time";
import { findNavItem, isAvailable } from "./navigation";

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
    <time dateTime={now.toISOString()} className="tabular hidden font-mono text-xs text-ink-soft sm:block">
      {formatSiteClock(now)} <span className="text-ink-faint">LKT</span>
    </time>
  );
}

interface TopBarProps {
  onOpenMenu: () => void;
}

export function TopBar({ onOpenMenu }: TopBarProps) {
  const { pathname } = useLocation();
  const match = findNavItem(pathname);
  // A module that is not built yet renders the 404 page, so it must not be named here either.
  const current = match && isAvailable(match) ? match : undefined;

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-4 border-b border-rule bg-paper/90 px-4 backdrop-blur-sm sm:px-8">
      <button
        type="button"
        onClick={onOpenMenu}
        className="-ml-2 inline-flex size-11 items-center justify-center rounded-[var(--radius-sheet)] text-ink hover:bg-paper-sunk lg:hidden"
        aria-label="Open navigation"
      >
        <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
          <path d="M3 6h18M3 12h12M3 18h18" stroke="currentColor" strokeWidth="2" fill="none" />
        </svg>
      </button>

      <p className="flex min-w-0 items-baseline gap-2 text-sm">
        <span className="hidden font-mono text-xs text-ink-faint sm:inline">{current?.code ?? "--"}</span>
        <span aria-hidden="true" className="hidden text-rule-strong sm:inline">
          /
        </span>
        <span className="font-wide truncate font-bold tracking-[0.08em] uppercase">{current?.label ?? "SiteSense"}</span>
      </p>

      <div className="ml-auto flex items-center gap-4">
        <SiteClock />
        <span className="font-wide rounded-full border border-dashed border-rule-strong px-3 py-1 text-[0.65rem] font-bold tracking-[0.16em] text-ink-faint uppercase">
          {import.meta.env.MODE === "production" ? "Live" : "Dev build"}
        </span>
      </div>
    </header>
  );
}
