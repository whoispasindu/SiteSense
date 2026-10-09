import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router";

import { useAuth } from "../../auth/context";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "")).toUpperCase();
}

/** Signed-in user chip with a small menu: role, sites, change password, sign out. */
export function UserMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointer(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => {
          setOpen((v) => !v);
        }}
        className="flex min-h-11 items-center gap-2.5 rounded-[var(--radius-sheet)] border border-rule bg-paper-raised py-1 pr-3 pl-1 hover:border-ink"
      >
        <span
          aria-hidden="true"
          className="font-wide grid size-9 place-items-center rounded-[2px] bg-asphalt text-xs font-bold tracking-wider text-hivis"
        >
          {initials(user.full_name)}
        </span>
        <span className="hidden text-left leading-tight md:block">
          <span className="block max-w-40 truncate text-sm font-semibold">{user.full_name}</span>
          <span className="block font-mono text-[0.65rem] tracking-wider text-ink-faint uppercase">
            {user.role_label}
          </span>
        </span>
        <span className="sr-only md:hidden">Account menu for {user.full_name}</span>
      </button>

      {open ? (
        <div
          id={menuId}
          className="animate-rise absolute top-full right-0 z-30 mt-2 w-72 rounded-[var(--radius-sheet)] border border-rule bg-paper-raised shadow-[var(--shadow-sheet)]"
        >
          <div className="border-b border-dashed border-rule px-4 py-3">
            <p className="truncate font-semibold">{user.full_name}</p>
            <p className="truncate text-sm text-ink-soft">{user.email}</p>
            <p className="mt-2 font-mono text-[0.65rem] tracking-wider text-ink-faint uppercase">
              {user.role_label} ·{" "}
              {user.site_scoped
                ? `${String(user.sites.length)} site${user.sites.length === 1 ? "" : "s"}`
                : "All sites"}
            </p>
            {user.site_scoped && user.sites.length > 0 ? (
              <p className="mt-1.5 flex flex-wrap gap-1">
                {user.sites.map((site) => (
                  <span key={site.id} className="rounded-[2px] bg-paper-sunk px-1.5 py-0.5 font-mono text-[0.65rem]">
                    {site.code}
                  </span>
                ))}
              </p>
            ) : null}
          </div>
          <div className="p-1.5">
            <Link
              to="/change-password"
              onClick={() => {
                setOpen(false);
              }}
              className="flex min-h-11 items-center rounded-[2px] px-3 text-sm hover:bg-paper-sunk"
            >
              Change password
            </Link>
            <button
              type="button"
              onClick={() => void signOut()}
              className="flex min-h-11 w-full items-center rounded-[2px] px-3 text-left text-sm font-semibold text-signal-high hover:bg-signal-high-tint"
            >
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
