import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { useVariation, useVariationStep, type Variation, type VariationStep } from "../../api/contract";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { TextAreaField, TextField } from "../../components/ui/Field";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { VariationStatusBadge, VariationTimeline } from "../../features/contract/ContractBits";
import { daysText, signedMoney } from "../../features/contract/format";
import { VariationForm } from "../../features/contract/VariationForm";
import { formatMoney, formatQuantity } from "../../lib/money";
import { formatSiteDateTime } from "../../lib/time";
import { NotFoundPage } from "../NotFoundPage";
import { currencyCode } from "../../lib/locale";

const MONEY_CHANGE = /^-?\d{1,13}(\.\d{1,2})?$/;

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-6 gap-y-0.5 border-b border-dashed border-rule py-2 text-sm">
      <dt className="text-ink-faint">{label}</dt>
      <dd className="text-right text-ink">{children}</dd>
    </div>
  );
}

function routingText(v: Variation): string {
  if (v.status === "awaiting_pricing") return "The quantity surveyor prices it next.";
  if (v.approver === "client") {
    if (v.time_impact_days > 0) return "Goes to the client: it has a time impact (BR-09).";
    if (v.needs_client) return `Goes to the client: the change is above the limit of ${formatMoney(v.limit_applied ?? v.limit)} (BR-09).`;
    return "Goes to the client: it was raised by a project manager, who does not approve their own.";
  }
  if (v.approver === "pm") return `A project manager approves it: within the limit of ${formatMoney(v.limit_applied ?? v.limit)}, no time impact.`;
  return "";
}

/** The QS's price: two amounts, then BR-09 routes it. */
function PriceForm({ step, busy }: { step: (s: VariationStep) => void; busy: boolean }) {
  const [contract, setContract] = useState("");
  const [budget, setBudget] = useState("0");
  const [comment, setComment] = useState("");
  const valid = MONEY_CHANGE.test(contract) && MONEY_CHANGE.test(budget);
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) step({ step: "price", contract_change: contract, budget_change: budget, comment: comment.trim() || null });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField label={`Contract change, ${currencyCode()}`} hint="Minus for an omission." inputMode="decimal" value={contract} onChange={(e) => { setContract(e.target.value); }} />
        <TextField label={`Cost budget change, ${currencyCode()}`} hint="Internal." inputMode="decimal" value={budget} onChange={(e) => { setBudget(e.target.value); }} />
      </div>
      <TextField label="Note (internal, optional)" maxLength={1000} value={comment} onChange={(e) => { setComment(e.target.value); }} />
      <div className="flex justify-end">
        <Button type="submit" variant="primary" disabled={!valid || busy}>
          Price and send on
        </Button>
      </div>
    </form>
  );
}

function DecisionForm({ step, busy }: { step: (s: VariationStep) => void; busy: boolean }) {
  const [mode, setMode] = useState<"query" | "reject" | null>(null);
  const [comment, setComment] = useState("");
  if (mode === null) {
    return (
      <div className="flex flex-wrap justify-end gap-2">
        <Button onClick={() => { setMode("query"); }}>Query…</Button>
        <Button variant="danger" onClick={() => { setMode("reject"); }}>Reject…</Button>
        <Button variant="primary" disabled={busy} onClick={() => { step({ step: "decision", decision: "approve" }); }}>
          Approve variation
        </Button>
      </div>
    );
  }
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        step({ step: "decision", decision: mode, comment: comment.trim() });
      }}
    >
      <TextAreaField
        label={mode === "query" ? "Your question for the raiser and QS" : "Why it is rejected"}
        rows={2}
        required
        maxLength={1000}
        value={comment}
        onChange={(e) => {
          setComment(e.target.value);
        }}
      />
      <div className="flex justify-end gap-2">
        <Button onClick={() => { setMode(null); }}>Cancel</Button>
        <Button type="submit" variant={mode === "reject" ? "danger" : "primary"} disabled={!comment.trim() || busy}>
          {mode === "query" ? "Send query" : "Reject variation"}
        </Button>
      </div>
    </form>
  );
}

export function VariationDetailPage() {
  const { variationId = "" } = useParams();
  const variation = useVariation(variationId);
  const v = variation.data;
  const step = useVariationStep({ id: variationId, project_id: v?.project_id ?? "" });
  const [revising, setRevising] = useState(false);

  if (variation.isPending) return <p className="py-16 text-center text-ink-faint">Loading variation…</p>;
  if (variation.isError) {
    if (variation.error instanceof ApiError && variation.error.status === 404) return <NotFoundPage />;
    return <Alert tone="error">{errorText(variation.error)}</Alert>;
  }
  if (!v) return null;
  const run = (s: VariationStep) => {
    step.mutate(s, { onSuccess: () => { setRevising(false); } });
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <nav aria-label="Breadcrumb" className="text-sm text-ink-faint">
        <Link to={`/projects/${v.project_id}/variations`} className="hover:text-ink hover:underline">
          {v.project_code} variations
        </Link>{" "}
        / {v.number}
      </nav>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-sm text-ink-faint">{v.number}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">{v.title}</h1>
          <p className="mt-1 text-sm text-ink-faint">
            Raised by {v.raised_by} ({v.raised_by_role === "pm" ? "project manager" : "quantity surveyor"}),{" "}
            {formatSiteDateTime(v.raised_at)}
          </p>
        </div>
        <VariationStatusBadge status={v.status} />
      </header>

      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <div className="space-y-6">
          <Sheet className="p-5">
            <p className="text-sm whitespace-pre-line text-ink-soft">{v.description}</p>
            <dl className="mt-4">
              <Fact label="BOQ section">{v.section}</Fact>
              {v.boq_item ? (
                <Fact label="Extra quantity">
                  {formatQuantity(v.quantity_change ?? "0")} on {v.boq_item}
                </Fact>
              ) : null}
              <Fact label="Contract change">{signedMoney(v.contract_change)}</Fact>
              <Fact label="Cost budget change (internal)">{signedMoney(v.budget_change)}</Fact>
              <Fact label="Time impact">
                {daysText(v.time_impact_days)}
                {v.task ? ` · ${v.task}` : ""}
              </Fact>
              {v.priced_by ? <Fact label="Priced by">{v.priced_by}</Fact> : null}
            </dl>
            <p className="mt-4 rounded-md bg-paper-sunk px-3 py-2 text-sm text-ink-soft">{routingText(v)}</p>
          </Sheet>

          {v.actions.length > 0 ? (
            <Sheet className="space-y-4 p-5">
              <h2 className="text-base font-semibold text-ink">Your next step</h2>
              {v.actions.includes("price") ? <PriceForm step={run} busy={step.isPending} /> : null}
              {v.actions.includes("approve") ? <DecisionForm step={run} busy={step.isPending} /> : null}
              <div className="flex flex-wrap justify-end gap-2">
                {v.actions.includes("revise") ? (
                  <Button variant="primary" onClick={() => { setRevising(true); }}>
                    Revise…
                  </Button>
                ) : null}
                {v.actions.includes("withdraw") ? (
                  <Button variant="ghost" disabled={step.isPending} onClick={() => { run({ step: "withdraw" }); }}>
                    Withdraw
                  </Button>
                ) : null}
              </div>
              {step.isError ? <Alert tone="error">{errorText(step.error)}</Alert> : null}
            </Sheet>
          ) : null}
        </div>

        <Sheet className="p-5">
          <h2 className="mb-4 text-base font-semibold text-ink">History</h2>
          <VariationTimeline events={v.events} />
        </Sheet>
      </div>

      <Dialog open={revising} title={`Revise ${v.number}`} onClose={() => { setRevising(false); }}>
        <VariationForm
          projectId={v.project_id}
          limit={v.limit}
          initial={v}
          submitLabel="Save revision"
          busy={step.isPending}
          error={step.isError ? errorText(step.error) : null}
          onCancel={() => { setRevising(false); }}
          onSubmit={(input) => { run({ step: "revision", ...input }); }}
        />
      </Dialog>
    </div>
  );
}
