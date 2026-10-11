/** "on time", "3 working days late", "1 working day early" (Phase 9 slip, in working days). */
export function slipText(days: number): string {
  if (days === 0) return "on time";
  const n = Math.abs(days);
  return `${String(n)} working day${n === 1 ? "" : "s"} ${days > 0 ? "late" : "early"}`;
}
