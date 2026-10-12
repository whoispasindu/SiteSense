import { PageHeader } from "../../components/ui/PageHeader";
import { RiskRankingPanel } from "../../features/risk/RiskRankingPanel";

/** Risk & what-if: every open project by risk. Each project's Risk tab holds its trend and the planner. */
export function RiskPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader
        title="Risk & what-if"
        description="Every open project on your sites by delay and cost risk, each with its likely range. Open a project's Risk tab for its trend and to test recovery actions."
      />
      <RiskRankingPanel linkTo="risk" />
    </div>
  );
}
