import { useEffect, useId, useRef, type ReactNode } from "react";

import { Icon } from "./icons";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

/**
 * Modal built on the native <dialog>: focus trap, Escape to close and an inert page behind it
 * come from the browser, not from custom code.
 */
export function Dialog({ open, onClose, title, children }: DialogProps) {
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
      className="m-auto w-[min(34rem,calc(100vw-2rem))] max-w-none rounded-xl border border-rule bg-paper-raised p-0 text-ink shadow-[var(--shadow-pop)] backdrop:bg-black/50 backdrop:backdrop-blur-[2px]"
    >
      {open ? (
        <>
          <div className="flex items-center justify-between gap-4 border-b border-rule px-6 py-4">
            <h2 id={titleId} className="text-base font-semibold text-ink">
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close dialog"
              className="-mr-2 inline-flex size-9 items-center justify-center rounded-lg text-ink-soft hover:bg-paper-sunk hover:text-ink"
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="max-h-[75dvh] overflow-y-auto px-6 py-5">{children}</div>
        </>
      ) : null}
    </dialog>
  );
}
