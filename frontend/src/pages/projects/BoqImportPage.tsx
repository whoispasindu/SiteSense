import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";

import { useImportBoq, type ImportReport } from "../../api/projects";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Icon } from "../../components/ui/icons";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { formatAmount } from "../../lib/money";
import { useCurrentProject } from "./projectContext";

const MAX_BYTES = 5 * 1024 * 1024;

function plural(n: number, word: string): string {
  return `${String(n)} ${word}${n === 1 ? "" : "s"}`;
}
const COLUMN_LABELS: Record<string, string> = {
  section_code: "Section code",
  section_name: "Section name",
  item_code: "Item code",
  description: "Description",
  unit: "Unit",
  quantity: "Quantity",
  rate: "Rate",
  budget_rate: "Budget rate",
};

function Step({ n, label, state }: { n: string; label: string; state: "done" | "current" | "todo" }) {
  return (
    <li aria-current={state === "current" ? "step" : undefined} className="flex items-center gap-2">
      <span
        className={`grid size-7 place-items-center rounded-full text-xs font-semibold ${
          state === "done" ? "bg-signal-low text-white" : state === "current" ? "bg-hivis text-asphalt" : "border border-rule-strong text-ink-faint"
        }`}
      >
        {n}
      </span>
      <span className={`text-sm ${state === "todo" ? "text-ink-faint" : "font-medium text-ink"}`}>{label}</span>
    </li>
  );
}

function ReportView({ report }: { report: ImportReport }) {
  const errorRows = report.rows.filter((r) => r.status === "error");

  return (
    <div className="space-y-6">
      <dl className="grid gap-3 sm:grid-cols-4">
        {[
          ["Rows read", report.total_rows, ""],
          ["Valid items", report.ok_rows, "text-signal-low"],
          ["Headings skipped", report.skipped_rows, ""],
          ["Rows with errors", report.error_rows, report.error_rows ? "text-signal-high" : ""],
        ].map(([label, value, tone]) => (
          <div key={label} className="rounded-[var(--radius-sheet)] border border-rule bg-paper-raised px-4 py-3 shadow-[var(--shadow-sheet)]">
            <dt className="text-sm text-ink-faint">{label}</dt>
            <dd className={`tabular mt-1 text-2xl font-semibold ${String(tone) || "text-ink"}`}>{value}</dd>
          </div>
        ))}
      </dl>

      {errorRows.length > 0 ? (
        <section aria-labelledby="row-errors">
          <SectionHeading id="row-errors" annotation={plural(errorRows.length, "row")}>
            Fix these rows
          </SectionHeading>
          <Sheet>
            <ol aria-label="Rows with errors" className="max-h-[28rem] divide-y divide-rule overflow-y-auto">
              {errorRows.map((row) => (
                <li key={row.row} className="grid gap-1 px-5 py-3 sm:grid-cols-[6rem_1fr]">
                  <p className="text-sm font-medium text-ink">
                    Row {row.row}
                    {row.item_code ? <span className="block font-mono text-xs font-normal text-ink-faint">{row.item_code}</span> : null}
                  </p>
                  <div className="min-w-0">
                    {row.description ? <p className="truncate text-sm text-ink-soft">{row.description}</p> : null}
                    <ul className="mt-1 space-y-0.5">
                      {row.errors.map((e) => (
                        <li key={e.column} className="text-sm">
                          <span className="font-semibold text-signal-high">{COLUMN_LABELS[e.column] ?? e.column}:</span>{" "}
                          {e.message}
                        </li>
                      ))}
                    </ul>
                  </div>
                </li>
              ))}
            </ol>
          </Sheet>
        </section>
      ) : null}

      {report.sections.length > 0 ? (
        <section aria-labelledby="preview-sections">
          <SectionHeading id="preview-sections" annotation={`${String(report.sections.length)} sections`}>
            {report.error_rows ? "Valid rows so far" : "What will be imported"}
          </SectionHeading>
          <Sheet className="relative overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Sections found in the file, amounts in LKR</caption>
              <thead className="border-b border-rule bg-paper-sunk/60 text-xs font-medium text-ink-faint">
                <tr>
                  <th scope="col" className="px-4 py-2 text-left font-medium">Section</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Items</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">BOQ value</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Budget</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {report.sections.map((s) => (
                  <tr key={s.code}>
                    <th scope="row" className="px-4 py-2.5 text-left font-normal">
                      <span className="mr-2 font-mono text-xs text-ink-faint">{s.code}</span>
                      {s.name}
                    </th>
                    <td className="tabular px-4 py-2.5 text-right">{s.items}</td>
                    <td className="tabular px-4 py-2.5 text-right">{formatAmount(s.amount)}</td>
                    <td className="tabular px-4 py-2.5 text-right">{formatAmount(s.budget)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t border-rule-strong bg-paper-sunk/60 font-semibold text-ink">
                <tr>
                  <th scope="row" className="px-4 py-2.5 text-left">Total</th>
                  <td className="tabular px-4 py-2.5 text-right">{report.ok_rows}</td>
                  <td className="tabular px-4 py-2.5 text-right">{formatAmount(report.boq_total)}</td>
                  <td className="tabular px-4 py-2.5 text-right">{formatAmount(report.budget_total)}</td>
                </tr>
              </tfoot>
            </table>
          </Sheet>
          {!report.has_budget_rates ? (
            <p className="mt-2 text-xs text-ink-faint">
              No "Budget rate" column: each section's cost budget starts equal to its BOQ value. Adjust budgets after import.
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

/** A stable ref to the latest version of a callback (for listeners attached once). */
function useCallbackRef<A extends unknown[]>(fn: (...args: A) => void) {
  const ref = useRef(fn);
  useEffect(() => {
    ref.current = fn;
  });
  return ref;
}

export function BoqImportPage() {
  const project = useCurrentProject();
  const navigate = useNavigate();
  const importBoq = useImportBoq(project.id);
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [dragging, setDragging] = useState(false);

  const { reset } = importBoq;
  const choose = useCallbackRef((next: File | null) => {
    setReport(null);
    reset();
    const problem = !next
      ? null
      : !/\.(xlsx|csv)$/i.test(next.name)
        ? "Choose an .xlsx or .csv file."
        : next.size > MAX_BYTES
          ? "The file is larger than 5 MB."
          : null;
    setLocalError(problem);
    setFile(problem ? null : next);
  });

  // Drag and drop is a pointer convenience on top of the normal file chooser, so the listeners
  // are attached directly rather than as JSX handlers on the label.
  const dropRef = useRef<HTMLLabelElement>(null);
  useEffect(() => {
    const zone = dropRef.current;
    if (!zone) return;
    const over = (e: DragEvent) => {
      e.preventDefault();
      setDragging(true);
    };
    const leave = () => {
      setDragging(false);
    };
    const drop = (e: DragEvent) => {
      e.preventDefault();
      setDragging(false);
      choose.current(e.dataTransfer?.files[0] ?? null);
    };
    zone.addEventListener("dragover", over);
    zone.addEventListener("dragleave", leave);
    zone.addEventListener("drop", drop);
    return () => {
      zone.removeEventListener("dragover", over);
      zone.removeEventListener("dragleave", leave);
      zone.removeEventListener("drop", drop);
    };
  }, [choose]);

  function check() {
    if (!file) return;
    importBoq.mutate({ file, dryRun: true }, { onSuccess: setReport });
  }

  function commit() {
    if (!file) return;
    importBoq.mutate(
      { file, dryRun: false },
      {
        onSuccess: (result) => {
          if (result.imported) {
            void navigate(`/projects/${project.id}/boq`, { state: { imported: result.ok_rows } });
          } else {
            setReport(result);
          }
        },
      },
    );
  }

  const step = !file ? 1 : !report ? 2 : 3;
  const canImport = report !== null && report.error_rows === 0 && report.ok_rows > 0;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-2xl font-semibold tracking-tight">Import the bill of quantities</h2>
        <Link to={`/projects/${project.id}/boq`} className="text-sm text-ink-soft underline underline-offset-4 hover:text-ink">
          Back to BOQ
        </Link>
      </div>

      <ol aria-label="Import steps" className="flex flex-wrap gap-6">
        <Step n="1" label="Choose file" state={step > 1 ? "done" : "current"} />
        <Step n="2" label="Check rows" state={step > 2 ? "done" : step === 2 ? "current" : "todo"} />
        <Step n="3" label="Import" state={step === 3 ? "current" : "todo"} />
      </ol>

      <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
        <label
          ref={dropRef}
          className={`flex min-h-48 cursor-pointer flex-col items-center justify-center gap-3 rounded-[var(--radius-sheet)] border-2 border-dashed px-6 py-10 text-center transition-colors focus-within:border-survey ${
            dragging ? "border-accent-line bg-hivis/10" : "border-rule-strong bg-paper-raised hover:border-accent-line"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
            className="sr-only"
            onChange={(e) => {
              choose.current(e.target.files?.[0] ?? null);
            }}
          />
          <span aria-hidden="true" className="grid size-12 place-items-center rounded-full bg-paper-sunk text-ink-soft">
            <Icon name="upload" className="size-6" />
          </span>
          {file ? (
            <span>
              <span className="block font-semibold text-ink">{file.name}</span>
              <span className="tabular text-xs text-ink-faint">{(file.size / 1024).toFixed(1)} KB · choose another</span>
            </span>
          ) : (
            <span>
              <span className="block font-semibold text-ink">Drop the BOQ here, or choose a file</span>
              <span className="text-sm text-ink-faint">Excel .xlsx or CSV, up to 5 MB and 5,000 rows</span>
            </span>
          )}
        </label>

        <Sheet as="aside" className="p-5 text-sm">
          <h3 className="text-sm font-semibold text-ink">Expected columns</h3>
          <ul className="mt-3 space-y-1 text-sm text-ink-soft">
            {["Section Code", "Section Name", "Item Code", "Description", "Unit", "Quantity", "Rate", "Budget Rate (optional)"].map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-ink-faint">Headings and notes between items are skipped. Formulas must have saved values.</p>
          <a href="/boq-template.csv" download className="mt-4 inline-block text-sm font-medium text-survey hover:underline">
            Download the template
          </a>
        </Sheet>
      </div>

      {localError ? <Alert tone="error">{localError}</Alert> : null}
      {importBoq.isError ? <Alert tone="error">{errorText(importBoq.error)}</Alert> : null}

      {!report ? (
        <Button variant="primary" disabled={!file || importBoq.isPending} onClick={check}>
          {importBoq.isPending ? "Checking…" : "Check file"}
        </Button>
      ) : (
        <>
          <ReportView report={report} />
          {report.error_rows > 0 ? (
            <Alert tone="error" title={`${plural(report.error_rows, "row")} need${report.error_rows === 1 ? "s" : ""} fixing`}>
              Nothing has been imported. Correct the rows above in your file, then choose it again.
            </Alert>
          ) : report.replaces_items > 0 ? (
            <Alert tone="warn" title="This replaces the current BOQ">
              The project's {report.replaces_items} existing items and their section budgets will be replaced.
            </Alert>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <Button variant="primary" disabled={!canImport || importBoq.isPending} onClick={commit}>
              {importBoq.isPending ? "Importing…" : `Import ${plural(report.ok_rows, "item")}`}
            </Button>
            <Button
              onClick={() => {
                if (inputRef.current) inputRef.current.value = "";
                choose.current(null);
              }}
            >
              Choose another file
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
