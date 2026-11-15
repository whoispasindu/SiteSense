import {
  CLAIM_STATUS_LABELS,
  CLIENT_STATUS_LABELS,
  VARIATION_STATUS_LABELS,
  type ClaimFigures,
  type ClaimStatus,
  type VariationEvent,
  type VariationStatus,
} from "../../api/contract";
import { StatusBadge, type Tone } from "../../components/ui/StatusBadge";
import { formatMoney, toNumber } from "../../lib/money";
import { formatSiteDateTime } from "../../lib/time";

const CLAIM_TONES: Record<ClaimStatus, Tone> = { submitted: "warn", approved: "ok", returned: "idle", paid: "ok" };
const VARIATION_TONES: Record<VariationStatus, Tone> = {
  awaiting_pricing: "warn",
  awaiting_pm: "warn",
  awaiting_client: "warn",
  queried: "warn",
  approved: "ok",
  rejected: "down",
  withdrawn: "idle",
};

export function ClaimStatusBadge({ status }: { status: ClaimStatus }) {
  return <StatusBadge tone={CLAIM_TONES[status]} label={CLAIM_STATUS_LABELS[status]} />;
}

export function VariationStatusBadge({ status, forClient = false }: { status: VariationStatus; forClient?: boolean }) {
  const labels = forClient ? CLIENT_STATUS_LABELS : VARIATION_STATUS_LABELS;
  return <StatusBadge tone={VARIATION_TONES[status]} label={labels[status]} />;
}



/**
 * BR-08 as a worked calculation, the way a QS writes it on a valuation sheet:
 * certified value, less retention, less previous claims, equals this claim.
 */
export function ClaimCalculation({ figures, caption }: { figures: ClaimFigures; caption?: string }) {
  const retentionPct = `${String(toNumber(figures.retention_rate) * 100)}%`;
  const rows: { label: string; value: string; sub?: string; minus?: boolean }[] = [
    {
      label: "Certified to date",
      value: figures.certified_value,
      sub: `${figures.certified_pct}% of the contract value, ${formatMoney(figures.contract_value)}`,
    },
    { label: `Less retention (${retentionPct})`, value: figures.retention, minus: true, sub: "Held until the defects period ends" },
    { label: "Less previous claims", value: figures.previous_claims, minus: true, sub: "Approved claims so far" },
  ];
  return (
    <table className="w-full text-sm">
      {caption ? <caption className="sr-only">{caption}</caption> : null}
      <tbody>
        {rows.map((row) => (
          <tr key={row.label} className="border-b border-dashed border-rule">
            <th scope="row" className="py-2 pr-4 text-left font-normal text-ink-soft">
              {row.label}
              {row.sub ? <span className="block text-xs text-ink-faint">{row.sub}</span> : null}
            </th>
            <td className="tabular py-2 text-right whitespace-nowrap text-ink">
              {row.minus ? "− " : ""}{formatMoney(row.value)}
            </td>
          </tr>
        ))}
        <tr>
          <th scope="row" className="pt-3 pr-4 text-left font-semibold text-ink">
            This claim
            <span className="block text-xs font-normal text-ink-faint">BR-08: never more than certified progress less retention and previous claims</span>
          </th>
          <td className="tabular border-t-2 border-ink pt-3 text-right text-lg font-semibold whitespace-nowrap text-ink">
            {formatMoney(figures.amount)}
          </td>
        </tr>
      </tbody>
    </table>
  );
}

const EVENT_TEXT: Record<VariationEvent["action"], string> = {
  raised: "Raised",
  priced: "Priced",
  revised: "Revised",
  approved: "Approved",
  queried: "Queried",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

/** For the client, internal steps read as what they mean to them. */
const CLIENT_EVENT_TEXT: Partial<Record<VariationEvent["action"], string>> = {
  priced: "Sent to you for approval",
  revised: "Revised",
};

/** The variation's history, newest last, as a vertical timeline. */
export function VariationTimeline({ events, statusLabels = VARIATION_STATUS_LABELS, forClient = false }: {
  events: VariationEvent[];
  statusLabels?: Record<VariationStatus, string>;
  forClient?: boolean;
}) {
  if (events.length === 0) return <p className="text-sm text-ink-faint">Nothing has happened yet.</p>;
  return (
    <ol className="relative space-y-4 border-l border-rule-strong pl-5">
      {events.map((event, i) => (
        <li key={`${event.at}-${String(i)}`} className="relative">
          <span aria-hidden="true" className="absolute top-1.5 -left-[1.6rem] size-2.5 rounded-full border-2 border-paper-raised bg-accent-line" />
          <p className="text-sm text-ink">
            <span className="font-medium">{(forClient ? CLIENT_EVENT_TEXT[event.action] : undefined) ?? EVENT_TEXT[event.action]}</span> by{" "}
            {event.actor}
            {event.to_status in statusLabels ? (
              <span className="text-ink-faint"> → {statusLabels[event.to_status as VariationStatus]}</span>
            ) : null}
          </p>
          <p className="text-xs text-ink-faint">{formatSiteDateTime(event.at)}</p>
          {event.comment ? (
            <p className="mt-1 rounded-md bg-paper-sunk px-3 py-2 text-sm text-ink-soft">“{event.comment}”</p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

