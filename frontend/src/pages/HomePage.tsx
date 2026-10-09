import { useAuth } from "../auth/context";
import { Sheet } from "../components/ui/Sheet";
import { DashboardPage } from "./dashboard/DashboardPage";

/** Internal roles land on the dashboard; clients get their own (portal arrives in Phase 12). */
export function HomePage() {
  const { can } = useAuth();
  return can("dashboard:view") ? <DashboardPage /> : <ClientHome />;
}

function ClientHome() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <div className="mx-auto max-w-4xl space-y-10">
      <div>
        <p className="font-mono text-xs tracking-[0.2em] text-ink-faint uppercase">Client view</p>
        <h1 className="font-wide mt-4 text-5xl font-extrabold tracking-tight">Welcome, {user.full_name}.</h1>
        <p className="mt-5 max-w-xl text-lg text-ink-soft">
          Your project portal will show honest progress, the forecast handover date, milestones, photos, variations
          and payments. It opens in a later release.
        </p>
      </div>
      <Sheet sheetCode="C-01" className="p-6">
        <h2 className="font-wide text-xs font-bold tracking-[0.2em] uppercase">Your sites</h2>
        {user.sites.length ? (
          <ul className="mt-4 divide-y divide-rule">
            {user.sites.map((site) => (
              <li key={site.id} className="flex items-center gap-4 py-3">
                <span className="font-mono text-xs text-ink-faint">{site.code}</span>
                <span className="font-semibold">{site.name}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 text-ink-soft">No sites are linked to your account yet.</p>
        )}
      </Sheet>
    </div>
  );
}
