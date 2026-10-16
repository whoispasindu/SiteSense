import { useAuth } from "../../auth/context";

/** Shown when the server runs the demo (``SITESENSE_DEMO_MODE``), so nobody mistakes it for real data. */
export function DemoBanner() {
  const { user } = useAuth();
  if (!user?.demo_mode) return null;
  return (
    <aside aria-label="Demo notice" className="bg-hivis px-4 py-1.5 text-center text-sm font-medium text-asphalt">
      Demo data, not real projects. The demo accounts sign in without two-step codes.
    </aside>
  );
}
