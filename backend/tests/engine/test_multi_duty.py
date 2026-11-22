"""Multiple compatible duties per day, load caps, shifts and double counting."""
from collections import defaultdict

from app.scheduling import generate, validate
from app.scheduling.types import (
    EntryStatus,
    Role,
    Roster,
    RosterDuty,
    RosterEntry,
    SlotStatus,
    ValidationStatus,
)

from .builder import D, GEN, MOR, NGT, PB


def test_one_employee_three_compatible_duties_across_two_brands_same_day():
    pb = PB()
    meera = pb.employee("Meera")
    lumo_cs, lumo_ndr, kito_cs = pb.bp("Lumo", "CS"), pb.bp("Lumo", "NDR"), pb.bp("Kito", "CS")
    slots = [pb.slot(bp, GEN, 1) for bp in (lumo_cs, lumo_ndr, kito_cs)]
    for bp, load in ((lumo_cs, 40), (lumo_ndr, 20), (kito_cs, 40)):
        pb.assign(meera, bp, load=load)
    prob = pb.build()
    out = generate(prob)

    by_day = out.roster.duties_by_day()
    work_days = [e.date for e in out.roster.entries if e.status == EntryStatus.WORK]
    assert work_days
    for d in work_days:
        duties = by_day[(meera, d)]
        assert sorted(x.slot_id for x in duties) == sorted(slots)
        assert {x.shift_id for x in duties} == {GEN}                  # one shift
        assert sum(prob.assignments[x.assignment_id - 1].load_pct for x in duties) == 100
    cov = {(c.slot_id, c.date): c for c in out.report.coverage}
    for d in work_days:
        for s in slots:
            assert cov[(s, d)].staffed == 1 and cov[(s, d)].status == SlotStatus.MET
    assert out.report.hard_rule_violations == 0
    assert not out.report.issues_of("DUPLICATE_DUTY", "LOAD_CAP_EXCEEDED")


def test_shared_process_counts_each_person_once():
    pb = PB()
    a, b = pb.employee("Asha"), pb.employee("Bilal")
    shared = pb.bp("Urban", "CS")
    s_shared = pb.slot(shared, GEN, 2)
    other = pb.bp("Kito", "CS")
    s_other = pb.slot(other, GEN, 1)
    pb.assign(a, shared, load=50)
    pb.assign(b, shared, load=50)
    pb.assign(a, other, load=50)
    out = generate(pb.build())

    for c in out.report.coverage:
        assert c.staffed <= {s_shared: 2, s_other: 1}[c.slot_id]
    # Coverage numbers equal distinct people in the duty table.
    people = defaultdict(set)
    for du in out.roster.duties:
        people[(du.slot_id, du.date)].add(du.employee_id)
    for c in out.report.coverage:
        assert c.staffed == len(people.get((c.slot_id, c.date), set()))


def test_duplicate_duty_is_invalid_and_not_double_counted():
    pb = PB()
    a = pb.employee("Asha")
    bp = pb.bp("Urban", "CS")
    s = pb.slot(bp, GEN, 2)
    asg = pb.assign(a, bp, load=50)
    prob = pb.build()
    entries = [RosterEntry(a, d, EntryStatus.WORK, GEN) for d in [D(i) for i in range(1, 32)]]
    dup = RosterDuty(a, D(1), s, bp, GEN, asg, Role.PRIMARY)
    roster = Roster(entries, [dup, dup] + [RosterDuty(a, D(i), s, bp, GEN, asg, Role.PRIMARY)
                                          for i in range(2, 32)])
    rep = validate(prob, roster)
    assert rep.issues_of("DUPLICATE_DUTY")
    assert rep.status == ValidationStatus.INVALID
    day1 = next(c for c in rep.coverage if c.date == D(1))
    assert day1.staffed == 1 and day1.status == SlotStatus.UNDERSTAFFED


def test_incompatible_primary_shifts_one_shift_per_day_and_gap_flagged():
    pb = PB()
    nina = pb.employee("Nina")
    day_bp, night_bp = pb.bp("Glow", "NDR"), pb.bp("Glow", "CS")
    s_day, s_night = pb.slot(day_bp, GEN, 1), pb.slot(night_bp, NGT, 1)
    pb.assign(nina, day_bp, load=30)
    pb.assign(nina, night_bp, load=70)
    out = generate(pb.build())

    for (e, d), duties in out.roster.duties_by_day().items():
        assert len({x.shift_id for x in duties}) == 1
    assert out.solve.presolve.issues and any(
        i.type == "INCOMPATIBLE_PRIMARY_SHIFTS" for i in out.report.issues)
    assert out.status == ValidationStatus.PARTIALLY_COVERED
    assert out.report.hard_rule_violations == 0


def test_validator_rejects_duties_on_two_shifts_same_day():
    pb = PB()
    nina = pb.employee("Nina")
    day_bp, night_bp = pb.bp("Glow", "NDR"), pb.bp("Glow", "CS")
    s_day, s_night = pb.slot(day_bp, GEN, 1), pb.slot(night_bp, NGT, 1)
    a1, a2 = pb.assign(nina, day_bp, load=30), pb.assign(nina, night_bp, load=70)
    prob = pb.build()
    out = generate(prob)
    roster = out.roster
    d = next(e.date for e in roster.entries if e.status == EntryStatus.WORK)
    entry = roster.entry_map()[(nina, d)]
    extra_slot, extra_bp, extra_a, extra_shift = (
        (s_night, night_bp, a2, NGT) if entry.shift_id == GEN else (s_day, day_bp, a1, GEN))
    roster.duties = [x for x in roster.duties if not (x.employee_id == nina and x.date == d)] + [
        RosterDuty(nina, d, s_day if entry.shift_id == GEN else s_night,
                   day_bp if entry.shift_id == GEN else night_bp, entry.shift_id,
                   a1 if entry.shift_id == GEN else a2, Role.PRIMARY),
        RosterDuty(nina, d, extra_slot, extra_bp, extra_shift, extra_a, Role.PRIMARY),
    ]
    rep = validate(prob, roster)
    assert rep.issues_of("DUTY_SHIFT_MISMATCH")
    assert rep.status == ValidationStatus.INVALID


def test_load_cap_limits_primary_duties_and_reports_over_allocation():
    pb = PB()
    a = pb.employee("Asha")
    b1, b2 = pb.bp("Lumo", "CS"), pb.bp("Kito", "CS")
    pb.slot(b1, GEN, 1)
    pb.slot(b2, GEN, 1)
    pb.assign(a, b1, load=60)
    pb.assign(a, b2, load=60)
    out = generate(pb.build())
    for duties in out.roster.duties_by_day().values():
        assert len(duties) == 1                                   # 60 + 60 > 100
    assert out.report.issues_of("OVER_ALLOCATED")
    assert out.report.hard_rule_violations == 0


def test_backup_stretch_allows_up_to_cap_plus_stretch_only():
    def scenario(backup_load):
        pb = PB()
        owner, buddy = pb.employee("Owner"), pb.employee("Buddy")
        cs = pb.bp("Ember", "CS")
        pb.slot(cs, GEN, 1)
        pb.assign(owner, cs)
        own = pb.bp("Kito", "CS")
        pb.slot(own, GEN, 1)
        pb.assign(buddy, own, load=100)
        pb.assign(buddy, cs, Role.BACKUP, load=backup_load)
        return generate(pb.build())

    ok = scenario(25)      # 100 + 25 == cap + stretch
    assert any(d.duty_type == Role.BACKUP for d in ok.roster.duties)
    too_big = scenario(30)  # 130 > 125: never activated
    assert not any(d.duty_type == Role.BACKUP for d in too_big.roster.duties)


def test_night_then_morning_is_blocked_by_min_rest():
    pb = PB()
    a, b = pb.employee("Asha"), pb.employee("Bilal")
    bp = pb.bp("Glow", "CS")
    pb.slot(bp, MOR, 1)
    pb.slot(bp, NGT, 1)
    pb.assign(a, bp)
    pb.assign(b, bp)
    out = generate(pb.build())
    entries = out.roster.entry_map()
    for emp in (a, b):
        for day in range(1, 31):
            today, tomorrow = entries[(emp, D(day))], entries[(emp, D(day + 1))]
            assert not (today.shift_id == NGT and tomorrow.shift_id == MOR)
    assert not out.report.issues_of("MIN_REST_VIOLATED")


def test_validator_flags_night_then_morning():
    pb = PB()
    a = pb.employee("Asha")
    bp = pb.bp("Glow", "CS")
    s_mor, s_ngt = pb.slot(bp, MOR, 1), pb.slot(bp, NGT, 1)
    asg = pb.assign(a, bp)
    prob = pb.build()
    entries, duties = [], []
    for i in range(1, 32):
        shift, slot = (NGT, s_ngt) if i == 1 else (MOR, s_mor)
        status = EntryStatus.WORK if i <= 2 else EntryStatus.WEEKLY_OFF
        entries.append(RosterEntry(a, D(i), status, shift if status == EntryStatus.WORK else None))
        if status == EntryStatus.WORK:
            duties.append(RosterDuty(a, D(i), slot, bp, shift, asg, Role.PRIMARY))
    rep = validate(prob, Roster(entries, duties))
    assert rep.issues_of("MIN_REST_VIOLATED")
    assert rep.status == ValidationStatus.INVALID
