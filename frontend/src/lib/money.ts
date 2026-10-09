/**
 * Money arrives from the API as exact decimal strings ("1113985000.00"). These helpers are for
 * display only; totals are always computed by the server.
 */

const full = new Intl.NumberFormat("en-LK", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const quantity = new Intl.NumberFormat("en-LK", { maximumFractionDigits: 3 });

export function toNumber(value: string | number): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** "1,113,985,000.00" (no currency symbol: column headers say LKR). */
export function formatAmount(value: string | number): string {
  return full.format(toNumber(value));
}

export function formatQuantity(value: string | number): string {
  return quantity.format(toNumber(value));
}

/** "LKR 1.11 bn", "LKR 685 M", "LKR 42.5 k": for tiles and lists, where exact cents are noise. */
export function formatCompactLKR(value: string | number): string {
  const n = toNumber(value);
  const abs = Math.abs(n);
  const [divisor, unit] = abs >= 1e9 ? [1e9, "bn"] : abs >= 1e6 ? [1e6, "M"] : abs >= 1e3 ? [1e3, "k"] : [1, ""];
  const scaled = n / divisor;
  const digits = Math.abs(scaled) >= 100 ? 0 : Math.abs(scaled) >= 10 ? 1 : 2;
  const text = scaled.toLocaleString("en-LK", { maximumFractionDigits: digits });
  return unit ? `LKR ${text} ${unit}` : `LKR ${text}`;
}

/** Share of ``part`` in ``whole`` as a percentage, 0 when the whole is zero. */
export function percent(part: string | number, whole: string | number): number {
  const w = toNumber(whole);
  return w === 0 ? 0 : (toNumber(part) / w) * 100;
}
