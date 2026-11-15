import { formatMoney, toNumber } from "../../lib/money";
import { formatDate } from "../projects/dates";

/** "+ LKR 850,000.00" / "− LKR 1,200.00" / "No change": a change in words, not only a sign. */
export function signedMoney(value: string | null): string {
  if (value === null) return "Not priced yet";
  const n = toNumber(value);
  if (n === 0) return "No change";
  return `${n > 0 ? "+" : "−"} ${formatMoney(Math.abs(n))}`;
}

export function daysText(days: number): string {
  if (days === 0) return "No time impact";
  return `${String(days)} day${days === 1 ? "" : "s"} later`;
}

export function paidText(paidOn: string | null): string {
  return paidOn ? `Paid ${formatDate(paidOn)}` : "Not paid yet";
}
