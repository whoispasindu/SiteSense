import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet } from "react-router";

import { SidebarContent } from "./Sidebar";
import { TopBar } from "./TopBar";

/**
 * App shell: fixed asphalt sidebar on large screens; on phones the same navigation opens in a
 * native modal <dialog>, which gives focus trapping, Escape-to-close and inert background for free.
 */
export function AppLayout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (menuOpen && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    } else if (!menuOpen && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [menuOpen]);

  const closeMenu = useCallback(() => {
    setMenuOpen(false);
  }, []);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[17rem_1fr]">
      <a
        href="#main"
        className="font-wide sr-only z-50 bg-hivis px-4 py-3 text-xs font-bold tracking-widest text-ink uppercase focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>

      <aside className="sticky top-0 hidden h-dvh lg:block">
        <SidebarContent />
      </aside>

      <dialog
        ref={dialogRef}
        aria-label="Navigation"
        onClose={closeMenu}
        className="m-0 h-dvh max-h-none w-[min(19rem,86vw)] max-w-none bg-transparent p-0 backdrop:bg-asphalt/60 lg:hidden"
      >
        <div className="relative h-full">
          <SidebarContent onNavigate={closeMenu} />
          <button
            type="button"
            onClick={closeMenu}
            aria-label="Close navigation"
            className="absolute top-5 right-3 inline-flex size-11 items-center justify-center text-asphalt-text hover:text-paper"
          >
            <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" />
            </svg>
          </button>
        </div>
      </dialog>

      <div className="flex min-w-0 flex-col">
        <TopBar
          onOpenMenu={() => {
            setMenuOpen(true);
          }}
        />
        <main id="main" tabIndex={-1} className="drafting-grid flex-1 px-4 py-8 outline-none sm:px-8 lg:py-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
