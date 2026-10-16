import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { disableMfa, fetchMe, getMfaStatus, renewRecoveryCodes } from "../../api/auth";
import { ApiError } from "../../api/client";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { TextField } from "../../components/ui/Field";
import { PageHeader } from "../../components/ui/PageHeader";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { MfaSetupFlow, RecoveryCodes } from "../../features/auth/TwoStep";
import { formatSiteDateTime } from "../../lib/time";

const statusKey = ["auth", "mfa"] as const;

function message(error: unknown): string {
  if (error instanceof ApiError && error.code === "invalid_mfa_code") return "That code is not right. Use the newest code from the app.";
  return error instanceof ApiError ? error.message : "Something went wrong. Try again.";
}

/** A code from the app, then an action: used to renew recovery codes and to turn two-step sign-in off. */
function CodeAction({
  label,
  action,
  tone = "secondary",
  onDone,
}: {
  label: string;
  action: (code: string) => Promise<void>;
  tone?: "primary" | "secondary";
  onDone?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^\d{6}$/.test(code.trim())) {
      setError("Enter the 6-digit code from the app.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await action(code.trim());
      setOpen(false);
      setCode("");
      onDone?.();
    } catch (err) {
      setError(message(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Button
        variant={tone}
        onClick={() => {
          setOpen(true);
        }}
      >
        {label}
      </Button>
    );
  }
  return (
    <form noValidate onSubmit={(event) => void onSubmit(event)} className="w-full max-w-sm space-y-3 rounded-lg border border-rule p-4">
      {error ? <Alert tone="error">{error}</Alert> : null}
      <TextField
        label="6-digit code from the app"
        value={code}
        onChange={(event) => {
          setCode(event.target.value);
        }}
        autoComplete="one-time-code"
        inputMode="numeric"
        maxLength={6}
        className="tabular tracking-[0.3em]"
      />
      <div className="flex gap-3">
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Checking…" : label}
        </Button>
        <Button
          onClick={() => {
            setOpen(false);
            setError(null);
          }}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** The user's own two-step sign-in: status, recovery codes, and turning it on or off where it is optional. */
export function SecuritySettingsPage() {
  const { setUser } = useAuth();
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: statusKey, queryFn: ({ signal }) => getMfaStatus(signal) });
  const [newCodes, setNewCodes] = useState<string[] | null>(null);
  const [settingUp, setSettingUp] = useState(false);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: statusKey });
    setUser(await fetchMe());
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="Two-step sign-in"
        description="A code from your phone as well as your password, so a stolen password alone is not enough."
      />
      {status.isPending ? <p className="text-sm text-ink-faint">Loading…</p> : null}
      {status.isError ? <Alert tone="error">{message(status.error)}</Alert> : null}
      {status.data ? (
        <Sheet className="space-y-5 p-5">
          <SectionHeading annotation={status.data.required ? "required for your role" : "optional for your role"}>
            {status.data.enabled ? "On" : "Off"}
          </SectionHeading>
          {status.data.enabled ? (
            <>
              <p className="text-sm text-ink-soft">
                Turned on {status.data.enabled_at ? formatSiteDateTime(status.data.enabled_at) : ""}. You have{" "}
                <span className="font-medium text-ink">{status.data.recovery_codes_left}</span> unused recovery code
                {status.data.recovery_codes_left === 1 ? "" : "s"}.
              </p>
              {status.data.recovery_codes_left <= 3 ? (
                <Alert tone="warn">You are running out of recovery codes. Renew them so you are never locked out.</Alert>
              ) : null}
              {newCodes ? (
                <RecoveryCodes
                  codes={newCodes}
                  doneLabel="Done"
                  onDone={() => {
                    setNewCodes(null);
                  }}
                />
              ) : (
                <div className="flex flex-wrap items-start gap-3">
                  <CodeAction
                    label="Renew recovery codes"
                    action={async (code) => {
                      setNewCodes(await renewRecoveryCodes(code));
                      await queryClient.invalidateQueries({ queryKey: statusKey });
                    }}
                  />
                  {!status.data.required ? (
                    <CodeAction
                      label="Turn off two-step sign-in"
                      action={async (code) => {
                        await disableMfa(code);
                      }}
                      onDone={() => void refresh()}
                    />
                  ) : null}
                </div>
              )}
              <p className="text-sm text-ink-faint">
                New phone? Use a recovery code to sign in, then ask your Company Admin to reset two-step sign-in so you
                can set it up again.
              </p>
            </>
          ) : settingUp ? (
            <MfaSetupFlow
              doneLabel="Done"
              onFinished={() => {
                setSettingUp(false);
                void refresh();
              }}
            />
          ) : (
            <>
              <p className="text-sm text-ink-soft">
                Your role does not require it, but it protects your account if your password is ever guessed or reused.
              </p>
              <Button
                variant="primary"
                onClick={() => {
                  setSettingUp(true);
                }}
              >
                Set up two-step sign-in
              </Button>
            </>
          )}
        </Sheet>
      ) : null}
    </div>
  );
}
