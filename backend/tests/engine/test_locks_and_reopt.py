"""Locked rows, INFEASIBLE vs SOLVER_TIMEOUT, and window-scoped re-optimisation."""
from dataclasses import replace

from ortools.sat.python import cp_model

from app.scheduling import affected_scope, classify, generate, regenerate_window
from app.scheduling.solver import Lock, solve
from app.scheduling.types import (
    Absence,
    AbsenceKind,
    EntryStatus,
    Role,
    RosterDuty,
    RosterEntry,
    SolveStatus,
    Source,
    ValidationStatus,
)

from .builder import D, GEN, PB


def _simple(pb=None):
    pb = pb or PB()
    a, b = pb.employee("Asha"), pb.employee("Bilal")
    bp = pb.bp("Lumo", "CS")
    s = pb.slot(bp, GEN, 1)
    aa, ba = pb.assign(a, bp), pb.assign(b, bp)
    return pb, a, b, bp, s, aa, ba


def test_locked_work_on_leave_day_is_infeasible_and_names_the_row():
    pb, a, b, bp, s, aa, _ = _simple()
    pb.leave(a, D(10), D(10))
    lock = Lock(RosterEntry(a, D(10), EntryStatus.WORK, GEN, Source.MANUAL, True),
                (RosterDuty(a, D(10), s, bp, GEN, aa, Role.PRIMARY, Source.MANUAL, True),))
    out = generate(pb.build(), locks={(a, D(10)): lock})
    assert out.status == ValidationStatus.INFEASIBLE
    assert out.roster is None
    assert [(c.employee_id, c.date) for c in out.solve.lock_conflicts] == [(a, D(10))]


def test_locked_streak_breaking_max_consecutive_is_infeasible():
    pb, a, b, bp, s, aa, _ = _simple()
    locks = {}
    for i in range(1, 9):   # 8 locked work days > max 6
        locks[(a, D(i))] = Lock(RosterEntry(a, D(i), EntryStatus.WORK, GEN, Source.MANUAL, True),
                                (RosterDuty(a, D(i), s, bp, GEN, aa, Role.PRIMARY, Source.MANUAL, True),))
    out = generate(pb.build(), locks=locks)
    assert out.status == ValidationStatus.INFEASIBLE
    culprits = {c.date for c in out.solve.lock_conflicts}
    assert culprits and culprits <= {D(i) for i in range(1, 9)}


def test_lock_with_invalid_assignment_is_reported_directly():
    pb, a, b, bp, s, aa, ba = _simple()
    lock = Lock(RosterEntry(a, D(5), EntryStatus.WORK, GEN, Source.MANUAL, True),
                (RosterDuty(a, D(5), s, bp, GEN, ba, Role.PRIMARY, Source.MANUAL, True),))  # b's assignment
    out = generate(pb.build(), locks={(a, D(5)): lock})
    assert out.status == ValidationStatus.INFEASIBLE
    assert "no valid assignment" in out.solve.lock_conflicts[0].reason


def test_timeout_without_solution_is_solver_timeout_not_infeasible(monkeypatch):
    pb, *_ = _simple()
    monkeypatch.setattr(cp_model.CpSolver, "Solve", lambda self, model, *a, **k: cp_model.UNKNOWN)
    res = solve(pb.build())
    assert res.status == SolveStatus.SOLVER_TIMEOUT
    out = generate(pb.build())
    assert out.status == ValidationStatus.SOLVER_TIMEOUT
    assert out.status != ValidationStatus.INFEASIBLE and out.roster is None


def test_classify_keeps_solver_outcomes_distinct():
    assert classify(SolveStatus.INFEASIBLE, None) == ValidationStatus.INFEASIBLE
    assert classify(SolveStatus.SOLVER_TIMEOUT, None) == ValidationStatus.SOLVER_TIMEOUT


def test_unlocked_model_is_always_feasible_even_when_coverage_impossible():
    pb = PB()
    a = pb.employee("Asha")
    bp = pb.bp("Lumo", "CS")
    pb.slot(bp, GEN, 5)                 # needs 5, only 1 person exists
    pb.assign(a, bp)
    out = generate(pb.build())
    assert out.solve.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
    assert out.status == ValidationStatus.PARTIALLY_COVERED
    assert out.report.hard_rule_violations == 0


# ── re-optimisation ──────────────────────────────────────────────────────────
def _reopt_case():
    pb = PB()
    owner, buddy, other = pb.employee("Owner"), pb.employee("Buddy"), pb.employee("Other")
    cs = pb.bp("Ember", "CS")
    s = pb.slot(cs, GEN, 1)
    pb.assign(owner, cs)
    own = pb.bp("Kito", "CS")
    pb.slot(own, GEN, 1)
    pb.assign(buddy, own, load=70)
    pb.assign(buddy, cs, Role.BACKUP, load=50)
    unrelated = pb.bp("Zest", "CS")
    pb.slot(unrelated, GEN, 1)
    pb.assign(other, unrelated)
    return pb, owner, buddy, other, cs, s


def test_reopt_changes_only_window_and_scope():
    pb, owner, buddy, other, cs, s = _reopt_case()
    base = generate(pb.build()).roster
    # Change after generation: owner becomes unavailable 15-17 Dec.
    pb.leave(owner, D(15), D(17))
    prob = pb.build()
    scope = affected_scope(prob, {owner})
    assert scope == {owner, buddy}
    out = regenerate_window(prob, base, D(14), D(18), scope)

    assert out.status in (ValidationStatus.FULLY_COVERED, ValidationStatus.PARTIALLY_COVERED)
    new = out.roster
    in_free = lambda e, d: D(14) <= d <= D(18) and e in scope  # noqa: E731
    base_e, new_e = base.entry_map(), new.entry_map()
    for key, be in base_e.items():
        if not in_free(*key):
            assert new_e[key] == be                     # byte-identical outside window/scope
    base_d = {(d.employee_id, d.date, d.slot_id): d for d in base.duties if not in_free(d.employee_id, d.date)}
    new_d = {(d.employee_id, d.date, d.slot_id): d for d in new.duties if not in_free(d.employee_id, d.date)}
    assert base_d == new_d
    for day in (15, 16, 17):
        assert new_e[(owner, D(day))].status == EntryStatus.LEAVE
    # The trained backup absorbs the owner's new leave.
    ember = {c.date: c for c in out.report.coverage if c.slot_id == s}
    for day in (15, 16, 17):
        assert ember[D(day)].status.value == "MET" and ember[D(day)].backup_count == 1
    assert not out.diff.is_empty
    assert out.report.hard_rule_violations == 0
    assert all(x.source in (Source.REOPT, Source.AUTO) for x in new.entries)


def test_reopt_preserves_manual_rows_unless_overridden():
    pb, owner, buddy, other, cs, s = _reopt_case()
    base = generate(pb.build()).roster
    # Manager manually set buddy's 16 Dec to WEEKLY_OFF.
    entries = base.entry_map()
    manual = replace(entries[(buddy, D(16))], status=EntryStatus.WEEKLY_OFF, shift_id=None,
                     source=Source.MANUAL, is_locked=True)
    base.entries = [manual if (x.employee_id, x.date) == (buddy, D(16)) else x for x in base.entries]
    base.duties = [x for x in base.duties if not (x.employee_id == buddy and x.date == D(16))]

    pb.leave(owner, D(15), D(17))
    prob = pb.build()
    kept = regenerate_window(prob, base, D(14), D(18), affected_scope(prob, {owner}))
    assert kept.roster.entry_map()[(buddy, D(16))] == manual       # preserved verbatim
    ember_16 = next(c for c in kept.report.coverage if c.slot_id == s and c.date == D(16))
    assert ember_16.staffed == 0                                    # the gap stays visible

    over = regenerate_window(prob, base, D(14), D(18), affected_scope(prob, {owner}),
                             override_manual={(buddy, D(16))})
    new16 = over.roster.entry_map()[(buddy, D(16))]
    assert new16.status == EntryStatus.WORK and new16.source == Source.REOPT
    assert any(d.employee_id == buddy and d.date == D(16) and d.slot_id == s for d in over.roster.duties)


def test_reopt_diff_lists_changes():
    pb, owner, buddy, other, cs, s = _reopt_case()
    base = generate(pb.build()).roster
    pb.absences.append(Absence(owner, D(20), D(20), AbsenceKind.UNAVAILABLE))
    prob = pb.build()
    out = regenerate_window(prob, base, D(20), D(20), affected_scope(prob, {owner}))
    if base.entry_map()[(owner, D(20))].status == EntryStatus.WORK:
        assert any(b.employee_id == owner for b, a in out.diff.changed_entries)
        assert any(d.employee_id == owner for d in out.diff.removed_duties)
