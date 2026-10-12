import { br12Alternative, chanceText, type OnTime, type Outlook } from "../../api/suppliers";
import { Alert } from "../../components/ui/Alert";
import { StatusBadge } from "../../components/ui/StatusBadge";

/** A supplier's on-time chance in one line: the number, its likely range, and the deliveries behind it. */
export function SupplierChance({ estimate }: { estimate: OnTime }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span className="tabular">On time {chanceText(estimate)}</span>
      {estimate.low_data ? <StatusBadge tone="idle" label="Low data" /> : null}
    </span>
  );
}

/**
 * BR-12: a critical-path item from a supplier under 50% gets a suggested alternative. When either supplier
 * rests on few deliveries, the suggestion says it is tentative. It only suggests: the choice stays with
 * procurement.
 */
export function Br12Notice({ outlook, supplierId, criticalNumbers }: { outlook: Outlook; supplierId: string; criticalNumbers: string[] }) {
  const current = outlook.suppliers.find((s) => s.supplier_id === supplierId);
  if (!current?.below_br12 || criticalNumbers.length === 0) return null;
  const alternative = br12Alternative(outlook, supplierId);
  const tentative = current.low_data || (alternative?.low_data ?? false);
  const items = criticalNumbers.join(", ");
  return (
    <Alert tone="warn" title={tentative ? "BR-12: consider another supplier (tentative)" : "BR-12: consider another supplier"}>
      <p>
        {items} {criticalNumbers.length === 1 ? "is a critical-path item" : "are critical-path items"}, and {current.supplier_name} is
        likely to be late: on time {chanceText(current)}.
      </p>
      {alternative ? (
        <p className="mt-1">
          {alternative.supplier_name} does better, if they supply it: on time {chanceText(alternative)}.
        </p>
      ) : (
        <p className="mt-1">No other active supplier does better.</p>
      )}
      {tentative ? <p className="mt-1 text-xs">Few deliveries are on record, so treat this as a hint, not a verdict.</p> : null}
    </Alert>
  );
}
