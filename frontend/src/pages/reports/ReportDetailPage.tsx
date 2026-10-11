import { useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { Link, useLocation, useParams } from "react-router";

import { ApiError } from "../../api/client";
import {
  reportKeys,
  uploadPhoto,
  useDeletePhoto,
  useReport,
  useUpdateReport,
  type ReportDetail,
} from "../../api/reports";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { TextAreaField, TextField } from "../../components/ui/Field";
import { Icon } from "../../components/ui/icons";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { AiCheck } from "../../features/reports/AiCheck";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { formatDate } from "../../features/projects/dates";
import { prepareImage, type PendingPhoto } from "../../features/reports/images";
import { PhotoGrid, PhotoPicker } from "../../features/reports/photos";
import { summaryIcon } from "../../features/reports/weather";
import { formatSiteTime } from "../../lib/time";
import { NotFoundPage } from "../NotFoundPage";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <dt className="text-sm text-ink-faint">{label}</dt>
      <dd className="tabular text-right text-sm font-medium text-ink">{children}</dd>
    </div>
  );
}

function EditReportDialog({ report, onClose }: { report: ReportDetail; onClose: () => void }) {
  const update = useUpdateReport(report.id);
  const [crew, setCrew] = useState(String(report.crew_count));
  const [workDone, setWorkDone] = useState(report.work_done);
  const [problems, setProblems] = useState(report.problems ?? "");
  const [summary, setSummary] = useState(report.weather_summary ?? "");
  const [rain, setRain] = useState(report.rain_mm ?? "");
  const [error, setError] = useState<string | null>(null);

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^\d{1,4}$/.test(crew.trim()) || Number(crew) > 5000) { setError("Crew must be a whole number from 0 to 5000."); return; }
    if (workDone.trim().length < 10) { setError("Describe the work done (at least 10 characters)."); return; }
    if (rain.trim() !== "" && !(/^\d{1,4}(\.\d)?$/.test(rain.trim()) && Number(rain) <= 2000)) {
      setError("Rainfall must be a number from 0 to 2000 mm."); return;
    }
    setError(null);
    const weatherChanged = summary.trim() !== (report.weather_summary ?? "") || rain.trim() !== (report.rain_mm ?? "");
    update.mutate(
      {
        crew_count: Number(crew),
        work_done: workDone.trim(),
        problems: problems.trim() || null,
        ...(weatherChanged
          ? { weather_summary: summary.trim() || null, rain_mm: rain.trim() || null, weather_source: "manual" as const }
          : {}),
      },
      { onSuccess: onClose },
    );
  }

  return (
    <Dialog open onClose={onClose} title="Correct the report">
      <form noValidate onSubmit={onSubmit} className="space-y-4">
        {error ? <Alert tone="error">{error}</Alert> : null}
        {update.isError ? <Alert tone="error">{errorText(update.error)}</Alert> : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Crew on site" inputMode="numeric" value={crew} onChange={(e) => { setCrew(e.target.value); }} />
          <TextField label="Rainfall (mm)" inputMode="decimal" value={rain} onChange={(e) => { setRain(e.target.value); }} />
        </div>
        <TextField label="Conditions" maxLength={60} value={summary} onChange={(e) => { setSummary(e.target.value); }} />
        <TextAreaField label="Work done" rows={5} maxLength={5000} value={workDone} onChange={(e) => { setWorkDone(e.target.value); }} />
        <TextAreaField label="Problems (optional)" rows={3} maxLength={5000} value={problems} onChange={(e) => { setProblems(e.target.value); }} />
        <p className="text-xs text-ink-faint">Task progress is not changed here; update it in the Schedule tab.</p>
        <div className="flex justify-end gap-3 border-t border-rule pt-4">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={update.isPending}>
            {update.isPending ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function AddPhotos({ report }: { report: ReportDetail }) {
  const queryClient = useQueryClient();
  const [items, setItems] = useState<PendingPhoto[]>([]);
  const [busy, setBusy] = useState(false);
  const [failures, setFailures] = useState<string[]>([]);
  const room = report.photo_limit - report.photos.length;

  async function upload() {
    setBusy(true);
    const failed: string[] = [];
    for (const item of items) {
      try {
        await uploadPhoto(report.id, await prepareImage(item.file), item.caption.trim() || null);
      } catch (error) {
        failed.push(`${item.file.name}: ${error instanceof ApiError ? error.message : "upload failed"}`);
      }
    }
    setFailures(failed);
    setItems([]);
    setBusy(false);
    await queryClient.invalidateQueries({ queryKey: reportKeys.detail(report.id) });
  }

  if (room <= 0) return <p className="text-sm text-ink-faint">This report has the maximum of {report.photo_limit} photos.</p>;
  return (
    <div className="space-y-3">
      {failures.length ? (
        <Alert tone="warn" title="Some photos were not added">
          <ul className="list-disc pl-5">
            {failures.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </Alert>
      ) : null}
      <PhotoPicker items={items} limit={room} onChange={setItems} disabled={busy} />
      {items.length ? (
        <Button variant="primary" disabled={busy} onClick={() => void upload()}>
          {busy ? "Uploading…" : `Upload ${String(items.length)} ${items.length === 1 ? "photo" : "photos"}`}
        </Button>
      ) : null}
    </div>
  );
}

export function ReportDetailPage() {
  const { reportId = "" } = useParams();
  const location = useLocation();
  const report = useReport(reportId);
  const remove = useDeletePhoto(reportId);
  const [editing, setEditing] = useState(false);
  const uploadFailures = (location.state as { uploadFailures?: string[] } | null)?.uploadFailures ?? [];

  if (report.isPending) return <p className="py-16 text-center text-ink-faint">Loading report…</p>;
  if (report.isError) {
    if (report.error instanceof ApiError && report.error.status === 404) return <NotFoundPage />;
    return <Alert tone="error">{errorText(report.error)}</Alert>;
  }
  const r = report.data;
  const corrected = new Date(r.updated_at).getTime() - new Date(r.submitted_at).getTime() > 60_000;

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <nav aria-label="Breadcrumb" className="text-sm text-ink-faint">
        <Link to={`/projects/${r.project_id}/reports`} className="hover:text-ink hover:underline">
          {r.project_name}
        </Link>{" "}
        / Daily reports
      </nav>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">Daily report · {formatDate(r.report_date)}</h1>
          <p className="mt-1 text-ink-soft">
            Filed by {r.author.full_name} at {formatSiteTime(r.submitted_at)}
            {corrected ? ` · corrected at ${formatSiteTime(r.updated_at)}` : ""}
          </p>
        </div>
        {r.editable ? (
          <Button
            onClick={() => {
              setEditing(true);
            }}
          >
            <Icon name="edit" className="size-4" />
            Correct report
          </Button>
        ) : null}
      </header>

      {uploadFailures.length ? (
        <Alert tone="warn" title="The report was saved, but some photos were not">
          <ul className="list-disc pl-5">
            {uploadFailures.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          You can add them again below today.
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="space-y-6">
          <Sheet className="p-5">
            <SectionHeading>Work done</SectionHeading>
            <p className="leading-relaxed whitespace-pre-line text-ink">{r.work_done}</p>
          </Sheet>
          {r.problems ? (
            <section aria-labelledby="problems-heading" className="rounded-[var(--radius-sheet)] border border-signal-medium/40 bg-signal-medium-tint p-5">
              <h2 id="problems-heading" className="mb-2 flex items-center gap-2 font-semibold text-signal-medium">
                <Icon name="alert" className="size-5" />
                Problems
              </h2>
              <p className="leading-relaxed whitespace-pre-line text-ink">{r.problems}</p>
            </section>
          ) : null}
          <AiCheck reportId={r.id} projectId={r.project_id} hasProblems={Boolean(r.problems)} />
          {r.progress.length ? (
            <Sheet className="relative overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="px-5 pt-4 text-left text-base font-semibold text-ink">Task progress reported</caption>
                <thead className="text-xs text-ink-faint">
                  <tr>
                    <th scope="col" className="px-5 py-2 text-left font-medium">Task</th>
                    <th scope="col" className="px-5 py-2 text-right font-medium">Before</th>
                    <th scope="col" className="px-5 py-2 text-right font-medium">After</th>
                    <th scope="col" className="px-5 py-2 text-right font-medium">Change</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-rule border-t border-rule">
                  {r.progress.map((p) => {
                    const delta = Number(p.percent_after) - Number(p.percent_before);
                    return (
                      <tr key={p.task_id ?? p.task_name}>
                        <th scope="row" className="px-5 py-2.5 text-left font-medium text-ink">{p.task_name}</th>
                        <td className="tabular px-5 py-2.5 text-right text-ink-soft">{Number(p.percent_before)}%</td>
                        <td className="tabular px-5 py-2.5 text-right text-ink">{Number(p.percent_after)}%</td>
                        <td className={`tabular px-5 py-2.5 text-right font-medium whitespace-nowrap ${delta < 0 ? "text-signal-high" : "text-signal-low"}`}>
                          {delta > 0 ? "+" : ""}
                          {delta.toFixed(1)} pts
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Sheet>
          ) : null}
        </div>

        <aside className="space-y-6">
          <Sheet className="p-5">
            <SectionHeading annotation={r.weather_source === "forecast" ? "from forecast" : "recorded on site"}>Weather</SectionHeading>
            {r.weather_summary ? (
              <p className="mb-2 flex items-center gap-2 font-medium text-ink">
                <Icon name={summaryIcon(r.weather_summary)} className="size-5 text-ink-soft" />
                {r.weather_summary}
              </p>
            ) : (
              <p className="mb-2 text-sm text-ink-faint">Not recorded</p>
            )}
            <dl className="divide-y divide-rule">
              <Fact label="Max">{r.temp_max_c === null ? "—" : `${r.temp_max_c} °C`}</Fact>
              <Fact label="Min">{r.temp_min_c === null ? "—" : `${r.temp_min_c} °C`}</Fact>
              <Fact label="Rainfall">{r.rain_mm === null ? "—" : `${r.rain_mm} mm`}</Fact>
            </dl>
          </Sheet>
          <Sheet className="p-5">
            <dl>
              <Fact label="Crew on site">{r.crew_count}</Fact>
              <Fact label="Photos">{r.photos.length}</Fact>
            </dl>
          </Sheet>
        </aside>
      </div>

      <section aria-labelledby="photos-heading" className="space-y-4">
        <SectionHeading id="photos-heading" annotation={r.photos.length ? `${String(r.photos.length)} of ${String(r.photo_limit)}` : undefined}>
          Photos
        </SectionHeading>
        {remove.isError ? <Alert tone="error">{errorText(remove.error)}</Alert> : null}
        {r.photos.length === 0 && !r.editable ? <p className="text-sm text-ink-faint">No photos with this report.</p> : null}
        {r.photos.length ? (
          <PhotoGrid
            photos={r.photos}
            deleting={remove.isPending}
            onDelete={
              r.editable
                ? (photo) => {
                    remove.mutate(photo.id);
                  }
                : undefined
            }
          />
        ) : null}
        {r.editable ? <AddPhotos report={r} /> : null}
      </section>

      {editing ? (
        <EditReportDialog
          report={r}
          onClose={() => {
            setEditing(false);
          }}
        />
      ) : null}
    </div>
  );
}
