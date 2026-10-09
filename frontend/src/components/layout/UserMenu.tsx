import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router";

import { useAuth } from "../../auth/context";
import { useTheme, type ThemePreference } from "../../lib/theme";
import { Icon, type IconName } from "../ui/icons";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "")).toUpperCase();
}

const THEMES: { value: ThemePreference; label: string; icon: IconName }[] = [
  { value: "light", label: "Light", icon: "sun" },
  { value: "dark", label: "Dark", icon: "moon" },
  { value: "system", label: "System", icon: "monitor" },
];

function ThemeSwitch() {
  const [theme, setTheme] = useTheme();
  return (
    <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 gap-1 rounded-lg bg-paper-sunk p-1">
      {THEMES.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={theme === option.value}
          onClick={() => {
            setTheme(option.value);
          }}
          className={`flex min-h-8 items-center justify-center gap-1.5 rounded-md text-xs font-medium transition-colors ${
            theme === option.value ? "bg-paper-raised text-ink shadow-[var(--shadow-sheet)]" : "text-ink-soft hover:text-ink"
          }`}
        >
          <Icon name={option.icon} className="size-3.5" />
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** Signed-in user chip with a menu: role, sites, theme, change password, sign out. */
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
        className="flex min-h-10 items-center gap-2.5 rounded-lg py-1 pr-2 pl-1 hover:bg-paper-sunk"
      >
        <span
          aria-hidden="true"
          className="grid size-8 place-items-center rounded-full bg-asphalt text-xs font-semibold text-hivis"
        >
          {initials(user.full_name)}
        </span>
        <span className="hidden text-left leading-tight md:block">
          <span className="block max-w-44 truncate text-sm font-medium text-ink">{user.full_name}</span>
          <span className="block text-xs text-ink-faint">{user.role_label}</span>
        </span>
        <span className="sr-only md:hidden">Account menu for {user.full_name}</span>
      </button>

      {open ? (
        <div
          id={menuId}
          className="animate-rise absolute top-full right-0 z-30 mt-2 w-72 rounded-xl border border-rule bg-paper-raised p-1.5 shadow-[var(--shadow-pop)]"
        >
          <div className="px-3 pt-2 pb-3">
            <p className="truncate font-medium text-ink">{user.full_name}</p>
            <p className="truncate text-sm text-ink-soft">{user.email}</p>
            <p className="mt-2 text-xs text-ink-faint">
              {user.role_label} ·{" "}
              {user.site_scoped ? `${String(user.sites.length)} site${user.sites.length === 1 ? "" : "s"}` : "All sites"}
            </p>
            {user.site_scoped && user.sites.length > 0 ? (
              <p className="mt-1.5 flex flex-wrap gap-1">
                {user.sites.map((site) => (
                  <span key={site.id} className="rounded-md bg-paper-sunk px-1.5 py-0.5 font-mono text-xs text-ink-soft">
                    {site.code}
                  </span>
                ))}
              </p>
            ) : null}
          </div>
          <div className="border-t border-rule px-2 py-3">
            <p className="mb-2 px-1 text-xs font-medium text-ink-faint">Appearance</p>
            <ThemeSwitch />
          </div>
          <div className="border-t border-rule pt-1.5">
            <Link
              to="/change-password"
              onClick={() => {
                setOpen(false);
              }}
              className="flex min-h-10 items-center rounded-lg px-3 text-sm text-ink hover:bg-paper-sunk"
            >
              Change password
            </Link>
            <button
              type="button"
              onClick={() => void signOut()}
              className="flex min-h-10 w-full items-center rounded-lg px-3 text-left text-sm font-medium text-signal-high hover:bg-signal-high-tint"
            >
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
