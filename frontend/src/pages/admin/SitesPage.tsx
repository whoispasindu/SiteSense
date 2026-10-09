import { useState, type SubmitEvent } from "react";
import { z } from "zod";

import { useCreateSite, useSites, useUpdateSite } from "../../api/admin";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { TextField } from "../../components/ui/Field";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { errorText } from "../../features/admin/adminUtils";

const optionalNumber = (min: number, max: number, label: string) =>
  z
    .string()
    .trim()
    .transform((v) => (v === "" ? null : Number(v)))
    .refine((v) => v === null || (Number.isFinite(v) && v >= min && v <= max), `${label} must be between ${String(min)} and ${String(max)}.`);

const siteFormSchema = z.object({
  code: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^[A-Z0-9][A-Z0-9-]{1,15}$/, "2–16 letters, digits or dashes, e.g. COL-07."),
  name: z.string().trim().min(2, "Enter the site name.").max(120),
  location: z.string().trim().min(2, "Enter the town or district.").max(120),
  latitude: optionalNumber(-90, 90, "Latitude"),
  longitude: optionalNumber(-180, 180, "Longitude"),
});

type Field = "code" | "name" | "location" | "latitude" | "longitude";

function NewSiteDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const createSite = useCreateSite();
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});

  function close() {
    setErrors({});
    createSite.reset();
    onClose();
  }

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    const parsed = siteFormSchema.safeParse(form);
    if (!parsed.success) {
      const next: Partial<Record<Field, string>> = {};
      for (const issue of parsed.error.issues) {
        const field = issue.path[0] as Field;
        next[field] ??= issue.message;
      }
      setErrors(next);
      return;
    }
    setErrors({});
    createSite.mutate(parsed.data, { onSuccess: close });
  }

  return (
    <Dialog open={open} onClose={close} title="Add a site" code="S-NEW">
      <form noValidate onSubmit={onSubmit} className="space-y-5">
        {createSite.isError ? <Alert tone="error">{errorText(createSite.error)}</Alert> : null}
        <div className="grid gap-5 sm:grid-cols-[9rem_1fr]">
          <TextField label="Code" name="code" placeholder="COL-07" autoComplete="off" className="font-mono uppercase" error={errors.code} />
          <TextField label="Site name" name="name" placeholder="Havelock Residences" autoComplete="off" error={errors.name} />
        </div>
        <TextField label="Location" name="location" placeholder="Colombo 05" autoComplete="off" error={errors.location} />
        <div className="grid gap-5 sm:grid-cols-2">
          <TextField label="Latitude" name="latitude" inputMode="decimal" placeholder="6.8836" error={errors.latitude} />
          <TextField label="Longitude" name="longitude" inputMode="decimal" placeholder="79.8650" error={errors.longitude} />
        </div>
        <p className="text-xs text-ink-faint">Coordinates are optional now; the weather forecast (Phase 4) uses them.</p>
        <div className="flex justify-end gap-3 border-t border-dashed border-rule pt-4">
          <Button onClick={close}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={createSite.isPending}>
            {createSite.isPending ? "Saving…" : "Add site"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function SitesPage() {
  const sites = useSites();
  const updateSite = useUpdateSite();
  const [creating, setCreating] = useState(false);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHeader
        sheet="A-02"
        title="Sites"
        description="Every construction site the company runs. Site engineers, QS, project managers and clients only see the sites they are assigned to."
        action={
          <Button
            variant="primary"
            onClick={() => {
              setCreating(true);
            }}
          >
            Add site
          </Button>
        }
      />

      {sites.isError ? <Alert tone="error">{errorText(sites.error)}</Alert> : null}
      {updateSite.isError ? <Alert tone="error">{errorText(updateSite.error)}</Alert> : null}

      {sites.data && sites.data.length === 0 ? (
        <Sheet className="px-6 py-12 text-center">
          <p className="font-wide text-lg font-bold">No sites yet</p>
          <p className="mt-2 text-ink-soft">Add your first site so you can assign people to it.</p>
        </Sheet>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {(sites.data ?? []).map((site) => (
            <li key={site.id}>
              <Sheet as="article" sheetCode={site.code} className={`flex h-full flex-col p-5 ${site.is_active ? "" : "opacity-70"}`}>
                <h2 className="pr-16 text-lg leading-snug font-semibold">{site.name}</h2>
                <p className="mt-1 text-sm text-ink-soft">{site.location}</p>
                <p className="tabular mt-3 font-mono text-xs text-ink-faint">
                  {site.latitude !== null && site.longitude !== null
                    ? `${site.latitude.toFixed(4)}°, ${site.longitude.toFixed(4)}°`
                    : "No coordinates"}
                </p>
                <div className="mt-auto flex items-center justify-between gap-3 border-t border-dashed border-rule pt-4">
                  <StatusBadge tone={site.is_active ? "ok" : "idle"} label={site.is_active ? "Active" : "Closed"} />
                  <Button
                    variant="ghost"
                    disabled={updateSite.isPending}
                    onClick={() => {
                      updateSite.mutate({ id: site.id, is_active: !site.is_active });
                    }}
                  >
                    {site.is_active ? "Close site" : "Reopen"}
                  </Button>
                </div>
              </Sheet>
            </li>
          ))}
        </ul>
      )}

      <NewSiteDialog
        open={creating}
        onClose={() => {
          setCreating(false);
        }}
      />
    </div>
  );
}
