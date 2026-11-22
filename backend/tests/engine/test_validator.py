"""Validator: coverage semantics, statuses, roll-ups and integrity checks."""
from app.scheduling import validate
from app.scheduling.calendar import Context
from app.scheduling.types import (
    EntryStatus,
    Role,
    Roster,
    RosterDuty,
    RosterEntry,
    SlotStatus,
    ValidationStatus,
)
from app.scheduling.validator import slot_status, worst

from .builder import D, GEN, MOR, NGT, PB

DAYS = [D(i) for i in range(1, 32)]


def _all_off(emps):
    return [RosterEntry(e, d, EntryStatus.WEEKLY_OFF) for e in emps for d in DAYS]


def test_slot_status_definitions():
    assert slot_status(0, 0) == SlotStatus.NOT_REQUIRED
    assert slot_status(2, 2) == SlotStatus.MET
    assert slot_status(2, 3) == SlotStatus.MET
    assert slot_status(2, 1) == SlotStatus.UNDERSTAFFED
    assert slot_status(2, 0) == SlotStatus.UNCOVERED


def test_rollup_precedence_uncovered_beats_understaffed():
    assert worst([SlotStatus.MET, SlotStatus.UNDERSTAFFED, SlotStatus.UNCOVERED]) == SlotStatus.UNCOVERED
    assert worst([SlotStatus.MET, SlotStatus.UNDERSTAFFED]) == SlotStatus.UNDERSTAFFED
    assert worst([SlotStatus.NOT_REQUIRED, SlotStatus.MET]) == SlotStatus.MET
    assert worst([SlotStatus.NOT_REQUIRED]) == SlotStatus.NOT_REQUIRED


def test_process_rollup_in_report_uses_precedence():
    pb = PB()
    a = pb.employee("Asha")
    bp = pb.bp("Glow", "CS")
    s_mor, s_ngt = pb.slot(bp, MOR, 2), pb.slot(bp, NGT, 1)
    asg = pb.assign(a, bp)
    prob = pb.build()
    entries = _all_off([a])
    entries[0] = RosterEntry(a, D(1), EntryStatus.WORK, MOR)
    rep = validate(prob, Roster(entries, [RosterDuty(a, D(1), s_mor, bp, MOR, asg, Role.PRIMARY)]))
    cov = {(c.slot_id, c.date): c.status for c in rep.coverage}
    assert cov[(s_mor, D(1))] == SlotStatus.UNDERSTAFFED
    assert cov[(s_ngt, D(1))] == SlotStatus.UNCOVERED
    assert rep.process_day[(bp, D(1))] == SlotStatus.UNCOVERED


def test_shift_specific_minimums_and_overrides():
    pb = PB()
    pb.employee("Asha")
    bp = pb.bp("Glow", "CS")
    s_mor, s_ngt = pb.slot(bp, MOR, 2), pb.slot(bp, NGT, 1)
    pb.override(s_mor, 1, dow=6)            # Sundays: 1 in the morning
    pb.override(s_ngt, 0, on=D(25))         # no night shift on 25 Dec
    pb.override(s_ngt, 3, on=D(31))         # NYE surge
    ctx = Context(pb.build())
    assert ctx.required(s_mor, D(7)) == 2   # Monday
    assert ctx.required(s_mor, D(6)) == 1   # Sunday override
    assert ctx.required(s_ngt, D(7)) == 1
    assert ctx.required(s_ngt, D(25)) == 0  # switched off
    assert ctx.required(s_ngt, D(31)) == 3  # specific date beats default


def test_unactivated_backup_counts_zero_activated_counts_one():
    pb = PB()
    owner, backup = pb.employee("Owner"), pb.employee("Backup")
    bp = pb.bp("Ember", "CS")
    s = pb.slot(bp, GEN, 1)
    pb.assign(owner, bp)
    b_asg = pb.assign(backup, bp, Role.BACKUP, load=40)
    prob = pb.build()

    rep = validate(prob, Roster(_all_off([owner, backup]), []))
    day1 = next(c for c in rep.coverage if c.date == D(1))
    assert day1.staffed == 0 and day1.backup_capacity == 1 and day1.status == SlotStatus.UNCOVERED

    entries = _all_off([owner, backup])
    idx = entries.index(RosterEntry(backup, D(1), EntryStatus.WEEKLY_OFF))
    entries[idx] = RosterEntry(backup, D(1), EntryStatus.WORK, GEN)
    rep = validate(prob, Roster(entries, [RosterDuty(backup, D(1), s, bp, GEN, b_asg, Role.BACKUP)]))
    day1 = next(c for c in rep.coverage if c.date == D(1))
    assert day1.staffed == 1 and day1.backup_count == 1 and day1.status == SlotStatus.MET


def test_coverage_pct_is_capped_so_overstaffing_cannot_hide_a_gap():
    pb = PB()
    a, b = pb.employee("Asha"), pb.employee("Bilal")
    bp1, bp2 = pb.bp("Lumo", "CS"), pb.bp("Kito", "CS")
    s1, s2 = pb.slot(bp1, GEN, 1), pb.slot(bp2, GEN, 1)
    a1, b1 = pb.assign(a, bp1, load=50), pb.assign(b, bp1, load=50)
    pb.assign(a, bp2, load=50)
    prob = pb.build()
    entries = [RosterEntry(e, d, EntryStatus.WORK, GEN) for e in (a, b) for d in DAYS]
    duties = [RosterDuty(e, d, s1, bp1, GEN, asg, Role.PRIMARY) for e, asg in ((a, a1), (b, b1)) for d in DAYS]
    rep = validate(prob, Roster(entries, duties))
    # bp1 overstaffed (2/1), bp2 empty (0/1) => 50%, not 100%.
    assert rep.coverage_pct == 50.0
    assert rep.status == ValidationStatus.INVALID  # 31 straight days also breaks rest rules


def test_work_without_duty_and_duty_on_off_day_are_invalid():
    pb = PB()
    a = pb.employee("Asha")
    bp = pb.bp("Lumo", "CS")
    s = pb.slot(bp, GEN, 1)
    asg = pb.assign(a, bp)
    prob = pb.build()
    entries = _all_off([a])
    entries[0] = RosterEntry(a, D(1), EntryStatus.WORK, GEN)           # no duty
    duties = [RosterDuty(a, D(2), s, bp, GEN, asg, Role.PRIMARY)]      # entry is WEEKLY_OFF
    rep = validate(prob, Roster(entries, duties))
    assert rep.issues_of("WORK_WITHOUT_DUTY")
    assert rep.issues_of("DUTY_ON_NON_WORK_DAY")
    assert rep.status == ValidationStatus.INVALID
    day2 = next(c for c in rep.coverage if c.date == D(2))
    assert day2.staffed == 0                                          # invalid duty never counts


def test_duty_during_leave_is_invalid_and_excluded_from_coverage():
    pb = PB()
    a = pb.employee("Asha")
    bp = pb.bp("Lumo", "CS")
    s = pb.slot(bp, GEN, 1)
    asg = pb.assign(a, bp)
    pb.leave(a, D(3), D(3))
    prob = pb.build()
    entries = _all_off([a])
    entries[2] = RosterEntry(a, D(3), EntryStatus.WORK, GEN)
    rep = validate(prob, Roster(entries, [RosterDuty(a, D(3), s, bp, GEN, asg, Role.PRIMARY)]))
    assert rep.issues_of("WORK_DURING_ABSENCE")
    assert next(c for c in rep.coverage if c.date == D(3)).staffed == 0


def test_ineligible_duties_are_detected():
    pb = PB()
    a, b = pb.employee("Asha"), pb.employee("Bilal")
    bp = pb.bp("Lumo", "CS")
    s_gen, s_mor = pb.slot(bp, GEN, 1), pb.slot(bp, MOR, 1)
    a_asg = pb.assign(a, bp, shift=GEN, to=D(10))      # expires 10 Dec, GEN only
    b_asg = pb.assign(b, bp, Role.BACKUP, load=30)
    prob = pb.build()
    entries = _all_off([a, b])
    em = {(x.employee_id, x.date): i for i, x in enumerate(entries)}
    for emp, day, shift in ((a, 15, GEN), (a, 2, MOR), (b, 3, GEN), (a, 4, GEN)):
        entries[em[(emp, D(day))]] = RosterEntry(emp, D(day), EntryStatus.WORK, shift)
    duties = [
        RosterDuty(a, D(15), s_gen, bp, GEN, a_asg, Role.PRIMARY),   # assignment expired
        RosterDuty(a, D(2), s_mor, bp, MOR, a_asg, Role.PRIMARY),    # shift not allowed
        RosterDuty(b, D(3), s_gen, bp, GEN, b_asg, Role.PRIMARY),    # role mismatch
        RosterDuty(a, D(4), s_gen, bp, GEN, b_asg, Role.BACKUP),     # someone else's assignment
    ]
    rep = validate(prob, Roster(entries, duties))
    reasons = " ".join(i.message for i in rep.issues_of("INELIGIBLE_DUTY"))
    assert len(rep.issues_of("INELIGIBLE_DUTY")) == 4
    assert "not effective" in reasons and "does not allow this shift" in reasons
    assert "differs from assignment role" in reasons and "another employee" in reasons


def test_missing_entries_and_weekly_rest_violations():
    pb = PB()
    a = pb.employee("Asha")
    bp = pb.bp("Lumo", "CS")
    s = pb.slot(bp, GEN, 1)
    asg = pb.assign(a, bp)
    prob = pb.build()
    entries = [RosterEntry(a, d, EntryStatus.WORK, GEN) for d in DAYS[:-1]]   # 31 Dec missing
    duties = [RosterDuty(a, d, s, bp, GEN, asg, Role.PRIMARY) for d in DAYS[:-1]]
    rep = validate(prob, Roster(entries, duties))
    assert rep.issues_of("MISSING_ENTRY")
    assert rep.issues_of("INSUFFICIENT_WEEKLY_REST")
    assert rep.issues_of("MAX_CONSECUTIVE_EXCEEDED")
    assert rep.status == ValidationStatus.INVALID


def test_fully_covered_requires_zero_gaps():
    pb = PB()
    a = pb.employee("Asha")
    bp = pb.bp("Lumo", "CS", mask=0)          # never operates
    pb.slot(bp, GEN, 1)
    pb.assign(a, bp)
    rep = validate(pb.build(), Roster(_all_off([a]), []))
    assert rep.status == ValidationStatus.FULLY_COVERED and rep.coverage_pct == 100.0

    pb2 = PB()
    a = pb2.employee("Asha")
    bp = pb2.bp("Lumo", "CS")
    pb2.slot(bp, GEN, 1)
    pb2.assign(a, bp)
    rep2 = validate(pb2.build(), Roster(_all_off([a]), []))
    assert rep2.status == ValidationStatus.PARTIALLY_COVERED
