import { useAuth } from "../../auth/context";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { CURRENT_PHASE, PHASES } from "../../lib/programme";
import { formatSiteDate, greeting } from "../../lib/time";
import { BuildProgramme } from "./BuildProgramme";
import { SystemReadings } from "./SystemReadings";

function TitleBlock() {
  const phase = PHASES[CURRENT_PHASE];
  const today = formatSiteDate(new Date());
  const rows: [string, React.ReactNode][] = [
    ["Project", "SiteSense"],
    ["Phase", `${String(CURRENT_PHASE).padStart(2, "0")} · ${phase?.name ?? ""}`],
    ["Revision", `v${__APP_VERSION__}`],
    ["Date", today],
    ["Status", <StatusBadge key="status" tone="warn" label="Building" />],
  ];

  return (
    <Sheet as="div" className="self-end">
      <p className="font-wide border-b-2 border-ink px-4 py-2 text-[0.65rem] font-extrabold tracking-[0.24em] uppercase">
        Title block
      </p>
      <dl className="divide-y divide-rule text-sm">
        {rows.map(([term, value]) => (
          <div key={term} className="grid grid-cols-[6rem_1fr] items-center gap-3 px-4 py-2.5">
            <dt className="font-mono text-[0.68rem] tracking-wider text-ink-faint uppercase">{term}</dt>
            <dd className="min-w-0 break-words">{value}</dd>
          </div>
        ))}
      </dl>
    </Sheet>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const firstName = user?.full_name.split(" ")[0] ?? "";

  return (
    <div className="mx-auto max-w-6xl space-y-14">
      <div className="animate-rise grid gap-8 lg:grid-cols-[1fr_22rem]">
        <div>
          <p className="font-mono text-xs tracking-[0.2em] text-ink-faint uppercase">
            Sheet S-00 · Phase {CURRENT_PHASE} of {PHASES.length - 1}
          </p>
          <h1 className="font-wide mt-4 text-5xl leading-[0.95] font-extrabold tracking-tight text-balance sm:text-6xl">
            {greeting(new Date())},{" "}
            <span className="relative inline-block">
              <span className="relative z-10">{firstName}.</span>
              <span aria-hidden="true" className="absolute inset-x-0 bottom-[0.08em] z-0 h-[0.32em] bg-hivis" />
            </span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-soft">
            SiteSense will tell a construction company which site will slip before it does, and what to do about it.
            The gate is up: sign-in, six roles and site access are in place. Projects, BOQ and budgets arrive next.
          </p>
        </div>
        <TitleBlock />
      </div>

      <SystemReadings />
      <BuildProgramme />
    </div>
  );
}
