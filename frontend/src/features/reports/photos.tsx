import { useEffect, useState } from "react";

import { usePhotoUrl, type Photo } from "../../api/reports";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { Icon } from "../../components/ui/icons";
import { blobToDataUrl } from "../../lib/files";
import { ACCEPTED_TYPES, type PendingPhoto } from "./images";


/** A local file as a data: URL for previews (nothing to revoke, works under the strict CSP). */
function useDataUrl(blob: Blob): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void blobToDataUrl(blob).then((next) => {
      if (!cancelled) setUrl(next);
    });
    return () => {
      cancelled = true;
    };
  }, [blob]);
  return url;
}

/** A stored site photo. Fetched with the user's session; never a public link. */
export function StoredPhoto({ photo, size, className = "" }: { photo: Photo; size: "full" | "thumb"; className?: string }) {
  const query = usePhotoUrl(photo.id, size);
  const url = query.data;
  const alt = photo.caption ?? "Site photo";

  if (query.isError) {
    return (
      <div className={`grid place-items-center bg-paper-sunk text-xs text-ink-faint ${className}`} role="img" aria-label={`${alt} (could not load)`}>
        Could not load
      </div>
    );
  }
  if (!url) return <div className={`animate-pulse bg-paper-sunk ${className}`} role="img" aria-label={`${alt} (loading)`} />;
  return <img src={url} alt={alt} className={`object-cover ${className}`} />;
}

export function PhotoGrid({
  photos,
  onDelete,
  deleting,
}: {
  photos: Photo[];
  onDelete?: ((photo: Photo) => void) | undefined;
  deleting?: boolean;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const current = open === null ? undefined : photos[open];

  return (
    <>
      <ul aria-label="Site photos" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {photos.map((photo, index) => (
          <li key={photo.id} className="group relative overflow-hidden rounded-lg border border-rule bg-paper-raised">
            <button
              type="button"
              onClick={() => {
                setOpen(index);
              }}
              className="block w-full text-left"
              aria-label={`Open photo ${String(index + 1)}${photo.caption ? `: ${photo.caption}` : ""}`}
            >
              <StoredPhoto photo={photo} size="thumb" className="aspect-[4/3] w-full" />
              {photo.caption ? <p className="truncate px-3 py-2 text-sm text-ink-soft">{photo.caption}</p> : null}
            </button>
            {onDelete ? (
              <button
                type="button"
                disabled={deleting}
                onClick={() => {
                  onDelete(photo);
                }}
                aria-label={`Remove photo ${String(index + 1)}`}
                className="absolute top-2 right-2 grid size-9 place-items-center rounded-full bg-black/60 text-white hover:bg-black/80 disabled:opacity-50"
              >
                <Icon name="trash" className="size-4" />
              </button>
            ) : null}
          </li>
        ))}
      </ul>

      <Dialog
        open={current !== undefined}
        onClose={() => {
          setOpen(null);
        }}
        title={open === null ? "Photo" : `Photo ${String(open + 1)} of ${String(photos.length)}`}
      >
        {current ? (
          <div className="space-y-3">
            <StoredPhoto photo={current} size="full" className="max-h-[60dvh] w-full rounded-lg object-contain" />
            {current.caption ? <p className="text-sm text-ink-soft">{current.caption}</p> : null}
            <div className="flex justify-between gap-3">
              <Button
                disabled={open === 0}
                onClick={() => {
                  setOpen((i) => (i === null ? null : Math.max(0, i - 1)));
                }}
              >
                Previous
              </Button>
              <Button
                disabled={open === photos.length - 1}
                onClick={() => {
                  setOpen((i) => (i === null ? null : Math.min(photos.length - 1, i + 1)));
                }}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </>
  );
}

function PendingPreview({ item }: { item: PendingPhoto }) {
  const url = useDataUrl(item.file);
  return url ? (
    <img src={url} alt="" className="aspect-[4/3] w-full object-cover" />
  ) : (
    <div className="aspect-[4/3] w-full bg-paper-sunk" />
  );
}

/** Photos chosen on the form, with captions, before they are uploaded. */
export function PhotoPicker({
  items,
  limit,
  onChange,
  disabled,
}: {
  items: PendingPhoto[];
  limit: number;
  onChange: (next: PendingPhoto[]) => void;
  disabled?: boolean;
}) {
  const remaining = limit - items.length;
  return (
    <div className="space-y-3">
      {items.length > 0 ? (
        <ul aria-label="Photos to upload" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {items.map((item, index) => (
            <li key={item.key} className="overflow-hidden rounded-lg border border-rule bg-paper-raised">
              <PendingPreview item={item} />
              <div className="flex items-center gap-1 p-2">
                <label className="sr-only" htmlFor={`caption-${item.key}`}>
                  Caption for photo {index + 1}
                </label>
                <input
                  id={`caption-${item.key}`}
                  value={item.caption}
                  maxLength={200}
                  placeholder="Caption (optional)"
                  disabled={disabled}
                  onChange={(e) => {
                    onChange(items.map((p) => (p.key === item.key ? { ...p, caption: e.target.value } : p)));
                  }}
                  className="min-h-9 w-full min-w-0 rounded-md border border-rule bg-paper-raised px-2 text-sm text-ink placeholder:text-ink-faint focus:border-survey focus:outline-none"
                />
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    onChange(items.filter((p) => p.key !== item.key));
                  }}
                  aria-label={`Remove photo ${String(index + 1)}`}
                  className="grid size-9 shrink-0 place-items-center rounded-md text-ink-soft hover:bg-paper-sunk hover:text-signal-high"
                >
                  <Icon name="trash" className="size-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      <label
        className={`flex min-h-14 cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-3 text-sm font-medium transition-colors focus-within:border-survey ${
          remaining <= 0 || disabled
            ? "cursor-not-allowed border-rule text-ink-faint"
            : "border-rule-strong text-ink-soft hover:border-accent-line hover:text-ink"
        }`}
      >
        <Icon name="camera" className="size-5" />
        {remaining <= 0 ? "Photo limit reached" : `Add photos (${String(remaining)} left)`}
        <input
          type="file"
          accept={ACCEPTED_TYPES}
          multiple
          disabled={remaining <= 0 || disabled}
          className="sr-only"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []).slice(0, Math.max(0, remaining));
            onChange([
              ...items,
              ...files.map((file) => ({ key: crypto.randomUUID(), file, caption: "" })),
            ]);
            e.target.value = "";
          }}
        />
      </label>
      <p className="text-xs text-ink-faint">
        JPEG, PNG or WebP. Location data is removed before saving. Photograph the work, not people: avoid faces where
        you can.
      </p>
    </div>
  );
}
