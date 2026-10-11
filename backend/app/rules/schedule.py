"""Critical path method, forecast durations and BR-06 pour flags (Phase 9). Written from scratch.

Activities are programme tasks with a duration in working days; links are finish-to-start
dependencies with an optional lag in working days. ``analyse`` runs the classic two passes:

- **forward:** a task starts on the first working day after all its predecessors have finished
  (plus lag), and never before its own earliest start (its planned start, or tomorrow for work not
  yet begun in a forecast). Work already under way has fixed dates.
- **backward:** from the last finish, each task's latest finish is the working day before the
  earliest of its successors' latest starts (less lag).

Total float is the working days between a task's early and late finish. A task with no float is on
the critical path: any delay to it moves the end date. All dates are on the project's working
calendar (``app.rules.calendar``).

Pure functions over plain values: no database, no clock.
"""

import math
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.rules.calendar import WorkCalendar

# BR-06: a day with 10 mm or more of rain forecast is a heavy-rain day.
HEAVY_RAIN_MM = Decimal(10)
# A task's own rate of progress is trusted from 10% done and five working days of work; before that
# the planned rate is used.
TRUST_RATE_FROM_PERCENT = Decimal(10)
TRUST_RATE_FROM_DAYS = 5
# A forecast never stretches a task beyond ten times its planned duration (a near-zero rate would
# otherwise forecast centuries); the screen still shows how far behind it is.
MAX_STRETCH = 10


class ScheduleError(ValueError):
    """The network is not valid (unknown task, a task linked to itself)."""


class CycleError(ScheduleError):
    """The dependencies form a loop, so no order exists."""

    def __init__(self, members: list[Hashable]) -> None:
        super().__init__("These dependencies form a loop.")
        self.members = members


@dataclass(frozen=True, slots=True)
class Activity:
    id: Hashable
    duration: int  # working days, >= 1
    earliest_start: date  # "start no earlier than": the planned start, or tomorrow in a forecast
    fixed_start: date | None = None  # work already begun (or done)
    fixed_finish: date | None = None  # its actual finish, or the forecast finish of work under way


@dataclass(frozen=True, slots=True)
class Link:
    predecessor: Hashable
    successor: Hashable
    lag: int = 0  # working days between the predecessor's finish and the successor's start


@dataclass(frozen=True, slots=True)
class Timing:
    early_start: date
    early_finish: date
    late_start: date
    late_finish: date
    total_float: int  # working days; 0 or less is critical

    @property
    def critical(self) -> bool:
        return self.total_float <= 0


@dataclass(frozen=True, slots=True)
class Network:
    timings: dict[Hashable, Timing]
    finish: date | None  # the last early finish (None for an empty programme)
    order: list[Hashable]


def topological_order(ids: Sequence[Hashable], links: Sequence[Link]) -> list[Hashable]:
    """Tasks so that every predecessor comes before its successors (Kahn's algorithm, stable)."""
    known = set(ids)
    incoming = dict.fromkeys(ids, 0)
    successors: dict[Hashable, list[Hashable]] = {i: [] for i in ids}
    for link in links:
        if link.predecessor not in known or link.successor not in known:
            raise ScheduleError("A dependency refers to a task that is not in this programme.")
        if link.predecessor == link.successor:
            raise ScheduleError("A task cannot depend on itself.")
        successors[link.predecessor].append(link.successor)
        incoming[link.successor] += 1
    ready = [i for i in ids if incoming[i] == 0]
    order: list[Hashable] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for nxt in successors[current]:
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                ready.append(nxt)
    if len(order) != len(ids):
        raise CycleError([i for i in ids if incoming[i] > 0])
    return order


def creates_cycle(links: Sequence[Link], predecessor: Hashable, successor: Hashable) -> bool:
    """True when adding predecessor -> successor would close a loop (successor already leads back)."""
    if predecessor == successor:
        return True
    following: dict[Hashable, list[Hashable]] = {}
    for link in links:
        following.setdefault(link.predecessor, []).append(link.successor)
    seen: set[Hashable] = set()
    stack = [successor]
    while stack:
        node = stack.pop()
        if node == predecessor:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(following.get(node, []))
    return False


def analyse(activities: Sequence[Activity], links: Sequence[Link], calendar: WorkCalendar) -> Network:
    by_id = {a.id: a for a in activities}
    order = topological_order([a.id for a in activities], links)
    preds: dict[Hashable, list[Link]] = {a.id: [] for a in activities}
    succs: dict[Hashable, list[Link]] = {a.id: [] for a in activities}
    for link in links:
        preds[link.successor].append(link)
        succs[link.predecessor].append(link)

    early_start: dict[Hashable, date] = {}
    early_finish: dict[Hashable, date] = {}
    for task_id in order:
        a = by_id[task_id]
        if a.fixed_finish is not None:
            early_finish[task_id] = a.fixed_finish
            early_start[task_id] = a.fixed_start or calendar.start(a.fixed_finish, a.duration)
            continue
        start = calendar.on_or_after(a.earliest_start)
        for link in preds[task_id]:
            start = max(start, calendar.shift(early_finish[link.predecessor], 1 + link.lag))
        if a.fixed_start is not None:
            start = a.fixed_start
        early_start[task_id] = start
        early_finish[task_id] = calendar.finish(start, a.duration)

    if not order:
        return Network(timings={}, finish=None, order=[])
    finish = max(early_finish.values())

    late_start: dict[Hashable, date] = {}
    late_finish: dict[Hashable, date] = {}
    for task_id in reversed(order):
        a = by_id[task_id]
        latest = finish
        for link in succs[task_id]:
            latest = min(latest, calendar.shift(late_start[link.successor], -(1 + link.lag)))
        late_finish[task_id] = latest
        late_start[task_id] = calendar.start(latest, a.duration)

    timings = {
        task_id: Timing(
            early_start=early_start[task_id],
            early_finish=early_finish[task_id],
            late_start=late_start[task_id],
            late_finish=late_finish[task_id],
            total_float=calendar.gap(early_finish[task_id], late_finish[task_id]),
        )
        for task_id in order
    }
    return Network(timings=timings, finish=finish, order=order)


def remaining_days(*, percent_complete: Decimal, active_days: int, planned_duration: int) -> int:
    """Working days of work left, at the task's own rate so far (or the planned rate, early on).

    ``active_days`` are the working days since the task started, less the days it was stopped by a
    stop-work flag (BR-11), so a stopped task's forecast moves one working day later per stopped day.
    """
    if percent_complete >= 100:
        return 0
    planned_duration = max(planned_duration, 1)
    left = Decimal(100) - percent_complete
    if percent_complete < TRUST_RATE_FROM_PERCENT or active_days < TRUST_RATE_FROM_DAYS:
        rate = Decimal(100) / planned_duration
    else:
        rate = percent_complete / active_days
    return max(1, min(math.ceil(left / rate), MAX_STRETCH * planned_duration))


def is_heavy_rain(rain_mm: Decimal | None) -> bool:
    """BR-06: 10 mm or more."""
    return rain_mm is not None and rain_mm >= HEAVY_RAIN_MM


def pour_rain_days(
    first: date, last: date, rain: Mapping[date, Decimal | None], calendar: WorkCalendar
) -> list[date]:
    """BR-06: the working days of a pour task's window with heavy rain forecast (only forecast days)."""
    return sorted(
        d for d, mm in rain.items() if first <= d <= last and calendar.is_working(d) and is_heavy_rain(mm)
    )
