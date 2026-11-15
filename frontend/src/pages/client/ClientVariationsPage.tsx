import { useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { CLIENT_STATUS_LABELS, useClientDecision, useClientVariation, useClientVariations } from "../../api/contract";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { TextAreaField } from "../../components/ui/Field";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { VariationStatusBadge, VariationTimeline } from "../../features/contract/ContractBits";
import { daysText, signedMoney } from "../../features/contract/format";
import { formatMoney } from "../../lib/money";
import { formatSiteDateTime } from "../../lib/time";
import { NotFoundPage } from "../NotFoundPage";

/** The client's list: every variation sent to them, the ones waiting for a decision first. */
export function ClientVariationsPage() {
  const variations = useClientVariations();
  if (variations.isPending) return <p className="py-16 text-center text-ink-faint">Loading variations…</p>;
  if (variations.isError) return <Alert tone="error">{errorText(variations.error)}</Alert>;
  const rows = [...variations.data].sort((a, b) => Number(b.can_decide) - Number(a.can_decide));

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        eyebrow="Your projects"
        title="Variations"
        description="Changes to your contract that need your approval: a change to the price above the agreed limit, or to the completion date."
      />
      {rows.length === 0 ? (
        <Sheet className="p-8 text-center text-sm text-ink-faint">Nothing has been sent to you yet.</Sheet>
      ) : (
        <Sheet className="divide-y divide-rule">
          {rows.map((v) => (
            <article key={v.id} className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-4">
              <div className="min-w-0 flex-1">
                <p className="text-sm text-ink-faint">
                  {v.project_name} · <span className="font-mono">{v.number}</span>
                </p>
                <Link to={`/client/variations/${v.id}`} className="font-medium text-ink hover:underline">
                  {v.title}
                </Link>
              </div>
              <div className="tabular text-right text-sm">
                <p className="text-ink">{signedMoney(v.contract_change)}</p>
                <p className="text-ink-faint">{daysText(v.time_impact_days)}</p>
              </div>
              <VariationStatusBadge status={v.status} forClient />
            </article>
          ))}
        </Sheet>
      )}
    </div>
  );
}

/** One variation for the client: what changes, why it needs them, and approve or ask a question. */
export function ClientVariationPage() {
  const { variationId = "" } = useParams();
  const variation = useClientVariation(variationId);
  const v = variation.data;
  const decide = useClientDecision({ id: variationId, project_id: v?.project_id ?? "" });
  const [querying, setQuerying] = useState(false);
  const [comment, setComment] = useState("");

  if (variation.isPending) return <p className="py-16 text-center text-ink-faint">Loading variation…</p>;
  if (variation.isError) {
    if (variation.error instanceof ApiError && variation.error.status === 404) return <NotFoundPage />;
    return <Alert tone="error">{errorText(variation.error)}</Alert>;
  }
  if (!v) return null;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <nav aria-label="Breadcrumb" className="text-sm text-ink-faint">
        <Link to="/client/variations" className="hover:text-ink hover:underline">
          Variations
        </Link>{" "}
        / {v.number}
      </nav>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm text-ink-faint">
            {v.project_name} · <span className="font-mono">{v.number}</span>
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">{v.title}</h1>
          <p className="mt-1 text-sm text-ink-faint">Raised {formatSiteDateTime(v.raised_at)}</p>
        </div>
        <VariationStatusBadge status={v.status} forClient />
      </header>

      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <div className="space-y-6">
          <Sheet className="p-5">
            <p className="text-sm whitespace-pre-line text-ink-soft">{v.description}</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <div className="rounded-lg border border-rule p-4">
                <p className="text-sm text-ink-faint">Change to your contract</p>
                <p className="tabular mt-1 text-xl font-semibold text-ink">{signedMoney(v.contract_change)}</p>
              </div>
              <div className="rounded-lg border border-rule p-4">
                <p className="text-sm text-ink-faint">Completion date</p>
                <p className="mt-1 text-xl font-semibold text-ink">{daysText(v.time_impact_days)}</p>
              </div>
            </div>
            <p className="mt-4 rounded-md bg-paper-sunk px-3 py-2 text-sm text-ink-soft">
              <span className="font-medium text-ink">Why you are asked: </span>
              {v.reason_for_client} Changes above {formatMoney(v.limit)}, or to the completion date, need your
              approval before the work starts.
            </p>
          </Sheet>

          {v.can_decide ? (
            <Sheet className="space-y-4 p-5">
              <h2 className="text-base font-semibold text-ink">Your decision</h2>
              {querying ? (
                <form
                  className="space-y-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    decide.mutate({ decision: "query", comment: comment.trim() });
                  }}
                >
                  <TextAreaField
                    label="Your question for the contractor"
                    rows={3}
                    required
                    maxLength={1000}
                    value={comment}
                    onChange={(e) => {
                      setComment(e.target.value);
                    }}
                  />
                  <div className="flex justify-end gap-2">
                    <Button onClick={() => { setQuerying(false); }}>Cancel</Button>
                    <Button type="submit" variant="primary" disabled={!comment.trim() || decide.isPending}>
                      Send question
                    </Button>
                  </div>
                </form>
              ) : (
                <div className="flex flex-wrap justify-end gap-2">
                  <Button onClick={() => { setQuerying(true); }}>Ask a question…</Button>
                  <Button
                    variant="primary"
                    disabled={decide.isPending}
                    onClick={() => {
                      decide.mutate({ decision: "approve" });
                    }}
                  >
                    Approve this variation
                  </Button>
                </div>
              )}
              <p className="text-xs text-ink-faint">
                Approving changes the contract value and completion date as shown. Your decision is recorded.
              </p>
              {decide.isError ? <Alert tone="error">{errorText(decide.error)}</Alert> : null}
            </Sheet>
          ) : null}
        </div>
        <Sheet className="p-5">
          <h2 className="mb-4 text-base font-semibold text-ink">History</h2>
          <VariationTimeline events={v.events} statusLabels={CLIENT_STATUS_LABELS} forClient />
        </Sheet>
      </div>
    </div>
  );
}
