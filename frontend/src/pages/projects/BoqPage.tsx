import { useState, type SubmitEvent } from "react";
import { Link, useLocation } from "react-router";

import { useBoq, useUpdateBudgetLine, type Boq } from "../../api/projects";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { formatAmount, formatQuantity, toNumber } from "../../lib/money";
import { useCurrentProject } from "./projectContext";

type Section = Boq["sections"][number];

function BudgetEditor({ projectId, section, onDone }: { projectId: string; section: Section; onDone: () => void }) {
  const update = useUpdateBudgetLine(projectId);
  const [value, setValue] = useState(section.budget_amount);
  const valid = /^\d{1,14}(\.\d{1,2})?$/.test(value.replace(/,/g, ""));

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    update.mutate({ lineId: section.budget_line_id, amount: value.replace(/,/g, "") }, { onSuccess: onDone });
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-center justify-end gap-2">
      <label className="sr-only" htmlFor={`budget-${section.id}`}>
        Budget for section {section.code}, LKR
      </label>
      <input
        id={`budget-${section.id}`}
        value={value}
        inputMode="decimal"
        aria-invalid={!valid}
        onChange={(e) => {
          setValue(e.target.value);
        }}
        className="tabular min-h-9 w-44 rounded-[2px] border-2 border-ink bg-paper-raised px-2 text-right font-mono text-sm focus:outline-none aria-[invalid=true]:border-signal-high"
      />
      <Button type="submit" variant="primary" disabled={!valid || update.isPending} className="min-h-9">
        Save
      </Button>
      <Button variant="ghost" onClick={onDone} className="min-h-9">
        Cancel
      </Button>
      {update.isError ? <p className="w-full text-right text-xs text-signal-high">{errorText(update.error)}</p> : null}
    </form>
  );
}

function SectionSheet({ projectId, section, canEdit }: { projectId: string; section: Section; canEdit: boolean }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const amount = toNumber(section.amount);
  const margin = amount > 0 ? ((amount - toNumber(section.budget_amount)) / amount) * 100 : 0;
  const panelId = `section-${section.id}`;

  return (
    <Sheet as="article" aria-label={`Section ${section.code}: ${section.name}`}>
      <div className="grid gap-3 px-5 py-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => {
            setOpen((v) => !v);
          }}
          className="flex min-h-11 min-w-0 items-center gap-3 text-left"
        >
          <span aria-hidden="true" className={`font-mono text-xs transition-transform ${open ? "rotate-90" : ""}`}>
            ▶
          </span>
          <span className="font-wide grid size-9 shrink-0 place-items-center rounded-[2px] bg-asphalt text-sm font-extrabold text-hivis">
            {section.code}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-semibold">{section.name}</span>
            <span className="block text-xs text-ink-faint">{section.item_count} items</span>
          </span>
        </button>

        <div className="grid grid-cols-3 gap-4 text-right md:min-w-[30rem]">
          <p>
            <span className="block font-mono text-[0.62rem] tracking-wider text-ink-faint uppercase">BOQ value</span>
            <span className="tabular font-mono text-sm">{formatAmount(section.amount)}</span>
          </p>
          <div>
            <span className="block font-mono text-[0.62rem] tracking-wider text-ink-faint uppercase">Budget</span>
            {editing ? null : (
              <span className="tabular font-mono text-sm">
                {formatAmount(section.budget_amount)}
                {canEdit ? (
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(true);
                    }}
                    className="mt-0.5 block w-full text-right text-xs text-survey underline underline-offset-2"
                    aria-label={`Edit budget for section ${section.code}`}
                  >
                    Edit
                  </button>
                ) : null}
              </span>
            )}
          </div>
          <p>
            <span className="block font-mono text-[0.62rem] tracking-wider text-ink-faint uppercase">Margin</span>
            <span className={`tabular font-mono text-sm ${margin < 0 ? "text-signal-high" : ""}`}>{margin.toFixed(1)} %</span>
          </p>
        </div>
        {editing ? (
          <div className="md:col-span-2">
            <BudgetEditor
              projectId={projectId}
              section={section}
              onDone={() => {
                setEditing(false);
              }}
            />
          </div>
        ) : null}
      </div>

      <div id={panelId} hidden={!open} className="overflow-x-auto border-t border-rule">
        <table className="w-full text-sm">
          <caption className="sr-only">Items in section {section.code}</caption>
          <thead className="bg-paper-sunk font-mono text-[0.62rem] tracking-[0.14em] text-ink-soft uppercase">
            <tr>
              <th scope="col" className="px-4 py-2 text-left font-normal">Item</th>
              <th scope="col" className="px-4 py-2 text-left font-normal">Description</th>
              <th scope="col" className="px-4 py-2 text-left font-normal">Unit</th>
              <th scope="col" className="px-4 py-2 text-right font-normal">Qty</th>
              <th scope="col" className="px-4 py-2 text-right font-normal">Rate</th>
              <th scope="col" className="px-4 py-2 text-right font-normal">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {section.items.map((item) => (
              <tr key={item.id}>
                <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap">{item.item_code}</td>
                <td className="min-w-64 px-4 py-2.5">{item.description}</td>
                <td className="px-4 py-2.5 font-mono text-xs">{item.unit}</td>
                <td className="tabular px-4 py-2.5 text-right font-mono whitespace-nowrap">{formatQuantity(item.quantity)}</td>
                <td className="tabular px-4 py-2.5 text-right font-mono whitespace-nowrap">{formatAmount(item.rate)}</td>
                <td className="tabular px-4 py-2.5 text-right font-mono whitespace-nowrap">{formatAmount(item.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Sheet>
  );
}

export function BoqPage() {
  const project = useCurrentProject();
  const boq = useBoq(project.id);
  const { can } = useAuth();
  const location = useLocation();
  const justImported = (location.state as { imported?: number } | null)?.imported;

  const importLink = can("boq:manage") ? (
    <Link
      to={`/projects/${project.id}/boq/import`}
      className="font-wide inline-flex min-h-11 items-center rounded-[var(--radius-sheet)] border-2 border-ink bg-hivis px-5 text-xs font-bold tracking-[0.12em] uppercase shadow-[3px_3px_0_0_var(--color-ink)] hover:bg-hivis-deep"
    >
      {project.item_count ? "Re-import BOQ" : "Import BOQ"}
    </Link>
  ) : null;

  if (boq.isPending) return <p className="py-10 text-center text-ink-faint">Loading BOQ…</p>;
  if (boq.isError) return <Alert tone="error">{errorText(boq.error)}</Alert>;
  const data = boq.data;
  const total = toNumber(data.boq_total);
  const margin = total > 0 ? ((total - toNumber(data.budget_total)) / total) * 100 : 0;

  return (
    <div className="space-y-6">
      {justImported ? (
        <Alert tone="success">
          BOQ imported: {justImported} {justImported === 1 ? "item" : "items"}. Section budgets are ready to review.
        </Alert>
      ) : null}

      <div className="flex flex-wrap items-end justify-between gap-4">
        <dl className="flex flex-wrap gap-x-10 gap-y-3">
          {[
            ["Items", String(data.item_count)],
            ["BOQ value (LKR)", formatAmount(data.boq_total)],
            ["Cost budget (LKR)", formatAmount(data.budget_total)],
            ["Margin", `${margin.toFixed(1)} %`],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="font-mono text-[0.65rem] tracking-[0.14em] text-ink-faint uppercase">{label}</dt>
              <dd className="tabular mt-1 font-mono text-xl">{value}</dd>
            </div>
          ))}
        </dl>
        {importLink}
      </div>

      {data.sections.length === 0 ? (
        <Sheet className="px-6 py-12 text-center">
          <p className="font-semibold">No bill of quantities yet</p>
          <p className="mt-1 text-sm text-ink-soft">
            {can("boq:manage") ? "Import it from an Excel or CSV file." : "The quantity surveyor imports the BOQ."}
          </p>
        </Sheet>
      ) : (
        <div className="space-y-3">
          {data.sections.map((section) => (
            <SectionSheet key={section.id} projectId={project.id} section={section} canEdit={can("boq:manage")} />
          ))}
        </div>
      )}
    </div>
  );
}
