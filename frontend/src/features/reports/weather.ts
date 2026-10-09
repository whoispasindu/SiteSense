import type { WeatherDay } from "../../api/reports";
import type { IconName } from "../../components/ui/icons";

/** WMO weather code to one of four simple pictures. The summary text always accompanies it. */
export function weatherIcon(code: number | null): IconName {
  if (code === null) return "cloud";
  if (code <= 1) return "sun";
  if (code >= 95) return "storm";
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) return "rain";
  return "cloud";
}

/** The same pictures from free text (reports store the summary, not the code). */
export function summaryIcon(summary: string): IconName {
  const text = summary.toLowerCase();
  if (text.includes("thunder")) return "storm";
  if (/rain|drizzle|shower/.test(text)) return "rain";
  if (/clear|sun/.test(text)) return "sun";
  return "cloud";
}

export function isHeavyRain(day: Pick<WeatherDay, "rain_mm">, threshold: string): boolean {
  return day.rain_mm !== null && Number(day.rain_mm) > Number(threshold);
}
