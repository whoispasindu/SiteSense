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
  pending: { icon: "schedule", tone: "text-ink-faint", label: "Waiting for the price" },
};

const RULE_NAMES: Record<string, string> = {
  "BR-01": "Unit price against the budgeted rate",
  "BR-02": "Quantity against the BOQ",
  "BR-13": "Section cost against its budget line",
  "BR-14": "Order price against the approved price",
};

/** A price, or "Price pending" while the QS has not entered the quoted price yet. */
export function PriceText({ value, prefix = "LKR " }: { value: string | null; prefix?: string }) {
  if (value === null) return <span className="font-normal text-ink-faint italic">Price pending</span>;
  return (
    <>
      {prefix}
      {formatAmount(value)}
    </>
  );
}

/** "Sent to the project manager by BR-01 and BR-13", or null when the QS can approve. */
function routingText(check: RuleCheck): string | null {
  if (check.routed_by.length === 0) return null;
  return `Sent to the project manager by ${check.routed_by.join(" and ")}`;
}

/** The business-rule results for a request, each with its rule id, outcome in words and the key figures. */
export function RuleChecks({ check, compact = false }: { check: RuleCheck; compact?: boolean }) {
  const routing = routingText(check);
  return (
    <div className="space-y-3">
      {routing ? (
        <p className="rounded-lg bg-signal-medium-tint px-3 py-2 text-sm font-medium text-signal-medium">{routing}.</p>
      ) : null}
      <ul aria-label="Rule checks" className="space-y-2">
        {check.results.map((result) => {
          const s = SEVERITY[result.severity];
          const fired = check.routed_by.includes(result.rule);
          return (
            <li
              key={result.rule}
              className={`flex gap-3 rounded-lg border bg-paper-raised p-3 ${fired ? "border-signal-medium/50" : "border-rule"}`}
            >
              <Icon name={s.icon} className={`mt-0.5 size-5 shrink-0 ${s.tone}`} />
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink">
                  <span className="mr-2 font-mono text-xs text-ink-faint">{result.rule}</span>
                  {RULE_NAMES[result.rule] ?? result.rule}
                  <span className="sr-only">: {s.label}</span>
                  {fired ? (
                    <span className="ml-2 rounded-full bg-signal-medium-tint px-2 py-0.5 text-xs font-medium text-signal-medium">
                      Sends to PM
                    </span>
                  ) : null}
                </p>
                <p className="text-sm text-ink-soft">{result.message}</p>
              </div>
            </li>
          );
        })}
      </ul>
      {compact ? null : (
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          {check.amount !== undefined ? (
            <div>
              <dt className="text-ink-faint">Request value</dt>
              <dd className="tabular font-medium text-ink">
                <PriceText value={check.amount} />
              </dd>
            </div>
          ) : null}
          {check.budget_rate !== undefined ? (
            <div>
              <dt className="text-ink-faint">Budgeted rate</dt>
              <dd className="tabular font-medium text-ink">LKR {formatAmount(check.budget_rate)}</dd>
            </div>
          ) : null}
          <div>
            <dt className="text-ink-faint">Approved by</dt>
            <dd className="font-medium text-ink">{check.approval_level === "pm" ? "Project manager" : "Quantity surveyor"}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}
