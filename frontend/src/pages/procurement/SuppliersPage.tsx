import { useState, type SubmitEvent } from "react";

import { useSaveSupplier, useSuppliers, type Supplier } from "../../api/materials";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { TextField } from "../../components/ui/Field";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { errorText } from "../../features/admin/adminUtils";

function SupplierDialog({ supplier, onClose }: { supplier?: Supplier; onClose: () => void }) {
  const save = useSaveSupplier(supplier?.id);
  const [values, setValues] = useState({
    name: supplier?.name ?? "",
    contact_name: supplier?.contact_name ?? "",
    phone: supplier?.phone ?? "",
    email: supplier?.email ?? "",
    categories: supplier?.categories ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const set = (field: keyof typeof values) => (e: { target: { value: string } }) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
  };

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (values.name.trim().length < 2) { setError("Enter the supplier's name."); return; }
    if (values.phone.trim() && !/^[0-9 +()-]{7,32}$/.test(values.phone.trim())) { setError("Enter a phone number with digits, spaces, + ( ) or -."); return; }
    setError(null);
    const blank = (v: string) => v.trim() || null;
    save.mutate(
      {
        name: values.name.trim(),
        contact_name: blank(values.contact_name),
        phone: blank(values.phone),
        email: blank(values.email),
        categories: blank(values.categories),
      },
      { onSuccess: onClose },
    );
  }

  return (
    <Dialog open onClose={onClose} title={supplier ? `Edit ${supplier.name}` : "Add a supplier"}>
      <form noValidate onSubmit={onSubmit} className="space-y-4">
        {save.isError ? <Alert tone="error">{errorText(save.error)}</Alert> : null}
        {error ? <Alert tone="error">{error}</Alert> : null}
        <TextField label="Name" maxLength={160} value={values.name} onChange={set("name")} />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Contact person (optional)" maxLength={120} value={values.contact_name} onChange={set("contact_name")} />
          <TextField label="Phone (optional)" inputMode="tel" maxLength={32} value={values.phone} onChange={set("phone")} />
        </div>
        <TextField label="Email (optional)" type="email" value={values.email} onChange={set("email")} />
        <TextField label="Supplies (optional)" maxLength={200} placeholder="e.g. cement, blocks" value={values.categories} onChange={set("categories")} />
        <div className="flex justify-end gap-3 border-t border-rule pt-4">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : supplier ? "Save changes" : "Add supplier"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function ActiveToggle({ supplier }: { supplier: Supplier }) {
  const save = useSaveSupplier(supplier.id);
  return (
    <Button
      variant="ghost"
      disabled={save.isPending}
      onClick={() => {
        save.mutate({ is_active: !supplier.is_active });
      }}
    >
      {supplier.is_active ? "Deactivate" : "Reactivate"}
    </Button>
  );
}

export function SuppliersPage() {
  const suppliers = useSuppliers(true);
  const [editing, setEditing] = useState<Supplier | "new" | null>(null);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader
        title="Suppliers"
        description="Suppliers available on purchase orders. Deactivated suppliers stay on past orders but cannot receive new ones."
        action={
          <Button variant="primary" onClick={() => { setEditing("new"); }}>
            Add supplier
          </Button>
        }
      />
      {suppliers.isError ? <Alert tone="error">{errorText(suppliers.error)}</Alert> : null}
      <Sheet className="relative overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Suppliers</caption>
          <thead className="border-b border-rule bg-paper-sunk/60 text-xs font-medium text-ink-faint">
            <tr>
              <th scope="col" className="px-4 py-2.5 text-left font-medium">Supplier</th>
              <th scope="col" className="hidden px-4 py-2.5 text-left font-medium md:table-cell">Contact</th>
              <th scope="col" className="px-4 py-2.5 text-left font-medium">Status</th>
              <th scope="col" className="px-4 py-2.5"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {(suppliers.data ?? []).map((s) => (
              <tr key={s.id} className={s.is_active ? "" : "text-ink-faint"}>
                <td className="px-4 py-3">
                  <p className="font-medium text-ink">{s.name}</p>
                  {s.categories ? <p className="text-xs text-ink-faint">{s.categories}</p> : null}
                </td>
                <td className="hidden px-4 py-3 text-ink-soft md:table-cell">
                  {[s.contact_name, s.phone, s.email].filter(Boolean).join(" · ") || "—"}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge tone={s.is_active ? "ok" : "idle"} label={s.is_active ? "Active" : "Inactive"} />
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  <Button variant="ghost" aria-label={`Edit ${s.name}`} onClick={() => { setEditing(s); }}>
                    Edit
                  </Button>
                  <ActiveToggle supplier={s} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Sheet>
      {editing ? (
        <SupplierDialog
          key={editing === "new" ? "new" : editing.id}
          supplier={editing === "new" ? undefined : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}
