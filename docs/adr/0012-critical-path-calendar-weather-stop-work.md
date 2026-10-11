# ADR 0012: Critical path, working calendar, pour weather and stop-work scope

- Status: accepted
- Date: 2026-10-11

## Context

Phase 9 turns the task list into a programme. The build guide asks for:

- task dependencies and a critical path calculated from scratch;
- forecast end dates from the current progress rate;
- BR-06: concrete pours on heavy-rain days flagged and the PM alerted (TC-12);
- BR-11: stop-work blocks the related tasks until the PM clears it;
- a Gantt with the critical path, forecast slip and a today line, with stop-work flags shown on tasks.

Three questions needed the project owner. They decided:

- **Calendar:** Monday to Saturday, with Poya days and public holidays off. The holiday list is kept
  by the Company Admin, seeded with 2026, with a warning when next year's list is missing. The
  working week is a per-project setting.
- **Stop-work scope:** the author picks the stopped tasks (in-progress ones suggested), or the whole
  project for serious cases; the PM can change the choice. While tasks are stopped, their forecast
  keeps moving later by each stopped working day, and the critical path and risk model see it.
- **Heavy rain:** 10 mm or more of forecast rain on a day the pour is forecast to be worked. BR-06's
  text changes from "over 10 mm" to "10 mm or more".

## Decisions

**Everything is counted in working days.** `app/rules/calendar.py` holds a `WorkCalendar` (the
project's ISO weekdays plus the company's holidays) with shift, count and gap. Counting is
arithmetic: whole weeks times working days per week, less holidays found by bisection. Shifting
jumps whole weeks and walks the last stretch. The calculation for a 500-task, 15-year programme
takes about 15 ms, against 1.2 s walking day by day. A randomised test checks both against a
day-by-day walk. The calendar refuses to search or count past 30 years, which guards against a
calendar with no working days left.

**Holidays are company data, not code.** A `holidays` table, managed only by the Company Admin
(`holidays:manage`), audited. Migration 0011 seeds 2026's 25 days from the government's list, with
the May Day holiday moved to 31 May as amended on 21 April 2026. A year with no holidays is reported
wherever it matters: the schedule page and the admin's list.

**Finish-to-start links only, with lag.** That covers how the demo and most small builders plan. A
link is refused across projects, onto itself, or when it would make a loop (checked under a project
row lock, so two simultaneous links cannot make one together). Other link types (start-to-start,
finish-to-finish) can come later without changing the stored links.

**The critical path is the classic two-pass CPM, written from scratch** (`rules/schedule.py`).

- A task's planned start acts as "start no earlier than".
- The forward pass gives earliest dates; the backward pass from the last finish gives latest dates.
- Float is the working days from earliest to latest finish. Unfinished tasks with no float are
  critical. Finished tasks are never shown as critical.
- `is_critical` is now calculated, not stored. The Phase 3 column was dropped.

**The forecast is the same analysis on what is happening.**

- Finished tasks keep their actual dates. `tasks.actual_start` and `actual_finish` are new columns,
  kept by progress updates, backfilled from report history, and guarded by checks.
- Work under way finishes at its own rate: percent per active working day. Under 10% done or under
  5 working days in, the planned rate is used, because early rates are noise. The remaining time is
  capped at 10× the planned duration.
- Work not started begins no earlier than today, or tomorrow while it is stopped.

If long lags or very slow work would push the network past the calendar's horizon, the network is
shown on each task's own dates with no critical path and a warning. The page still loads, so the PM
can fix the cause.

**BR-06 checks the forecast window, not the plan.** A pour task (`is_concrete_pour`), not finished,
is flagged for each working day in its forecast window with 10 mm or more of rain in the cached
forecast. The site's project managers are notified, de-duplicated per task and hashed set of rain
days (so a new rain day alerts again, and the key stays within its column). The check runs:

- daily at 05:45, after the weather refresh;
- when a task is created or marked as a pour;
- from `app.cli check-pours`.

No outbound call is made for it.

**BR-11 stores what each flag stops.**

- `report_actions.stop_scope` is `tasks` or `project`, with the chosen tasks in
  `report_action_tasks`. Existing flags became `project`, the safe reading.
- Progress goes through one function (`schedule_service.apply_progress`), used by the task PATCH
  and by daily reports. It refuses a stopped task with `422 stop_work`.
- Only a PM changes the scope of an open flag, audited before and after. Clearing a flag or changing
  its scope re-scores the project's risk.
- Stopped working days are counted from the flags' dates. Overlapping flags count a day once. They
  are taken out of the task's active days, which moves its forecast.

**The Gantt draws the network the API calculates.** Planned bars, forecast bars, critical
highlighting, links, a today line, slip, STOP badges and rain marks. A screen-reader table carries
the same facts. The browser never recalculates the critical path.

## Consequences

- Programmes now depend on the holiday list being kept. The warning makes a missing year visible.
  A project in another country would need its own list, which the per-company table does not give.
- Only finish-to-start links are supported for now.
- The forecast and BR-06 react to rain, but the risk score barely does: rain holds 0.0% of the delay
  model's gain. The simulator's rain effect is to be reviewed before retraining in Phase 10
  ([#27](https://github.com/whoispasindu/SiteSense/issues/27)).
