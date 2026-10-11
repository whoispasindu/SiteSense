import { useState, type SubmitEvent } from "react";

import { useSetVariationLimit, useVariationLimits, type ProjectLimit } from "../../api/contract";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { TextAreaField, TextField } from "../../components/ui/Field";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { formatAmount } from "../../lib/money";

const AMOUNT = /^\d{1,13}(\.\d{1,2})?$/;

function LimitDialog({ project, onClose }: { project: ProjectLimit; onClose: () => void }) {
  const save = useSetVariationLimit();
  const [limit, setLimit] = useState(project.variation_limit);
  const [reason, setReason] = useState("");
  const amount = limit.replace(/,/g, "").trim();
  const valid = AMOUNT.test(amount) && reason.trim().length >= 3;

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (valid) save.mutate({ projectId: project.project_id, variation_limit: amount, reason: reason.trim() }, { onSuccess: onClose });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <p className="text-sm text-ink-soft">
        Variations that change {project.code}&apos;s contract by more than this, either way, need the client&apos;s approval
        (BR-09). The client sees the limit. Variations already sent on keep the limit they were routed with.
      </p>
      <TextField
        label="Limit, LKR"
        inputMode="decimal"
        required
        value={limit}
        error={AMOUNT.test(amount) ? undefined : "Enter an amount, up to two decimals."}
        onChange={(e) => {
          setLimit(e.target.value);
        }}
      />
      <TextAreaField
        label="Reason (kept in the audit log)"
        rows={2}
        required
        maxLength={500}
        value={reason}
        onChange={(e) => {
          setReason(e.target.value);
        }}
      />
      {save.isError ? <Alert tone="error">{errorText(save.error)}</Alert> : null}
      <div className="flex justify-end gap-3">
        <Button onClick={onClose}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!valid || save.isPending}>
          Save limit
        </Button>
      </div>
    </form>
  );
}

/** Company Admin only: each project's BR-09 limit (1% of the contract value when it was created). */
export function VariationLimitsPage() {
  const limits = useVariationLimits();
  const [editing, setEditing] = useState<ProjectLimit | null>(null);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader
        title="Variation limits"
        description="BR-09: a variation that changes the contract by more than its project's limit, or changes the completion date, needs the client's approval. Every change here is audited."
      />
      {limits.isPending ? <p className="text-sm text-ink-faint">Loading projects…</p> : null}
      {limits.isError ? <Alert tone="error">{errorText(limits.error)}</Alert> : null}
      {limits.data ? (
        <Sheet className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Variation limit by project, in LKR</caption>
            <thead className="border-b border-rule bg-paper-sunk/60 text-xs text-ink-faint">
              <tr>
                <th scope="col" className="px-4 py-2.5 text-left font-medium">Project</th>
                <th scope="col" className="hidden px-4 py-2.5 text-left font-medium sm:table-cell">Site</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Limit, LKR</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">
                  <span className="sr-only">Change</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {limits.data.map((p) => (
                <tr key={p.project_id}>
                  <th scope="row" className="px-4 py-3 text-left font-normal">
                    <span className="mr-2 font-mono text-xs text-ink-faint">{p.code}</span>
                    {p.name}
                  </th>
                  <td className="hidden px-4 py-3 text-ink-soft sm:table-cell">{p.site_code}</td>
                  <td className="tabular px-4 py-3 text-right text-ink">{formatAmount(p.variation_limit)}</td>
                  <td className="px-4 py-3 text-right">
                    <Button variant="ghost" aria-label={`Change the limit for ${p.code}`} onClick={() => { setEditing(p); }}>
                      Change
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Sheet>
      ) : null}
      <Dialog open={editing !== null} title={editing ? `Variation limit for ${editing.code}` : "Variation limit"} onClose={() => { setEditing(null); }}>
        {editing ? <LimitDialog key={editing.project_id} project={editing} onClose={() => { setEditing(null); }} /> : null}
      </Dialog>
    </div>
  );
}
