import { useState } from "react";

import type { AdminUser } from "../../api/admin";
import { Button } from "../../components/ui/Button";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { userStatus } from "./adminUtils";

export function UserStatus({ user }: { user: AdminUser }) {
  const { tone, label } = userStatus(user);
  return <StatusBadge tone={tone} label={label} />;
}

/** Shows a one-time password exactly once, with a copy button and a clear warning. */
export function TemporaryPassword({ password, name, onDone }: { password: string; name: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="space-y-5">
      <p className="text-sm text-ink-soft">
        Give this temporary password to <strong className="text-ink">{name}</strong> in person or by phone. They will
        be asked to replace it at first sign-in.
      </p>
      <div className="rounded-[var(--radius-sheet)] border-2 border-dashed border-ink bg-paper-sunk px-4 py-4">
        <p className="font-mono text-[0.65rem] tracking-[0.18em] text-ink-faint uppercase">Temporary password</p>
        <p className="tabular mt-1 font-mono text-xl font-medium break-all select-all" data-testid="temporary-password">
          {password}
        </p>
      </div>
      <p className="font-wide text-[0.68rem] font-bold tracking-[0.14em] text-signal-medium uppercase">
        Shown once. It cannot be displayed again.
      </p>
      <div className="flex flex-wrap gap-3">
        <Button
          onClick={() => {
            void navigator.clipboard.writeText(password).then(() => {
              setCopied(true);
            });
          }}
        >
          {copied ? "Copied" : "Copy password"}
        </Button>
        <Button variant="primary" onClick={onDone}>
          Done
        </Button>
      </div>
    </div>
  );
}

export function SiteCheckboxes({
  sites,
  selected,
  onChange,
}: {
  sites: { id: string; code: string; name: string; is_active: boolean }[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const active = sites.filter((s) => s.is_active || selected.includes(s.id));
  if (active.length === 0) {
    return <p className="text-sm text-ink-faint">No sites yet. Add one on the Sites page first.</p>;
  }
  return (
    <fieldset>
      <legend className="font-mono text-[0.7rem] tracking-[0.14em] text-ink-soft uppercase">Assigned sites</legend>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {active.map((site) => {
          const checked = selected.includes(site.id);
          return (
            <label
              key={site.id}
              className={`flex min-h-11 cursor-pointer items-center gap-3 rounded-[var(--radius-sheet)] border-2 px-3 text-sm ${
                checked ? "border-ink bg-hivis/15" : "border-rule hover:border-rule-strong"
              }`}
            >
              <input
                type="checkbox"
                className="size-4 accent-[var(--color-ink)]"
                checked={checked}
                onChange={(e) => {
                  onChange(e.target.checked ? [...selected, site.id] : selected.filter((id) => id !== site.id));
                }}
              />
              <span className="shrink-0 font-mono text-xs whitespace-nowrap">{site.code}</span>
              <span className="truncate text-ink-soft">{site.name}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
