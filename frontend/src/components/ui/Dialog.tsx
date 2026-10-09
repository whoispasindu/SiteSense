import { useEffect, useId, useRef, type ReactNode } from "react";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Short mono reference printed in the header, like a drawing sheet. */
  code?: string;
  children: ReactNode;
}

/**
 * Modal built on the native <dialog>: focus trap, Escape to close and an inert page behind it
 * come from the browser, not from custom code.
 */
export function Dialog({ open, onClose, title, code, children }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      className="m-auto w-[min(34rem,calc(100vw-2rem))] max-w-none rounded-[var(--radius-sheet)] border border-rule bg-paper-raised p-0 text-ink shadow-[var(--shadow-sheet)] backdrop:bg-asphalt/55"
    >
      {open ? (
        <>
          <div className="flex items-center justify-between gap-4 border-b-2 border-ink px-5 py-3">
            <h2 id={titleId} className="font-wide text-sm font-extrabold tracking-[0.12em] uppercase">
              {title}
            </h2>
            <div className="flex items-center gap-3">
              {code ? <span className="font-mono text-[0.65rem] text-ink-faint">{code}</span> : null}
              <button
                type="button"
                onClick={onClose}
                aria-label="Close dialog"
                className="inline-flex size-9 items-center justify-center rounded-[2px] text-ink-soft hover:bg-paper-sunk hover:text-ink"
              >
                <svg viewBox="0 0 24 24" className="size-4" aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" />
                </svg>
              </button>
            </div>
          </div>
          <div className="max-h-[75dvh] overflow-y-auto px-5 py-5">{children}</div>
        </>
      ) : null}
    </dialog>
  );
}
