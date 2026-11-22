"""End-to-end generation scenarios: solver + independent validator."""
from collections import Counter

from app.scheduling import generate
from app.scheduling.calendar import Context
from app.scheduling.types import (
    Category,
    EntryStatus,
    OffPolicy,
    Role,
    SlotStatus,
    ValidationStatus,
)

from .builder import D, GEN, MON_SAT, PB


def _work_days(roster, emp):
    return [e.date for e in roster.entries if e.employee_id == emp and e.status == EntryStatus.WORK]


def test_normal_month_two_people_sharing_365_day_process_is_fully_covered():
    pb = PB()
    a, b = pb.employee("Asha"), pb.employee("Bilal")
    cs = pb.bp("Lumo", "CS")
    pb.slot(cs, GEN, 1)
    pb.assign(a, cs)
    pb.assign(b, cs)
    out = generate(pb.build())

    assert out.status == ValidationStatus.FULLY_COVERED
    assert out.report.coverage_pct == 100.0
    assert out.report.hard_rule_violations == 0
    # Both get rest; offs never coincide on a required day.
    for emp in (a, b):
        assert len(_work_days(out.roster, emp)) <= 31 - 4


def test_single_resource_365_brand_without_backup_flags_rest_day_gaps():
    pb = PB()
    owner = pb.employee("Priya")
    for proc, load in (("CS", 60), ("ACC", 25), ("NDR", 15)):
        bp = pb.bp("Ember", proc)
        pb.slot(bp, GEN, 1)
        pb.assign(owner, bp, load=load)
    out = generate(pb.build())

    assert out.status == ValidationStatus.PARTIALLY_COVERED   # never silently "valid"
    assert out.report.hard_rule_violations == 0                # rest rules respected
    offs = [e.date for e in out.roster.entries if e.status != EntryStatus.WORK]
    assert len(offs) >= 4                                      # 31 days, max 6 consecutive
    gap_days = {c.date for c in out.report.gaps}
    assert gap_days == set(offs)
    # Every gap is explained: the only resource is resting.
    for issue in out.report.issues_of("UNCOVERED_SHIFT"):
        assert issue.details["gap_kind"] == "TRADE_OFF"
        assert "weekly off" in issue.details["people"][0]["reason"]
    # On working days the owner does all three processes (single-resource brand).
    by_day = out.roster.duties_by_day()
    for d in _work_days(out.roster, owner):
        assert len(by_day[(owner, d)]) == 3


def test_single_resource_brand_with_backup_is_fully_covered_by_activated_backup():
    pb = PB()
    owner, buddy = pb.employee("Priya"), pb.employee("Rohan")
    cs = pb.bp("Ember", "CS")
    pb.slot(cs, GEN, 1)
    pb.assign(owner, cs, load=100)
    own = pb.bp("Kito", "CS", mask=MON_SAT)
    pb.slot(own, GEN, 1)
    pb.assign(buddy, own, load=80)
    backup_asg = pb.assign(buddy, cs, Role.BACKUP, load=40)   # 80 + 40 > 100 but <= 125
    out = generate(pb.build())

    assert out.status == ValidationStatus.FULLY_COVERED
    backup_duties = [d for d in out.roster.duties if d.duty_type == Role.BACKUP]
    assert backup_duties, "backup must be activated on the owner's off days"
    for du in backup_duties:
        assert du.assignment_id == backup_asg and du.employee_id == buddy
        owner_entry = out.roster.entry_map()[(owner, du.date)]
        assert owner_entry.status != EntryStatus.WORK


def test_sole_resource_on_leave_without_backup_is_unavoidable_gap():
    pb = PB()
    owner = pb.employee("Priya")
    cs = pb.bp("Ember", "CS")
    pb.slot(cs, GEN, 1)
    pb.assign(owner, cs)
    pb.leave(owner, D(14), D(18))
    out = generate(pb.build())

    entries = out.roster.entry_map()
    for day in range(14, 19):
        assert entries[(owner, D(day))].status == EntryStatus.LEAVE
        assert not [x for x in out.roster.duties if x.date == D(day)]
    leave_gaps = [i for i in out.report.issues_of("UNCOVERED_SHIFT") if D(14) <= i.date <= D(18)]
    assert len(leave_gaps) == 5
    assert all(i.details["gap_kind"] == "UNAVOIDABLE" for i in leave_gaps)
    assert out.status == ValidationStatus.PARTIALLY_COVERED


def test_three_person_brand_absorbs_one_absence_through_backup():
    pb = PB()
    a, b, c = pb.employee("Anil"), pb.employee("Bea"), pb.employee("Chen")
    cs, acc = pb.bp("Hearth", "CS", MON_SAT), pb.bp("Hearth", "ACC", MON_SAT)
    pb.slot(cs, GEN, 1)
    acc_slot = pb.slot(acc, GEN, 1)
    pb.assign(a, cs, load=70)
    pb.assign(b, cs, load=70)
    pb.assign(b, acc, Role.BACKUP, load=40)
    pb.assign(c, acc, load=70)
    pb.leave(c, D(7), D(12))
    out = generate(pb.build())

    cov = {(x.slot_id, x.date): x for x in out.report.coverage}
    for day in range(7, 13):
        row = cov[(acc_slot, D(day))]
        assert row.status == SlotStatus.MET and row.backup_count == 1
    assert out.status == ValidationStatus.FULLY_COVERED


def test_required_coverage_beats_preferred_off_day():
    pb = PB()
    owner, buddy = pb.employee("Priya", preferred_off_days=((6, 3),)), pb.employee(
        "Rohan", fixed_off_days=frozenset({6}))
    cs = pb.bp("Ember", "CS")
    ember_slot = pb.slot(cs, GEN, 1)
    pb.assign(owner, cs, load=100)
    own = pb.bp("Kito", "CS")
    pb.slot(own, GEN, 1)
    pb.assign(buddy, own, load=70)
    pb.assign(buddy, cs, Role.BACKUP, load=50)
    out = generate(pb.build())

    # The backup can never work Sundays, so the owner must work Sundays despite the preference.
    sundays = [D(d) for d in (6, 13, 20, 27)]
    entries = out.roster.entry_map()
    assert all(entries[(owner, d)].status == EntryStatus.WORK for d in sundays)
    pref = out.report.issues_of("PREFERRED_OFF_DAY_WORKED")
    assert pref and pref[0].category == Category.PREFERENCE
    ember_gaps = [i for i in out.report.issues_of("UNCOVERED_SHIFT") if i.slot_id == ember_slot]
    assert all(i.date.weekday() != 6 for i in ember_gaps)   # Ember never loses Sunday cover


def test_preference_is_honoured_when_coverage_allows():
    pb = PB()
    owner = pb.employee("Priya", preferred_off_days=((6, 3),))
    cs = pb.bp("Ember", "CS", mask=MON_SAT)   # closed Sundays
    pb.slot(cs, GEN, 1)
    pb.assign(owner, cs)
    out = generate(pb.build())
    entries = out.roster.entry_map()
    assert all(entries[(owner, D(d))].status == EntryStatus.WEEKLY_OFF for d in (6, 13, 20, 27))
    assert out.status == ValidationStatus.FULLY_COVERED


def test_brand_and_employee_holiday_calendars_are_independent():
    pb = PB()
    pb.holiday(D(25), "Christmas", calendar=1)
    pb.holiday(D(1), "Regional Day", calendar=2)
    closed_owner = pb.employee("Ola")
    open_owner = pb.employee("Ivan", holiday_calendar_id=2)
    closed = pb.bp("Verde", "CS", holidays=False)          # brand calendar 1 (default)
    s_closed = pb.slot(closed, GEN, 1)
    pb.assign(closed_owner, closed)
    always = pb.bp("Orbit", "CS", holidays=True)
    s_open = pb.slot(always, GEN, 1)
    pb.assign(open_owner, always)
    prob = pb.build()
    ctx = Context(prob)

    assert ctx.required(s_closed, D(25)) == 0               # brand closed on its holiday
    assert ctx.required(s_open, D(25)) == 1                 # 365-day brand still requires cover
    assert ctx.required(s_open, D(1)) == 1                  # employee's regional holiday ≠ brand rule

    out = generate(prob)
    entries = out.roster.entry_map()
    assert entries[(closed_owner, D(25))].status == EntryStatus.HOLIDAY
    # Ivan's regional holiday: either worked (soft warning, comp-off) or off with status HOLIDAY.
    ivan = entries[(open_owner, D(1))]
    if ivan.status == EntryStatus.WORK:
        assert out.report.issues_of("HOLIDAY_WORKED")
    else:
        assert ivan.status == EntryStatus.HOLIDAY


def test_rest_policy_is_per_employee():
    pb = PB()
    five_day = OffPolicy(min_offs_per_week=2, max_consecutive_work_days=5)
    a, b = pb.employee("Five", policy=five_day), pb.employee("Six")
    cs = pb.bp("Lumo", "CS")
    pb.slot(cs, GEN, 1)
    pb.assign(a, cs)
    pb.assign(b, cs)
    out = generate(pb.build())
    assert out.report.hard_rule_violations == 0
    ctx = Context(pb.build())
    for week in ctx.weeks():
        if len(week) == 7:
            offs = sum(out.roster.entry_map()[(a, d)].status != EntryStatus.WORK for d in week)
            assert offs >= 2


def test_generation_is_deterministic(rich_problem):
    r1 = generate(rich_problem).roster
    r2 = generate(rich_problem).roster
    assert r1.entries == r2.entries and r1.duties == r2.duties


def test_solver_output_never_invalid(rich_problem):
    out = generate(rich_problem)
    assert out.status in (ValidationStatus.FULLY_COVERED, ValidationStatus.PARTIALLY_COVERED)
    assert out.report.hard_rule_violations == 0
    # Exactly one entry per active employee per day.
    counts = Counter((e.employee_id, e.date) for e in out.roster.entries)
    assert set(counts.values()) == {1}
    assert len(counts) == len(rich_problem.employees) * 31
