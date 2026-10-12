import { useState, type SubmitEvent } from "react";

import { useConfirmHandover, useHandover, useProjectPhotos, usePublishHandover, useSharePhotos, type ProjectPhotos } from "../../api/portal";
import { usePhotoUrl } from "../../api/reports";
import { useTasks, useUpdateTask, type Task } from "../../api/schedule";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { TextAreaField, TextField } from "../../components/ui/Field";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { formatSiteDateTime } from "../../lib/time";
import { errorText } from "../admin/adminUtils";
import { formatDate } from "../projects/dates";
import { againstContract, guessTask, SUGGESTED_MILESTONES } from "./portal";

// --- The handover date ---------------------------------------------------------------------------------

/** What the client sees, the suggestions behind it, the reminder, and the form to publish or confirm. */
export function HandoverPanel({ projectId }: { projectId: string }) {
  const state = useHandover(projectId);
  const publish = usePublishHandover(projectId);
  const confirm = useConfirmHandover(projectId);
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (state.isPending) return <Sheet className="p-5 text-sm text-ink-faint">Loading the handover date…</Sheet>;
  if (state.isError) return <Alert tone="error">{errorText(state.error)}</Alert>;
  const s = state.data;
  const published = s.published;
  const suggestions: { label: string; date: string }[] = [
    { label: "Contract end", date: s.suggestions.contract_end },
    ...(s.suggestions.programme_forecast ? [{ label: "Programme, at current rates", date: s.suggestions.programme_forecast }] : []),
    ...(s.suggestions.risk_range
      ? [
          { label: "Risk model, early end", date: s.suggestions.risk_range.start },
          { label: "Risk model, late end", date: s.suggestions.risk_range.end },
        ]
      : []),
  ];

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!date) {
      setError("Choose the date to publish.");
      return;
    }
    if (reason.trim().length < 3) {
      setError("Write a short reason for the client.");
      return;
    }
    setError(null);
    publish.mutate(
      { handover_date: date, reason: reason.trim() },
      {
        onSuccess: () => {
          setDate("");
          setReason("");
        },
      },
    );
  }

  return (
    <Sheet className="p-5">
      <SectionHeading annotation="the one date the client sees">Handover date for the client</SectionHeading>
      {s.reminder ? (
        <div className="mb-4">
          <Alert tone="warn" title="This date may be out of date">
            <ul className="list-disc pl-4">
              {s.reminder.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            Publish a new date, or confirm this one if it still stands.
          </Alert>
        </div>
      ) : null}
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div>
          <p className="text-xs text-ink-faint">The client sees</p>
          <p className="tabular text-[1.625rem] leading-tight font-semibold tracking-tight text-ink">
            {formatDate(published?.handover_date ?? s.suggestions.contract_end)}
          </p>
          <p className="text-sm text-ink-soft">
            {published
              ? `${againstContract(published.handover_date, s.suggestions.contract_end)}. Published ${formatSiteDateTime(published.published_at)} by ${published.published_by}.`
              : "Nothing published yet: the client sees the contract date."}
          </p>
          {published ? <blockquote className="mt-2 border-l-2 border-accent-line pl-3 text-sm text-ink">{published.reason}</blockquote> : null}
          {s.current?.kind === "confirmed" ? (
            <p className="mt-2 text-xs text-ink-faint">
              Last reviewed {formatSiteDateTime(s.current.published_at)} by {s.current.published_by}.
            </p>
          ) : null}
          {published && s.can_publish ? (
            <div className="mt-3">
              <Button
                disabled={confirm.isPending}
                onClick={() => {
                  confirm.mutate(undefined);
                }}
              >
                {confirm.isPending ? "Confirming…" : "Confirm unchanged"}
              </Button>
              {confirm.isError ? <p className="mt-1 text-sm text-signal-high">{errorText(confirm.error)}</p> : null}
            </div>
          ) : null}
        </div>
        {s.can_publish ? (
          <form noValidate onSubmit={onSubmit} className="space-y-3 rounded-lg border border-rule bg-paper-sunk/50 p-4">
            <p className="text-sm font-medium text-ink">Publish a new date</p>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Suggested dates">
              {suggestions.map((sug) => (
                <button
                  key={sug.label}
                  type="button"
                  onClick={() => {
                    setDate(sug.date);
                  }}
                  className={`rounded-full border px-2.5 py-1 text-xs ${date === sug.date ? "border-ink bg-ink text-paper" : "border-rule-strong text-ink-soft hover:border-ink hover:text-ink"}`}
                >
                  {sug.label}: <span className="tabular font-medium">{formatDate(sug.date)}</span>
                </button>
              ))}
            </div>
            <TextField
              label="Handover date"
              name="handover_date"
              type="date"
              value={date}
              onChange={(event) => {
                setDate(event.target.value);
              }}
            />
            <TextAreaField
              label="Reason, for the client"
              name="reason"
              rows={3}
              maxLength={300}
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
              }}
              hint="Plain words: what moved the date and what is being done. The client is notified."
            />
            {error ? <p role="alert" className="text-sm text-signal-high">{error}</p> : null}
            {publish.isError ? <Alert tone="error">{errorText(publish.error)}</Alert> : null}
            <Button type="submit" variant="primary" disabled={publish.isPending}>
              {publish.isPending ? "Publishing…" : "Publish to the client"}
            </Button>
          </form>
        ) : null}
      </div>
      {s.history.length > 0 ? (
        <details className="mt-5 text-sm">
          <summary className="cursor-pointer font-medium text-survey hover:underline">History ({s.history.length})</summary>
          <ol className="mt-2 divide-y divide-rule">
            {s.history.map((e) => (
              <li key={`${e.kind}-${e.published_at}`} className="py-2">
                <p className="text-ink">
                  <span className="tabular font-medium">{formatDate(e.handover_date)}</span>{" "}
                  <span className="text-ink-faint">· {e.kind === "published" ? "published" : "confirmed unchanged"} by {e.published_by}, {formatSiteDateTime(e.published_at)}</span>
                </p>
                {e.kind === "published" ? <p className="text-ink-soft">{e.reason}</p> : null}
                {e.programme_forecast ? <p className="text-xs text-ink-faint">Programme forecast then: {formatDate(e.programme_forecast)}</p> : null}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </Sheet>
  );
}

// --- Milestones ----------------------------------------------------------------------------------------

function SuggestionRow({ name, tasks, guess, projectId }: { name: string; tasks: Task[]; guess: Task | undefined; projectId: string }) {
  const update = useUpdateTask(projectId);
  const [taskId, setTaskId] = useState(guess?.id ?? "");
  const id = `suggest-${name.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <li className="grid gap-2 py-3 sm:grid-cols-[11rem_minmax(0,1fr)_auto] sm:items-center">
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {name}
      </label>
      <select
        id={id}
        value={taskId}
        onChange={(event) => {
          setTaskId(event.target.value);
        }}
        className="min-h-10 rounded-lg border border-rule-strong bg-paper-raised px-3 text-sm text-ink"
      >
        <option value="">Choose the task that ends it…</option>
        {tasks.map((t) => (
          <option key={t.id} value={t.id}>
            {t.code ? `${t.code} ` : ""}
            {t.name} (ends {formatDate(t.planned_end)})
          </option>
        ))}
      </select>
      <Button
        disabled={!taskId || update.isPending}
        onClick={() => {
          update.mutate({ id: taskId, client_milestone: true, milestone_name: name });
        }}
      >
        {update.isPending ? "Adding…" : "Add"}
      </Button>
      {update.isError ? <p className="text-sm text-signal-high sm:col-span-3">{errorText(update.error)}</p> : null}
    </li>
  );
}

export function MilestonesPanel({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const tasks = useTasks(projectId);
  const update = useUpdateTask(projectId);
  if (tasks.isPending) return <Sheet className="p-5 text-sm text-ink-faint">Loading the programme…</Sheet>;
  if (tasks.isError) return <Alert tone="error">{errorText(tasks.error)}</Alert>;
  const all = tasks.data.tasks;
  const flagged = all.filter((t) => t.client_milestone).sort((a, b) => a.planned_end.localeCompare(b.planned_end));
  const used = new Set(flagged.map((t) => t.milestone_name ?? t.name));
  const remaining = SUGGESTED_MILESTONES.filter((m) => !used.has(m.name));

  return (
    <Sheet className="p-5">
      <SectionHeading annotation="programme tasks the client follows">Client milestones</SectionHeading>
      {flagged.length > 0 ? (
        <ul aria-label="Client milestones" className="divide-y divide-rule">
          {flagged.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <span className="min-w-0">
                <span className="block font-medium text-ink">{t.milestone_name ?? t.name}</span>
                <span className="block text-xs text-ink-faint">
                  {t.code ? `${t.code} · ` : ""}
                  {t.name} · ends {formatDate(t.planned_end)} · {Math.round(Number(t.percent_complete))}% done
                </span>
              </span>
              {canEdit ? (
                <Button
                  disabled={update.isPending}
                  onClick={() => {
                    update.mutate({ id: t.id, client_milestone: false });
                  }}
                >
                  Remove
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="pb-2 text-sm text-ink-soft">No milestones yet: the client sees none until some are flagged.</p>
      )}
      {canEdit && all.length > 0 && remaining.length > 0 ? (
        <div className="mt-4 border-t border-rule pt-3">
          <p className="text-sm font-medium text-ink">{flagged.length === 0 ? "Suggested milestones" : "Add a suggested milestone"}</p>
          <p className="text-xs text-ink-faint">Map each to the task that ends it. You can rename or flag any task from the Schedule tab too.</p>
          <ul aria-label="Suggested milestones" className="divide-y divide-rule">
            {remaining.map((m) => (
              <SuggestionRow
                key={m.name}
                name={m.name}
                tasks={all.filter((t) => !t.client_milestone)}
                guess={guessTask(all.filter((t) => !t.client_milestone), m.keywords)}
                projectId={projectId}
              />
            ))}
          </ul>
        </div>
      ) : null}
    </Sheet>
  );
}

// --- Photos --------------------------------------------------------------------------------------------

function PhotoTile({
  photo,
  selected,
  onToggle,
  canEdit,
}: {
  photo: ProjectPhotos["items"][number];
  selected: boolean;
  onToggle: () => void;
  canEdit: boolean;
}) {
  const image = usePhotoUrl(photo.id, "thumb");
  const label = `${photo.caption ?? "Photo"}, ${formatDate(photo.report_date)}`;
  return (
    <li className={`overflow-hidden rounded-lg border ${selected ? "border-ink ring-2 ring-ink" : "border-rule"} bg-paper-raised`}>
      <label className={`block ${canEdit ? "cursor-pointer" : ""}`}>
        <span className="relative block aspect-[4/3] bg-paper-sunk">
          {image.data ? <img src={image.data} alt="" className="size-full object-cover" /> : null}
          {canEdit ? (
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggle}
              aria-label={`Select ${label}`}
              className="absolute top-2 left-2 size-5 accent-[var(--color-ink)]"
            />
          ) : null}
          <span
            className={`absolute right-2 bottom-2 rounded-full px-2 py-0.5 text-[0.6875rem] font-medium ${
              photo.shared_with_client ? "bg-signal-low text-white" : "bg-asphalt/80 text-asphalt-text"
            }`}
          >
            {photo.shared_with_client ? "Shared with client" : "Private"}
          </span>
        </span>
        <span className="block px-3 py-2">
          <span className="line-clamp-1 block text-sm text-ink">{photo.caption ?? "No caption"}</span>
          <span className="block text-xs text-ink-faint">{formatDate(photo.report_date)}</span>
        </span>
      </label>
    </li>
  );
}

/** Every report photo; the PM selects and shares (or stops sharing). Private by default. */
export function PhotoSharingPanel({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const photos = useProjectPhotos(projectId);
  const share = useSharePhotos(projectId);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  if (photos.isPending) return <Sheet className="p-5 text-sm text-ink-faint">Loading photos…</Sheet>;
  if (photos.isError) return <Alert tone="error">{errorText(photos.error)}</Alert>;
  const p = photos.data;

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function apply(shared: boolean) {
    share.mutate(
      { photo_ids: [...selected], shared },
      {
        onSuccess: () => {
          setSelected(new Set());
        },
      },
    );
  }

  return (
    <Sheet className="p-5">
      <SectionHeading annotation={`${String(p.shared)} of ${String(p.total)} shared`}>Photos for the client</SectionHeading>
      <p className="mb-3 text-sm text-ink-soft">
        Photos stay private until shared. Shared copies carry no location, device or time stamps. Check for faces and unsafe moments first.
      </p>
      {canEdit && p.items.length > 0 ? (
        <div className="sticky top-16 z-10 mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-rule bg-paper-raised/95 px-3 py-2 backdrop-blur">
          <span className="text-sm text-ink-soft" aria-live="polite">
            {selected.size ? `${String(selected.size)} selected` : "Select photos to share or stop sharing"}
          </span>
          <Button
            variant="primary"
            disabled={!selected.size || share.isPending}
            onClick={() => {
              apply(true);
            }}
          >
            Share selected
          </Button>
          <Button
            disabled={!selected.size || share.isPending}
            onClick={() => {
              apply(false);
            }}
          >
            Stop sharing selected
          </Button>
          {selected.size ? (
            <Button
              onClick={() => {
                setSelected(new Set());
              }}
            >
              Clear
            </Button>
          ) : null}
        </div>
      ) : null}
      {share.isError ? <Alert tone="error">{errorText(share.error)}</Alert> : null}
      {p.items.length === 0 ? (
        <p className="py-4 text-sm text-ink-soft">No photos in this project's reports yet.</p>
      ) : (
        <ul aria-label="Report photos" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {p.items.map((photo) => (
            <PhotoTile
              key={photo.id}
              photo={photo}
              selected={selected.has(photo.id)}
              onToggle={() => {
                toggle(photo.id);
              }}
              canEdit={canEdit}
            />
          ))}
        </ul>
      )}
    </Sheet>
  );
}
