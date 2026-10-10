import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type SubmitEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { checkRequest, useBoqOptions, useCreateRequest, type BoqOption } from "../../api/materials";
import { useProjects } from "../../api/projects";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { SelectField, TextAreaField, TextField } from "../../components/ui/Field";
import { PageHeader } from "../../components/ui/PageHeader";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { RuleChecks } from "../../features/materials/MaterialBits";
import { formatAmount, formatQuantity } from "../../lib/money";
import { addDaysIso, siteTodayIso } from "../../lib/time";
import { useDebounced } from "../../lib/useDebounced";

const QUANTITY = /^\d{1,11}(\.\d{1,3})?$/;
const PRICE = /^\d{1,12}(\.\d{1,2})?$/;

function ItemPicker({
  options,
  selected,
  onSelect,
  disabled,
}: {
  options: BoqOption[];
  selected: string;
  onSelect: (item: BoqOption) => void;
  disabled: boolean;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = q
    ? options.filter((o) => o.item_code.toLowerCase().includes(q) || o.description.toLowerCase().includes(q))
    : options;

  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-sm font-medium text-ink">BOQ item</legend>
      <label className="block">
        <span className="sr-only">Search BOQ items</span>
        <input
          type="search"
          value={query}
          placeholder="Search code or description, e.g. cement"
          onChange={(e) => {
            setQuery(e.target.value);
          }}
          className="min-h-10 w-full rounded-lg border border-rule-strong bg-paper-raised px-3 text-sm text-ink placeholder:text-ink-faint focus:border-survey focus:ring-2 focus:ring-survey/25 focus:outline-none"
        />
      </label>
      <div className="relative max-h-72 overflow-y-auto rounded-lg border border-rule">
        {shown.length === 0 ? <p className="px-3 py-6 text-center text-sm text-ink-faint">No items match.</p> : null}
        <ul className="divide-y divide-rule">
          {shown.map((o) => {
            return (
              <li key={o.id}>
                <label
                  className={`flex cursor-pointer gap-3 px-3 py-2.5 hover:bg-paper-sunk ${selected === o.id ? "bg-hivis/10" : ""}`}
                >
                  <input
                    type="radio"
                    name="boq-item"
                    value={o.id}
                    checked={selected === o.id}
                    onChange={() => {
                      onSelect(o);
                    }}
                    className="mt-1 size-4 accent-[var(--color-accent-line)]"
                  />
                  <span className="min-w-0 flex-1 text-sm text-ink">
                    <span className="mr-1.5 font-mono text-xs text-ink-faint">{o.item_code}</span>
                    {o.description}
                    <span className="tabular block text-xs text-ink-faint">
                      {formatQuantity(o.remaining_quantity)} of {formatQuantity(o.boq_quantity)} {o.unit} left ·{" "}
                      {formatQuantity(o.requested_quantity)} requested so far
                      {o.budget_rate !== undefined ? ` · budget LKR ${formatAmount(o.budget_rate)} / ${o.unit}` : ""}
                    </span>
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      </div>
    </fieldset>
  );
}

export function RequestFormPage() {
  const { can } = useAuth();
  // Site engineers do not see rates: they enter no price and the QS prices the request.
  const pricing = can("rates:read");
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const projects = useProjects();
  const create = useCreateRequest();
  const open = (projects.data ?? []).filter((p) => p.status === "active" || p.status === "on_hold");

  const [projectId, setProjectId] = useState(params.get("project") ?? "");
  const [item, setItem] = useState<BoqOption | null>(null);
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [neededBy, setNeededBy] = useState(addDaysIso(siteTodayIso(), 7));
  // Opened from a daily report's follow-up (Phase 7): the notes start with the reported problem.
  const fromAction = params.get("action") ?? "";
  const [notes, setNotes] = useState(params.get("notes")?.slice(0, 2000) ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const options = useBoqOptions(projectId);

  const draft = useMemo(
    () => ({
      project_id: projectId,
      boq_item_id: item?.id ?? "",
      quantity: quantity.trim(),
      ...(pricing ? { unit_price: price.trim() } : {}),
    }),
    [projectId, item, quantity, price, pricing],
  );
  const settled = useDebounced(draft);
  const priceReady = !pricing || (PRICE.test(settled.unit_price ?? "") && Number(settled.unit_price) > 0);
  const ready = settled.boq_item_id !== "" && QUANTITY.test(settled.quantity) && Number(settled.quantity) > 0 && priceReady;
  const check = useQuery({
    queryKey: ["materials", "check", settled],
    queryFn: ({ signal }) => checkRequest(settled, signal),
    enabled: ready,
    staleTime: 15_000,
  });

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!projectId) next.project = "Choose the project.";
    if (!item) next.item = "Choose the BOQ item you need.";
    if (!QUANTITY.test(quantity.trim()) || Number(quantity) <= 0) next.quantity = "Enter a quantity greater than zero.";
    if (pricing && (!PRICE.test(price.trim()) || Number(price) <= 0)) next.price = "Enter the expected unit price, greater than zero.";
    if (!neededBy || neededBy < siteTodayIso()) next.neededBy = "The needed-by date cannot be in the past.";
    setErrors(next);
    if (Object.keys(next).length || !item) return;
    create.mutate(
      { ...draft, needed_by: neededBy, notes: notes.trim() || null, ...(fromAction ? { report_action_id: fromAction } : {}) },
      {
        onSuccess: (request) => {
          void navigate(`/materials/${request.id}`);
        },
      },
    );
  }

  return (
    <form noValidate onSubmit={onSubmit} aria-label="New material request" className="mx-auto max-w-5xl space-y-6">
      <PageHeader
        eyebrow={<Link to="/materials" className="hover:text-ink hover:underline">Materials</Link>}
        title="New material request"
        description="Requests are checked against the BOQ quantity (BR-02, 3% tolerance). The QS approves, unless the unit price is more than 5% above the budgeted rate (BR-01) or the section's committed cost would exceed its budget line (BR-13): then the project manager approves."
      />

      {create.isError ? <Alert tone="error">{errorText(create.error)}</Alert> : null}
      {fromAction ? <Alert tone="info">Raising the material request from a daily report. The report's follow-up closes when you submit.</Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Sheet className="space-y-5 p-5">
          <SelectField
            label="Project"
            value={projectId}
            error={errors.project}
            disabled={create.isPending}
            onChange={(e) => {
              setProjectId(e.target.value);
              setItem(null);
            }}
          >
            <option value="">Choose a project</option>
            {open.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.site.code})
              </option>
            ))}
          </SelectField>

          {projectId ? (
            options.isPending ? (
              <p className="text-sm text-ink-faint">Loading the BOQ…</p>
            ) : options.data?.length === 0 ? (
              <Alert tone="warn">This project has no BOQ yet. The quantity surveyor imports it first.</Alert>
            ) : (
              <ItemPicker
                options={options.data ?? []}
                selected={item?.id ?? ""}
                disabled={create.isPending}
                onSelect={(o) => {
                  setItem(o);
                  if (!price && o.budget_rate !== undefined) setPrice(o.budget_rate);
                }}
              />
            )
          ) : null}
          {errors.item ? <p className="text-sm font-medium text-signal-high">{errors.item}</p> : null}

          <div className="grid gap-4 sm:grid-cols-3">
            <TextField
              label={`Quantity${item ? ` (${item.unit})` : ""}`}
              inputMode="decimal"
              value={quantity}
              error={errors.quantity}
              disabled={create.isPending}
              onChange={(e) => {
                setQuantity(e.target.value);
              }}
            />
{pricing ? (
            <TextField
              label="Unit price (LKR)"
              inputMode="decimal"
              value={price}
              error={errors.price}
              disabled={create.isPending}
              hint={item?.budget_rate !== undefined ? `Budgeted ${formatAmount(item.budget_rate)}` : undefined}
              onChange={(e) => {
                setPrice(e.target.value);
              }}
            />
            ) : null}
            <TextField
              label="Needed by"
              type="date"
              min={siteTodayIso()}
              value={neededBy}
              error={errors.neededBy}
              disabled={create.isPending}
              onChange={(e) => {
                setNeededBy(e.target.value);
              }}
            />
          </div>
          <TextAreaField
            label="Notes (optional)"
            rows={3}
            maxLength={2000}
            value={notes}
            disabled={create.isPending}
            hint="Where it is needed, delivery constraints, preferred supplier."
            onChange={(e) => {
              setNotes(e.target.value);
            }}
          />
        </Sheet>

        <div className="space-y-6">
          <Sheet className="p-5" aria-live="polite">
            <SectionHeading annotation={check.isFetching ? "checking…" : undefined}>Rules check</SectionHeading>
            {!ready ? (
              <p className="text-sm text-ink-faint">
                {pricing
                  ? "Choose an item and enter a quantity and price to see how the rules apply."
                  : "Choose an item and enter a quantity to check it against the BOQ. The price stays pending until the quantity surveyor enters the quoted price at the QS check."}
              </p>
            ) : check.data ? (
              <RuleChecks check={check.data} />
            ) : check.isError ? (
              <Alert tone="error">{errorText(check.error)}</Alert>
            ) : (
              <p className="text-sm text-ink-faint">Checking…</p>
            )}
          </Sheet>
          <div className="flex flex-wrap items-center justify-end gap-3">
            <Link to="/materials" className="text-sm font-medium text-ink-soft hover:text-ink">
              Cancel
            </Link>
            <Button type="submit" variant="primary" disabled={create.isPending || check.data?.blocked === true} className="min-h-11 px-6">
              {create.isPending ? "Submitting…" : "Submit request"}
            </Button>
          </div>
        </div>
      </div>
    </form>
  );
}
