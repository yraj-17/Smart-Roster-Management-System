"""Realistic, fictional sample dataset.

Shape (see docs/ASSUMPTIONS.md for the full rationale):
* 32 employees in 4 pods, each pod led by a pod lead who also owns a small brand
  and acts as a trained backup for the pod's single-resource brands.
* 26 brands: 21 single-resource (81%) and 5 multi-resource (2-3 people):
    Hearth & Co   3 people, separate processes (CS / ACC / NDR)
    UrbanKart     2 people sharing CS (weekend minimum 2), separate ACC / NDR
    Nimbus Sleep  2 people, separate processes with cross-backups
    VitaBloom     3 people, 2 sharing CS + 1 on ACC & Retention
    Glow Theory   3 people, shift-specific CS (GEN day + NGT night, 2 night agents)
* Deliberately invalid / stressed scenarios for December 2026:
    - Ember Candles: sole resource on leave 14-18 Dec, no backup  -> unavoidable gaps
    - Harsh Vardhan: primaries need 130% on one shift          -> OVER_ALLOCATED
    - Aakash Jain: night-only CS + day NDR primaries            -> INCOMPATIBLE_PRIMARY_SHIFTS
    - UrbanKart CS needs 3 on 31 Dec with 2 trained people     -> unavoidable UNDERSTAFFED
    - Petal Florals CS needs 2 on 24 Dec; the only backup is on leave -> UNDERSTAFFED
    - Karan Malhotra (2 brands) on leave 21-23 Dec             -> gaps across multiple brands
"""
from __future__ import annotations

import json
from datetime import date, time, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import (
    Assignment,
    Base,
    Brand,
    BrandProcess,
    BrandProcessShift,
    CompOffCredit,
    CompOffRequest,
    CoverageRequirement,
    Employee,
    EmployeeOffDay,
    HolidayCalendar,
    Leave,
    Pod,
    Process,
    PublicHoliday,
    Shift,
    Unavailability,
    WeeklyOffPolicy,
)

DATA = Path(__file__).parent / "data"
EPOCH = date(2026, 1, 1)

# Operating-rule presets (bit0 = Monday).  (mask, operates_on_holidays)
R365 = (0b1111111, True)        # 365-day operations incl. Sundays and public holidays
DAILY = (0b1111111, False)      # every day except public holidays
MON_SAT = (0b0111111, False)    # Sundays and public holidays off

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

SHIFTS = [("MOR", "Morning", time(7), time(15)), ("GEN", "General", time(9), time(18)),
          ("EVE", "Evening", time(14), time(22)), ("NGT", "Night", time(22), time(6))]

PROCESSES = [("CS", "Customer Support", "Inbound tickets, chat and calls"),
             ("ACC", "Abandoned Cart Conversions", "Outbound recovery of abandoned carts"),
             ("NDR", "NDR Management", "Non-delivery report follow-up with customers and couriers"),
             ("RET", "Retention", "Win-back and subscription retention"),
             ("SOC", "Social Media Care", "Replies on social channels")]

POLICIES = [("Standard 6-day", 1, 6, 11, True),
            ("5-day week", 2, 5, 11, True),
            ("Night shift", 1, 5, 12, True)]

PODS = ["Pod Alpha", "Pod Bravo", "Pod Cosmos", "Pod Delta"]

# code, name, pod, policy, calendar, is_lead, fixed_off, preferred[(dow, prio)]
EMPLOYEES = [
    ("E001", "Ananya Rao", 0, "Standard 6-day", None, True, [], []),
    ("E002", "Rahul Mehta", 0, "Standard 6-day", None, False, [], [(WED, 1)]),
    ("E003", "Sneha Kulkarni", 0, "Standard 6-day", None, False, [], []),
    ("E004", "Arjun Nair", 0, "Standard 6-day", None, False, [], [(SUN, 2)]),
    ("E005", "Pooja Sharma", 0, "Standard 6-day", None, False, [], [(SUN, 3)]),
    ("E006", "Karan Malhotra", 0, "Standard 6-day", None, False, [], []),
    ("E007", "Divya Menon", 0, "Standard 6-day", None, False, [], [(MON, 1)]),
    ("E008", "Imran Shaikh", 0, "Standard 6-day", None, False, [], [(SAT, 2)]),
    ("E009", "Neha Joshi", 0, "Standard 6-day", None, False, [], []),
    ("E010", "Vikram Desai", 1, "Standard 6-day", None, True, [], []),
    ("E011", "Aditi Verma", 1, "Standard 6-day", None, False, [], [(WED, 1)]),
    ("E012", "Rohan Gupta", 1, "Standard 6-day", None, False, [], [(THU, 1)]),
    ("E013", "Tanvi Bhatt", 1, "Standard 6-day", None, False, [], []),
    ("E014", "Siddharth Rao", 1, "Standard 6-day", None, False, [], []),
    ("E015", "Kavya Reddy", 1, "Standard 6-day", "India - Karnataka", False, [], [(SUN, 2)]),
    ("E016", "Manish Kumar", 1, "Standard 6-day", None, False, [], []),
    ("E017", "Ishita Banerjee", 1, "Standard 6-day", "India - Karnataka", False, [], []),
    ("E018", "Yash Agarwal", 1, "Standard 6-day", None, False, [], []),
    ("E019", "Meenakshi Iyer", 2, "5-day week", None, True, [], [(SUN, 2)]),
    ("E020", "Nikhil Patil", 2, "Standard 6-day", None, False, [], []),
    ("E021", "Shreya Pillai", 2, "Standard 6-day", None, False, [], [(TUE, 1)]),
    ("E022", "Aman Chopra", 2, "Standard 6-day", None, False, [], []),
    ("E023", "Riya Saxena", 2, "Standard 6-day", None, False, [], []),
    ("E024", "Harsh Vardhan", 2, "Standard 6-day", None, False, [], []),
    ("E025", "Lavanya Krishnan", 2, "Standard 6-day", None, False, [], [(SUN, 1)]),
    ("E026", "Gaurav Singh", 2, "Standard 6-day", None, False, [SUN], []),
    ("E027", "Farhan Qureshi", 3, "Standard 6-day", None, True, [], []),
    ("E028", "Zoya Khan", 3, "Standard 6-day", None, False, [], []),
    ("E029", "Aakash Jain", 3, "Night shift", None, False, [], []),
    ("E030", "Sana Mirza", 3, "Standard 6-day", None, False, [], []),
    ("E031", "Kabir Sethi", 3, "Night shift", None, False, [], []),
    ("E032", "Tara D'Souza", 3, "Standard 6-day", None, False, [], []),
]

# brand code, name, calendar, notes, processes: [(process, rule, [(shift, min_staff)])]
BRANDS = [
    # single-resource brands
    ("ZEST", "Zest Juices", None, "Owned by pod lead", [("CS", MON_SAT, [("GEN", 1)])]),
    ("LUMO", "Lumo Skincare", None, None, [("CS", R365, [("GEN", 1)]), ("ACC", DAILY, [("GEN", 1)]),
                                         ("NDR", MON_SAT, [("GEN", 1)])]),
    ("KITO", "Kito Snacks", None, None, [("CS", DAILY, [("GEN", 1)]), ("ACC", MON_SAT, [("GEN", 1)])]),
    ("VERDE", "Verde Home", None, None, [("CS", MON_SAT, [("GEN", 1)]), ("NDR", MON_SAT, [("GEN", 1)])]),
    ("AURUM", "Aurum Jewels", None, None, [("CS", R365, [("GEN", 1)]), ("RET", MON_SAT, [("GEN", 1)])]),
    ("PEBBLE", "Pebble Kids", None, None, [("CS", DAILY, [("GEN", 1)])]),
    ("FABLE", "Fable Books", None, None, [("CS", MON_SAT, [("GEN", 1)])]),
    ("SAFFRON", "Saffron Spice Co", None, "Owned by pod lead", [("CS", DAILY, [("GEN", 1)])]),
    ("TIDAL", "Tidal Wear", None, None, [("CS", R365, [("GEN", 1)]), ("SOC", R365, [("GEN", 1)])]),
    ("BREW", "Brew Haus Coffee", None, None, [("CS", DAILY, [("GEN", 1)]), ("ACC", MON_SAT, [("GEN", 1)])]),
    ("ORBIT", "Orbit Gadgets", None, None, [("CS", R365, [("GEN", 1)]), ("NDR", DAILY, [("GEN", 1)])]),
    ("PETAL", "Petal Florals", None, "Christmas Eve rush", [("CS", R365, [("GEN", 1)]),
                                                           ("ACC", R365, [("GEN", 1)])]),
    ("COBALT", "Cobalt Fitness", None, "Owned by pod lead", [("CS", MON_SAT, [("GEN", 1)])]),
    ("EMBER", "Ember Candles", None, "No backup configured", [("CS", R365, [("GEN", 1)]),
                                                             ("ACC", DAILY, [("GEN", 1)])]),
    ("MONSOON", "Monsoon Umbrellas", None, None, [("CS", MON_SAT, [("GEN", 1)]), ("NDR", MON_SAT, [("GEN", 1)])]),
    ("CRATE", "Crate & Co", None, None, [("CS", MON_SAT, [("GEN", 1)])]),
    ("BLOOM", "Bloom Basket", "India - Karnataka", "Bengaluru-based client",
     [("CS", DAILY, [("GEN", 1)]), ("RET", MON_SAT, [("GEN", 1)])]),
    ("QUILL", "Quill Stationery", None, None, [("CS", MON_SAT, [("GEN", 1)]), ("ACC", MON_SAT, [("GEN", 1)])]),
    ("NOVA", "Nova Audio", None, "Owned by pod lead", [("CS", DAILY, [("GEN", 1)])]),
    ("LUXE", "Luxe Linen", None, "Evening support window", [("CS", DAILY, [("EVE", 1)]),
                                                           ("SOC", DAILY, [("EVE", 1)])]),
    ("CRUMB", "Crumb Bakery", None, "Evening support window", [("CS", DAILY, [("EVE", 1)])]),
    # multi-resource brands
    ("HEARTH", "Hearth & Co", None, "3 people, separate processes",
     [("CS", R365, [("GEN", 1)]), ("ACC", DAILY, [("GEN", 1)]), ("NDR", MON_SAT, [("GEN", 1)])]),
    ("URBAN", "UrbanKart", None, "Shared CS; weekend minimum 2",
     [("CS", R365, [("GEN", 1)]), ("ACC", DAILY, [("GEN", 1)]), ("NDR", MON_SAT, [("GEN", 1)])]),
    ("NIMBUS", "Nimbus Sleep", None, "2 people with cross-backups",
     [("CS", DAILY, [("GEN", 1)]), ("RET", MON_SAT, [("GEN", 1)]), ("NDR", MON_SAT, [("GEN", 1)])]),
    ("VITA", "VitaBloom Nutrition", None, "2 share CS; Saturday minimum 2",
     [("CS", R365, [("GEN", 1)]), ("ACC", DAILY, [("GEN", 1)]), ("RET", MON_SAT, [("GEN", 1)])]),
    ("GLOW", "Glow Theory", None, "24x7 CS: day + night shift",
     [("CS", R365, [("GEN", 1), ("NGT", 1)]), ("ACC", DAILY, [("GEN", 1)]), ("NDR", MON_SAT, [("GEN", 1)])]),
]

# employee, brand, process, role, load, shift restriction
P, B = "PRIMARY", "BACKUP"
ASSIGNMENTS = [
    # Pod Alpha
    ("E001", "ZEST", "CS", P, 40, None),
    ("E001", "LUMO", "CS", B, 40, None), ("E001", "LUMO", "ACC", B, 20, None), ("E001", "LUMO", "NDR", B, 10, None),
    ("E001", "AURUM", "CS", B, 30, None), ("E001", "PEBBLE", "CS", B, 30, None),
    ("E001", "KITO", "ACC", B, 20, None),
    ("E002", "LUMO", "CS", P, 60, None), ("E002", "LUMO", "ACC", P, 25, None), ("E002", "LUMO", "NDR", P, 15, None),
    ("E003", "KITO", "CS", P, 70, None), ("E003", "KITO", "ACC", P, 30, None), ("E003", "VERDE", "CS", B, 25, None),
    ("E004", "VERDE", "CS", P, 70, None), ("E004", "VERDE", "NDR", P, 30, None), ("E004", "KITO", "CS", B, 25, None),
    ("E005", "AURUM", "CS", P, 60, None), ("E005", "AURUM", "RET", P, 40, None), ("E005", "ZEST", "CS", B, 25, None),
    ("E006", "PEBBLE", "CS", P, 50, None), ("E006", "FABLE", "CS", P, 50, None),
    ("E007", "HEARTH", "CS", P, 80, None), ("E007", "HEARTH", "ACC", B, 20, None),
    ("E008", "HEARTH", "ACC", P, 60, None), ("E008", "HEARTH", "CS", B, 40, None),
    ("E009", "HEARTH", "NDR", P, 60, None), ("E009", "HEARTH", "ACC", B, 30, None),
    # Pod Bravo
    ("E010", "SAFFRON", "CS", P, 40, None),
    ("E010", "TIDAL", "CS", B, 40, None), ("E010", "ORBIT", "CS", B, 40, None),
    ("E010", "PETAL", "CS", B, 30, None), ("E010", "BREW", "CS", B, 30, None),
    ("E011", "URBAN", "CS", P, 60, None), ("E011", "URBAN", "ACC", P, 30, None), ("E011", "URBAN", "NDR", B, 15, None),
    ("E012", "URBAN", "CS", P, 60, None), ("E012", "URBAN", "NDR", P, 25, None), ("E012", "URBAN", "ACC", B, 30, None),
    ("E013", "NIMBUS", "CS", P, 80, None), ("E013", "NIMBUS", "RET", B, 20, None),
    ("E013", "NIMBUS", "NDR", B, 15, None),
    ("E014", "NIMBUS", "RET", P, 50, None), ("E014", "NIMBUS", "NDR", P, 30, None),
    ("E014", "NIMBUS", "CS", B, 30, None),
    ("E015", "TIDAL", "CS", P, 70, None), ("E015", "TIDAL", "SOC", P, 30, None), ("E015", "ORBIT", "NDR", B, 20, None),
    ("E016", "BREW", "CS", P, 60, None), ("E016", "BREW", "ACC", P, 40, None), ("E016", "PETAL", "ACC", B, 20, None),
    ("E016", "SAFFRON", "CS", B, 25, None),
    ("E017", "ORBIT", "CS", P, 70, None), ("E017", "ORBIT", "NDR", P, 30, None), ("E017", "TIDAL", "SOC", B, 15, None),
    ("E018", "PETAL", "CS", P, 60, None), ("E018", "PETAL", "ACC", P, 40, None), ("E018", "BREW", "ACC", B, 20, None),
    # Pod Cosmos
    ("E019", "COBALT", "CS", P, 40, None),
    ("E019", "BLOOM", "CS", B, 40, None), ("E019", "QUILL", "CS", B, 40, None),
    ("E019", "MONSOON", "CS", B, 30, None), ("E019", "CRATE", "CS", B, 40, None), ("E019", "VITA", "ACC", B, 30, None),
    ("E020", "VITA", "CS", P, 60, None),
    ("E021", "VITA", "CS", P, 60, None), ("E021", "VITA", "RET", B, 20, None),
    ("E022", "VITA", "ACC", P, 50, None), ("E022", "VITA", "RET", P, 30, None), ("E022", "VITA", "CS", B, 20, None),
    ("E023", "EMBER", "CS", P, 70, None), ("E023", "EMBER", "ACC", P, 30, None),
    ("E024", "MONSOON", "CS", P, 60, None), ("E024", "MONSOON", "NDR", P, 30, None), ("E024", "CRATE", "CS", P, 40, None),
    ("E025", "BLOOM", "CS", P, 70, None), ("E025", "BLOOM", "RET", P, 30, None), ("E025", "QUILL", "ACC", B, 20, None),
    ("E025", "COBALT", "CS", B, 25, None),
    ("E026", "QUILL", "CS", P, 60, None), ("E026", "QUILL", "ACC", P, 40, None), ("E026", "BLOOM", "RET", B, 20, None),
    # Pod Delta
    ("E027", "NOVA", "CS", P, 40, None),
    ("E027", "GLOW", "CS", B, 40, "GEN"), ("E027", "GLOW", "ACC", B, 20, None), ("E027", "GLOW", "NDR", B, 20, None),
    ("E028", "GLOW", "CS", P, 70, "GEN"), ("E028", "GLOW", "ACC", P, 30, None), ("E028", "GLOW", "NDR", B, 20, None),
    ("E028", "NOVA", "CS", B, 25, None),
    ("E029", "GLOW", "CS", P, 80, "NGT"), ("E029", "GLOW", "NDR", P, 20, None),
    ("E030", "LUXE", "CS", P, 70, None), ("E030", "LUXE", "SOC", P, 30, None), ("E030", "CRUMB", "CS", B, 25, None),
    ("E031", "GLOW", "CS", P, 100, "NGT"),
    ("E032", "CRUMB", "CS", P, 70, None), ("E032", "LUXE", "CS", B, 30, None), ("E032", "LUXE", "SOC", B, 20, None),
]

# Historical assignment (ended) to show effective dating.
ENDED_ASSIGNMENTS = [("E008", "LUMO", "CS", B, 30, None, date(2026, 1, 1), date(2026, 6, 30))]

# brand, process, shift, dow | date, min_staff, reason
OVERRIDES = [
    ("URBAN", "CS", "GEN", SAT, None, 2, "Weekend sale traffic"),
    ("URBAN", "CS", "GEN", SUN, None, 2, "Weekend sale traffic"),
    ("URBAN", "CS", "GEN", None, date(2026, 12, 31), 3, "Year-end sale"),
    ("VITA", "CS", "GEN", SAT, None, 2, "Saturday campaign volume"),
    ("PETAL", "CS", "GEN", None, date(2026, 12, 24), 2, "Christmas Eve rush"),
    ("GLOW", "CS", "NGT", None, date(2026, 12, 25), 0, "No night shift on Christmas"),
]

# employee, start, end, type, status, reason
LEAVES = [
    ("E023", date(2026, 12, 14), date(2026, 12, 18), "PLANNED", "APPROVED", "Family wedding"),
    ("E006", date(2026, 12, 21), date(2026, 12, 23), "PLANNED", "APPROVED", "Travel"),
    ("E021", date(2026, 12, 28), date(2026, 12, 31), "PLANNED", "APPROVED", "Year-end vacation"),
    ("E010", date(2026, 12, 24), date(2026, 12, 24), "CASUAL", "APPROVED", "Personal"),
    ("E028", date(2026, 12, 10), date(2026, 12, 11), "SICK", "APPROVED", "Fever"),
    ("E013", date(2026, 12, 7), date(2026, 12, 9), "PLANNED", "APPROVED", "Exam"),
    ("E002", date(2026, 12, 30), date(2026, 12, 31), "PLANNED", "REQUESTED", "New Year travel"),
    ("E017", date(2026, 12, 19), date(2026, 12, 20), "CASUAL", "REJECTED", "Overlaps peak week"),
]

UNAVAILABILITY = [("E031", date(2026, 12, 19), date(2026, 12, 19), "Compliance training")]


def seed_if_empty(session: Session) -> dict[str, int] | None:
    """Production-safe seeding: load the sample dataset only into an empty database.

    Returns the seed summary, or None when data already exists (nothing is changed).
    Safe to run on every deployment.
    """
    from sqlalchemy import func, select
    if session.scalar(select(func.count()).select_from(Employee)):
        return None
    return seed(session)


def reset(session: Session) -> None:
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def seed(session: Session) -> dict[str, int]:
    reset(session)

    cal_data = json.loads((DATA / "holidays.json").read_text(encoding="utf-8"))["calendars"]
    calendars: dict[str, HolidayCalendar] = {}
    national: list[dict] = []
    for c in cal_data:
        cal = HolidayCalendar(name=c["name"], region=c["region"], is_default=c["is_default"])
        rows = list(c["holidays"])
        if c.get("inherits"):
            rows = national + rows
        else:
            national = list(rows)
        cal.holidays = [PublicHoliday(date=date.fromisoformat(h["date"]), name=h["name"], kind=h["kind"])
                        for h in rows]
        session.add(cal)
        calendars[c["name"]] = cal

    shifts = {code: Shift(code=code, name=n, start_time=s, end_time=e) for code, n, s, e in SHIFTS}
    processes = {code: Process(code=code, name=n, description=d) for code, n, d in PROCESSES}
    policies = {n: WeeklyOffPolicy(name=n, min_offs_per_week=o, max_consecutive_work_days=c,
                                   min_rest_hours=r, holidays_count_as_rest=h) for n, o, c, r, h in POLICIES}
    pods = [Pod(name=n) for n in PODS]
    session.add_all([*shifts.values(), *processes.values(), *policies.values(), *pods])
    session.flush()

    employees: dict[str, Employee] = {}
    for code, name, pod, pol, cal, is_lead, fixed, pref in EMPLOYEES:
        local = name.lower().replace("'", "").replace(" ", ".")
        emp = Employee(code=code, name=name, email=f"{local}@example-cx.test", pod_id=pods[pod].id,
                       weekly_off_policy_id=policies[pol].id,
                       holiday_calendar_id=calendars[cal].id if cal else None)
        emp.off_days = [EmployeeOffDay(day_of_week=d, kind="FIXED", priority=1) for d in fixed] + \
                       [EmployeeOffDay(day_of_week=d, kind="PREFERRED", priority=p) for d, p in pref]
        session.add(emp)
        employees[code] = emp
    session.flush()
    for code, _n, pod, *_rest in EMPLOYEES:
        if _rest[2]:  # is_lead
            pods[pod].lead_employee_id = employees[code].id

    bps: dict[tuple[str, str], BrandProcess] = {}
    slots: dict[tuple[str, str, str], BrandProcessShift] = {}
    for code, name, cal, notes, procs in BRANDS:
        brand = Brand(code=code, name=name, notes=notes,
                      holiday_calendar_id=calendars[cal].id if cal else None)
        for proc, (mask, on_hol), shift_list in procs:
            bp = BrandProcess(process_id=processes[proc].id, operating_days_mask=mask,
                              operates_on_holidays=on_hol)
            for sh, mn in shift_list:
                slot = BrandProcessShift(shift_id=shifts[sh].id, default_min_staff=mn)
                bp.slots.append(slot)
                slots[(code, proc, sh)] = slot
            brand.processes.append(bp)
            bps[(code, proc)] = bp
        session.add(brand)
    session.flush()

    for emp, brand, proc, role, load, sh in ASSIGNMENTS:
        session.add(Assignment(employee_id=employees[emp].id, brand_process_id=bps[(brand, proc)].id,
                               role=role, load_pct=load, shift_id=shifts[sh].id if sh else None,
                               effective_from=EPOCH))
    for emp, brand, proc, role, load, sh, frm, to in ENDED_ASSIGNMENTS:
        session.add(Assignment(employee_id=employees[emp].id, brand_process_id=bps[(brand, proc)].id,
                               role=role, load_pct=load, shift_id=shifts[sh].id if sh else None,
                               effective_from=frm, effective_to=to))

    for brand, proc, sh, dow, on, mn, why in OVERRIDES:
        session.add(CoverageRequirement(brand_process_shift_id=slots[(brand, proc, sh)].id,
                                        day_of_week=dow, specific_date=on, min_staff=mn, reason=why))

    for emp, s, e, typ, status, why in LEAVES:
        session.add(Leave(employee_id=employees[emp].id, start_date=s, end_date=e, leave_type=typ,
                          status=status, reason=why,
                          decided_by="ops.manager" if status in ("APPROVED", "REJECTED") else None))
    for emp, s, e, why in UNAVAILABILITY:
        session.add(Unavailability(employee_id=employees[emp].id, start_date=s, end_date=e, reason=why))

    # Comp-offs: Yash worked Diwali -> approved credit consumed on 12 Dec;
    # Pooja worked Guru Nanak Jayanti -> credit pending manager approval.
    yash = CompOffCredit(employee_id=employees["E018"].id, earned_on=date(2026, 11, 8), source="HOLIDAY_WORK",
                         status="CONSUMED", expires_on=date(2026, 11, 8) + timedelta(days=60),
                         consumed_on=date(2026, 12, 12), note="Worked Diwali")
    session.add(yash)
    session.add(CompOffCredit(employee_id=employees["E005"].id, earned_on=date(2026, 11, 24),
                              source="HOLIDAY_WORK", status="PENDING", note="Worked Guru Nanak Jayanti"))
    session.flush()
    session.add(CompOffRequest(employee_id=employees["E018"].id, date=date(2026, 12, 12), credit_id=yash.id,
                               status="APPROVED", decided_by="ops.manager"))
    session.commit()
    single = sum(1 for b in BRANDS if len({a[0] for a in ASSIGNMENTS if a[1] == b[0] and a[3] == P}) == 1)
    return {"employees": len(EMPLOYEES), "pods": len(PODS), "brands": len(BRANDS),
            "single_resource_brands": single, "brand_processes": len(bps), "slots": len(slots),
            "assignments": len(ASSIGNMENTS) + len(ENDED_ASSIGNMENTS)}
