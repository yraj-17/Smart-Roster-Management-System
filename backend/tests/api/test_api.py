"""HTTP-level tests of the main workflows against the seeded December 2026 roster."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m


@pytest.fixture
def client(db):
    from app.api.deps import get_session
    from app.main import app

    def _session():
        try:
            yield db
        finally:
            if not db.is_active:  # a request failed mid-flush: return to the test's savepoint
                db.rollback()

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        c.headers["X-Actor"] = "test.manager"
        yield c
    app.dependency_overrides.clear()


def _version(db) -> m.RosterVersion:
    return db.scalar(select(m.RosterVersion).order_by(m.RosterVersion.id))


def _emp(db, code: str) -> m.Employee:
    return db.scalar(select(m.Employee).where(m.Employee.code == code))


def _slot(db, brand: str, process: str, shift: str = "GEN") -> m.BrandProcessShift:
    return db.scalar(select(m.BrandProcessShift).join(m.BrandProcess).join(m.Brand).join(m.Process)
                     .join(m.Shift, m.Shift.id == m.BrandProcessShift.shift_id)
                     .where(m.Brand.code == brand, m.Process.code == process, m.Shift.code == shift))


def _entry(db, version_id: int, emp_id: int, d: date) -> m.RosterEntry:
    return db.scalar(select(m.RosterEntry).where(m.RosterEntry.version_id == version_id,
                                                 m.RosterEntry.employee_id == emp_id, m.RosterEntry.date == d))


def _work_day(db, version_id: int, emp_id: int) -> m.RosterEntry:
    return db.scalar(select(m.RosterEntry).where(m.RosterEntry.version_id == version_id,
                                                 m.RosterEntry.employee_id == emp_id,
                                                 m.RosterEntry.status == "WORK").order_by(m.RosterEntry.date))


# ── master data ──────────────────────────────────────────────────────────────
def test_master_data_crud_and_validation(client, db):
    proc = client.get("/api/processes").json()
    assert {p["code"] for p in proc} >= {"CS", "ACC", "NDR", "RET"}
    b = client.post("/api/brands", json={"code": "NEWCO", "name": "NewCo"}).json()
    cs = next(p for p in proc if p["code"] == "CS")
    bp = client.post("/api/brand-processes", json={"brand_id": b["id"], "process_id": cs["id"],
                                                    "operating_days_mask": 63}).json()
    gen = next(s for s in client.get("/api/shifts").json() if s["code"] == "GEN")
    slot = client.post("/api/slots", json={"brand_process_id": bp["id"], "shift_id": gen["id"],
                                            "default_min_staff": 1})
    assert slot.status_code == 201
    emp = _emp(db, "E003")
    payload = {"employee_id": emp.id, "brand_process_id": bp["id"], "role": "BACKUP", "load_pct": 20,
               "effective_from": "2026-12-01"}
    assert client.post("/api/assignments", json=payload).status_code == 201
    # Overlapping assignment for the same employee/brand-process is rejected by the exclusion constraint.
    dup = client.post("/api/assignments", json={**payload, "role": "PRIMARY"})
    assert dup.status_code == 409 and "overlapping" in dup.json()["error"]["message"]
    # Coverage override must target exactly one of weekday/date.
    bad = client.post("/api/coverage-requirements", json={"brand_process_shift_id": slot.json()["id"],
                                                          "day_of_week": 5, "specific_date": "2026-12-05",
                                                          "min_staff": 2})
    assert bad.status_code == 422
    # Deactivate instead of delete for brands.
    assert client.delete(f"/api/brands/{b['id']}").json()["deactivated"] is True


def test_employee_with_off_day_preferences(client, db):
    pod = client.get("/api/pods").json()[0]
    pol = client.get("/api/weekly-off-policies").json()[0]
    body = {"code": "E900", "name": "Test Person", "email": "test.person@example-cx.test", "pod_id": pod["id"],
            "weekly_off_policy_id": pol["id"],
            "off_days": [{"day_of_week": 6, "kind": "FIXED"}, {"day_of_week": 2, "kind": "PREFERRED", "priority": 3}]}
    r = client.post("/api/employees", json=body)
    assert r.status_code == 201 and len(r.json()["off_days"]) == 2
    dup_day = client.post("/api/employees", json={**body, "code": "E901", "email": "x@example-cx.test",
                                                  "off_days": [{"day_of_week": 1, "kind": "FIXED"},
                                                               {"day_of_week": 1, "kind": "PREFERRED"}]})
    assert dup_day.status_code == 422
    assert client.post("/api/employees", json={**body, "email": "other@example-cx.test"}).status_code == 409


# ── generation and views ─────────────────────────────────────────────────────
def test_generate_creates_new_draft_version_and_keeps_history(client, db):
    r = client.post("/api/roster-plans/2026/12/generate", json={"notes": "second run"})
    assert r.status_code == 201
    v = r.json()
    assert v["version_no"] == 2 and v["status"] == "DRAFT"
    assert v["validation_status"] == "PARTIALLY_COVERED"
    assert len(client.get("/api/roster-plans/2026/12/versions").json()) == 2


@pytest.mark.parametrize("view,ref", [("company", None), ("pod", "pod"), ("brand", "HEARTH"),
                                      ("process", "CS"), ("employee", "E002")])
def test_roster_views(client, db, view, ref):
    v = _version(db)
    ref_id = None
    if ref == "pod":
        ref_id = db.scalar(select(m.Pod.id))
    elif view == "brand":
        ref_id = db.scalar(select(m.Brand.id).where(m.Brand.code == ref))
    elif view == "process":
        ref_id = db.scalar(select(m.Process.id).where(m.Process.code == ref))
    elif view == "employee":
        ref_id = _emp(db, ref).id
    params = {"view": view, **({"ref_id": ref_id} if ref_id is not None else {})}
    r = client.get(f"/api/versions/{v.id}/roster", params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["days"]) == 31 and body["employees"] and body["coverage"]
    assert all(len(row["cells"]) == 31 for row in body["employees"])
    if view == "brand":
        assert {row["code"] for row in body["employees"]} == {"E007", "E008", "E009"}
    if view == "employee":
        assert len(body["employees"]) == 1


def test_day_view_and_export(client, db):
    v = _version(db)
    day = client.get(f"/api/versions/{v.id}/days/2026-12-15").json()
    assert day["working"] and any(g["brand"] == "Ember Candles" for g in day["gaps"])
    csv_text = client.get(f"/api/versions/{v.id}/export.csv").text
    assert csv_text.startswith("employee_code,employee,pod,date,status,shift,duties")
    assert csv_text.count("\n") == 32 * 31 + 1


# ── edits ────────────────────────────────────────────────────────────────────
def test_edit_day_to_leave_removes_duties_then_revalidates(client, db):
    v = _version(db)
    rahul = _emp(db, "E002")
    e = _work_day(db, v.id, rahul.id)
    r = client.put(f"/api/versions/{v.id}/entries/{e.id}", json={"status": "WEEKLY_OFF"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entry"]["status"] == "WEEKLY_OFF" and body["entry"]["source"] == "MANUAL"
    assert body["duties"] == []
    gaps = [i for i in body["issues_on_day"] if i["category"] == "COVERAGE"]
    assert any("Lumo Skincare/CS" in i["message"] for i in gaps)   # his brand loses cover that day
    assert body["version"]["validation_status"] == "PARTIALLY_COVERED"
    assert db.scalar(select(m.AuditLog).where(m.AuditLog.entity_type == "roster_entry",
                                              m.AuditLog.entity_id == e.id)) is not None


def test_edit_rejects_shift_clash_ineligible_load_and_absence(client, db):
    v = _version(db)
    rahul = _emp(db, "E002")
    e = _work_day(db, v.id, rahul.id)
    lumo_cs, glow_ngt = _slot(db, "LUMO", "CS"), _slot(db, "GLOW", "CS", "NGT")
    # Duty on a slot whose shift differs from the day's shift.
    r = client.put(f"/api/versions/{v.id}/entries/{e.id}",
                   json={"status": "WORK", "shift_id": lumo_cs.shift_id, "slot_ids": [lumo_cs.id, glow_ngt.id]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "shift_clash"
    # A brand-process he is not assigned to.
    kito = _slot(db, "KITO", "CS")
    r = client.put(f"/api/versions/{v.id}/entries/{e.id}",
                   json={"status": "WORK", "shift_id": kito.shift_id, "slot_ids": [kito.id]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_eligible"
    # Load cap: Harsh's primaries add to 130%.
    harsh = _emp(db, "E024")
    he = _work_day(db, v.id, harsh.id)
    slots = [_slot(db, "MONSOON", "CS").id, _slot(db, "MONSOON", "NDR").id, _slot(db, "CRATE", "CS").id]
    r = client.put(f"/api/versions/{v.id}/entries/{he.id}",
                   json={"status": "WORK", "shift_id": lumo_cs.shift_id, "slot_ids": slots})
    assert r.status_code == 409 and r.json()["error"]["code"] == "load_cap"
    # Working on an approved leave day.
    riya = _emp(db, "E023")
    le = _entry(db, v.id, riya.id, date(2026, 12, 15))
    ember = _slot(db, "EMBER", "CS")
    r = client.put(f"/api/versions/{v.id}/entries/{le.id}",
                   json={"status": "WORK", "shift_id": ember.shift_id, "slot_ids": [ember.id]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "employee_absent"
    # Schema-level: WORK without duties is invalid input.
    assert client.put(f"/api/versions/{v.id}/entries/{e.id}",
                      json={"status": "WORK", "shift_id": lumo_cs.shift_id}).status_code == 422


def test_rest_rule_breach_is_allowed_but_marks_version_invalid(client, db):
    v = _version(db)
    rahul = _emp(db, "E002")
    lumo = [_slot(db, "LUMO", p).id for p in ("CS", "ACC")]
    gen = _slot(db, "LUMO", "CS").shift_id
    # Work every day 14-20 Dec (Mon-Sun): breaks the weekly-off rule.
    for day in range(14, 21):
        e = _entry(db, v.id, rahul.id, date(2026, 12, day))
        r = client.put(f"/api/versions/{v.id}/entries/{e.id}",
                       json={"status": "WORK", "shift_id": gen, "slot_ids": lumo})
        assert r.status_code == 200, r.text
    assert r.json()["version"]["validation_status"] == "INVALID"
    pub = client.post(f"/api/versions/{v.id}/publish")
    assert pub.status_code == 409 and pub.json()["error"]["code"] == "not_publishable"


def test_add_and_remove_duty(client, db):
    v = _version(db)
    ananya = _emp(db, "E001")
    e = _work_day(db, v.id, ananya.id)
    lumo_cs = _slot(db, "LUMO", "CS")
    r = client.post(f"/api/versions/{v.id}/duties",
                    json={"employee_id": ananya.id, "date": e.date.isoformat(), "brand_process_shift_id": lumo_cs.id})
    assert r.status_code == 201, r.text
    added = next(d for d in r.json()["duties"] if d["slot_id"] == lumo_cs.id)
    assert added["duty_type"] == "BACKUP"
    r = client.delete(f"/api/versions/{v.id}/duties/{added['id']}")
    assert r.status_code == 200 and all(d["slot_id"] != lumo_cs.id for d in r.json()["duties"])


# ── conflicts, suggestions, publishing ───────────────────────────────────────
def test_apply_suggestion_closes_gap(client, db):
    v = _version(db)
    rahul = _emp(db, "E002")
    e = _work_day(db, v.id, rahul.id)
    client.put(f"/api/versions/{v.id}/entries/{e.id}", json={"status": "WEEKLY_OFF"})
    gaps = client.get(f"/api/versions/{v.id}/conflicts",
                      params={"category": "COVERAGE", "status": "OPEN", "day": e.date.isoformat()}).json()
    lumo_gap = next(g for g in gaps if "Lumo Skincare/CS" in g["message"])
    sugg = client.get(f"/api/conflicts/{lumo_gap['id']}/suggestions").json()
    assert sugg, "the trained backup should be suggested"
    r = client.post(f"/api/conflicts/{lumo_gap['id']}/apply-suggestion",
                    json={"employee_id": sugg[0]["employee_id"], "action": sugg[0]["action"]})
    assert r.status_code == 200, r.text
    assert r.json()["conflict"]["status"] == "RESOLVED"


def test_publish_requires_acknowledged_gaps_then_supersedes(client, db):
    v = _version(db)
    r = client.post(f"/api/versions/{v.id}/publish")
    assert r.status_code == 409 and r.json()["error"]["code"] == "open_gaps"
    for c in client.get(f"/api/versions/{v.id}/conflicts", params={"category": "COVERAGE", "status": "OPEN"}).json():
        a = client.post(f"/api/conflicts/{c['id']}/acknowledge", json={"reason": "Client informed of reduced cover"})
        assert a.status_code == 200
    # Rule violations cannot be acknowledged away.
    pref = client.get(f"/api/versions/{v.id}/conflicts", params={"category": "PREFERENCE"}).json()
    assert pref  # soft issues exist and may be acknowledged
    pub = client.post(f"/api/versions/{v.id}/publish", json={"reason": "December roster"})
    assert pub.status_code == 200, pub.text
    assert pub.json()["version"]["status"] == "PUBLISHED"
    # Published versions are immutable.
    e = _work_day(db, v.id, _emp(db, "E002").id)
    r = client.put(f"/api/versions/{v.id}/entries/{e.id}", json={"status": "WEEKLY_OFF"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "version_immutable"
    # Clone -> draft (acknowledgements carried) -> publish supersedes the first.
    clone = client.post(f"/api/versions/{v.id}/clone").json()
    assert clone["status"] == "DRAFT" and clone["parent_version_id"] == v.id
    pub2 = client.post(f"/api/versions/{clone['id']}/publish")
    assert pub2.status_code == 200, pub2.text
    assert pub2.json()["superseded_version_id"] == v.id
    assert client.get(f"/api/versions/{v.id}").json()["status"] == "SUPERSEDED"


# ── change management ────────────────────────────────────────────────────────
def test_leave_after_generation_flags_gaps_suggests_and_reoptimizes_only_window(client, db):
    v = _version(db)
    rahul = _emp(db, "E002")
    leave = db.scalar(select(m.Leave).where(m.Leave.employee_id == rahul.id, m.Leave.status == "REQUESTED"))

    # 1. What-if before approving.
    preview = client.post("/api/impact-preview", json={"employee_id": rahul.id,
                                                       "date_from": leave.start_date.isoformat(),
                                                       "date_to": leave.end_date.isoformat()}).json()
    month = preview["months"][0]
    assert "Lumo Skincare" in month["brands_affected"]
    assert month["coverage_pct_after"] <= month["coverage_pct_before"]

    # 2. Approve -> version becomes STALE, response carries the re-optimise window.
    r = client.post(f"/api/leaves/{leave.id}/approve").json()
    assert v.id in r["stale_version_ids"]
    hint = r["reoptimize_hint"]
    assert db.get(m.RosterVersion, v.id).validation_status == "STALE"

    # 3. Next read re-validates: rostered on approved leave -> INVALID, gaps get suggestions.
    status = client.get(f"/api/versions/{v.id}").json()["validation_status"]
    worked = [en for en in db.scalars(select(m.RosterEntry).where(
        m.RosterEntry.version_id == v.id, m.RosterEntry.employee_id == rahul.id,
        m.RosterEntry.date.between(leave.start_date, leave.end_date), m.RosterEntry.status == "WORK"))]
    assert worked, "seed roster has Rahul working on the newly approved leave days"
    assert status == "INVALID"
    assert client.get(f"/api/versions/{v.id}/conflicts", params={"type": "WORK_DURING_ABSENCE"}).json()
    lumo_gaps = client.get(f"/api/versions/{v.id}/conflicts",
                           params={"category": "COVERAGE", "day": worked[0].date.isoformat()}).json()
    assert any("Lumo Skincare" in g["message"] and g["suggestions"] for g in lumo_gaps)

    # 4. Re-optimise only the window for the affected scope.
    r = client.post(f"/api/versions/{v.id}/reoptimize", json={**hint, "reason": "Rahul leave approved"})
    assert r.status_code == 201, r.text
    new = r.json()["version"]
    assert new["kind"] == "REOPTIMIZED" and new["parent_version_id"] == v.id
    assert new["validation_status"] in ("FULLY_COVERED", "PARTIALLY_COVERED")
    for day in range(leave.start_date.day, leave.end_date.day + 1):
        assert _entry(db, new["id"], rahul.id, date(2026, 12, day)).status == "LEAVE"
    # Rows outside the window are identical.
    old_rows = {(e.employee_id, e.date): (e.status, e.shift_id) for e in db.scalars(
        select(m.RosterEntry).where(m.RosterEntry.version_id == v.id, m.RosterEntry.date < leave.start_date))}
    new_rows = {(e.employee_id, e.date): (e.status, e.shift_id) for e in db.scalars(
        select(m.RosterEntry).where(m.RosterEntry.version_id == new["id"], m.RosterEntry.date < leave.start_date))}
    assert old_rows == new_rows
    diff = r.json()["diff"]
    assert all(c["date"] >= leave.start_date.isoformat() for c in diff["changed_entries"])


def test_holiday_edit_marks_roster_stale(client, db):
    v = _version(db)
    cal = db.scalar(select(m.HolidayCalendar).where(m.HolidayCalendar.is_default))
    r = client.post(f"/api/holiday-calendars/{cal.id}/holidays",
                    json={"date": "2026-12-31", "name": "Company Day", "kind": "OPTIONAL"})
    assert r.status_code == 201
    assert db.get(m.RosterVersion, v.id).validation_status == "STALE"
    imp = client.post(f"/api/holiday-calendars/{cal.id}/holidays/import", content="date,name,kind\nbad,row\n",
                      headers={"Content-Type": "text/csv"})
    assert imp.status_code == 400 and imp.json()["error"]["details"][0]["line"] == 2


def test_comp_off_lifecycle(client, db):
    v = _version(db)
    for c in client.get(f"/api/versions/{v.id}/conflicts", params={"category": "COVERAGE", "status": "OPEN"}).json():
        client.post(f"/api/conflicts/{c['id']}/acknowledge", json={"reason": "Accepted for demo"})
    pub = client.post(f"/api/versions/{v.id}/publish").json()
    created = pub["comp_offs"]["created"]
    assert created, "365-day brands work Christmas -> credits earned"
    credit = client.get(f"/api/comp-offs/credits", params={"status": "PENDING"}).json()
    cid = next(c for c in credit if c["id"] in created)
    approved = client.post(f"/api/comp-offs/credits/{cid['id']}/approve").json()
    assert approved["status"] == "AVAILABLE" and approved["expires_on"]
    req = client.post("/api/comp-offs/requests", json={"employee_id": cid["employee_id"], "date": "2026-12-29",
                                                       "credit_id": cid["id"]})
    assert req.status_code == 201
    dup = client.post("/api/comp-offs/requests", json={"employee_id": cid["employee_id"], "date": "2026-12-30",
                                                       "credit_id": cid["id"]})
    assert dup.status_code == 409
    done = client.post(f"/api/comp-offs/requests/{req.json()['id']}/approve").json()
    assert v.id in done["stale_version_ids"]
    bal = client.get(f"/api/employees/{cid['employee_id']}/comp-off-balance").json()
    assert bal["by_status"].get("CONSUMED", 0) >= 1
    actions = {a["action"] for a in client.get("/api/audit-log", params={"entity_type": "comp_off_credit"}).json()}
    assert {"earn", "approve", "consume"} <= actions


def test_dashboard_summary(client, db):
    r = client.get("/api/dashboard/summary", params={"year": 2026, "month": 12})
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["employees"] == 32 and body["counts"]["single_resource_brands"] == 21
    cur = body["current"]
    assert cur["version"]["validation_status"] == "PARTIALLY_COVERED"
    assert len(cur["daily_coverage"]) == 31
    assert cur["brands_at_risk"][0]["brand"] == "Ember Candles"


def test_errors_are_uniform(client, db):
    r = client.get("/api/versions/999999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.post("/api/leaves", json={"employee_id": 1, "start_date": "2026-12-10", "end_date": "2026-12-01"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
