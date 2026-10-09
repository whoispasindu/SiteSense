/** The SiteSense build programme (product guide, section 11), shown on the dashboard. */

export type PhaseStatus = "done" | "active" | "planned";

export interface Phase {
  number: number;
  name: string;
  stage: 1 | 2;
  startWeek: number;
  endWeek: number;
  output: string;
}

export interface Milestone {
  label: string;
  week: number;
  afterPhase: number;
}

/** The phase currently being built. Bump this as each phase merges. */
export const CURRENT_PHASE = 1;
export const PROGRAMME_WEEKS = 26;

export const PHASES: readonly Phase[] = [
  { number: 0, name: "Setup and foundations", stage: 1, startWeek: 1, endWeek: 2, output: "Running skeleton, CI, database" },
  { number: 1, name: "Authentication, roles and users", stage: 1, startWeek: 2, endWeek: 3, output: "Secure sign-in, 6 roles, site access" },
  { number: 2, name: "Projects, BOQ and budget", stage: 1, startWeek: 3, endWeek: 5, output: "Projects with imported BOQ and budget lines" },
  { number: 3, name: "Schedule basics", stage: 1, startWeek: 5, endWeek: 6, output: "Tasks and planned progress curve" },
  { number: 4, name: "Daily site reports", stage: 1, startWeek: 6, endWeek: 8, output: "Report form, photos, weather auto-fill" },
  { number: 5, name: "Materials, approvals and rules", stage: 1, startWeek: 8, endWeek: 10, output: "Request to delivery workflow" },
  { number: 6, name: "Demo data and risk model v1", stage: 1, startWeek: 10, endWeek: 13, output: "First AI feature on the dashboard" },
  { number: 7, name: "Report NLP classifier", stage: 2, startWeek: 14, endWeek: 16, output: "AI tags issues in reports" },
  { number: 8, name: "Cost control, claims and variations", stage: 2, startWeek: 16, endWeek: 18, output: "Budget forecast, claims, variations" },
  { number: 9, name: "Advanced schedule", stage: 2, startWeek: 18, endWeek: 19, output: "Critical path, Gantt, weather rules" },
  { number: 10, name: "Risk v2, what-if and suppliers", stage: 2, startWeek: 19, endWeek: 21, output: "Explained forecasts, recovery planner" },
  { number: 11, name: "Dashboard, alerts and briefing", stage: 2, startWeek: 21, endWeek: 22, output: "Full dashboard and notifications" },
  { number: 12, name: "Client portal", stage: 2, startWeek: 22, endWeek: 23, output: "Read-only client view, variation approval" },
  { number: 13, name: "Hardening and deployment", stage: 2, startWeek: 23, endWeek: 24, output: "Secure, tested, deployed demo" },
  { number: 14, name: "Testing, UAT and evaluation", stage: 2, startWeek: 24, endWeek: 26, output: "Release v1.0" },
];

export const MILESTONES: readonly Milestone[] = [
  { label: "v0.1 MVP", week: 13, afterPhase: 6 },
  { label: "v1.0", week: 26, afterPhase: 14 },
];

export function phaseStatus(phase: number, current: number = CURRENT_PHASE): PhaseStatus {
  if (phase < current) return "done";
  if (phase === current) return "active";
  return "planned";
}
