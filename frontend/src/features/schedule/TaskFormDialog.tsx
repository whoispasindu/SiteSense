import { useState, type SubmitEvent } from "react";
import { z } from "zod";

import type { ProjectDetail } from "../../api/projects";
import { useCreateTask, useUpdateTask, type Task } from "../../api/schedule";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { SelectField, TextField } from "../../components/ui/Field";
import { percent } from "../../lib/money";
import { errorText } from "../admin/adminUtils";

const taskFormSchema = z.object({
  code: z
    .string()
    .trim()
    .toUpperCase()
    .refine((v) => v === "" || /^[A-Z0-9][A-Z0-9.-]{0,15}$/.test(v), "Up to 16 letters, digits, dots or dashes.")
    .transform((v) => v || null),
  name: z.string().trim().min(2, "Enter the task name.").max(160),
  boq_section_id: z
    .string()
    .transform((v) => v || null),
  planned_start: z.iso.date("Choose the planned start."),
  planned_end: z.iso.date("Choose the planned end."),
  weight: z
    .string()
    .trim()
    .refine((v) => /^\d{1,3}(\.\d{1,2})?$/.test(v) && Number(v) > 0 && Number(v) <= 100, "A share between 0.01 and 100 %."),
  is_critical: z.preprocess((v) => v === "on", z.boolean()),
});

type Field = keyof z.infer<typeof taskFormSchema>;

interface TaskFormDialogProps {
  project: ProjectDetail;
  task?: Task;
  open: boolean;
  onClose: () => void;
}

export function TaskFormDialog({ project, task, open, onClose }: TaskFormDialogProps) {
  const create = useCreateTask(project.id);
  const update = useUpdateTask(project.id);
  const save = task ? update : create;
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [sectionId, setSectionId] = useState(task?.boq_section_id ?? "");
  const section = project.sections.find((s) => s.id === sectionId);

  function close() {
    setErrors({});
    create.reset();
    update.reset();
    onClose();
  }

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const raw = Object.fromEntries(new FormData(event.currentTarget));
    const parsed = taskFormSchema.safeParse(raw);
    const next: Partial<Record<Field, string>> = {};
    if (!parsed.success) {
      for (const issue of parsed.error.issues) next[issue.path[0] as Field] ??= issue.message;
    } else {
      if (parsed.data.planned_end < parsed.data.planned_start) next.planned_end = "The end must be on or after the start.";
      if (parsed.data.planned_start < project.start_date) next.planned_start = "A task cannot start before the project starts.";
    }
    setErrors(next);
    if (!parsed.success || Object.keys(next).length > 0) return;

    const options = { onSuccess: close };
    if (task) update.mutate({ id: task.id, ...parsed.data }, options);
    else create.mutate(parsed.data, options);
  }

  return (
    <Dialog open={open} onClose={close} title={task ? `Edit ${task.code ?? "task"}` : "Add a task"} code={task?.code ?? "T-NEW"}>
      <form noValidate onSubmit={onSubmit} className="space-y-5">
        {save.isError ? <Alert tone="error">{errorText(save.error)}</Alert> : null}
        <div className="grid gap-5 sm:grid-cols-[9rem_1fr]">
          <TextField label="Code (optional)" name="code" defaultValue={task?.code ?? ""} placeholder="T-010" className="font-mono uppercase" error={errors.code} />
          <TextField label="Task name" name="name" defaultValue={task?.name} autoComplete="off" error={errors.name} />
        </div>
        <SelectField
          label="BOQ section (optional)"
          name="boq_section_id"
          value={sectionId}
          onChange={(e) => {
            setSectionId(e.target.value);
          }}
          hint={section ? `Section ${section.code} is ${percent(section.amount, project.boq_total).toFixed(1)}% of the BOQ value: a guide for the weight.` : undefined}
        >
          <option value="">None</option>
          {project.sections.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code} · {s.name}
            </option>
          ))}
        </SelectField>
        <div className="grid gap-5 sm:grid-cols-2">
          <TextField label="Planned start" name="planned_start" type="date" defaultValue={task?.planned_start} min={project.start_date} error={errors.planned_start} />
          <TextField label="Planned end" name="planned_end" type="date" defaultValue={task?.planned_end} error={errors.planned_end} />
        </div>
        <TextField
          label="Weight (% of contract)"
          name="weight"
          inputMode="decimal"
          defaultValue={task?.weight}
          placeholder="12.5"
          className="tabular font-mono"
          error={errors.weight}
          hint="All task weights together should add up to 100%."
        />
        <label className="flex min-h-11 items-center gap-3 text-sm">
          <input type="checkbox" name="is_critical" defaultChecked={task?.is_critical} className="size-4 accent-[var(--color-ink)]" />
          Critical task (delay here delays handover). Calculated automatically from Phase 9.
        </label>
        <div className="flex justify-end gap-3 border-t border-dashed border-rule pt-4">
          <Button onClick={close}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : task ? "Save task" : "Add task"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
