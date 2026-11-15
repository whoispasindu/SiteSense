import { useState, type SubmitEvent } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { REQUEST_STATUS_LABELS, useDecide, useRequest, useUpdateRequest, type RequestDetail, type RequestStatus } from "../../api/materials";
import { Alert } from "../../components/ui/Alert";
import { Button, primaryLinkClass } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { TextAreaField, TextField } from "../../components/ui/Field";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { formatDate } from "../../features/projects/dates";
import { PriceText, RequestStatusBadge, RuleChecks } from "../../features/materials/MaterialBits";
import { formatMoney, formatQuantity } from "../../lib/money";
import { formatSiteTime, siteTodayIso } from "../../lib/time";
import { NotFoundPage } from "../NotFoundPage";
import { SupplierPanel } from "../../features/materials/SupplierPanel";
import { currencyCode } from "../../lib/locale";

const ACTION_TEXT: Record<string, string> = {
  submit: "Submitted",
  resubmit: "Changed and resubmitted",
  return_for_approval: "Sent back for PM approval",
  approve: "Approved",
  reject: "Rejected",
  request_change: "Asked for a change",
  cancel: "Cancelled",
  order: "Ordered",
  deliver: "Delivered in full",
};

const FLOW: RequestStatus[] = ["requested", "pm_approval", "approved", "ordered", "delivered"];

function Progress({ request }: { request: RequestDetail }) {
  const steps = FLOW.filter((s) => s !== "pm_approval" || request.approval_level === "pm");
  const at = steps.indexOf(request.status);
  return (
    <ol aria-label="Request progress" className="flex flex-wrap gap-x-2 gap-y-2">
      {steps.map((s, index) => {
        const done = at >= 0 && index < at;
        const current = index === at;
        return (
          <li key={s} aria-current={current ? "step" : undefined} className="flex items-center gap-2">
            <span
              className={`grid size-6 place-items-center rounded-full text-xs font-semibold ${
                done ? "bg-signal-low text-white" : current ? "bg-hivis text-asphalt" : "border border-rule-strong text-ink-faint"
              }`}
            >
              {index + 1}
            </span>
            <span className={`text-sm ${current ? "font-medium text-ink" : done ? "text-ink-soft" : "text-ink-faint"}`}>
              {REQUEST_STATUS_LABELS[s]}
            </span>
            {index < steps.length - 1 ? <span aria-hidden="true" className="h-px w-5 bg-rule-strong" /> : null}
          </li>
        );
      })}
    </ol>
  );
}

type Pending = "approve" | "reject" | "request_change" | "cancel";

const DECISION_TITLE: Record<Pending, string> = {
  approve: "Approve this request",
  reject: "Reject this request",
  request_change: "Ask for a change",
  cancel: "Cancel this request",
};

function DecisionDialog({ request, decision, onClose }: { request: RequestDetail; decision: Pending; onClose: () => void }) {
  const decide = useDecide(request.id);
  const [comment, setComment] = useState("");
  const needsComment = decision === "reject" || decision === "request_change";
  // At the QS check the QS enters the quoted price. Requests from site engineers arrive with the
  // price pending, and cannot be approved until it is entered.
  const pricing = decision === "approve" && request.status === "requested" && request.unit_price !== undefined;
  const pricePending = request.unit_price === null;
  const [price, setPrice] = useState(request.unit_price ?? "");
  const [error, setError] = useState<string | null>(null);

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (needsComment && comment.trim().length < 3) {
      setError("Add a comment so the requester knows why.");
      return;
    }
    if (pricing && !(/^\d{1,12}(\.\d{1,2})?$/.test(price.trim()) && Number(price) > 0)) {
      setError(pricePending ? "Enter the quoted unit price before approving: the price is pending." : "Enter the quoted unit price, greater than zero.");
      return;
    }
    const priceChanged = pricing && Number(price) !== Number(request.unit_price);
    decide.mutate(
      { decision, comment: comment.trim() || null, ...(priceChanged ? { unit_price: price.trim() } : {}) },
      { onSuccess: onClose },
    );
  }

  const routing = request.rules.routed_by;
  const routedToPm = decision === "approve" && request.status === "requested" && routing.length > 0;
  return (
    <Dialog open onClose={onClose} title={DECISION_TITLE[decision]}>
      <form noValidate onSubmit={onSubmit} className="space-y-4">
        {decide.isError ? <Alert tone="error">{errorText(decide.error)}</Alert> : null}
        {error ? <Alert tone="error">{error}</Alert> : null}
        {routedToPm ? (
          <Alert tone="info">
            {routing.join(" and ")} {routing.length > 1 ? "send" : "sends"} this request to the project manager: approving
            passes it on.
          </Alert>
        ) : null}
        <p className="text-sm text-ink-soft">
          {request.number}: {formatQuantity(request.quantity)} {request.boq_item.unit} of {request.boq_item.description}
          {request.amount ? `, ${formatMoney(request.amount)}` : ""}
          {pricePending ? ", price pending" : ""}.
        </p>
        {pricing ? (
          <div className="grid items-start gap-3 sm:grid-cols-[1fr_auto]">
            <TextField
              label={`Quoted unit price (${currencyCode()} / ${request.boq_item.unit})`}
              inputMode="decimal"
              required
              value={price}
              hint="BR-01 and BR-13 are checked with this price when you approve."
              onChange={(e) => {
                setPrice(e.target.value);
              }}
            />
            {request.rules.budget_rate !== undefined ? (
              <div className="rounded-lg border border-dashed border-rule-strong bg-paper-sunk/60 px-3 py-2 sm:mt-6" aria-label="Reference">
                <p className="text-xs text-ink-faint">Budgeted rate</p>
                <p className="tabular text-sm font-medium text-ink">
                  {formatMoney(request.rules.budget_rate)} / {request.boq_item.unit}
                </p>
                <p className="text-xs text-ink-faint">More than 5% above: PM approves</p>
              </div>
            ) : null}
          </div>
        ) : null}
        <TextAreaField
          label={needsComment ? "Comment" : "Comment (optional)"}
          rows={3}
          maxLength={1000}
          value={comment}
          onChange={(e) => {
            setComment(e.target.value);
          }}
        />
        <div className="flex justify-end gap-3 border-t border-rule pt-4">
          <Button onClick={onClose}>Back</Button>
          <Button type="submit" variant={decision === "reject" || decision === "cancel" ? "danger" : "primary"} disabled={decide.isPending}>
            {decide.isPending ? "Saving…" : DECISION_TITLE[decision].replace(" this request", "")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function EditDialog({ request, onClose }: { request: RequestDetail; onClose: () => void }) {
  const update = useUpdateRequest(request.id);
  const [quantity, setQuantity] = useState(String(Number(request.quantity)));
  // Roles without rates (site engineers) change quantity and dates only; the QS prices the request.
  // A rate reader may leave a pending price empty: the QS enters it at the QS check.
  const pricing = request.unit_price !== undefined;
  const [price, setPrice] = useState(request.unit_price ?? "");
  const priceGiven = price.trim() !== "";
  const [neededBy, setNeededBy] = useState(request.needed_by);
  const [notes, setNotes] = useState(request.notes ?? "");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!(Number(quantity) > 0) || (pricing && priceGiven && !(Number(price) > 0))) {
      setError(pricing ? "Quantity and price must be greater than zero." : "The quantity must be greater than zero.");
      return;
    }
    if (neededBy < siteTodayIso()) {
      setError("The needed-by date cannot be in the past.");
      return;
    }
    setError(null);
    update.mutate(
      {
        quantity: quantity.trim(),
        ...(pricing && priceGiven ? { unit_price: price.trim() } : {}),
        needed_by: neededBy,
        notes: notes.trim() || null,
        comment: comment.trim() || null,
      },
      { onSuccess: onClose },
    );
  }

  return (
    <Dialog open onClose={onClose} title="Change and resubmit">
      <form noValidate onSubmit={onSubmit} className="space-y-4">
        {update.isError ? <Alert tone="error">{errorText(update.error)}</Alert> : null}
        {error ? <Alert tone="error">{error}</Alert> : null}
        <div className="grid gap-4 sm:grid-cols-3">
          <TextField label={`Quantity (${request.boq_item.unit})`} inputMode="decimal" value={quantity} onChange={(e) => { setQuantity(e.target.value); }} />
          {pricing ? (
            <TextField label={`Unit price (${currencyCode()})`} inputMode="decimal" value={price} onChange={(e) => { setPrice(e.target.value); }} />
          ) : null}
          <TextField label="Needed by" type="date" value={neededBy} onChange={(e) => { setNeededBy(e.target.value); }} />
        </div>
        <TextAreaField label="Notes" rows={2} maxLength={2000} value={notes} onChange={(e) => { setNotes(e.target.value); }} />
        <TextAreaField label="What changed (optional)" rows={2} maxLength={1000} value={comment} onChange={(e) => { setComment(e.target.value); }} />
        <div className="flex justify-end gap-3 border-t border-rule pt-4">
          <Button onClick={onClose}>Back</Button>
          <Button type="submit" variant="primary" disabled={update.isPending}>
            {update.isPending ? "Saving…" : "Resubmit"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function RequestDetailPage() {
  const { requestId = "" } = useParams();
  const request = useRequest(requestId);
  const [pending, setPending] = useState<Pending | null>(null);
  const [editing, setEditing] = useState(false);

  if (request.isPending) return <p className="py-16 text-center text-ink-faint">Loading request…</p>;
  if (request.isError) {
    if (request.error instanceof ApiError && request.error.status === 404) return <NotFoundPage />;
    return <Alert tone="error">{errorText(request.error)}</Alert>;
  }
  const r = request.data;
  const decisions = r.actions.filter((a): a is "approve" | "reject" | "request_change" => ["approve", "reject", "request_change"].includes(a));

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <nav aria-label="Breadcrumb" className="text-sm text-ink-faint">
        <Link to="/materials" className="hover:text-ink hover:underline">
          Materials
        </Link>{" "}
        / {r.number}
      </nav>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <RequestStatusBadge status={r.status} />
            <span className="text-sm text-ink-faint">
              {r.project.name} · {r.project.site_code}
            </span>
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            {r.number}: {r.boq_item.description}
          </h1>
          <p className="mt-1 text-ink-soft">
            Requested by {r.requested_by.full_name} · needed by {formatDate(r.needed_by)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {decisions.includes("approve") ? (
            <Button variant="primary" onClick={() => { setPending("approve"); }}>
              {r.status === "requested" && r.rules.routed_by.length > 0 ? "Pass to PM" : "Approve"}
            </Button>
          ) : null}
          {decisions.includes("request_change") ? <Button onClick={() => { setPending("request_change"); }}>Ask for a change</Button> : null}
          {decisions.includes("reject") ? <Button variant="danger" onClick={() => { setPending("reject"); }}>Reject</Button> : null}
          {r.actions.includes("edit") ? <Button variant="primary" onClick={() => { setEditing(true); }}>Change and resubmit</Button> : null}
          {r.actions.includes("cancel") ? <Button variant="ghost" onClick={() => { setPending("cancel"); }}>Cancel request</Button> : null}
          {r.actions.includes("order") ? (
            <Link to="/purchase-orders" className={primaryLinkClass}>
              Order it
            </Link>
          ) : null}
        </div>
      </header>

      {r.status !== "rejected" && r.status !== "cancelled" && r.status !== "change_requested" ? <Progress request={r} /> : null}
      {r.status === "pm_approval" && r.history.at(-1)?.action === "return_for_approval" ? (
        <Alert tone="warn" title="Sent back from ordering">
          {r.history.at(-1)?.comment ?? ""}
        </Alert>
      ) : null}
      {r.status === "change_requested" ? (
        <Alert tone="warn" title="A change was requested">
          {r.history.at(-1)?.comment ?? ""}
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <Sheet className="p-5">
            <SectionHeading>Request</SectionHeading>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-ink-faint">BOQ item</dt>
                <dd className="font-medium text-ink">
                  <span className="font-mono text-xs">{r.boq_item.item_code}</span> (section {r.boq_item.section_code})
                </dd>
              </div>
              <div>
                <dt className="text-ink-faint">Quantity</dt>
                <dd className="tabular font-medium text-ink">
                  {formatQuantity(r.quantity)} {r.boq_item.unit}
                  <span className="block text-xs font-normal text-ink-faint">BOQ {formatQuantity(r.boq_quantity)}</span>
                </dd>
              </div>
              {r.unit_price !== undefined ? (
                <div>
                  <dt className="text-ink-faint">Unit price</dt>
                  <dd className="tabular font-medium text-ink">
                    <PriceText value={r.unit_price} />
                  </dd>
                </div>
              ) : null}
              {r.amount !== undefined ? (
                <div>
                  <dt className="text-ink-faint">Value</dt>
                  <dd className="tabular font-medium text-ink">
                    <PriceText value={r.amount} />
                  </dd>
                </div>
              ) : null}
            </dl>
            {r.notes ? <p className="mt-4 text-sm whitespace-pre-line text-ink-soft">{r.notes}</p> : null}
          </Sheet>

          {r.order ? (
            <Sheet className="p-5">
              <SectionHeading
                action={
                  <Link to={`/purchase-orders/${r.order.id}`} className="text-sm font-medium text-survey hover:underline">
                    {r.order.number}
                  </Link>
                }
              >
                Order and delivery
              </SectionHeading>
              <p className="text-sm text-ink-soft">
                {r.order.supplier_name}
                {r.order.unit_price !== undefined ? ` · ${formatMoney(r.order.unit_price)} / ${r.boq_item.unit}` : ""} · expected{" "}
                {formatDate(r.order.expected_delivery)}
              </p>
              <div aria-hidden="true" className="mt-3 h-2 rounded-full bg-paper-sunk">
                <div
                  className="h-full rounded-full bg-signal-low"
                  style={{ width: `${String(Math.min(100, (Number(r.order.delivered_quantity) / Number(r.quantity)) * 100))}%` }}
                />
              </div>
              <p className="tabular mt-1 text-sm text-ink">
                {formatQuantity(r.order.delivered_quantity)} of {formatQuantity(r.quantity)} {r.boq_item.unit} delivered
              </p>
            </Sheet>
          ) : null}

          <Sheet className="p-5">
            <SectionHeading>History</SectionHeading>
            <ol aria-label="Request history" className="space-y-4 border-l border-rule pl-5">
              {r.history.map((h, index) => (
                <li key={`${h.created_at}-${String(index)}`} className="relative">
                  <span aria-hidden="true" className="absolute top-1.5 -left-[1.6rem] size-2.5 rounded-full border-2 border-paper-raised bg-accent-line" />
                  <p className="text-sm font-medium text-ink">
                    {ACTION_TEXT[h.action] ?? h.action}
                    <span className="font-normal text-ink-soft"> by {h.actor.full_name}</span>
                  </p>
                  <p className="text-xs text-ink-faint">
                    {formatDate(h.created_at.slice(0, 10))} {formatSiteTime(h.created_at)}
                  </p>
                  {h.comment ? <p className="mt-1 text-sm text-ink-soft">“{h.comment}”</p> : null}
                </li>
              ))}
            </ol>
          </Sheet>
        </div>

        <div className="space-y-6">
          <Sheet className="h-fit p-5">
            <SectionHeading annotation="live figures">Rules check</SectionHeading>
            <RuleChecks check={r.rules} />
          </Sheet>
          <SupplierPanel request={r} />
        </div>
      </div>

      {pending ? (
        <DecisionDialog
          request={r}
          decision={pending}
          onClose={() => {
            setPending(null);
          }}
        />
      ) : null}
      {editing ? (
        <EditDialog
          request={r}
          onClose={() => {
            setEditing(false);
          }}
        />
      ) : null}
    </div>
  );
}
