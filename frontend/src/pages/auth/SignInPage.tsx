import { useState, type SubmitEvent } from "react";
import { z } from "zod";

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

export function SignInPage() {
  const { signIn } = useAuth();
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
      await signIn(parsed.data.email, parsed.data.password);
    } catch (error) {
      setFailure(signInErrorMessage(error));
      setSubmitting(false);
    }
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
