import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { useRaiseVariation, useVariations } from "../../api/contract";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { VariationStatusBadge } from "../../features/contract/ContractBits";
import { daysText, signedMoney } from "../../features/contract/format";
import { VariationForm } from "../../features/contract/VariationForm";
import { KpiTile } from "../../features/projects/ProjectBits";
import { formatCompactMoney, formatMoney, toNumber } from "../../lib/money";
import { formatSiteDateTime } from "../../lib/time";
import { useCurrentProject } from "./projectContext";

/** "+ LKR 850 k", "− LKR 1.2 M" (in the company's currency) or "None". */
function changeCompact(value: string): string {
  const n = toNumber(value);
  if (n === 0) return "None";
  return `${n > 0 ? "+" : "−"} ${formatCompactMoney(Math.abs(n))}`;
}

export function ProjectVariations() {
  const project = useCurrentProject();
  const variations = useVariations(project.id);
  const raise = useRaiseVariation(project.id);
  const navigate = useNavigate();
  const [raising, setRaising] = useState(false);

  if (variations.isPending) return <p className="text-sm text-ink-faint">Loading variations…</p>;
  if (variations.isError) return <Alert tone="error">{errorText(variations.error)}</Alert>;
  const data = variations.data;
  const open = data.variations.filter((v) => !["approved", "rejected", "withdrawn"].includes(v.status)).length;

  return (
    <div className="space-y-8">
      <div className="grid gap-4 sm:grid-cols-3">
        <KpiTile
          icon="cost"
          label="Approved changes"
          value={changeCompact(data.approved_contract_change)}
          title={formatMoney(data.approved_contract_change)}
          note={daysText(data.approved_time_impact_days)}
        />
        <KpiTile icon="schedule" label="Open" value={String(open)} note="To price, or waiting for a decision" />
        <KpiTile
          icon="client"
          label="Client approval limit"
          value={formatCompactMoney(data.limit)}
          title={formatMoney(data.limit)}
          note="BR-09; set by the Company Admin"
        />
      </div>

      <section aria-labelledby="variations-heading" className="space-y-4">
        <SectionHeading
          id="variations-heading"
          annotation="the QS prices every variation; BR-09 decides who approves"
          action={
            <Button variant="primary" onClick={() => { setRaising(true); }}>
              Raise a variation
            </Button>
          }
        >
          Variation orders
        </SectionHeading>
        {data.variations.length === 0 ? (
          <Sheet className="p-8 text-center text-sm text-ink-faint">No variations on {project.code} yet.</Sheet>
        ) : (
          <Sheet className="divide-y divide-rule">
            {data.variations.map((v) => (
              <article key={v.id} className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-4">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-3">
                    <span className="font-mono text-sm text-ink-faint">{v.number}</span>
                    <Link to={`/variations/${v.id}`} className="font-medium text-ink hover:underline">
                      {v.title}
                    </Link>
                  </p>
                  <p className="mt-0.5 text-sm text-ink-faint">
                    {v.section} · raised by {v.raised_by}, {formatSiteDateTime(v.raised_at)}
                  </p>
                </div>
                <div className="tabular text-right text-sm">
                  <p className="text-ink">{signedMoney(v.contract_change)}</p>
                  <p className="text-ink-faint">{daysText(v.time_impact_days)}</p>
                </div>
                <VariationStatusBadge status={v.status} />
              </article>
            ))}
          </Sheet>
        )}
      </section>

      <Dialog
        open={raising}
        title="Raise a variation"
        onClose={() => {
          setRaising(false);
          raise.reset();
        }}
      >
        <VariationForm
          projectId={project.id}
          limit={data.limit}
          submitLabel="Raise variation"
          busy={raise.isPending}
          error={raise.isError ? errorText(raise.error) : null}
          onCancel={() => {
            setRaising(false);
          }}
          onSubmit={(input) => {
            raise.mutate(input, {
              onSuccess: (created) => {
                setRaising(false);
                void navigate(`/variations/${created.id}`);
              },
            });
          }}
        />
      </Dialog>
    </div>
  );
}
