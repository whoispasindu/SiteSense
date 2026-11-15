/**
 * The company's time zone, country and currency: server settings (SITESENSE_TIME_ZONE,
 * SITESENSE_CURRENCY…), the same for everyone, sent with the signed-in user (`/me`).
 *
 * The auth provider calls `configureLocale` before any signed-in screen renders, so the money and
 * time helpers can stay plain functions. Until then (the sign-in page, tests that do not set it)
 * the defaults are Sri Lanka's.
 */

export interface CompanyLocale {
  time_zone: string;
  country: string;
  currency: string;
  currency_decimals: number;
  number_locale: string;
}

export const DEFAULT_LOCALE: CompanyLocale = {
  time_zone: "Asia/Colombo",
  country: "LK",
  currency: "LKR",
  currency_decimals: 2,
  number_locale: "en-LK",
};

let current: CompanyLocale = DEFAULT_LOCALE;
const listeners = new Set<() => void>();

export function configureLocale(next: CompanyLocale): void {
  current = next;
  for (const listener of listeners) listener();
}

export function companyLocale(): CompanyLocale {
  return current;
}

/** "LKR", "GBP"…: for labels such as "Unit price (GBP)". */
export function currencyCode(): string {
  return current.currency;
}

export function siteTimeZone(): string {
  return current.time_zone;
}

/** For caches built from the locale (formatters): called after every change. */
export function onLocaleChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
