import { useState, type SubmitEvent } from "react";

import { enableMfa, startMfaSetup, type MfaSetup } from "../../api/auth";
import { ApiError } from "../../api/client";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { TextField } from "../../components/ui/Field";

function errorOf(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "invalid_mfa_code") return "That code is not right. Check the time on your phone and use the newest code.";
    return error.message;
  }
  return "Something went wrong. Try again.";
}

/** "ABCD EFGH IJKL …": the key in groups of four, easier to type into an app by hand. */
function groupedKey(secret: string): string {
  return secret.replace(/(.{4})/g, "$1 ").trim();
}

/** Recovery codes, shown once: copy, download, and a tick to say they are saved before moving on. */
export function RecoveryCodes({ codes, onDone, doneLabel }: { codes: string[]; onDone: () => void; doneLabel: string }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const text = `SiteSense recovery codes. Each works once.\n\n${codes.join("\n")}\n`;

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "sitesense-recovery-codes.txt";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 10_000);
  }

  return (
    <div className="space-y-4">
      <Alert tone="warn" title="Save these recovery codes now">
        If you lose your phone, each code signs you in once. They will not be shown again.
      </Alert>
      <ol aria-label="Recovery codes" className="grid grid-cols-2 gap-x-6 gap-y-1.5 rounded-lg border border-rule bg-paper-sunk px-4 py-3 font-mono text-sm text-ink">
        {codes.map((code) => (
          <li key={code} className="tabular">
            {code}
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-3">
        <Button
          onClick={() => {
            // Missing in some browsers outside a secure context: then the download is the way.
            const clipboard = navigator.clipboard as Clipboard | undefined;
            void clipboard?.writeText(text).then(() => {
              setCopied(true);
            });
          }}
        >
          {copied ? "Copied" : "Copy all"}
        </Button>
        <Button onClick={download}>Download as a text file</Button>
      </div>
      <label className="flex min-h-11 items-center gap-3 text-sm text-ink">
        <input
          type="checkbox"
          checked={saved}
          onChange={(event) => {
            setSaved(event.target.checked);
          }}
          className="size-4 accent-[var(--color-ink)]"
        />
        I have saved these codes somewhere safe
      </label>
      <Button variant="primary" disabled={!saved} onClick={onDone} className="w-full">
        {doneLabel}
      </Button>
    </div>
  );
}

/**
 * Setting up two-step sign-in: show the QR code (and the key, for typing in), confirm a code from the
 * app, then show the recovery codes once. Nothing changes on the account until the code is confirmed.
 */
export function MfaSetupFlow({ onFinished, doneLabel = "Continue to SiteSense" }: { onFinished: () => void; doneLabel?: string }) {
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function begin() {
    setBusy(true);
    setError(null);
    try {
      setSetup(await startMfaSetup());
    } catch (err) {
      setError(errorOf(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^\d{6}$/.test(code.trim())) {
      setError("Enter the 6-digit code from the app.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setCodes(await enableMfa(code.trim()));
    } catch (err) {
      setError(errorOf(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  if (codes) return <RecoveryCodes codes={codes} onDone={onFinished} doneLabel={doneLabel} />;

  if (!setup) {
    return (
      <div className="space-y-4">
        {error ? <Alert tone="error">{error}</Alert> : null}
        <ol className="list-decimal space-y-1.5 pl-5 text-sm text-ink-soft">
          <li>Install an authenticator app on your phone, such as Google Authenticator, Microsoft Authenticator or 2FAS.</li>
          <li>Scan the QR code SiteSense shows you.</li>
          <li>Enter the 6-digit code the app shows, and save your recovery codes.</li>
        </ol>
        <Button variant="primary" disabled={busy} onClick={() => void begin()} className="w-full">
          {busy ? "Preparing…" : "Show the QR code"}
        </Button>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={(event) => void confirm(event)} className="space-y-5">
      {error ? <Alert tone="error">{error}</Alert> : null}
      <div className="flex flex-col items-center gap-3 rounded-lg border border-rule bg-white p-4">
        <img src={setup.qr_png} alt="QR code to scan with your authenticator app" className="size-48 [image-rendering:pixelated]" />
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer font-medium text-survey hover:underline">Can&rsquo;t scan? Type the key instead</summary>
        <p className="mt-2 text-ink-soft">
          In the app, add an account by key: name it SiteSense, choose time-based, and enter:
        </p>
        <p className="mt-1 rounded-md bg-paper-sunk px-3 py-2 font-mono text-sm break-all text-ink" aria-label="Setup key">
          {groupedKey(setup.secret)}
        </p>
      </details>
      <TextField
        label="6-digit code from the app"
        name="code"
        value={code}
        onChange={(event) => {
          setCode(event.target.value);
        }}
        autoComplete="one-time-code"
        inputMode="numeric"
        maxLength={6}
        className="tabular tracking-[0.3em]"
      />
      <Button type="submit" variant="primary" disabled={busy} className="w-full">
        {busy ? "Checking…" : "Turn on two-step sign-in"}
      </Button>
    </form>
  );
}
