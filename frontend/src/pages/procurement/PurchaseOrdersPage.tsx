import { useState, type SubmitEvent } from "react";
import { Link, useNavigate } from "react-router";

import {
  PO_STATUS_LABELS,
  PO_STATUSES,
  useCreateOrder,
  useOrders,
  useReadyToOrder,
  useSuppliers,
  type PoStatus,
  type RequestSummary,
} from "../../api/materials";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { SelectField, TextAreaField, TextField } from "../../components/ui/Field";
import { PageHeader } from "../../components/ui/PageHeader";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge, type Tone } from "../../components/ui/StatusBadge";
import { errorText } from "../../features/admin/adminUtils";
import { formatDate } from "../../features/projects/dates";
import { formatAmount, formatCompactLKR, formatQuantity } from "../../lib/money";
import { addDaysIso, siteTodayIso } from "../../lib/time";

const PO_TONES: Record<PoStatus, Tone> = { issued: "idle", part_delivered: "warn", delivered: "ok" };

export function PoStatusBadge({ status }: { status: PoStatus }) {
  return <StatusBadge tone={PO_TONES[status]} label={PO_STATUS_LABELS[status]} />;
}

function OrderDialog({ requests, onClose }: { requests: RequestSummary[]; onClose: () => void }) {
  const suppliers = useSuppliers();
  const create = useCreateOrder();
  const navigate = useNavigate();
  const [supplierId, setSupplierId] = useState("");
  const [expected, setExpected] = useState(requests.reduce((min, r) => (r.needed_by < min ? r.needed_by : min), addDaysIso(siteTodayIso(), 365)));
  const [prices, setPrices] = useState<Record<string, string>>(Object.fromEntries(requests.map((r) => [r.id, r.unit_price ?? ""])));
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const total = requests.reduce((sum, r) => sum + Number(r.quantity) * Number(prices[r.id] ?? r.unit_price ?? 0), 0);

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supplierId) { setError("Choose the supplier."); return; }
    const over = requests.find((r) => !(Number(prices[r.id]) > 0) || Number(prices[r.id]) > Number(r.unit_price));
    if (over) { setError(`${over.number}: the price must be above zero and not above the approved LKR ${formatAmount(over.unit_price ?? 0)}.`); return; }
    if (expected < siteTodayIso()) { setError("The expected delivery date cannot be in the past."); return; }
    setError(null);
    create.mutate(
      {
        supplier_id: supplierId,
        expected_delivery: expected,
        notes: notes.trim() || null,
        lines: requests.map((r) => ({ request_id: r.id, unit_price: prices[r.id] ?? r.unit_price })),
      },
      {
        onSuccess: (po) => {
          onClose();
          void navigate(`/purchase-orders/${po.id}`);
        },
      },
    );
  }

  return (
    <Dialog open onClose={onClose} title="Create purchase order">
      <form noValidate onSubmit={onSubmit} className="space-y-4">
        {create.isError ? <Alert tone="error">{errorText(create.error)}</Alert> : null}
        {error ? <Alert tone="error">{error}</Alert> : null}
        <SelectField label="Supplier" value={supplierId} onChange={(e) => { setSupplierId(e.target.value); }}>
          <option value="">Choose a supplier</option>
          {(suppliers.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {s.categories ? ` (${s.categories})` : ""}
            </option>
          ))}
        </SelectField>
        <ul aria-label="Order lines" className="divide-y divide-rule rounded-lg border border-rule">
          {requests.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5">
              <div className="min-w-0 flex-1 text-sm">
                <p className="font-medium text-ink">
                  {r.number} · {formatQuantity(r.quantity)} {r.boq_item.unit}
                </p>
                <p className="truncate text-ink-faint">{r.boq_item.description}</p>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <span className="text-ink-faint">LKR / {r.boq_item.unit}</span>
                <input
                  aria-label={`Unit price for ${r.number}`}
                  inputMode="decimal"
                  value={prices[r.id] ?? ""}
                  onChange={(e) => {
                    setPrices((p) => ({ ...p, [r.id]: e.target.value }));
                  }}
                  className="tabular min-h-9 w-28 rounded-lg border border-rule-strong bg-paper-raised px-2 text-right text-sm text-ink focus:border-survey focus:outline-none"
                />
              </label>
            </li>
          ))}
        </ul>
        <p className="text-xs text-ink-faint">Order prices can be lower than approved, never higher (that needs a new approval).</p>
        <TextField label="Expected delivery" type="date" min={siteTodayIso()} value={expected} onChange={(e) => { setExpected(e.target.value); }} />
        <TextAreaField label="Notes for the supplier (optional)" rows={2} maxLength={2000} value={notes} onChange={(e) => { setNotes(e.target.value); }} />
        <div className="flex items-center justify-between gap-3 border-t border-rule pt-4">
          <p className="tabular text-sm font-medium text-ink">Total LKR {formatAmount(total.toFixed(2))}</p>
          <div className="flex gap-3">
            <Button onClick={onClose}>Back</Button>
            <Button type="submit" variant="primary" disabled={create.isPending}>
              {create.isPending ? "Issuing…" : "Issue order"}
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}

function ReadyToOrder() {
  const ready = useReadyToOrder();
  const [selected, setSelected] = useState<string[]>([]);
  const [ordering, setOrdering] = useState(false);
  const items = ready.data ?? [];
  const chosen = items.filter((r) => selected.includes(r.id));
  const project = chosen[0]?.project.id;

  return (
    <section aria-labelledby="ready-heading">
      <SectionHeading
        id="ready-heading"
        annotation={items.length ? `${String(items.length)} approved` : undefined}
        action={
          <Button variant="primary" disabled={chosen.length === 0} onClick={() => { setOrdering(true); }}>
            Create purchase order{chosen.length ? ` (${String(chosen.length)})` : ""}
          </Button>
        }
      >
        Ready to order
      </SectionHeading>
      {ready.isError ? <Alert tone="error">{errorText(ready.error)}</Alert> : null}
      <Sheet className="relative overflow-x-auto">
        {items.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-ink-faint">{ready.isPending ? "Loading…" : "Nothing is waiting to be ordered."}</p>
        ) : (
          <table className="w-full text-sm">
            <caption className="sr-only">Approved requests ready to order. One purchase order covers one project.</caption>
            <thead className="border-b border-rule bg-paper-sunk/60 text-xs font-medium whitespace-nowrap text-ink-faint">
              <tr>
                <th scope="col" className="w-10 px-4 py-2.5"><span className="sr-only">Select</span></th>
                <th scope="col" className="px-4 py-2.5 text-left font-medium">Request</th>
                <th scope="col" className="px-4 py-2.5 text-left font-medium">Item</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Value</th>
                <th scope="col" className="px-4 py-2.5 text-left font-medium">Needed by</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {items.map((r) => {
                const otherProject = project !== undefined && r.project.id !== project;
                return (
                  <tr key={r.id} className={otherProject ? "opacity-50" : ""}>
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        aria-label={`Select ${r.number}`}
                        checked={selected.includes(r.id)}
                        disabled={otherProject}
                        onChange={(e) => {
                          setSelected((s) => (e.target.checked ? [...s, r.id] : s.filter((id) => id !== r.id)));
                        }}
                        className="size-4 accent-[var(--color-accent-line)]"
                      />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <Link to={`/materials/${r.id}`} className="font-medium text-ink hover:underline">{r.number}</Link>
                      <p className="text-xs text-ink-faint">{r.project.name}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className="mr-1.5 font-mono text-xs text-ink-faint">{r.boq_item.item_code}</span>
                      {r.boq_item.description}
                      <p className="tabular text-xs text-ink-faint">{formatQuantity(r.quantity)} {r.boq_item.unit}</p>
                    </td>
                    <td className="tabular px-4 py-3 text-right font-medium whitespace-nowrap text-ink">
                      {r.amount !== undefined ? formatCompactLKR(r.amount) : "—"}
                    </td>
                    <td className="tabular px-4 py-3 whitespace-nowrap text-ink-soft">{formatDate(r.needed_by)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Sheet>
      {ordering ? (
        <OrderDialog
          requests={chosen}
          onClose={() => {
            setOrdering(false);
            setSelected([]);
          }}
        />
      ) : null}
    </section>
  );
}

export function PurchaseOrdersPage() {
  const { can } = useAuth();
  const [status, setStatus] = useState<PoStatus | "">("");
  const orders = useOrders(status);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHeader
        title="Purchase orders"
        description="Only approved requests can be ordered (BR-05). Committed cost updates when an order is issued, spent cost when deliveries are recorded."
      />
      {can("purchase_orders:manage") ? <ReadyToOrder /> : null}

      <section aria-labelledby="orders-heading">
        <SectionHeading id="orders-heading">Orders</SectionHeading>
        <div role="group" aria-label="Filter by status" className="mb-3 flex flex-wrap gap-1.5">
          {(["", ...PO_STATUSES] as const).map((s) => (
            <button
              key={s || "all"}
              type="button"
              aria-pressed={status === s}
              onClick={() => {
                setStatus(s);
              }}
              className={`min-h-9 rounded-full border px-3 text-sm font-medium ${
                status === s ? "border-ink bg-ink text-paper" : "border-rule-strong text-ink-soft hover:border-ink"
              }`}
            >
              {s ? PO_STATUS_LABELS[s] : "All"}
            </button>
          ))}
        </div>
        {orders.isError ? <Alert tone="error">{errorText(orders.error)}</Alert> : null}
        <ul aria-label="Purchase orders" className="space-y-3">
          {orders.data?.length === 0 ? <li className="py-6 text-center text-sm text-ink-faint">No purchase orders.</li> : null}
          {orders.data?.map((po) => (
            <li key={po.id}>
              <Link
                to={`/purchase-orders/${po.id}`}
                className="grid gap-3 rounded-[var(--radius-sheet)] border border-rule bg-paper-raised p-4 shadow-[var(--shadow-sheet)] transition hover:border-rule-strong hover:shadow-[var(--shadow-pop)] sm:grid-cols-[8rem_minmax(0,1fr)_auto_auto] sm:items-center sm:gap-6"
              >
                <span className="font-semibold text-ink">{po.number}</span>
                <span className="min-w-0">
                  <span className="block truncate text-ink">{po.supplier.name}</span>
                  <span className="block text-xs text-ink-faint">
                    {po.project.name} · expected {formatDate(po.expected_delivery)}
                  </span>
                </span>
                {po.total !== undefined ? <span className="tabular font-medium text-ink">{formatCompactLKR(po.total)}</span> : null}
                <PoStatusBadge status={po.status} />
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
