import type { RequestDetail } from "../../api/materials";
import { useCriticalPath, useSetCriticalPath, useSupplierOutlook } from "../../api/suppliers";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { errorText } from "../admin/adminUtils";
import { Br12Notice, SupplierChance } from "./Br12";

const OPEN = new Set(["requested", "pm_approval", "approved", "ordered", "change_requested"]);
const SHOWN = 5;

/**
 * BR-12 on a request: whether it is a critical-path item (from the programme, or the project manager's
 * override), and how likely each supplier is to deliver it on time.
 */
export function SupplierPanel({ request }: { request: RequestDetail }) {
  const critical = useCriticalPath(request.id);
  const setCritical = useSetCriticalPath(request.id);
  const expected = request.order?.expected_delivery ?? request.needed_by;
  const open = OPEN.has(request.status);
  const outlook = useSupplierOutlook(request.project.id, expected, open);
  const c = critical.data;
  const ordered = request.order ? outlook.data?.suppliers.find((s) => s.supplier_name === request.order?.supplier_name) : undefined;

  return (
    <Sheet className="h-fit space-y-4 p-5">
      <SectionHeading annotation="BR-12">Critical path and suppliers</SectionHeading>
      {critical.isError ? <Alert tone="error">{errorText(critical.error)}</Alert> : null}
      {c ? (
        <div className="space-y-2">
          <StatusBadge tone={c.critical ? "warn" : "idle"} label={c.critical ? "Critical-path item" : "Not a critical-path item"} />
          <p className="text-sm text-ink-soft">{c.reason}</p>
          <p className="text-xs text-ink-faint">
            Counts when its BOQ section is linked to a critical task, or one with {c.float_days} working days of float or fewer.
          </p>
          {c.can_override ? (
            <div className="flex flex-wrap gap-2">
              {c.override !== true ? (
                <Button
                  disabled={setCritical.isPending}
                  onClick={() => {
                    setCritical.mutate(true);
                  }}
                >
                  Mark critical
                </Button>
              ) : null}
              {c.override !== false ? (
                <Button
                  disabled={setCritical.isPending}
                  onClick={() => {
                    setCritical.mutate(false);
                  }}
                >
                  Mark not critical
                </Button>
              ) : null}
              {c.override !== null ? (
                <Button
                  variant="ghost"
                  disabled={setCritical.isPending}
                  onClick={() => {
                    setCritical.mutate(null);
                  }}
                >
                  Use the programme
                </Button>
              ) : null}
            </div>
          ) : null}
          {setCritical.isError ? <Alert tone="error">{errorText(setCritical.error)}</Alert> : null}
        </div>
      ) : null}

      {open && outlook.data ? (
        <div className="space-y-3 border-t border-rule pt-3">
          {ordered && c?.critical ? (
            <Br12Notice outlook={outlook.data} supplierId={ordered.supplier_id} criticalNumbers={[request.number]} />
          ) : null}
          <p className="text-sm font-medium text-ink">Suppliers for delivery by this date</p>
          <ol aria-label="Suppliers by on-time chance" className="space-y-2">
            {outlook.data.suppliers.slice(0, SHOWN).map((s) => (
              <li key={s.supplier_id} className="text-sm">
                <span className="font-medium text-ink">{s.supplier_name}</span>
                {s.supplier_id === ordered?.supplier_id ? <span className="text-xs text-ink-faint"> (on the order)</span> : null}
                <span className="block text-ink-soft">
                  <SupplierChance estimate={s} />
                </span>
              </li>
            ))}
          </ol>
          {outlook.data.suppliers.length === 0 ? <p className="text-sm text-ink-faint">No active suppliers yet.</p> : null}
          <p className="text-xs text-ink-faint">
            Estimates from {outlook.data.suppliers[0]?.model ?? "the supplier model"}, trained on simulated deliveries. Under 50% for a
            critical-path item, BR-12 suggests another supplier.
          </p>
        </div>
      ) : null}
    </Sheet>
  );
}
