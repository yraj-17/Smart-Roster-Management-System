"""PostgreSQL-level guarantees: composite FKs, WORK-only duties, exclusion
constraint, eligibility trigger, no double counting, single published version."""
from datetime import date

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import models as m
from app.scheduling import validate
from app.services.engine_adapter import load_problem, load_roster


def _version(db) -> m.RosterVersion:
    return db.scalar(select(m.RosterVersion).order_by(m.RosterVersion.id))


def _a_duty(db) -> m.RosterDuty:
    return db.scalar(select(m.RosterDuty).where(m.RosterDuty.version_id == _version(db).id)
                     .order_by(m.RosterDuty.id))


def _expect_db_error(db, fn, exc=IntegrityError):
    with pytest.raises(exc):
        with db.begin_nested():
            fn()
            db.flush()


def test_entry_with_duties_cannot_become_non_work(db):
    duty = _a_duty(db)
    for status in ("LEAVE", "WEEKLY_OFF", "COMP_OFF", "HOLIDAY", "UNAVAILABLE"):
        _expect_db_error(db, lambda st=status: db.execute(
            update(m.RosterEntry).where(m.RosterEntry.id == duty.entry_id).values(status=st, shift_id=None)))


def test_entry_shift_cannot_change_under_its_duties(db):
    duty = _a_duty(db)
    other_shift = db.scalar(select(m.Shift.id).where(m.Shift.id != duty.shift_id))
    _expect_db_error(db, lambda: db.execute(
        update(m.RosterEntry).where(m.RosterEntry.id == duty.entry_id).values(shift_id=other_shift)))


def test_status_change_succeeds_when_duties_removed_in_same_transaction(db):
    duty = _a_duty(db)
    with db.begin_nested():
        db.query(m.RosterDuty).filter(m.RosterDuty.entry_id == duty.entry_id).delete()
        db.execute(update(m.RosterEntry).where(m.RosterEntry.id == duty.entry_id)
                   .values(status="LEAVE", shift_id=None, source="MANUAL"))
    assert db.get(m.RosterEntry, duty.entry_id).status == "LEAVE"


def _clone(duty: m.RosterDuty, **changes) -> m.RosterDuty:
    cols = {c.name: getattr(duty, c.name) for c in m.RosterDuty.__table__.columns
            if c.name not in ("id", "created_at", "updated_at")}
    cols.update(changes)
    return m.RosterDuty(**cols)


def test_duty_cannot_claim_non_work_entry_status(db):
    duty = _a_duty(db)
    _expect_db_error(db, lambda: db.add(_clone(duty, entry_status="LEAVE")))


def test_duty_copied_columns_must_match_entry(db):
    duty = _a_duty(db)
    _expect_db_error(db, lambda: db.add(_clone(duty, date=date(2026, 12, 31) if duty.date.day != 31
                                               else date(2026, 12, 1))))
    other_emp = db.scalar(select(m.Employee.id).where(m.Employee.id != duty.employee_id))
    _expect_db_error(db, lambda: db.add(_clone(duty, employee_id=other_emp)))


def test_duty_slot_must_belong_to_its_brand_process(db):
    duty = _a_duty(db)
    foreign_slot = db.scalar(select(m.BrandProcessShift).where(
        m.BrandProcessShift.brand_process_id != duty.brand_process_id,
        m.BrandProcessShift.shift_id == duty.shift_id))
    _expect_db_error(db, lambda: db.add(_clone(duty, brand_process_shift_id=foreign_slot.id)))


def test_duty_type_must_equal_assignment_role(db):
    duty = _a_duty(db)
    flipped = "BACKUP" if duty.duty_type == "PRIMARY" else "PRIMARY"
    _expect_db_error(db, lambda: db.add(_clone(duty, duty_type=flipped)))


def test_no_double_counting_same_brand_process_same_day(db):
    # Glow Theory CS has GEN and NGT slots: a second duty on the same brand-process is rejected.
    glow_cs = db.scalar(select(m.RosterDuty).join(m.BrandProcess, m.BrandProcess.id == m.RosterDuty.brand_process_id)
                        .join(m.Brand).where(m.Brand.code == "GLOW").order_by(m.RosterDuty.id))
    other = db.scalar(select(m.BrandProcessShift).where(
        m.BrandProcessShift.brand_process_id == glow_cs.brand_process_id,
        m.BrandProcessShift.id != glow_cs.brand_process_shift_id))
    if other is not None:
        _expect_db_error(db, lambda: db.add(_clone(glow_cs, brand_process_shift_id=other.id,
                                                   shift_id=other.shift_id)))
    _expect_db_error(db, lambda: db.add(_clone(glow_cs)))


def test_trigger_rejects_duty_outside_assignment_dates(db):
    ended = db.scalar(select(m.Assignment).where(m.Assignment.effective_to.is_not(None)))
    entry = db.scalar(select(m.RosterEntry).where(m.RosterEntry.employee_id == ended.employee_id,
                                                  m.RosterEntry.status == "WORK"))
    slot = db.scalar(select(m.BrandProcessShift).where(
        m.BrandProcessShift.brand_process_id == ended.brand_process_id,
        m.BrandProcessShift.shift_id == entry.shift_id))
    duty = m.RosterDuty(version_id=entry.version_id, entry_id=entry.id, employee_id=entry.employee_id,
                        date=entry.date, shift_id=entry.shift_id, entry_status="WORK",
                        brand_process_shift_id=slot.id, brand_process_id=ended.brand_process_id,
                        assignment_id=ended.id, duty_type=ended.role, source="MANUAL")
    with pytest.raises(DBAPIError, match="not effective"):
        with db.begin_nested():
            db.add(duty)
            db.flush()


def test_trigger_rejects_shift_not_allowed_by_assignment(db):
    restricted = db.scalar(select(m.Assignment).where(m.Assignment.shift_id.is_not(None),
                                                      m.Assignment.role == "PRIMARY"))
    slot = db.scalar(select(m.BrandProcessShift).where(
        m.BrandProcessShift.brand_process_id == restricted.brand_process_id,
        m.BrandProcessShift.shift_id != restricted.shift_id))
    entry = db.scalar(select(m.RosterEntry).where(m.RosterEntry.employee_id == restricted.employee_id,
                                                  m.RosterEntry.status == "WORK"))
    db.query(m.RosterDuty).filter(m.RosterDuty.entry_id == entry.id).delete()
    db.execute(update(m.RosterEntry).where(m.RosterEntry.id == entry.id).values(shift_id=slot.shift_id))
    duty = m.RosterDuty(version_id=entry.version_id, entry_id=entry.id, employee_id=entry.employee_id,
                        date=entry.date, shift_id=slot.shift_id, entry_status="WORK",
                        brand_process_shift_id=slot.id, brand_process_id=restricted.brand_process_id,
                        assignment_id=restricted.id, duty_type="PRIMARY", source="MANUAL")
    assert slot.shift_id != restricted.shift_id
    with pytest.raises(DBAPIError, match="does not allow shift"):
        with db.begin_nested():
            db.add(duty)
            db.flush()


def test_overlapping_assignments_for_same_employee_and_process_rejected(db):
    a = db.scalar(select(m.Assignment).where(m.Assignment.effective_to.is_(None)))
    for role in ("PRIMARY", "BACKUP"):   # neither role may overlap an existing assignment
        _expect_db_error(db, lambda r=role: db.add(m.Assignment(
            employee_id=a.employee_id, brand_process_id=a.brand_process_id, role=r, load_pct=10,
            effective_from=date(2026, 12, 1))))
    # A non-overlapping, later assignment after the current one is closed is fine.
    with db.begin_nested():
        db.execute(update(m.Assignment).where(m.Assignment.id == a.id).values(effective_to=date(2026, 12, 31)))
        db.add(m.Assignment(employee_id=a.employee_id, brand_process_id=a.brand_process_id, role="BACKUP",
                            load_pct=10, effective_from=date(2027, 1, 1)))
        db.flush()


def test_only_one_published_version_per_month(db):
    v = _version(db)
    with db.begin_nested():
        db.execute(update(m.RosterVersion).where(m.RosterVersion.id == v.id).values(status="PUBLISHED"))
    _expect_db_error(db, lambda: db.add(m.RosterVersion(
        plan_id=v.plan_id, version_no=99, kind="MANUAL_CLONE", status="PUBLISHED",
        validation_status="FULLY_COVERED")))
    with db.begin_nested():   # drafts are unlimited
        db.add(m.RosterVersion(plan_id=v.plan_id, version_no=98, kind="MANUAL_CLONE", status="DRAFT",
                               validation_status="STALE"))
        db.flush()


def test_shift_iff_work_check(db):
    entry = db.scalar(select(m.RosterEntry).where(m.RosterEntry.status == "WEEKLY_OFF"))
    shift = db.scalar(select(m.Shift.id))
    _expect_db_error(db, lambda: db.execute(
        update(m.RosterEntry).where(m.RosterEntry.id == entry.id).values(shift_id=shift)))


def test_persisted_version_round_trips_through_validator(db):
    v = _version(db)
    problem = load_problem(db, 2026, 12)
    rep = validate(problem, load_roster(db, v.id))
    assert rep.status.value == v.validation_status
    assert float(v.coverage_pct) == rep.coverage_pct
    stored = db.query(m.RosterCoverage).filter(m.RosterCoverage.version_id == v.id).count()
    assert stored == len(rep.coverage)
    assert rep.hard_rule_violations == 0


def test_seed_reflects_required_staffing_patterns(db):
    brands = db.scalars(select(m.Brand)).all()
    primaries = {}
    for a in db.scalars(select(m.Assignment).where(m.Assignment.role == "PRIMARY")):
        bp = db.get(m.BrandProcess, a.brand_process_id)
        primaries.setdefault(bp.brand_id, set()).add(a.employee_id)
    single = [b for b in brands if len(primaries.get(b.id, ())) == 1]
    multi = [b for b in brands if len(primaries.get(b.id, ())) > 1]
    assert db.query(m.Employee).count() >= 30
    assert 0.75 <= len(single) / len(brands) <= 0.85
    assert all(2 <= len(primaries[b.id]) <= 3 for b in multi)
    assert db.query(m.Pod).filter(m.Pod.lead_employee_id.is_not(None)).count() == db.query(m.Pod).count()


def test_load_problem_excludes_ended_assignments_and_unapproved_leave(db):
    problem = load_problem(db, 2026, 12)
    ended = db.scalar(select(m.Assignment).where(m.Assignment.effective_to.is_not(None)))
    assert ended.id not in {a.id for a in problem.assignments}
    requested = db.scalar(select(m.Leave).where(m.Leave.status == "REQUESTED"))
    assert not any(ab.employee_id == requested.employee_id and ab.start == requested.start_date
                   for ab in problem.absences)


def test_seed_if_empty_never_duplicates_or_wipes(db):
    from app.seed.seed import seed_if_empty
    before = {t: db.query(t).count() for t in (m.Employee, m.Brand, m.Assignment, m.RosterVersion)}
    assert seed_if_empty(db) is None                       # data present: untouched
    assert {t: db.query(t).count() for t in before} == before
    assert before[m.RosterVersion] >= 1                    # existing rosters survived


def test_seed_if_empty_seeds_an_empty_database(db):
    from app.seed.seed import reset, seed_if_empty
    reset(db)                                              # inside the test's rolled-back transaction
    summary = seed_if_empty(db)
    assert summary and summary["employees"] == 32 and summary["single_resource_brands"] == 21
    assert seed_if_empty(db) is None                       # second deploy: no duplicates
    assert db.query(m.Employee).count() == 32
