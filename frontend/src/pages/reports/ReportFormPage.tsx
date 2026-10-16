import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type SubmitEvent } from "react";
import { Link, useNavigate } from "react-router";
import { z } from "zod";

import { ApiError } from "../../api/client";
import { reportKeys, uploadPhoto, useCreateReport, useWeather, type ReportInput, type WeatherDay } from "../../api/reports";
import { useTasks } from "../../api/schedule";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { TextAreaField, TextField } from "../../components/ui/Field";
import { Icon } from "../../components/ui/icons";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { prepareImage, type PendingPhoto } from "../../features/reports/images";
import { PhotoPicker } from "../../features/reports/photos";
import { weatherIcon } from "../../features/reports/weather";
import { addDaysIso, siteTodayIso } from "../../lib/time";
import { useCurrentProject } from "../projects/projectContext";

const MAX_BACKDATE_DAYS = 7;
const PHOTO_LIMIT = 12;
const decimalText = (label: string, min: number, max: number) =>
  z
    .string()
    .trim()
    .refine((v) => v === "" || (/^-?\d+(\.\d)?$/.test(v) && Number(v) >= min && Number(v) <= max), {
      message: `${label}: a number between ${String(min)} and ${String(max)}, one decimal at most.`,
    });

const formSchema = z.object({
  report_date: z.iso.date("Choose the report date."),
  crew_count: z
    .string()
    .trim()
    .regex(/^\d{1,4}$/, "Enter the number of people on site (0 to 5000).")
    .refine((v) => Number(v) <= 5000, "Enter the number of people on site (0 to 5000)."),
  work_done: z.string().trim().min(10, "Describe the work done (at least 10 characters).").max(5000),
  problems: z.string().trim().max(5000),
  weather_summary: z.string().trim().max(60),
  temp_max_c: decimalText("Max temperature", -60, 70),
  temp_min_c: decimalText("Min temperature", -60, 70),
  rain_mm: decimalText("Rainfall", 0, 2000),
});
type FormValues = z.infer<typeof formSchema>;
type FieldName = keyof FormValues;
type WeatherValues = Pick<FormValues, "weather_summary" | "temp_max_c" | "temp_min_c" | "rain_mm">;
const WEATHER_FIELDS: readonly FieldName[] = ["weather_summary", "temp_max_c", "temp_min_c", "rain_mm"];
type Errors = Partial<Record<FieldName | "progress", string>>;

function weatherValues(day: WeatherDay | undefined): WeatherValues {
  return {
    weather_summary: day?.summary ?? "",
    temp_max_c: day?.temp_max_c ?? "",
    temp_min_c: day?.temp_min_c ?? "",
    rain_mm: day?.rain_mm ?? "",
  };
}

const emptyToNull = (v: string) => (v.trim() === "" ? null : v.trim());

export function ReportFormPage() {
  const project = useCurrentProject();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const create = useCreateReport(project.id);
  const tasks = useTasks(project.id);
  const weather = useWeather(project.id);
  const today = siteTodayIso();

  const [fields, setFields] = useState({ report_date: today, crew_count: "", work_done: "", problems: "" });
  // Weather follows the forecast for the chosen date until the engineer edits a weather field.
  const [weatherDraft, setWeatherDraft] = useState<WeatherValues | null>(null);
  const [progress, setProgress] = useState<Record<string, string>>({});
  const [photos, setPhotos] = useState<PendingPhoto[]>([]);
  const [errors, setErrors] = useState<Errors>({});
  const [stage, setStage] = useState<"editing" | "saving" | "uploading">("editing");
  const [uploaded, setUploaded] = useState(0);

  const forecastDay = weather.data?.days.find((d) => d.date === fields.report_date);
  const weatherEdited = weatherDraft !== null;
  const values: FormValues = { ...fields, ...(weatherDraft ?? weatherValues(forecastDay)) };

  const openTasks = useMemo(
    () =>
      (tasks.data?.tasks ?? []).filter(
        (t) => Number(t.percent_complete) < 100 && t.planned_start <= addDaysIso(fields.report_date, 14),
      ),
    [tasks.data, fields.report_date],
  );

  const busy = stage !== "editing";
  const conflictId =
    create.error instanceof ApiError && create.error.status === 409
      ? (create.error.details.find((d) => typeof d.report_id === "string")?.report_id as string | undefined)
      : undefined;

  function set(field: FieldName, value: string) {
    if (WEATHER_FIELDS.includes(field)) {
      setWeatherDraft({ ...weatherValues(forecastDay), ...weatherDraft, [field]: value });
    } else {
      setFields((f) => ({ ...f, [field]: value }));
    }
  }

  async function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = formSchema.safeParse(values);
    const next: Errors = {};
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        const field = issue.path[0] as FieldName;
        next[field] ??= issue.message;
      }
    }
    const changes = Object.entries(progress).filter(([id, v]) => {
      const task = openTasks.find((t) => t.id === id);
      return task && v.trim() !== "" && Number(v) !== Number(task.percent_complete);
    });
    if (changes.some(([, v]) => !/^\d{1,3}(\.\d{1,2})?$/.test(v.trim()) || Number(v) > 100)) {
      next.progress = "Progress must be a percentage between 0 and 100.";
    }
    setErrors(next);
    if (!parsed.success || next.progress) return;

    const data = parsed.data;
    const body: ReportInput = {
      report_date: data.report_date,
      crew_count: Number(data.crew_count),
      work_done: data.work_done,
      problems: emptyToNull(data.problems),
      weather_summary: emptyToNull(data.weather_summary),
      temp_max_c: emptyToNull(data.temp_max_c),
      temp_min_c: emptyToNull(data.temp_min_c),
      rain_mm: emptyToNull(data.rain_mm),
      weather_source: weatherEdited || !forecastDay ? "manual" : "forecast",
      progress: changes.map(([task_id, v]) => ({ task_id, percent_complete: v.trim() })),
    };

    setStage("saving");
    let reportId: string;
    try {
      reportId = (await create.mutateAsync(body)).id;
    } catch {
      setStage("editing");
      return;
    }

    setStage("uploading");
    const failed: string[] = [];
    for (const [index, photo] of photos.entries()) {
      try {
        await uploadPhoto(reportId, await prepareImage(photo.file), photo.caption.trim() || null);
      } catch (error) {
        failed.push(`${photo.file.name}: ${error instanceof ApiError ? error.message : "upload failed"}`);
      }
      setUploaded(index + 1);
    }
    if (photos.length) {
      // The cached report was saved before its photos: fetch it again with them.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: reportKeys.detail(reportId) }),
        queryClient.invalidateQueries({ queryKey: reportKeys.project(project.id) }),
      ]);
    }
    void navigate(`/reports/${reportId}`, { state: { uploadFailures: failed } });
  }

  return (
    <form noValidate onSubmit={(e) => void onSubmit(e)} className="mx-auto max-w-3xl space-y-6" aria-label="Daily site report">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-ink">Daily site report</h2>
          <p className="text-sm text-ink-soft">One report per day. You can correct it until midnight on the day you submit it.</p>
        </div>
        <Link to={`/projects/${project.id}/reports`} className="text-sm font-medium text-survey hover:underline">
          Back to reports
        </Link>
      </div>

      {create.isError ? (
        <Alert tone="error">
          {errorText(create.error)}
          {conflictId ? (
            <>
              {" "}
              <Link to={`/reports/${conflictId}`} className="font-medium underline">
                Open the existing report
              </Link>
            </>
          ) : null}
        </Alert>
      ) : null}

      <Sheet className="space-y-5 p-5">
        <div className="grid gap-5 sm:grid-cols-2">
          <TextField
            label="Report date"
            type="date"
            value={values.report_date}
            min={addDaysIso(today, -MAX_BACKDATE_DAYS)}
            max={today}
            required
            disabled={busy}
            error={errors.report_date}
            onChange={(e) => {
              set("report_date", e.target.value);
            }}
          />
          <TextField
            label="Crew on site"
            inputMode="numeric"
            value={values.crew_count}
            placeholder="e.g. 42"
            required
            disabled={busy}
            error={errors.crew_count}
            hint="Workers and staff on site today."
            onChange={(e) => {
              set("crew_count", e.target.value);
            }}
          />
        </div>
      </Sheet>

      <Sheet className="space-y-4 p-5">
        <SectionHeading
          annotation={
            forecastDay && !weatherEdited ? (
              <span className="inline-flex items-center gap-1">
                <Icon name={weatherIcon(forecastDay.weather_code)} className="size-4" />
                Filled from the forecast
              </span>
            ) : weatherEdited ? (
              "Entered by you"
            ) : undefined
          }
        >
          Weather
        </SectionHeading>
        {weather.data?.stale ? <Alert tone="warn">{weather.data.message}</Alert> : null}
        {weather.data && !weather.data.available ? <p className="text-sm text-ink-soft">{weather.data.message}</p> : null}
        <div className="grid gap-4 sm:grid-cols-4">
          <div className="sm:col-span-4">
            <TextField
              label="Conditions"
              value={values.weather_summary}
              maxLength={60}
              placeholder="e.g. Light rain in the afternoon"
              disabled={busy}
              error={errors.weather_summary}
              onChange={(e) => {
                set("weather_summary", e.target.value);
              }}
            />
          </div>
          <TextField
            label="Max °C"
            inputMode="decimal"
            value={values.temp_max_c}
            disabled={busy}
            error={errors.temp_max_c}
            onChange={(e) => {
              set("temp_max_c", e.target.value);
            }}
          />
          <TextField
            label="Min °C"
            inputMode="decimal"
            value={values.temp_min_c}
            disabled={busy}
            error={errors.temp_min_c}
            onChange={(e) => {
              set("temp_min_c", e.target.value);
            }}
          />
          <div className="sm:col-span-2">
            <TextField
              label="Rainfall (mm)"
              inputMode="decimal"
              value={values.rain_mm}
              disabled={busy}
              error={errors.rain_mm}
              onChange={(e) => {
                set("rain_mm", e.target.value);
              }}
            />
          </div>
        </div>
      </Sheet>

      <Sheet className="space-y-5 p-5">
        <TextAreaField
          label="Work done"
          value={values.work_done}
          rows={5}
          maxLength={5000}
          required
          disabled={busy}
          error={errors.work_done}
          hint={`${String(values.work_done.length)} / 5000. Areas, quantities, pours, inspections.`}
          onChange={(e) => {
            set("work_done", e.target.value);
          }}
        />
        <TextAreaField
          label="Problems (optional)"
          value={values.problems}
          rows={3}
          maxLength={5000}
          disabled={busy}
          error={errors.problems}
          hint="Late deliveries, shortages, breakdowns, safety issues, weather stoppages."
          onChange={(e) => {
            set("problems", e.target.value);
          }}
        />
      </Sheet>

      <Sheet className="p-5">
        <SectionHeading annotation="change only what moved">Task progress</SectionHeading>
        {errors.progress ? <Alert tone="error">{errors.progress}</Alert> : null}
        {tasks.isPending ? <p className="text-sm text-ink-faint">Loading tasks…</p> : null}
        {tasks.data && openTasks.length === 0 ? (
          <p className="text-sm text-ink-soft">No open tasks in the programme for this period.</p>
        ) : null}
        {openTasks.length > 0 ? (
          <ul aria-label="Task progress" className="divide-y divide-rule">
            {openTasks.map((task) => (
              <li key={task.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-ink">
                    {task.code ? <span className="mr-2 font-mono text-xs text-ink-faint">{task.code}</span> : null}
                    {task.name}
                  </p>
                  <p className="text-xs text-ink-faint">
                    Now {Number(task.percent_complete)}% · plan says {task.planned_percent_today}% by today
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <label htmlFor={`progress-${task.id}`} className="sr-only">
                    Percent complete for {task.name}
                  </label>
                  <input
                    id={`progress-${task.id}`}
                    inputMode="decimal"
                    placeholder={String(Number(task.percent_complete))}
                    value={progress[task.id] ?? ""}
                    disabled={busy}
                    onChange={(e) => {
                      setProgress((p) => ({ ...p, [task.id]: e.target.value }));
                    }}
                    className="tabular min-h-10 w-20 rounded-lg border border-field-line bg-paper-raised px-2 text-right text-sm text-ink placeholder:text-ink-faint focus:border-survey focus:ring-2 focus:ring-survey/25 focus:outline-none"
                  />
                  <span className="text-sm text-ink-faint">%</span>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </Sheet>

      <Sheet className="p-5">
        <SectionHeading annotation={photos.length ? `${String(photos.length)} selected` : undefined}>Photos</SectionHeading>
        <PhotoPicker items={photos} limit={PHOTO_LIMIT} onChange={setPhotos} disabled={busy} />
      </Sheet>

      <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center justify-end gap-3 border-t border-rule bg-paper/90 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0">
        <p className="mr-auto text-sm text-ink-soft" aria-live="polite">
          {stage === "saving" ? "Saving the report…" : null}
          {stage === "uploading" ? `Uploading photo ${String(Math.min(uploaded + 1, photos.length))} of ${String(photos.length)}…` : null}
        </p>
        <Link to={`/projects/${project.id}/reports`} className="text-sm font-medium text-ink-soft hover:text-ink">
          Cancel
        </Link>
        <Button type="submit" variant="primary" disabled={busy} className="min-h-11 px-6">
          {busy ? "Submitting…" : "Submit report"}
        </Button>
      </div>
    </form>
  );
}
