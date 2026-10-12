import { useProjectRisk } from "../../api/risk";
import { useAuth } from "../../auth/context";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { ProjectRiskPanel } from "../../features/risk/ProjectRiskPanel";
import { RiskTrend } from "../../features/risk/RiskTrend";
import { WhatIfPlanner } from "../../features/risk/WhatIfPlanner";
import { useCurrentProject } from "./projectContext";

/** The project's risk page: the forecast with its range and drivers, two weeks of scores, and the what-if planner. */
export function ProjectRisk() {
  const project = useCurrentProject();
  const { can } = useAuth();
  const risk = useProjectRisk(project.id);

  return (
    <div className="space-y-10">
      <ProjectRiskPanel projectId={project.id} />
      <section aria-labelledby="trend-heading" className="space-y-3">
        <SectionHeading id="trend-heading" annotation="last 14 days">
          Score over time
        </SectionHeading>
        <Sheet className="p-5">{risk.data ? <RiskTrend history={risk.data.history} /> : null}</Sheet>
      </section>
      {can("risk:what_if") ? (
        <WhatIfPlanner projectId={project.id} />
      ) : (
        <p className="text-sm text-ink-faint">The project manager tests recovery actions in the what-if planner.</p>
      )}
    </div>
  );
}
