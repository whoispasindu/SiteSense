import { useState, type ReactNode, type SubmitEvent } from "react";

import { useNotificationPreferences, useSaveNotificationPreferences, type NotificationPreferences } from "../../api/dashboard";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Icon } from "../../components/ui/icons";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";

function Toggle({
  id,
  label,
  detail,
  checked,
  disabled = false,
  onChange,
}: {
  id: string;
  label: string;
  detail: ReactNode;
  checked: boolean;
  disabled?: boolean;
  onChange?: (value: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-6 py-4">
      <div>
        <label htmlFor={id} className="font-medium text-ink">
          {label}
        </label>
        <p id={`${id}-detail`} className="mt-0.5 text-sm text-ink-soft">
          {detail}
        </p>
      </div>
      <span className="relative mt-0.5 inline-flex shrink-0">
        <input
          id={id}
          type="checkbox"
          role="switch"
          aria-describedby={`${id}-detail`}
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange?.(event.target.checked)}
          className="peer h-6 w-11 cursor-pointer appearance-none rounded-full bg-rule-strong transition-colors checked:bg-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-survey disabled:cursor-not-allowed disabled:opacity-60"
        />
        <span
          aria-hidden="true"
          className="pointer-events-none absolute top-1 left-1 size-4 rounded-full bg-paper-raised shadow transition-transform peer-checked:translate-x-5"
        />
      </span>
    </div>
  );
}

function PreferencesForm({ prefs }: { prefs: NotificationPreferences }) {
  const save = useSaveNotificationPreferences();
  const [urgent, setUrgent] = useState(prefs.email_urgent);
  const [digest, setDigest] = useState(prefs.email_digest);
  const [weekly, setWeekly] = useState(prefs.weekly_report);
  const changed = urgent !== prefs.email_urgent || digest !== prefs.email_digest || weekly !== prefs.weekly_report;

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate({
      email_urgent: urgent,
      email_digest: digest,
      ...(prefs.weekly_report_available ? { weekly_report: weekly } : {}),
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      {!prefs.email_configured ? (
        <Alert tone="info">
          Email is not set up on this server yet, so emails are written to the server log instead of being sent.
          Your choices are saved and apply as soon as it is.
        </Alert>
      ) : null}
      <Sheet className="px-5">
        <div className="divide-y divide-rule">
          <Toggle
            id="email-urgent"
            label="Urgent alerts by email"
            detail="Sent at once: high risk (BR-10), heavy rain on a pour (BR-06), high-severity issues, and anything waiting for your approval."
            checked={urgent}
            onChange={setUrgent}
          />
          <Toggle
            id="email-stop-work"
            label="Stop-work alerts"
            detail="A stop-work flag (BR-11) is always emailed to the people it concerns. This cannot be turned off."
            checked
            disabled
          />
          <Toggle
            id="email-digest"
            label="Evening digest"
            detail={`Everything else in one email at ${prefs.digest_time} site time. Skipped on days with nothing new.`}
            checked={digest}
            onChange={setDigest}
          />
          {prefs.weekly_report_available ? (
            <Toggle
              id="email-weekly"
              label="Weekly report (PDF)"
              detail={`Your projects' progress, risk with likely ranges, and costs, every ${prefs.weekly_time} site time. It holds cost figures, so only project managers and quantity surveyors can get it.`}
              checked={weekly}
              onChange={setWeekly}
            />
          ) : null}
        </div>
      </Sheet>
      <p className="flex items-start gap-2 text-sm text-ink-faint">
        <Icon name="mail" className="mt-0.5 size-4 shrink-0" />
        Emails are short: a title, one line and a link into SiteSense. Comments, report text and amounts stay in the app.
      </p>
      {save.isError ? <Alert tone="error">{errorText(save.error)}</Alert> : null}
      {save.isSuccess && !changed ? (
        <p role="status" className="text-sm text-signal-low">
          Saved.
        </p>
      ) : null}
      <Button type="submit" variant="primary" disabled={!changed || save.isPending}>
        {save.isPending ? "Saving…" : "Save choices"}
      </Button>
    </form>
  );
}

/** Which emails this user gets. Every signed-in user, for themselves only. */
export function NotificationSettingsPage() {
  const prefs = useNotificationPreferences();
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="Email alerts"
        description="Alerts always appear in SiteSense. Choose which of them also reach your inbox."
      />
      {prefs.isPending ? <p className="text-sm text-ink-faint">Loading…</p> : null}
      {prefs.isError ? <Alert tone="error">{errorText(prefs.error)}</Alert> : null}
      {prefs.data ? <PreferencesForm prefs={prefs.data} /> : null}
    </div>
  );
}
