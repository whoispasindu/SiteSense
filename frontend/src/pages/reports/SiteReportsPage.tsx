import { PageHeader } from "../../components/ui/PageHeader";
import { TodayReports } from "../../features/reports/TodayReports";
import { formatSiteDate } from "../../lib/time";

export function SiteReportsPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <PageHeader
        eyebrow={formatSiteDate(new Date())}
        title="Site reports"
        description="Each active site files one daily report by 18:00: weather, crew, work done, problems, progress and photos. Open a project to see its report history."
      />
      <TodayReports />
    </div>
  );
}
