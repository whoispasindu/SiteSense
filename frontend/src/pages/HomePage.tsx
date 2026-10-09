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
    <div className="mx-auto max-w-4xl space-y-8">
      <div>
        <p className="text-sm text-ink-faint">Client view</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink sm:text-[1.75rem]">Welcome, {user.full_name}.</h1>
        <p className="mt-2 max-w-xl text-ink-soft">
          Your project portal will show honest progress, the forecast handover date, milestones, photos, variations
          and payments. It opens in a later release.
        </p>
      </div>
      <Sheet className="p-6">
        <h2 className="text-base font-semibold text-ink">Your sites</h2>
        {user.sites.length ? (
          <ul className="mt-4 divide-y divide-rule">
            {user.sites.map((site) => (
              <li key={site.id} className="flex items-center gap-4 py-3">
                <span className="rounded-md bg-paper-sunk px-1.5 py-0.5 font-mono text-xs font-medium text-ink-soft">{site.code}</span>
                <span className="font-medium text-ink">{site.name}</span>
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
