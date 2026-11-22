"""Window-scoped re-optimisation after a change (leave, unavailability, rule edit).

Only rows inside ``[window_from, window_to]`` *and* inside the affected employee
scope are free.  Everything else is passed to the solver as a lock and copied
back verbatim, so unaffected rows stay identical.  Manual rows (source MANUAL
or is_locked) stay locked even inside the window unless the manager explicitly
lists them in ``override_manual``.  A stability penalty keeps changes to free
rows minimal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .solver import Key, Lock, SolveResult, solve
from .types import Problem, Roster, RosterDuty, RosterEntry, SolveStatus, Source


@dataclass
class RosterDiff:
    changed_entries: list[tuple[RosterEntry, RosterEntry]] = field(default_factory=list)
    added_duties: list[RosterDuty] = field(default_factory=list)
    removed_duties: list[RosterDuty] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.changed_entries or self.added_duties or self.removed_duties)


@dataclass
class ReoptResult:
    solve: SolveResult
    diff: RosterDiff
    free_keys: set[Key]
    locked_keys: set[Key]


def affected_scope(problem: Problem, employee_ids: set[int]) -> set[int]:
    """Changed employees plus everyone (primary or backup) on the brand-processes they touch."""
    bps = {a.brand_process_id for a in problem.assignments if a.employee_id in employee_ids}
    return set(employee_ids) | {a.employee_id for a in problem.assignments if a.brand_process_id in bps}


def _is_manual(entry: RosterEntry, duties: list[RosterDuty]) -> bool:
    return (entry.is_locked or entry.source == Source.MANUAL
            or any(d.is_locked or d.source == Source.MANUAL for d in duties))


def build_locks(
    previous: Roster,
    window_from: date,
    window_to: date,
    scope: set[int] | None,
    override_manual: set[Key],
) -> tuple[dict[Key, Lock], set[Key]]:
    duties = previous.duties_by_day()
    locks: dict[Key, Lock] = {}
    free: set[Key] = set()
    for en in previous.entries:
        key = (en.employee_id, en.date)
        day_duties = duties.get(key, [])
        in_window = window_from <= en.date <= window_to
        in_scope = scope is None or en.employee_id in scope
        manual_kept = _is_manual(en, day_duties) and key not in override_manual
        if in_window and in_scope and not manual_kept:
            free.add(key)
        else:
            locks[key] = Lock(en, tuple(day_duties))
    return locks, free


def diff_rosters(before: Roster, after: Roster) -> RosterDiff:
    out = RosterDiff()
    b_entries, a_entries = before.entry_map(), after.entry_map()
    for key, be in b_entries.items():
        ae = a_entries.get(key)
        if ae is not None and (ae.status, ae.shift_id) != (be.status, be.shift_id):
            out.changed_entries.append((be, ae))
    sig = lambda d: (d.employee_id, d.date, d.slot_id, d.assignment_id)  # noqa: E731
    b_duties = {sig(d): d for d in before.duties}
    a_duties = {sig(d): d for d in after.duties}
    out.added_duties = [d for k, d in a_duties.items() if k not in b_duties]
    out.removed_duties = [d for k, d in b_duties.items() if k not in a_duties]
    return out


def reoptimize(
    problem: Problem,
    previous: Roster,
    window_from: date,
    window_to: date,
    scope: set[int] | None = None,
    override_manual: set[Key] | None = None,
) -> ReoptResult:
    locks, free = build_locks(previous, window_from, window_to, scope, override_manual or set())
    # Overridden manual rows lose their manual marker once the solver re-decides them.
    result = solve(problem, locks=locks, previous=previous, stability_keys=free)
    diff = diff_rosters(previous, result.roster) if result.status in (
        SolveStatus.OPTIMAL, SolveStatus.FEASIBLE) and result.roster else RosterDiff()
    return ReoptResult(result, diff, free, set(locks))
