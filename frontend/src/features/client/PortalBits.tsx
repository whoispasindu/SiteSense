import { useState } from "react";

import { useClientClaims, useClientPhoto, type ClientPhoto, type ClientProject } from "../../api/portal";
import { Alert } from "../../components/ui/Alert";
import { Dialog } from "../../components/ui/Dialog";
import { Icon } from "../../components/ui/icons";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { formatAmount, formatCompactMoney } from "../../lib/money";
import { formatSiteDateTime } from "../../lib/time";
import { errorText } from "../admin/adminUtils";
import { formatDate } from "../projects/dates";
import { againstContract, MILESTONE_LABELS, MILESTONE_TONES } from "./portal";
import { currencyCode } from "../../lib/locale";

/** The one handover date the client sees: published by the project manager, with the reason. */
export function HandoverCard({ project }: { project: ClientProject }) {
  const h = project.handover;
  const published = h.published_date;
  return (
    <section aria-labelledby="handover-title" className="relative overflow-hidden rounded-[var(--radius-sheet)] bg-asphalt p-6 text-asphalt-text">
      <span aria-hidden="true" className="hazard-band absolute inset-x-0 top-0 h-1" />
      <p id="handover-title" className="text-sm font-medium text-asphalt-muted">
        {published ? "Expected handover" : "Contract handover"}
      </p>
      <p className="tabular mt-1 text-[2rem] leading-tight font-semibold tracking-tight text-white">
        {formatDate(published ?? h.contract_end)}
      </p>
      {published ? (
        <>
          <p className="mt-1 text-sm text-asphalt-muted">
            {againstContract(published, h.contract_end)} ({formatDate(h.contract_end)})
          </p>
          {h.reason ? (
            <blockquote className="mt-4 border-l-2 border-hivis pl-3 text-[0.9375rem] text-asphalt-text">{h.reason}</blockquote>
          ) : null}
          {h.published_at ? <p className="mt-3 text-xs text-asphalt-muted">Updated {formatSiteDateTime(h.published_at)} by your project manager.</p> : null}
        </>
      ) : (
        <p className="mt-2 text-sm text-asphalt-muted">
          The date in your contract. Your project manager will publish an expected date with the reason when it is reviewed.
        </p>
      )}
      {h.history.length > 0 ? (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer font-medium text-hivis hover:underline">Earlier dates ({h.history.length})</summary>
          <ol className="mt-2 space-y-2 border-l border-asphalt-line pl-3">
            {h.history.map((change) => (
              <li key={change.published_at}>
                <p className="tabular font-medium text-white">{formatDate(change.handover_date)}</p>
                <p className="text-asphalt-muted">{change.reason}</p>
                <p className="text-xs text-asphalt-muted">Published {formatSiteDateTime(change.published_at)}</p>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  );
}

/** Milestones in order: a drawing-office line with a node for each, status in words. */
export function MilestoneTrack({ milestones }: { milestones: ClientProject["milestones"] }) {
  return (
    <Sheet className="p-5">
      <SectionHeading annotation="flagged by your project manager">Milestones</SectionHeading>
      {milestones.length === 0 ? (
        <p className="py-4 text-sm text-ink-soft">No milestones have been set out yet.</p>
      ) : (
        <ol aria-label="Milestones" className="relative mt-2 space-y-5 pl-7 before:absolute before:top-2 before:bottom-2 before:left-[0.4375rem] before:w-px before:bg-rule-strong">
          {milestones.map((m) => {
            const done = m.status === "done";
            return (
              <li key={`${m.name}-${m.planned_date}`} className="relative">
                <span
                  aria-hidden="true"
                  className={`absolute top-1 -left-7 grid size-[0.9375rem] place-items-center rounded-full border-2 ${
                    done ? "border-signal-low bg-signal-low" : m.status === "late" ? "border-signal-medium bg-paper-raised" : "border-rule-strong bg-paper-raised"
                  }`}
                >
                  {done ? <span className="size-1.5 rounded-full bg-paper-raised" /> : null}
                </span>
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <p className="font-medium text-ink">{m.name}</p>
                  <StatusBadge tone={MILESTONE_TONES[m.status]} label={MILESTONE_LABELS[m.status]} />
                </div>
                <p className="tabular mt-0.5 text-sm text-ink-soft">
                  {done && m.completed_on ? (
                    <>Completed {formatDate(m.completed_on)} · planned {formatDate(m.planned_date)}</>
                  ) : (
                    <>
                      Expected {formatDate(m.expected_date)} · planned {formatDate(m.planned_date)} · {Math.round(m.percent_complete)}% done
                    </>
                  )}
                </p>
              </li>
            );
          })}
        </ol>
      )}
    </Sheet>
  );
}

function Thumb({ photo, onOpen }: { photo: ClientPhoto; onOpen: () => void }) {
  const image = useClientPhoto(photo.id, "thumb");
  const label = photo.caption ?? "Site photo";
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group block w-full overflow-hidden rounded-lg border border-rule bg-paper-sunk text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-survey"
    >
      <span className="block aspect-[4/3] overflow-hidden">
        {image.data ? (
          <img src={image.data} alt={label} className="size-full object-cover transition-transform group-hover:scale-[1.02]" />
        ) : (
          <span className="grid size-full place-items-center text-xs text-ink-faint">{image.isError ? "Could not load" : "Loading…"}</span>
        )}
      </span>
      <span className="block px-3 py-2">
        <span className="line-clamp-1 block text-sm font-medium text-ink">{label}</span>
        <span className="block text-xs text-ink-faint">{formatDate(photo.taken_on)}</span>
      </span>
    </button>
  );
}

function FullPhoto({ photo }: { photo: ClientPhoto }) {
  const image = useClientPhoto(photo.id, "full");
  if (image.isError) return <Alert tone="error">{errorText(image.error)}</Alert>;
  return image.data ? (
    <img src={image.data} alt={photo.caption ?? "Site photo"} className="max-h-[70vh] w-full rounded-lg object-contain" />
  ) : (
    <p className="py-16 text-center text-sm text-ink-faint">Loading…</p>
  );
}

/** Photos the project manager chose to share, newest first. */
export function PhotoGallery({ photos }: { photos: ClientPhoto[] }) {
  const [open, setOpen] = useState<ClientPhoto | null>(null);
  return (
    <Sheet className="p-5">
      <SectionHeading annotation="shared by your project manager">Site photos</SectionHeading>
      {photos.length === 0 ? (
        <p className="py-4 text-sm text-ink-soft">No photos have been shared yet.</p>
      ) : (
        <ul aria-label="Site photos" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {photos.map((photo) => (
            <li key={photo.id}>
              <Thumb
                photo={photo}
                onOpen={() => {
                  setOpen(photo);
                }}
              />
            </li>
          ))}
        </ul>
      )}
      <Dialog
        open={open !== null}
        onClose={() => {
          setOpen(null);
        }}
        title={open ? `${open.caption ?? "Site photo"}, ${formatDate(open.taken_on)}` : "Site photo"}
      >
        {open ? <FullPhoto photo={open} /> : null}
      </Dialog>
    </Sheet>
  );
}

/** Approved and paid claims, the contract value, and the retention held so far. */
export function Payments({ projectId }: { projectId: string }) {
  const claims = useClientClaims(projectId);
  if (claims.isPending) return <Sheet className="p-5 text-sm text-ink-faint">Loading payments…</Sheet>;
  if (claims.isError) return <Alert tone="error">{errorText(claims.error)}</Alert>;
  const c = claims.data;
  const varied = Number(c.approved_variations) !== 0;

  return (
    <Sheet className="p-5">
      <SectionHeading annotation={`${currencyCode()}, approved by your project manager`}>Payments</SectionHeading>
      <dl className="grid gap-4 border-b border-rule pb-5 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-xs text-ink-faint">Contract value</dt>
          <dd className="tabular text-lg font-semibold text-ink">{formatCompactMoney(c.contract_value)}</dd>
          <dd className="text-xs text-ink-faint">
            {varied
              ? `${formatCompactMoney(c.original_contract_value)} plus ${formatCompactMoney(c.approved_variations)} of approved variations`
              : "No approved variations"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-faint">Claimed to date</dt>
          <dd className="tabular text-lg font-semibold text-ink">{formatCompactMoney(c.claimed_to_date)}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-faint">Paid to date</dt>
          <dd className="tabular text-lg font-semibold text-ink">{formatCompactMoney(c.paid_to_date)}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-faint">Retention held</dt>
          <dd className="tabular text-lg font-semibold text-ink">{formatCompactMoney(c.retention_held)}</dd>
          <dd className="text-xs text-ink-soft">Due back around {formatDate(c.retention_release.expected_on)}</dd>
          <dd className="text-xs text-ink-faint">{c.retention_note}</dd>
        </div>
      </dl>
      {c.claims.length === 0 ? (
        <p className="pt-4 text-sm text-ink-soft">No progress claims have been approved yet.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm">
            <caption className="sr-only">Approved progress claims, newest first, in {currencyCode()}</caption>
            <thead className="text-left text-xs text-ink-faint">
              <tr className="border-b border-rule">
                <th scope="col" className="py-2 pr-3 font-medium">Claim</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Certified</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Certified value</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Retention held</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Previous claims</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Due this claim</th>
                <th scope="col" className="py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="tabular divide-y divide-rule">
              {c.claims.map((claim) => (
                <tr key={claim.number}>
                  <th scope="row" className="py-2.5 pr-3 text-left font-mono font-medium text-ink">
                    {claim.number}
                    <span className="block font-sans text-xs font-normal text-ink-faint">Approved {formatDate(claim.approved_on)}</span>
                  </th>
                  <td className="py-2.5 pr-3 text-right">{Number(claim.certified_pct).toFixed(2)}%</td>
                  <td className="py-2.5 pr-3 text-right">{formatAmount(claim.certified_value)}</td>
                  <td className="py-2.5 pr-3 text-right">{formatAmount(claim.retention)}</td>
                  <td className="py-2.5 pr-3 text-right">{formatAmount(claim.previous_claims)}</td>
                  <td className="py-2.5 pr-3 text-right font-semibold text-ink">{formatAmount(claim.amount)}</td>
                  <td className="py-2.5">
                    {claim.paid_on ? (
                      <span className="inline-flex items-center gap-1.5 text-signal-low">
                        <Icon name="audit" className="size-4" /> Paid {formatDate(claim.paid_on)}
                      </span>
                    ) : (
                      <span className="text-ink-soft">Approved, awaiting payment</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Sheet>
  );
}
