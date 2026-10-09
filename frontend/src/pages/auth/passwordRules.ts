export const MIN_LENGTH = 12;

/** Mirrors the server policy for instant feedback; the server remains the authority. */
export function passwordChecks(password: string, confirm: string, email: string) {
  const local = email.split("@")[0]?.toLowerCase() ?? "";
  return [
    { label: `At least ${String(MIN_LENGTH)} characters`, ok: password.length >= MIN_LENGTH },
    { label: "Not your email name", ok: password.length > 0 && !(local.length >= 4 && password.toLowerCase().includes(local)) },
    { label: "At least 4 different characters", ok: new Set(password.toLowerCase()).size >= 4 },
    { label: "Both entries match", ok: password.length > 0 && password === confirm },
  ];
}
