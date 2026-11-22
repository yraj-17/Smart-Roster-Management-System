"""Scheduling engine: pure Python, no database or web framework imports.

Public entry points::

    generate(problem)                         -> Outcome
    regenerate_window(problem, previous, ...) -> Outcome (+ diff)
    validate(problem, roster)                 -> ValidationReport
    suggest(problem, roster, slot_id, date)   -> list[Suggestion]
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .reoptimize import ReoptResult, RosterDiff, affected_scope, reoptimize
from .solver import Key, Lock, SolveResult, solve
from .suggestions import Suggestion, suggest
from .types import Problem, Roster, SolveStatus, ValidationStatus
from .validator import ValidationReport, classify, validate


@dataclass
class Outcome:
    solve: SolveResult
    report: ValidationReport | None
    status: ValidationStatus
    diff: RosterDiff | None = None

    @property
    def roster(self) -> Roster | None:
        return self.solve.roster


def _finish(problem: Problem, res: SolveResult, diff: RosterDiff | None = None) -> Outcome:
    report = validate(problem, res.roster) if res.roster is not None else None
    return Outcome(res, report, classify(res.status, report), diff)


def generate(problem: Problem, locks: dict[Key, Lock] | None = None) -> Outcome:
    return _finish(problem, solve(problem, locks=locks))


def regenerate_window(
    problem: Problem,
    previous: Roster,
    window_from: date,
    window_to: date,
    scope: set[int] | None = None,
    override_manual: set[Key] | None = None,
) -> Outcome:
    r: ReoptResult = reoptimize(problem, previous, window_from, window_to, scope, override_manual)
    return _finish(problem, r.solve, r.diff)


__all__ = [
    "Outcome", "generate", "regenerate_window", "validate", "suggest", "affected_scope",
    "classify", "Lock", "Problem", "Roster", "SolveStatus", "ValidationStatus", "Suggestion",
]
