import { useAuth } from "../../auth/context";
import { HandoverPanel, MilestonesPanel, PhotoSharingPanel } from "../../features/client/ClientViewPanels";
import { useCurrentProject } from "./projectContext";

/**
 * What the client sees in their portal (Phase 12), and the project manager's controls for it: the
 * published handover date, the client milestones, and which report photos are shared.
 */
export function ProjectClientView() {
  const project = useCurrentProject();
  const { can } = useAuth();
  const canEdit = can("projects:manage");

  return (
    <div className="space-y-6">
      <p className="max-w-3xl text-sm text-ink-soft">
        The client&rsquo;s portal shows progress, this handover date, the milestones below, the photos you share, approved
        claims and the variations sent to them. Never budgets, costs, rates or risk scores.
      </p>
      <HandoverPanel projectId={project.id} />
      <MilestonesPanel projectId={project.id} canEdit={canEdit} />
      {can("reports:read") ? <PhotoSharingPanel projectId={project.id} canEdit={canEdit} /> : null}
    </div>
  );
}
