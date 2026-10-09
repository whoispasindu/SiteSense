import { useState, type SubmitEvent } from "react";
import { useNavigate } from "react-router";

import { changePassword } from "../../api/auth";
import { ApiError } from "../../api/client";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { TextField } from "../../components/ui/Field";
import { GateLayout, GatePass } from "./GateLayout";
import { PasswordToggle } from "../../components/ui/PasswordToggle";
import { passwordChecks } from "./passwordRules";

export function ChangePasswordPage() {
  const { user, setUser, signOut } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!user) return null;
  const checks = passwordChecks(next, confirm, user.email);
  const ready = checks.every((c) => c.ok) && current.length > 0;
  const forced = user.must_change_password;

  async function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready) return;
    setSubmitting(true);
    setError(null);
    try {
      const me = await changePassword(current, next);
      setUser(me);
      void navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The password could not be changed. Try again.");
      setSubmitting(false);
    }
  }

  return (
    <GateLayout>
      <GatePass title={forced ? "Set your own password" : "Change password"}>
        <p className="mt-2 text-ink-soft">
          {forced
            ? "You signed in with a temporary password. Choose a private one to continue."
            : "Other devices will be signed out."}
        </p>

        <form noValidate onSubmit={(event) => void onSubmit(event)} className="mt-7 space-y-5">
          {error ? <Alert tone="error">{error}</Alert> : null}
          <input type="email" name="username" autoComplete="username" value={user.email} readOnly hidden />
          <TextField
            label={forced ? "Temporary password" : "Current password"}
            type={visible ? "text" : "password"}
            autoComplete="current-password"
            value={current}
            maxLength={128}
            onChange={(e) => {
              setCurrent(e.target.value);
            }}
          />
          <TextField
            label="New password"
            type={visible ? "text" : "password"}
            autoComplete="new-password"
            value={next}
            maxLength={128}
            onChange={(e) => {
              setNext(e.target.value);
            }}
            trailing={
              <PasswordToggle
                visible={visible}
                onToggle={() => {
                  setVisible((v) => !v);
                }}
              />
            }
          />
          <TextField
            label="Repeat new password"
            type={visible ? "text" : "password"}
            autoComplete="new-password"
            value={confirm}
            maxLength={128}
            onChange={(e) => {
              setConfirm(e.target.value);
            }}
          />

          <ul aria-label="Password requirements" className="grid gap-1.5 sm:grid-cols-2">
            {checks.map((check) => (
              <li key={check.label} className="flex items-center gap-2 text-sm">
                <span
                  aria-hidden="true"
                  className={`grid size-4 place-items-center rounded-full border text-[0.625rem] ${
                    check.ok ? "border-signal-low bg-signal-low text-paper" : "border-rule-strong text-transparent"
                  }`}
                >
                  ✓
                </span>
                <span className={check.ok ? "text-ink" : "text-ink-faint"}>
                  {check.label}
                  <span className="sr-only">{check.ok ? " (met)" : " (not met)"}</span>
                </span>
              </li>
            ))}
          </ul>

          <Button type="submit" variant="primary" disabled={!ready || submitting} className="w-full">
            {submitting ? "Saving…" : "Save password"}
          </Button>
        </form>

        <button
          type="button"
          onClick={() => void signOut()}
          className="mt-5 text-sm text-ink-soft underline underline-offset-4 hover:text-ink"
        >
          Sign out instead
        </button>
      </GatePass>
    </GateLayout>
  );
}
