import { useState, type SubmitEvent } from "react";
import { z } from "zod";

import { ApiError } from "../../api/client";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { TextField } from "../../components/ui/Field";
import { PasswordToggle } from "../../components/ui/PasswordToggle";
import { signInErrorMessage } from "./authMessages";
import { GateLayout, GatePass } from "./GateLayout";

const signInSchema = z.object({
  email: z.email("Enter the email address you use for SiteSense."),
  password: z.string().min(1, "Enter your password."),
});

type FieldErrors = Partial<Record<"email" | "password", string>>;

/** The second step: a six-digit code from the authenticator app, or one recovery code. */
function CodeStep({ token, onRestart }: { token: string; onRestart: () => void }) {
  const { completeSignIn } = useAuth();
  const [useRecovery, setUseRecovery] = useState(false);
  const [value, setValue] = useState("");
  const [failure, setFailure] = useState<{ tone: "error" | "warn"; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const valid = useRecovery ? value.trim().length >= 10 : /^\d{6}$/.test(value.trim());

  async function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) {
      setFailure({ tone: "error", text: useRecovery ? "Enter one of your recovery codes." : "Enter the 6-digit code." });
      return;
    }
    setFailure(null);
    setSubmitting(true);
    try {
      // On success the AnonymousOnly guard moves on, as after a password-only sign-in.
      await completeSignIn(token, useRecovery ? { recovery_code: value.trim() } : { code: value.trim() });
    } catch (error) {
      const message = signInErrorMessage(error);
      setFailure(message);
      setSubmitting(false);
      setValue("");
      if (error instanceof ApiError && error.code === "mfa_challenge_expired") onRestart();
    }
  }

  return (
    <GatePass title="Two-step sign-in">
      <p className="mt-2 text-ink-soft">
        {useRecovery
          ? "Enter one of the recovery codes you saved when you set up two-step sign-in. Each works once."
          : "Open your authenticator app and enter the 6-digit code for SiteSense."}
      </p>
      <form noValidate onSubmit={(event) => void onSubmit(event)} className="mt-7 space-y-5">
        {failure ? <Alert tone={failure.tone}>{failure.text}</Alert> : null}
        <TextField
          key={useRecovery ? "recovery" : "code"}
          label={useRecovery ? "Recovery code" : "Code"}
          name={useRecovery ? "recovery_code" : "code"}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
          }}
          autoComplete="one-time-code"
          inputMode={useRecovery ? "text" : "numeric"}
          maxLength={useRecovery ? 20 : 6}
          spellCheck={false}
          className="tabular tracking-[0.3em]"
        />
        <Button type="submit" variant="primary" disabled={submitting} className="w-full">
          {submitting ? "Checking…" : "Continue"}
        </Button>
      </form>
      <div className="mt-6 flex flex-wrap justify-between gap-3 border-t border-rule pt-4 text-sm">
        <button
          type="button"
          className="font-medium text-survey hover:underline"
          onClick={() => {
            setUseRecovery((v) => !v);
            setValue("");
            setFailure(null);
          }}
        >
          {useRecovery ? "Use the app code instead" : "Lost your phone? Use a recovery code"}
        </button>
        <button type="button" className="text-ink-faint hover:text-ink hover:underline" onClick={onRestart}>
          Start again
        </button>
      </div>
    </GatePass>
  );
}

export function SignInPage() {
  const { signIn } = useAuth();
  const [challenge, setChallenge] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [failure, setFailure] = useState<{ tone: "error" | "warn"; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const parsed = signInSchema.safeParse({ email: form.get("email"), password: form.get("password") });
    if (!parsed.success) {
      const errors: FieldErrors = {};
      for (const issue of parsed.error.issues) {
        const field = issue.path[0];
        if (field === "email" || field === "password") errors[field] ??= issue.message;
      }
      setFieldErrors(errors);
      return;
    }

    setFieldErrors({});
    setFailure(null);
    setSubmitting(true);
    try {
      // On success the AnonymousOnly guard moves on to the safe "next" page (or the password change).
      const result = await signIn(parsed.data.email, parsed.data.password);
      if (result.kind === "challenge") {
        setChallenge(result.token);
        setSubmitting(false);
      }
    } catch (error) {
      setFailure(signInErrorMessage(error));
      setSubmitting(false);
    }
  }

  if (challenge) {
    return (
      <GateLayout>
        <CodeStep
          token={challenge}
          onRestart={() => {
            setChallenge(null);
          }}
        />
      </GateLayout>
    );
  }

  return (
    <GateLayout>
      <GatePass title="Sign in">
        <p className="mt-2 text-ink-soft">Use the account your company admin created for you.</p>

        <form noValidate onSubmit={(event) => void onSubmit(event)} className="mt-7 space-y-5">
          {failure ? <Alert tone={failure.tone}>{failure.text}</Alert> : null}

          <TextField
            label="Email"
            name="email"
            type="email"
            autoComplete="username"
            inputMode="email"
            spellCheck={false}
            required
            error={fieldErrors.email}
          />
          <TextField
            label="Password"
            name="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            required
            maxLength={128}
            error={fieldErrors.password}
            trailing={
              <PasswordToggle
                visible={showPassword}
                onToggle={() => {
                  setShowPassword((v) => !v);
                }}
              />
            }
          />

          <Button type="submit" variant="primary" disabled={submitting} className="w-full">
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        <p className="mt-6 border-t border-rule pt-4 text-sm leading-relaxed text-ink-faint">
          Forgot your password? Your company admin can issue a new temporary one. After 5 failed attempts the account
          locks for 15 minutes.
        </p>
      </GatePass>
    </GateLayout>
  );
}
