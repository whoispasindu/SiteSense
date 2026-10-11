import { useEffect, useState, type SubmitEvent } from "react";

import {
  checkClaim,
  useClaims,
  useCreateClaim,
  useDecideClaim,
  useRecordPayment,
  type Claim,
  type ClaimCheck,
  type ClaimSection,
} from "../../api/contract";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { TextAreaField, TextField } from "../../components/ui/Field";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { ClaimCalculation, ClaimStatusBadge } from "../../features/contract/ContractBits";
import { paidText } from "../../features/contract/format";
import { KpiTile } from "../../features/projects/ProjectBits";
import { formatAmount, formatCompactLKR, toNumber } from "../../lib/money";
import { formatSiteDateTime, siteTodayIso } from "../../lib/time";
import { useDebounced } from "../../lib/useDebounced";
import { useCurrentProject } from "./projectContext";

const PCT = /^(100(\.0{1,2})?|\d{1,2}(\.\d{1,2})?)$/;

/** The QS's new claim: a certified % per section, checked against BR-08 as it is typed. */
function NewClaim({ projectId, sections, onDone }: { projectId: string; sections: ClaimSection[]; onDone: () => void }) {
  const create = useCreateClaim(projectId);
  const [pcts, setPcts] = useState<Record<string, string>>(() =>
    Object.fromEntries(sections.map((s) => [s.section_id, s.previous_pct])),
  );
  const [notes, setNotes] = useState("");
  const [check, setCheck] = useState<ClaimCheck | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const valid = sections.every((s) => PCT.test(pcts[s.section_id] ?? ""));
  const body = { sections: sections.map((s) => ({ section_id: s.section_id, certified_pct: pcts[s.section_id] ?? "0" })) };
  const settled = useDebounced(JSON.stringify(body), 350);

  useEffect(() => {
    if (!valid) return;
    const controller = new AbortController();
    checkClaim(projectId, JSON.parse(settled) as typeof body, controller.signal)
      .then((result) => {
        setCheck(result);
        setCheckError(null);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setCheckError(errorText(error));
      });
    return () => {
      controller.abort();
    };
    // `body` is rebuilt every render; the settled JSON is the real dependency.
  }, [projectId, settled, valid]);

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    create.mutate({ ...body, notes: notes.trim() || null }, { onSuccess: onDone });
  }

  const blocked = check !== null && check.problems.length > 0;
  return (
    <Sheet className="p-5">
      <form onSubmit={onSubmit} className="space-y-5" aria-labelledby="new-claim-heading">
        <div>
          <h3 id="new-claim-heading" className="text-base font-semibold text-ink">
            New progress claim
          </h3>
          <p className="mt-1 text-sm text-ink-faint">
            Certify the percentage complete in each section. It can stay the same as the last approved claim but never go
            below it. The amount is calculated (BR-08).
          </p>
        </div>
        <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Certified progress by BOQ section</caption>
              <thead className="text-xs whitespace-nowrap text-ink-faint">
                <tr className="border-b border-rule">
                  <th scope="col" className="py-2 pr-3 text-left font-medium">Section</th>
                  <th scope="col" className="hidden py-2 pr-3 text-right font-medium sm:table-cell">Contract value</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Last approved</th>
                  <th scope="col" className="py-2 text-right font-medium">Certified now</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {sections.map((s) => {
                  const value = pcts[s.section_id] ?? "";
                  const bad = !PCT.test(value) || toNumber(value) < toNumber(s.previous_pct);
                  return (
                    <tr key={s.section_id}>
                      <th scope="row" className="py-2 pr-3 text-left font-normal">
                        <span className="mr-2 font-mono text-xs text-ink-faint">{s.code}</span>
                        {s.name}
                      </th>
                      <td className="tabular hidden py-2 pr-3 text-right text-ink-soft sm:table-cell">
                        {formatCompactLKR(s.section_value)}
                      </td>
                      <td className="tabular py-2 pr-3 text-right text-ink-soft">{s.previous_pct}%</td>
                      <td className="py-2 text-right">
                        <label className="sr-only" htmlFor={`pct-${s.section_id}`}>
                          Certified % for {s.code} {s.name}
                        </label>
                        <span className="inline-flex items-center gap-1">
                          <input
                            id={`pct-${s.section_id}`}
                            value={value}
                            inputMode="decimal"
                            aria-invalid={bad}
                            onChange={(e) => {
                              setPcts((p) => ({ ...p, [s.section_id]: e.target.value }));
                            }}
                            className={`tabular w-20 rounded-md border bg-paper px-2 py-1.5 text-right text-ink ${bad ? "border-signal-high" : "border-rule-strong"}`}
                          />
                          <span className="text-ink-faint">%</span>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="space-y-3 rounded-lg border border-dashed border-rule-strong bg-paper-sunk/40 p-4">
            {!valid ? (
              <p className="text-sm text-signal-high">Each section needs a percentage from 0 to 100, up to two decimals.</p>
            ) : check ? (
              <ClaimCalculation figures={check.figures} caption="The claim as it will be submitted" />
            ) : (
              <p className="text-sm text-ink-faint">Calculating…</p>
            )}
            {checkError ? <Alert tone="error">{checkError}</Alert> : null}
            {blocked ? (
              <Alert tone="warn" title="This claim cannot be submitted">
                {check.problems.map((p) => p.message).join(" ")}
              </Alert>
            ) : null}
          </div>
        </div>
        <TextAreaField
          label="Notes (optional)"
          rows={2}
          maxLength={2000}
          value={notes}
          onChange={(e) => {
            setNotes(e.target.value);
          }}
        />
        {create.isError ? <Alert tone="error">{errorText(create.error)}</Alert> : null}
        <div className="flex flex-wrap justify-end gap-3">
          <Button onClick={onDone}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={!valid || blocked || check === null || create.isPending}>
            {create.isPending ? "Submitting…" : "Submit to the PM"}
          </Button>
        </div>
      </form>
    </Sheet>
  );
}

function ClaimActions({ projectId, claim }: { projectId: string; claim: Claim }) {
  const decide = useDecideClaim(projectId);
  const pay = useRecordPayment(projectId);
  const [mode, setMode] = useState<"return" | "pay" | null>(null);
  const [comment, setComment] = useState("");
  const [paidOn, setPaidOn] = useState(siteTodayIso());
  const error = decide.error ?? pay.error;
  if (claim.actions.length === 0) return null;

  return (
    <div className="space-y-3 border-t border-rule pt-4">
      {mode === "return" ? (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            decide.mutate({ id: claim.id, decision: "return", comment: comment.trim() });
          }}
        >
          <TextAreaField
            label="What should the QS change?"
            rows={2}
            required
            maxLength={1000}
            value={comment}
            onChange={(e) => {
              setComment(e.target.value);
            }}
          />
          <div className="flex justify-end gap-2">
            <Button onClick={() => { setMode(null); }}>Cancel</Button>
            <Button type="submit" variant="danger" disabled={!comment.trim() || decide.isPending}>
              Return to the QS
            </Button>
          </div>
        </form>
      ) : mode === "pay" ? (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            pay.mutate({ id: claim.id, paid_on: paidOn });
          }}
        >
          <TextField
            label="Paid on"
            type="date"
            max={siteTodayIso()}
            required
            value={paidOn}
            onChange={(e) => {
              setPaidOn(e.target.value);
            }}
          />
          <Button onClick={() => { setMode(null); }}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={pay.isPending}>
            Record payment
          </Button>
        </form>
      ) : (
        <div className="flex flex-wrap justify-end gap-2">
          {claim.actions.includes("return") ? <Button onClick={() => { setMode("return"); }}>Return…</Button> : null}
          {claim.actions.includes("approve") ? (
            <Button
              variant="primary"
              disabled={decide.isPending}
              onClick={() => {
                decide.mutate({ id: claim.id, decision: "approve" });
              }}
            >
              Approve claim
            </Button>
          ) : null}
          {claim.actions.includes("record_payment") ? (
            <Button variant="primary" onClick={() => { setMode("pay"); }}>
              Record payment…
            </Button>
          ) : null}
        </div>
      )}
      {error ? <Alert tone="error">{errorText(error)}</Alert> : null}
    </div>
  );
}

function ClaimCard({ projectId, claim }: { projectId: string; claim: Claim }) {
  const [open, setOpen] = useState(claim.status === "submitted");
  return (
    <Sheet as="article" className="p-5" aria-labelledby={`claim-${claim.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={`claim-${claim.id}`} className="flex flex-wrap items-center gap-3 text-base font-semibold text-ink">
            <span className="font-mono">{claim.number}</span>
            <ClaimStatusBadge status={claim.status} />
          </h3>
          <p className="mt-1 text-sm text-ink-faint">
            {claim.submitted_by}, {formatSiteDateTime(claim.submitted_at)} · certified {claim.figures.certified_pct}% ·{" "}
            {claim.status === "paid" || claim.status === "approved" ? paidText(claim.paid_on) : "not yet approved"}
          </p>
        </div>
        <p className="tabular text-right text-xl font-semibold text-ink" title={`LKR ${formatAmount(claim.figures.amount)}`}>
          {formatCompactLKR(claim.figures.amount)}
          <span className="block text-xs font-normal text-ink-faint">after retention</span>
        </p>
      </div>
      {claim.decision_comment ? (
        <p className="mt-3 rounded-md bg-paper-sunk px-3 py-2 text-sm text-ink-soft">
          {claim.decided_by}: “{claim.decision_comment}”
        </p>
      ) : null}
      <button
        type="button"
        aria-expanded={open}
        className="mt-3 text-sm font-medium text-survey hover:underline"
        onClick={() => {
          setOpen((o) => !o);
        }}
      >
        {open ? "Hide the calculation" : "Show the calculation"}
      </button>
      {open ? (
        <div className="mt-3 grid gap-6 lg:grid-cols-2">
          <ClaimCalculation figures={claim.figures} caption={`Calculation of ${claim.number}`} />
          <table className="w-full text-sm">
            <caption className="sr-only">Certified progress by section for {claim.number}</caption>
            <thead className="text-xs text-ink-faint">
              <tr className="border-b border-rule">
                <th scope="col" className="py-2 text-left font-medium">Section</th>
                <th scope="col" className="py-2 text-right font-medium">Before</th>
                <th scope="col" className="py-2 text-right font-medium">Certified</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {claim.lines.map((line) => (
                <tr key={line.section_id}>
                  <th scope="row" className="py-1.5 text-left font-normal text-ink-soft">
                    <span className="mr-2 font-mono text-xs text-ink-faint">{line.code}</span>
                    {line.name}
                  </th>
                  <td className="tabular py-1.5 text-right text-ink-faint">{line.previous_pct}%</td>
                  <td className="tabular py-1.5 text-right text-ink">{line.certified_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="mt-4">
        <ClaimActions projectId={projectId} claim={claim} />
      </div>
    </Sheet>
  );
}

export function ProjectClaims() {
  const project = useCurrentProject();
  const claims = useClaims(project.id);
  const [creating, setCreating] = useState(false);

  if (claims.isPending) return <p className="text-sm text-ink-faint">Loading claims…</p>;
  if (claims.isError) return <Alert tone="error">{errorText(claims.error)}</Alert>;
  const data = claims.data;
  const waiting = data.claims.find((c) => c.status === "submitted");

  return (
    <div className="space-y-8">
      <div className="grid gap-4 sm:grid-cols-3">
        <KpiTile icon="cost" label="Claimed to date" value={formatCompactLKR(data.claimed_to_date)} note="Approved claims, after retention" />
        <KpiTile icon="materials" label="Retention held" value={formatCompactLKR(data.retention_held)} note="5% of certified work (BR-08)" />
        <KpiTile icon="reports" label="Paid to date" value={formatCompactLKR(data.paid_to_date)} note="Claims marked paid by the QS" />
      </div>

      <section aria-labelledby="claims-heading" className="space-y-4">
        <SectionHeading
          id="claims-heading"
          annotation="the QS certifies, the PM approves, the client is shown approved claims"
          action={
            data.can_create && !creating ? (
              <Button variant="primary" onClick={() => { setCreating(true); }}>
                New claim
              </Button>
            ) : null
          }
        >
          Progress claims
        </SectionHeading>
        {waiting && !data.can_create && data.claims.length > 0 && waiting.actions.length === 0 ? (
          <Alert tone="info">
            {waiting.number} is waiting for the project manager. A new claim can be made once it is decided.
          </Alert>
        ) : null}
        {creating ? (
          <NewClaim projectId={project.id} sections={data.sections} onDone={() => { setCreating(false); }} />
        ) : null}
        {data.claims.length === 0 && !creating ? (
          <Sheet className="p-8 text-center text-sm text-ink-faint">No claims yet on {project.code}.</Sheet>
        ) : null}
        {data.claims.map((claim) => (
          <ClaimCard key={claim.id} projectId={project.id} claim={claim} />
        ))}
      </section>
    </div>
  );
}
