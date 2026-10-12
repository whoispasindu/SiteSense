import { useAuth } from "../auth/context";
import { ClientHomePage } from "./client/ClientPortalPage";
import { DashboardPage } from "./dashboard/DashboardPage";

/** Staff land on the dashboard; clients on their projects (Phase 12). */
export function HomePage() {
  const { can } = useAuth();
  return can("dashboard:view") ? <DashboardPage /> : <ClientHomePage />;
}
