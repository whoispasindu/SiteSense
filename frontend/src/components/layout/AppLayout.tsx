import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet } from "react-router";

import { useAuth } from "../../auth/context";
import { Icon } from "../ui/icons";
import { ClientLayout } from "./ClientLayout";
import { DemoBanner } from "./DemoBanner";
import { SidebarContent } from "./Sidebar";
import { TopBar } from "./TopBar";

/**
 * App shell for staff: fixed asphalt sidebar on large screens; on phones the same navigation opens in a
 * native modal <dialog>, which gives focus trapping, Escape-to-close and inert background for free.
 */
export function AppLayout() {
  const { can } = useAuth();
  // Clients get a simpler top navigation (Phase 12); everyone else the site-office sidebar.
  return can("client:portal") ? <ClientLayout /> : <StaffLayout />;
}

function StaffLayout() {
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
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_1fr]">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-hivis px-4 py-2.5 text-sm font-semibold text-asphalt focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>

      {/* Named, so it stays distinct from any other complementary area a page has. */}
      <aside aria-label="Sidebar" className="sticky top-0 hidden h-dvh lg:block">
        <SidebarContent />
      </aside>

      <dialog
        ref={dialogRef}
        aria-label="Navigation"
        onClose={closeMenu}
        className="m-0 h-dvh max-h-none w-[min(18rem,86vw)] max-w-none bg-transparent p-0 backdrop:bg-black/50 lg:hidden"
      >
        <div className="relative h-full">
          <SidebarContent onNavigate={closeMenu} />
          <button
            type="button"
            onClick={closeMenu}
            aria-label="Close navigation"
            className="absolute top-5 right-3 inline-flex size-10 items-center justify-center rounded-lg text-asphalt-text hover:bg-asphalt-raised hover:text-white"
          >
            <Icon name="close" className="size-5" />
          </button>
        </div>
      </dialog>

      <div className="flex min-w-0 flex-col">
        <DemoBanner />
        <TopBar
          onOpenMenu={() => {
            setMenuOpen(true);
          }}
        />
        <main id="main" tabIndex={-1} className="flex-1 px-4 py-6 outline-none sm:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
