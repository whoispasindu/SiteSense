import type { Weather, WeatherDay } from "../../api/reports";
import { Alert } from "../../components/ui/Alert";
import { Icon } from "../../components/ui/icons";
import { formatDayShort, formatSiteTime } from "../../lib/time";
import { isHeavyRain, weatherIcon } from "./weather";

function DayCard({ day, today, threshold }: { day: WeatherDay; today: string; threshold: string }) {
  const heavy = isHeavyRain(day, threshold);
  return (
    <li
      className={`flex min-w-[8.5rem] flex-1 flex-col gap-2 rounded-lg border px-3 py-3 lg:min-w-0 ${
        heavy ? "border-signal-medium/40 bg-signal-medium-tint" : "border-rule bg-paper-raised"
      }`}
    >
      <p className="text-sm font-medium text-ink">{day.date === today ? "Today" : formatDayShort(day.date)}</p>
      <div className="flex items-center gap-2">
        <Icon name={weatherIcon(day.weather_code)} className={`size-7 ${heavy ? "text-signal-medium" : "text-ink-soft"}`} />
        <p className="tabular text-lg font-semibold text-ink">
          {day.temp_max_c === null ? "—" : `${Math.round(Number(day.temp_max_c))}°`}
          <span className="ml-1 text-sm font-normal text-ink-faint">
            {day.temp_min_c === null ? "" : `${Math.round(Number(day.temp_min_c))}°`}
          </span>
        </p>
      </div>
      <p className="text-sm text-ink-soft">{day.summary}</p>
      <p className="tabular text-xs text-ink-faint">
        {day.rain_mm === null ? "Rain —" : `Rain ${day.rain_mm} mm`}
        {day.rain_probability === null ? "" : ` · ${String(day.rain_probability)}%`}
      </p>
      {heavy ? (
        <p className="text-xs font-medium text-signal-medium">Heavy rain: check concrete pours</p>
      ) : null}
    </li>
  );
}

/** Five-day site forecast. When the weather service is down it says so and shows the last forecast (TC-08). */
export function WeatherStrip({ weather, today }: { weather: Weather; today: string }) {
  if (!weather.available) {
    return <p className="text-sm text-ink-soft">{weather.message ?? "No forecast available."}</p>;
  }
  return (
    <div className="space-y-3">
      {weather.stale ? (
        <Alert tone="warn">
          {weather.message}
          {weather.fetched_at ? ` Saved at ${formatSiteTime(weather.fetched_at)}.` : ""}
        </Alert>
      ) : null}
      <ul aria-label={`Five-day forecast for site ${weather.site_code}`} className="relative flex gap-3 overflow-x-auto pb-1 lg:grid lg:grid-cols-5 lg:overflow-visible lg:pb-0">
        {weather.days.map((day) => (
          <DayCard key={day.date} day={day} today={today} threshold={weather.heavy_rain_threshold_mm} />
        ))}
      </ul>
    </div>
  );
}
