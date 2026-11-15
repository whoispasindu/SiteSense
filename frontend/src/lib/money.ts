/**
 * Money arrives from the API as exact decimal strings ("1113985000.00"). These helpers are for
 * display only; totals are always computed by the server. The currency and number format are the
 * company's (lib/locale.ts): amounts are never converted, only labelled.
 */

import { companyLocale, currencyCode, onLocaleChange } from "./locale";

interface Formatters {
  full: Intl.NumberFormat;
  whole: Intl.NumberFormat;
  quantity: Intl.NumberFormat;
}

let cached: Formatters | null = null;
onLocaleChange(() => {
  cached = null;
});

function formatters(): Formatters {
  if (cached) return cached;
  const { number_locale: locale, currency_decimals: decimals } = companyLocale();
  cached = {
    full: new Intl.NumberFormat(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }),
    whole: new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }),
    quantity: new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }),
  };
  return cached;
}

export function toNumber(value: string | number): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** "1,113,985,000.00" (no currency code: the label or column header says it). */
export function formatAmount(value: string | number): string {
  return formatters().full.format(toNumber(value));
}

/** "LKR 1,113,985,000.00": an exact amount with its currency. */
export function formatMoney(value: string | number): string {
  return `${currencyCode()} ${formatAmount(value)}`;
}

/** "LKR 9,800,000": a rounded estimate, where cents would claim false precision. */
export function formatMoneyWhole(value: string | number): string {
  return `${currencyCode()} ${formatters().whole.format(toNumber(value))}`;
}

export function formatQuantity(value: string | number): string {
  return formatters().quantity.format(toNumber(value));
}

/** "LKR 1.11 bn", "LKR 685 M", "LKR 42.5 k": for tiles and lists, where exact cents are noise. */
export function formatCompactMoney(value: string | number): string {
  const n = toNumber(value);
  const abs = Math.abs(n);
  const [divisor, unit] = abs >= 1e9 ? [1e9, "bn"] : abs >= 1e6 ? [1e6, "M"] : abs >= 1e3 ? [1e3, "k"] : [1, ""];
  const scaled = n / divisor;
  const digits = Math.abs(scaled) >= 100 ? 0 : Math.abs(scaled) >= 10 ? 1 : 2;
  const text = scaled.toLocaleString(companyLocale().number_locale, { maximumFractionDigits: digits });
  return unit ? `${currencyCode()} ${text} ${unit}` : `${currencyCode()} ${text}`;
}

/** Share of ``part`` in ``whole`` as a percentage, 0 when the whole is zero. */
export function percent(part: string | number, whole: string | number): number {
  const w = toNumber(whole);
  return w === 0 ? 0 : (toNumber(part) / w) * 100;
}
