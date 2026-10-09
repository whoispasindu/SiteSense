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
      <div className="rounded-lg border border-hivis/60 bg-hivis/10 px-4 py-4">
        <p className="text-sm font-medium text-ink-soft">Temporary password</p>
        <p className="mt-1 font-mono text-xl font-medium break-all text-ink select-all" data-testid="temporary-password">
          {password}
        </p>
      </div>
      <p className="text-sm font-medium text-signal-medium">
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
      <legend className="text-sm font-medium text-ink">Assigned sites</legend>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {active.map((site) => {
          const checked = selected.includes(site.id);
          return (
            <label
              key={site.id}
              className={`flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border px-3 text-sm ${
                checked ? "border-accent-line bg-hivis/10" : "border-rule hover:border-rule-strong"
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
              <span className="shrink-0 font-mono text-xs font-medium whitespace-nowrap">{site.code}</span>
              <span className="truncate text-ink-soft">{site.name}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
