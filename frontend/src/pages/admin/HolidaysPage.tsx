import { useState, type SubmitEvent } from "react";

import { useAddHoliday, useHolidayCountries, useHolidays, useImportHolidays, useRemoveHoliday } from "../../api/schedule";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { SelectField, TextField } from "../../components/ui/Field";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { formatDate } from "../../features/projects/dates";
import { siteTodayIso } from "../../lib/time";

const weekday = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });

function countryName(code: string): string {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/**
 * Company Admin: the holidays every project's working calendar skips (public holidays and other days
 * off, such as Poya days in Sri Lanka). Critical path, forecasts and slip count working days, so a
 * missing year makes them optimistic. A country's public holidays can be imported, then edited.
 */
export function HolidaysPage() {
  const holidays = useHolidays();
  const add = useAddHoliday();
  const remove = useRemoveHoliday();
  const [date, setDate] = useState("");
  const [name, setName] = useState("");
  const nextYear = Number(siteTodayIso().slice(0, 4)) + 1;
  const countries = useHolidayCountries();
  const importHolidays = useImportHolidays();
  const [country, setCountry] = useState<string | null>(null);
  const [importYear, setImportYear] = useState(String(nextYear));
  const chosenCountry = country ?? countries.data?.default ?? "";
  const yearNumber = Number(importYear);
  const yearValid = Number.isInteger(yearNumber) && yearNumber >= 2000 && yearNumber <= 2100;

  function onImport(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!chosenCountry || !yearValid) return;
    importHolidays.mutate({ country: chosenCountry, year: yearNumber });
  }

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!date || name.trim().length < 2) return;
    add.mutate(
      { holiday_date: date, name: name.trim() },
      {
        onSuccess: () => {
          setDate("");
          setName("");
        },
      },
    );
  }

  const byYear = new Map<number, NonNullable<typeof holidays.data>["holidays"]>();
  for (const h of holidays.data?.holidays ?? []) {
    const year = Number(h.holiday_date.slice(0, 4));
    byYear.set(year, [...(byYear.get(year) ?? []), h]);
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        title="Holidays"
        description="Days no site works: public holidays and any other company days off. Each project's critical path, forecasts and slip skip them, along with the days outside its working week."
      />
      {holidays.data?.missing_next_year ? (
        <Alert tone="warn" title={`No holidays entered for ${String(nextYear)} yet`}>
          Programmes running into {nextYear} count its public holidays as working days until you add them: import them below,
          or add them from the official calendar.
        </Alert>
      ) : null}
      {holidays.isError ? <Alert tone="error">{errorText(holidays.error)}</Alert> : null}

      <Sheet className="p-5">
        <form onSubmit={onImport} className="flex flex-wrap items-end gap-3" aria-label="Import public holidays">
          <div className="min-w-48 flex-1">
            <SelectField
              label="Country"
              value={chosenCountry}
              disabled={!countries.data}
              onChange={(e) => {
                setCountry(e.target.value);
              }}
            >
              {(countries.data?.countries ?? []).map((code) => (
                <option key={code} value={code}>
                  {countryName(code)}
                </option>
              ))}
            </SelectField>
          </div>
          <div className="w-28">
            <TextField
              label="Year"
              inputMode="numeric"
              value={importYear}
              onChange={(e) => {
                setImportYear(e.target.value);
              }}
            />
          </div>
          <Button type="submit" variant="primary" disabled={!chosenCountry || !yearValid || importHolidays.isPending}>
            Import public holidays
          </Button>
        </form>
        <p className="mt-2 text-xs text-ink-faint">
          Adds the country&apos;s published public holidays. Dates you already entered stay as they are; check the list and
          add any other days your sites do not work.
        </p>
        {importHolidays.data ? (
          <div className="mt-3">
            <Alert tone={importHolidays.data.added.length ? "success" : "info"}>{importHolidays.data.message}</Alert>
          </div>
        ) : null}
        {importHolidays.isError ? (
          <div className="mt-3">
            <Alert tone="error">{errorText(importHolidays.error)}</Alert>
          </div>
        ) : null}
      </Sheet>

      <Sheet className="p-5">
        <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3" aria-label="Add a holiday">
          <TextField label="Date" type="date" required min="2000-01-01" max="2100-12-31" value={date} onChange={(e) => { setDate(e.target.value); }} />
          <div className="min-w-48 flex-1">
            <TextField label="Name" required maxLength={80} value={name} onChange={(e) => { setName(e.target.value); }} />
          </div>
          <Button type="submit" variant="primary" disabled={!date || name.trim().length < 2 || add.isPending}>
            Add holiday
          </Button>
        </form>
        {add.isError ? (
          <div className="mt-3">
            <Alert tone="error">{errorText(add.error)}</Alert>
          </div>
        ) : null}
      </Sheet>

      {[...byYear.entries()].map(([year, rows]) => (
        <section key={year} aria-labelledby={`year-${String(year)}`} className="space-y-2">
          <h2 id={`year-${String(year)}`} className="text-base font-semibold text-ink">
            {year} <span className="text-sm font-normal text-ink-faint">· {rows.length} days</span>
          </h2>
          <Sheet className="divide-y divide-rule">
            {rows.map((h) => (
              <div key={h.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                <span>
                  <span className="tabular mr-3 inline-block w-28 text-ink-soft">
                    {weekday.format(new Date(`${h.holiday_date}T00:00:00Z`))} {formatDate(h.holiday_date)}
                  </span>
                  {h.name}
                </span>
                <Button
                  variant="ghost"
                  disabled={remove.isPending}
                  aria-label={`Remove ${h.name} on ${formatDate(h.holiday_date)}`}
                  onClick={() => {
                    remove.mutate(h.id);
                  }}
                >
                  Remove
                </Button>
              </div>
            ))}
          </Sheet>
        </section>
      ))}
    </div>
  );
}
