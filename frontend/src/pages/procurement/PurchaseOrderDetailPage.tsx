import { useState, type SubmitEvent } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { useOrder, useRecordDelivery, type PoDetail } from "../../api/materials";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { SelectField, TextField } from "../../components/ui/Field";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { formatDate } from "../../features/projects/dates";
import { formatAmount, formatQuantity } from "../../lib/money";
import { siteTodayIso } from "../../lib/time";
import { NotFoundPage } from "../NotFoundPage";
import { PoStatusBadge } from "./PurchaseOrdersPage";

function DeliveryForm({ po }: { po: PoDetail }) {
  const record = useRecordDelivery(po.id);
  const open = po.lines.filter((l) => Number(l.delivered_quantity) < Number(l.quantity));
  const [lineId, setLineId] = useState(open[0]?.request_id ?? "");
  const line = open.find((l) => l.request_id === lineId);
  const remaining = line ? Number(line.quantity) - Number(line.delivered_quantity) : 0;
  const [quantity, setQuantity] = useState("");
  const [date, setDate] = useState(siteTodayIso());
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (open.length === 0) return <p className="text-sm text-signal-low">Everything on this order has been delivered.</p>;

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = Number(quantity);
    if (!(q > 0) || q > remaining) { setError(`Enter a quantity between 0 and ${formatQuantity(remaining)}.`); return; }
    if (date > siteTodayIso()) { setError("A delivery cannot be dated in the future."); return; }
    setError(null);
    record.mutate(
      { request_id: lineId, quantity: quantity.trim(), delivered_on: date, notes: notes.trim() || null },
      {
        onSuccess: () => {
          setQuantity("");
          setNotes("");
        },
      },
    );
  }

  return (
    <form noValidate onSubmit={onSubmit} aria-label="Record a delivery" className="space-y-4">
      {record.isError ? <Alert tone="error">{errorText(record.error)}</Alert> : null}
      {error ? <Alert tone="error">{error}</Alert> : null}
      <SelectField label="Line" value={lineId} onChange={(e) => { setLineId(e.target.value); }}>
        {open.map((l) => (
          <option key={l.request_id} value={l.request_id}>
            {l.request_number}: {l.description.slice(0, 50)}
          </option>
        ))}
      </SelectField>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label={`Quantity received${line ? ` (${line.unit})` : ""}`}
          inputMode="decimal"
          value={quantity}
          hint={line ? `${formatQuantity(remaining)} still to come` : undefined}
          onChange={(e) => {
            setQuantity(e.target.value);
          }}
        />
        <TextField label="Delivered on" type="date" max={siteTodayIso()} value={date} onChange={(e) => { setDate(e.target.value); }} />
      </div>
      <TextField label="Delivery note or remarks (optional)" maxLength={500} value={notes} onChange={(e) => { setNotes(e.target.value); }} />
      <Button type="submit" variant="primary" disabled={record.isPending}>
        {record.isPending ? "Saving…" : "Record delivery"}
      </Button>
    </form>
  );
}

export function PurchaseOrderDetailPage() {
  const { orderId = "" } = useParams();
  const order = useOrder(orderId);
  const { can } = useAuth();

  if (order.isPending) return <p className="py-16 text-center text-ink-faint">Loading purchase order…</p>;
  if (order.isError) {
    if (order.error instanceof ApiError && order.error.status === 404) return <NotFoundPage />;
    return <Alert tone="error">{errorText(order.error)}</Alert>;
  }
  const po = order.data;
  // Prices and amounts arrive only for roles that see rates (not site engineers).
  const priced = po.total !== undefined;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <nav aria-label="Breadcrumb" className="text-sm text-ink-faint">
        <Link to="/purchase-orders" className="hover:text-ink hover:underline">
          Purchase orders
        </Link>{" "}
        / {po.number}
      </nav>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <PoStatusBadge status={po.status} />
            <span className="text-sm text-ink-faint">{po.project.name}</span>
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            {po.number} · {po.supplier.name}
          </h1>
          <p className="mt-1 text-ink-soft">
            Issued by {po.issued_by.full_name} on {formatDate(po.issued_at.slice(0, 10))} · expected {formatDate(po.expected_delivery)}
          </p>
        </div>
        {po.total !== undefined ? (
          <p className="tabular text-right text-2xl font-semibold text-ink">
            <span className="block text-sm font-normal text-ink-faint">Total</span>LKR {formatAmount(po.total)}
          </p>
        ) : null}
      </header>

      <Sheet className="relative overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Order lines and delivered quantities</caption>
          <thead className="border-b border-rule bg-paper-sunk/60 text-xs font-medium whitespace-nowrap text-ink-faint">
            <tr>
              <th scope="col" className="px-4 py-2.5 text-left font-medium">Line</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Ordered</th>
              {priced ? (
                <>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Price</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Amount</th>
                </>
              ) : null}
              <th scope="col" className="px-4 py-2.5 text-left font-medium">Delivered</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {po.lines.map((l) => {
              const share = Math.min(100, (Number(l.delivered_quantity) / Number(l.quantity)) * 100);
              return (
                <tr key={l.id}>
                  <th scope="row" className="px-4 py-3 text-left font-normal">
                    <Link to={`/materials/${l.request_id}`} className="font-medium text-ink hover:underline">{l.request_number}</Link>
                    <p className="text-ink-soft">
                      <span className="mr-1.5 font-mono text-xs text-ink-faint">{l.item_code}</span>
                      {l.description}
                    </p>
                  </th>
                  <td className="tabular px-4 py-3 text-right whitespace-nowrap">{formatQuantity(l.quantity)} {l.unit}</td>
                  {l.unit_price !== undefined && l.amount !== undefined ? (
                    <>
                      <td className="tabular px-4 py-3 text-right whitespace-nowrap text-ink-soft">{formatAmount(l.unit_price)}</td>
                      <td className="tabular px-4 py-3 text-right font-medium whitespace-nowrap">{formatAmount(l.amount)}</td>
                    </>
                  ) : null}
                  <td className="min-w-40 px-4 py-3">
                    <div aria-hidden="true" className="h-2 rounded-full bg-paper-sunk">
                      <div className="h-full rounded-full bg-signal-low" style={{ width: `${String(share)}%` }} />
                    </div>
                    <p className="tabular mt-1 text-xs text-ink-soft">
                      {formatQuantity(l.delivered_quantity)} of {formatQuantity(l.quantity)}
                    </p>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Sheet>

      <div className="grid gap-6 lg:grid-cols-2">
        {can("purchase_orders:manage") ? (
          <Sheet className="p-5">
            <SectionHeading>Record a delivery</SectionHeading>
            <DeliveryForm key={po.lines.map((l) => l.delivered_quantity).join()} po={po} />
          </Sheet>
        ) : null}
        <Sheet className="p-5">
          <SectionHeading annotation={po.deliveries.length ? String(po.deliveries.length) : undefined}>Deliveries</SectionHeading>
          {po.deliveries.length === 0 ? (
            <p className="text-sm text-ink-faint">Nothing delivered yet.</p>
          ) : (
            <ul aria-label="Deliveries" className="divide-y divide-rule">
              {po.deliveries.map((d) => (
                <li key={d.id} className="py-2.5 text-sm">
                  <p className="tabular font-medium text-ink">
                    {formatQuantity(d.quantity)} {d.unit ?? ""} on {formatDate(d.delivered_on)}
                    {d.request_number ? <span className="font-normal text-ink-faint"> · {d.request_number}</span> : null}
                  </p>
                  {d.notes ? <p className="text-ink-soft">{d.notes}</p> : null}
                </li>
              ))}
            </ul>
          )}
          {po.notes ? <p className="mt-4 border-t border-rule pt-3 text-sm text-ink-soft">Notes: {po.notes}</p> : null}
        </Sheet>
      </div>
    </div>
  );
}
