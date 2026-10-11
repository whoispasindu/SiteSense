import { useState, type SubmitEvent } from "react";
import { useNavigate } from "react-router";
import { z } from "zod";

import {
  PROJECT_STATUSES,
  PROJECT_TYPES,
  STATUS_LABELS,
  TYPE_LABELS,
  useSaveProject,
  type ProjectDetail,
} from "../../api/projects";
import { useMySites } from "../../api/sites";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { SelectField, TextField } from "../../components/ui/Field";
import { errorText } from "../admin/adminUtils";

const baseSchema = z.object({
  name: z.string().trim().min(2, "Enter the project name.").max(160),
  client_name: z.string().trim().min(2, "Enter the client's name.").max(160),
  project_type: z.enum(PROJECT_TYPES),
  status: z.enum(PROJECT_STATUSES),
  contract_value: z
    .string()
    .trim()
    .transform((v) => v.replace(/,/g, ""))
    .refine((v) => /^\d{1,14}(\.\d{1,2})?$/.test(v) && Number(v) > 0, "Enter an amount in LKR, e.g. 1114000000.00"),
  start_date: z.iso.date("Choose a start date."),
  planned_end: z.iso.date("Choose a planned end date."),
  description: z
    .string()
    .trim()
    .max(2000)
    .transform((v) => v || null),
  planned_crew: z
    .string()
    .trim()
    .refine((v) => v === "" || (/^\d{1,4}$/.test(v) && Number(v) >= 1 && Number(v) <= 5000), "Enter a whole number of people, 1 to 5000.")
    .transform((v) => (v === "" ? null : Number(v))),
  // Phase 9: the days the site works, as ISO weekdays ("123456" = Monday to Saturday).
  working_week: z.string().regex(/^[1-7]{1,7}$/, "Choose at least one working day."),
});

const WEEKDAYS = [
  ["1", "Mon"],
  ["2", "Tue"],
  ["3", "Wed"],
  ["4", "Thu"],
  ["5", "Fri"],
  ["6", "Sat"],
  ["7", "Sun"],
] as const;

const createSchema = baseSchema.extend({
  code: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^[A-Z0-9][A-Z0-9-]{1,23}$/, "2–24 letters, digits or dashes, e.g. HR-2026-01."),
  site_id: z.uuid("Choose a site."),
});

type Field = keyof z.infer<typeof createSchema>;

interface ProjectFormDialogProps {
  open: boolean;
  onClose: () => void;
  /** Edit this project; omit to create a new one. */
  project?: ProjectDetail;
}

export function ProjectFormDialog({ open, onClose, project }: ProjectFormDialogProps) {
  const navigate = useNavigate();
  const sites = useMySites();
  const save = useSaveProject(project?.id);
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const editing = project !== undefined;
  const locked = project?.contract_locked === true;

  function close() {
    setErrors({});
    save.reset();
    onClose();
  }

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const days = form.getAll("working_day").filter((v): v is string => typeof v === "string");
    const raw = { ...Object.fromEntries(form), working_week: days.join("") };
    const parsed = (editing ? baseSchema : createSchema).safeParse(raw);
    const next: Partial<Record<Field, string>> = {};
    if (!parsed.success) {
      for (const issue of parsed.error.issues) next[issue.path[0] as Field] ??= issue.message;
    } else if (parsed.data.planned_end < parsed.data.start_date) {
      next.planned_end = "The planned end must be on or after the start date.";
    }
    setErrors(next);
    if (!parsed.success || Object.keys(next).length > 0) return;

    save.mutate(parsed.data, {
      onSuccess: (saved) => {
        close();
        if (!editing) void navigate(`/projects/${saved.id}`);
      },
    });
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={editing ? `Edit ${project.code}` : "New project"}
    >
      <form noValidate onSubmit={onSubmit} className="space-y-5">
        {save.isError ? <Alert tone="error">{errorText(save.error)}</Alert> : null}

        {!editing ? (
          <div className="grid gap-5 sm:grid-cols-[11rem_1fr]">
            <TextField label="Code" name="code" placeholder="HR-2026-01" autoComplete="off" className="font-mono" error={errors.code} />
            <SelectField label="Site" name="site_id" defaultValue="" error={errors.site_id} hint={sites.data?.length === 0 ? "You are not assigned to any site yet." : undefined}>
              <option value="" disabled>
                Choose a site…
              </option>
              {(sites.data ?? []).map((site) => (
                <option key={site.id} value={site.id}>
                  {site.code} · {site.name}
                </option>
              ))}
            </SelectField>
          </div>
        ) : null}

        <TextField label="Project name" name="name" defaultValue={project?.name} autoComplete="off" error={errors.name} />
        <TextField label="Client" name="client_name" defaultValue={project?.client_name} autoComplete="off" error={errors.client_name} />

        <div className="grid gap-5 sm:grid-cols-2">
          <SelectField label="Type" name="project_type" defaultValue={project?.project_type ?? "residential"}>
            {PROJECT_TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABELS[t]}
              </option>
            ))}
          </SelectField>
          <SelectField label="Status" name="status" defaultValue={project?.status ?? "planning"}>
            {PROJECT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </SelectField>
        </div>

        <TextField
          label="Contract value (LKR)"
          name="contract_value"
          inputMode="decimal"
          defaultValue={project?.contract_value}
          placeholder="1114000000.00"
          className="tabular"
          readOnly={locked}
          hint={locked ? "Changes through approved variations now that the project is under way." : undefined}
          error={errors.contract_value}
        />

        <div className="grid gap-5 sm:grid-cols-2">
          <TextField label="Start date" name="start_date" type="date" defaultValue={project?.start_date} error={errors.start_date} />
          <TextField
            label="Planned end"
            name="planned_end"
            type="date"
            defaultValue={project?.planned_end}
            readOnly={locked}
            hint={locked ? "Moves with approved variations' time impact." : undefined}
            error={errors.planned_end}
          />
        </div>

        <fieldset>
          <legend className="text-sm font-medium text-ink">Working week</legend>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {WEEKDAYS.map(([value, day]) => (
              <label key={value} className="flex min-h-9 items-center gap-1.5 rounded-md border border-rule-strong px-2.5 text-sm">
                <input
                  type="checkbox"
                  name="working_day"
                  value={value}
                  defaultChecked={(project?.working_week ?? "123456").includes(value)}
                  className="size-4 accent-[var(--color-ink)]"
                />
                {day}
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-ink-faint">
            The critical path and forecasts count these days, less the company holidays.
          </p>
          {errors.working_week ? <p className="mt-1 text-sm text-signal-high">{errors.working_week}</p> : null}
        </fieldset>

        <TextField
          label="Planned crew (optional)"
          name="planned_crew"
          inputMode="numeric"
          defaultValue={project?.planned_crew ?? ""}
          placeholder="55"
          className="tabular"
          hint="Average people on site. The risk forecast compares daily report crews with it."
          error={errors.planned_crew}
        />

        <label className="block space-y-1.5">
          <span className="block text-sm font-medium text-ink">Notes (optional)</span>
          <textarea
            name="description"
            rows={3}
            maxLength={2000}
            defaultValue={project?.description ?? ""}
            className="w-full rounded-lg border border-rule-strong bg-paper-raised px-3 py-2 text-sm text-ink focus:border-survey focus:ring-2 focus:ring-survey/25 focus:outline-none"
          />
        </label>

        <div className="flex justify-end gap-3 border-t border-rule pt-4">
          <Button onClick={close}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : editing ? "Save changes" : "Create project"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
