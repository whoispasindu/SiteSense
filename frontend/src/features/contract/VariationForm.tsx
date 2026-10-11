import { useState, type SubmitEvent } from "react";

import type { Variation, VariationInput } from "../../api/contract";
import { useBoq } from "../../api/projects";
import { useTasks } from "../../api/schedule";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { SelectField, TextAreaField, TextField } from "../../components/ui/Field";
import { formatAmount, formatQuantity, toNumber } from "../../lib/money";

const MONEY_CHANGE = /^-?\d{1,13}(\.\d{1,2})?$/;
const QUANTITY = /^\d{1,11}(\.\d{1,3})?$/;

interface Props {
  projectId: string;
  limit: string;
  initial?: Variation;
  submitLabel: string;
  busy: boolean;
  error: string | null;
  onSubmit: (input: VariationInput) => void;
  onCancel: () => void;
}

/**
 * Raise a variation, or revise a queried one. Anyone who manages variations describes the change;
 * only the QS prices it (contract change for the client, budget change for the cost plan). BR-09 is
 * explained next to the price, so the person raising it knows who will approve it.
 */
export function VariationForm({ projectId, limit, initial, submitLabel, busy, error, onSubmit, onCancel }: Props) {
  const { can } = useAuth();
  const canPrice = can("variations:price");
  const boq = useBoq(projectId);
  const tasks = useTasks(projectId);
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [sectionId, setSectionId] = useState(initial?.section_id ?? "");
  const [itemId, setItemId] = useState(initial?.boq_item_id ?? "");
  const [quantity, setQuantity] = useState(initial?.quantity_change ?? "");
  const [days, setDays] = useState(String(initial?.time_impact_days ?? 0));
  const [taskId, setTaskId] = useState(initial?.task_id ?? "");
  const [contract, setContract] = useState("");
  const [budget, setBudget] = useState("");
  const [comment, setComment] = useState("");

  const sections = boq.data?.sections ?? [];
  const items = sections.find((s) => s.id === sectionId)?.items ?? [];
  const dayCount = /^\d{1,4}$/.test(days) ? Number(days) : NaN;
  const pricing = canPrice && (contract !== "" || budget !== "");
  const problems = [
    title.trim().length < 3 ? "Give it a title." : null,
    description.trim().length < 3 ? "Describe the change." : null,
    sectionId === "" ? "Choose the BOQ section." : null,
    itemId !== "" && !QUANTITY.test(quantity) ? "Enter the extra quantity for the item." : null,
    itemId !== "" && toNumber(quantity) <= 0 ? "The extra quantity must be more than zero." : null,
    !Number.isInteger(dayCount) || dayCount > 3650 ? "Days must be a whole number up to 3650." : null,
    dayCount > 0 && taskId === "" ? "A time impact needs the task it delays." : null,
    pricing && !(MONEY_CHANGE.test(contract) && MONEY_CHANGE.test(budget)) ? "Price both changes (minus for an omission)." : null,
  ].filter((p): p is string => p !== null);

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (problems.length > 0) return;
    onSubmit({
      title: title.trim(),
      description: description.trim(),
      section_id: sectionId,
      boq_item_id: itemId || null,
      quantity_change: itemId ? quantity : null,
      task_id: taskId || null,
      time_impact_days: dayCount,
      ...(pricing ? { contract_change: contract, budget_change: budget } : {}),
      comment: comment.trim() || null,
    });
  }

  const overLimit = pricing && MONEY_CHANGE.test(contract) && Math.abs(toNumber(contract)) > toNumber(limit);
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <TextField label="Title" required maxLength={160} value={title} onChange={(e) => { setTitle(e.target.value); }} />
      <TextAreaField
        label="What changes, and why"
        rows={3}
        required
        maxLength={5000}
        value={description}
        onChange={(e) => {
          setDescription(e.target.value);
        }}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField
          label="BOQ section"
          required
          value={sectionId}
          onChange={(e) => {
            setSectionId(e.target.value);
            setItemId("");
          }}
        >
          <option value="">Choose…</option>
          {sections.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code} {s.name}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="Extra quantity on an item (optional)"
          hint="Raises the item's BR-02 allowance once approved."
          value={itemId}
          disabled={items.length === 0}
          onChange={(e) => {
            setItemId(e.target.value);
          }}
        >
          <option value="">No extra quantity</option>
          {items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.item_code} {item.description.slice(0, 60)} ({formatQuantity(item.quantity)} {item.unit})
            </option>
          ))}
        </SelectField>
      </div>
      {itemId ? (
        <TextField label="Extra quantity" inputMode="decimal" required value={quantity} onChange={(e) => { setQuantity(e.target.value); }} />
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Time impact (days)"
          hint="Any time impact needs the client's approval (BR-09)."
          inputMode="numeric"
          value={days}
          onChange={(e) => {
            setDays(e.target.value);
          }}
        />
        <SelectField
          label="Task it delays"
          value={taskId}
          disabled={dayCount === 0}
          onChange={(e) => {
            setTaskId(e.target.value);
          }}
        >
          <option value="">{dayCount === 0 ? "No time impact" : "Choose…"}</option>
          {(tasks.data?.tasks ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.code ? `${t.code} ` : ""}
              {t.name}
            </option>
          ))}
        </SelectField>
      </div>

      {canPrice ? (
        <fieldset className="space-y-3 rounded-lg border border-dashed border-rule-strong p-4">
          <legend className="px-1 text-sm font-semibold text-ink">Price (QS)</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Contract change, LKR"
              hint="What the client pays; minus for an omission."
              inputMode="decimal"
              value={contract}
              onChange={(e) => {
                setContract(e.target.value);
              }}
            />
            <TextField
              label="Cost budget change, LKR"
              hint="Internal: the section's budget line."
              inputMode="decimal"
              value={budget}
              onChange={(e) => {
                setBudget(e.target.value);
              }}
            />
          </div>
          <p className="text-xs text-ink-faint">
            The project's limit is LKR {formatAmount(limit)}. A contract change above it, any time impact, or a variation
            raised by a PM goes to the client; otherwise to a PM. Leave both empty to price it later.
          </p>
          {overLimit || dayCount > 0 ? (
            <p className="text-sm font-medium text-signal-medium">This one will go to the client.</p>
          ) : null}
        </fieldset>
      ) : (
        <p className="text-sm text-ink-faint">The quantity surveyor prices it next; then it goes to the PM or the client (BR-09).</p>
      )}
      <TextField label="Note for the record (optional)" maxLength={1000} value={comment} onChange={(e) => { setComment(e.target.value); }} />
      {problems.length > 0 ? <p className="text-sm text-ink-faint">{problems[0]}</p> : null}
      {error ? <Alert tone="error">{error}</Alert> : null}
      <div className="flex flex-wrap justify-end gap-3">
        <Button onClick={onCancel}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={problems.length > 0 || busy}>
          {busy ? "Saving…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
