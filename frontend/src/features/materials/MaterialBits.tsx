import { REQUEST_STATUS_LABELS, type RequestStatus, type RuleCheck } from "../../api/materials";
import { Icon, type IconName } from "../../components/ui/icons";
import { StatusBadge, type Tone } from "../../components/ui/StatusBadge";
import { formatAmount } from "../../lib/money";

const STATUS_TONES: Record<RequestStatus, Tone> = {
  requested: "warn",
  pm_approval: "warn",
  approved: "ok",
  ordered: "idle",
  delivered: "ok",
  change_requested: "warn",
  rejected: "down",
  cancelled: "idle",
};

export function RequestStatusBadge({ status }: { status: RequestStatus }) {
  return <StatusBadge tone={STATUS_TONES[status]} label={REQUEST_STATUS_LABELS[status]} />;
}

const SEVERITY: Record<RuleCheck["results"][number]["severity"], { icon: IconName; tone: string; label: string }> = {
  pass: { icon: "audit", tone: "text-signal-low", label: "Passed" },
  warn: { icon: "alert", tone: "text-signal-medium", label: "Check" },
  block: { icon: "close", tone: "text-signal-high", label: "Blocked" },
};

const RULE_NAMES: Record<string, string> = {
  "BR-01": "Price against the budget line",
  "BR-02": "Quantity against the BOQ",
};

/** The business-rule results for a request, each with its rule id, outcome in words and the key figures. */
export function RuleChecks({ check, compact = false }: { check: RuleCheck; compact?: boolean }) {
  return (
    <div className="space-y-3">
      <ul aria-label="Rule checks" className="space-y-2">
        {check.results.map((result) => {
          const s = SEVERITY[result.severity];
          return (
            <li key={result.rule} className="flex gap-3 rounded-lg border border-rule bg-paper-raised p-3">
              <Icon name={s.icon} className={`mt-0.5 size-5 shrink-0 ${s.tone}`} />
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink">
                  <span className="mr-2 font-mono text-xs text-ink-faint">{result.rule}</span>
                  {RULE_NAMES[result.rule] ?? result.rule}
                  <span className="sr-only">: {s.label}</span>
                </p>
                <p className="text-sm text-ink-soft">{result.message}</p>
              </div>
            </li>
          );
        })}
      </ul>
      {compact ? null : (
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-ink-faint">Request value</dt>
            <dd className="tabular font-medium text-ink">LKR {formatAmount(check.amount)}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Budgeted rate</dt>
            <dd className="tabular font-medium text-ink">LKR {formatAmount(check.budget_rate)}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Approved by</dt>
            <dd className="font-medium text-ink">{check.approval_level === "pm" ? "Project manager" : "Quantity surveyor"}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}
