# Assumptions

The brief leaves several operating details open. Each assumption below is either
configurable data (changeable without code) or a documented design limit.

## Calendar and rest

| Assumption | Default | Configurable? |
|---|---|---|
| Weeks run Monday–Sunday | – | Code constant |
| Minimum weekly offs | 1 per week | Per employee via `weekly_off_policies` |
| Maximum consecutive working days | 6 | Per policy |
| Minimum rest between consecutive shifts | 11 h (12 h for night policy) | Per policy |
| Public-holiday offs count toward weekly rest | Yes | Per policy (`holidays_count_as_rest`) |
| Leave / comp-off / unavailable days count as non-working days for rest rules | Yes | Design rule (a week fully on leave can't also need a weekly off) |
| Partial weeks at month start use the previous month's **published** roster; days with no history and days after month end are treated as possible offs | – | Design rule; the next month's generation enforces the full week |
| FIXED off days are hard; PREFERRED off days are soft with priority 1–5 | – | Per employee (`employee_off_days`) |

## Shifts and workload

* **One shift per employee per day.** All of a day's duties share that shift, and duties within one shift run concurrently (for example, chat queues for two brands). **Split shifts are intentionally out of scope.** They could be added later with a shift-compatibility table, without a schema rewrite.
* Shifts may cross midnight (`end_time < start_time`, for example Night 22:00–06:00).
* Each assignment carries a `load_pct`. Daily primary load must be ≤ `max_daily_load_pct` (default 100). Backup duties may add up to `backup_stretch_pct` more (default 25).
* **Coverage counts heads, not load.** Each person counts at most once toward a slot, however small their load on it. FTE-based coverage is out of scope.

## Coverage and holidays

* The unit of coverage is **brand-process + shift + date**. The minimum for a slot comes from the shift's default and can be overridden by weekday or by specific date. An override of 0 switches the shift off for that day.
* **Holiday calendars are per brand.** All processes under a brand share the brand's holiday calendar, but each process has its own operating rule (operating days + whether it runs on holidays). Employees have their own holiday calendar. The two are evaluated independently:
  * The brand calendar decides whether a process operates.
  * The employee calendar decides whether the day is that person's public holiday. That is soft: working it earns a comp-off.
* If an employee has no operating duties on a day (for example, their only brand is closed), they are off, and the day is recorded as `WEEKLY_OFF`.
* Missing calendar → the default calendar (`holiday_calendars.is_default`).

## Assignments and backups

* An employee holds at most **one assignment per brand-process at any date** (PRIMARY *or* BACKUP). A GiST exclusion constraint enforces this, so every duty maps to exactly one role and one load.
* A BACKUP assignment means the person is trained and eligible. **It never counts toward coverage until a BACKUP duty is activated** in the roster.
* A working employee is expected to do all their primary duties for their shift (soft, high weight). Over-allocated primaries are reported as `OVER_ALLOCATED` instead of silently idling the person.

## Comp-offs

* Earned when a **published** roster has someone working a public holiday or an overridden rest day (`PENDING`). A manager approves it (`AVAILABLE`, expires after 60 days by default, `COMP_OFF_EXPIRY_DAYS`) or rejects it.
* An approved comp-off request consumes one credit and becomes a hard unavailability.
* If a later published version removes the work, an unused credit is `REVERSED`. If the credit is already consumed, a conflict is flagged instead.

## Solver

* CP-SAT runs with a fixed seed, a single worker and a deterministic-time budget, so the same input always gives the same roster.
* A limit reached without any solution is reported as `SOLVER_TIMEOUT`, never as `INFEASIBLE`. `INFEASIBLE` means CP-SAT proved that locked rows contradict mandatory rules.

## Sample dataset (fictional)

* All company, brand and employee names and emails are fictional (`@example-cx.test`).
* **32 employees, 4 pods**, each with a pod lead. Leads own a small brand and act as trained backups.
* **26 brands, 21 single-resource (81%)**. The other 5 have 2–3 people:
  * Hearth & Co: 3 people on separate processes.
  * UrbanKart: 2 sharing CS with a weekend minimum of 2.
  * Nimbus Sleep: 2 people with cross-backups.
  * VitaBloom: 2 sharing CS, plus 1 on ACC and Retention.
  * Glow Theory: 3 people, with shift-specific CS (GEN day + NGT night, 2 night agents).
* Operating rules mix 365-day, daily-except-holidays and Sundays-and-holidays-off, often differing between processes of the same brand.
* Holidays come from `backend/app/seed/data/holidays.json`: an India national calendar plus a Karnataka regional calendar. Movable festival dates are approximate and editable.
* **Deliberate problem cases in December 2026:**
  * Ember Candles: sole resource on leave 14–18 Dec, no backup → unavoidable gaps.
  * Karan Malhotra (owns 2 brands) on leave 21–23 Dec → gaps across brands.
  * Petal Florals needs 2 on 24 Dec; the only backup is on leave → understaffed.
  * UrbanKart CS needs 3 on 31 Dec; only 2 people are trained → understaffed.
  * Harsh Vardhan's primaries need 130% on one shift → `OVER_ALLOCATED`.
  * Aakash Jain holds night-only CS + day NDR primaries → `INCOMPATIBLE_PRIMARY_SHIFTS`.
  * A `REQUESTED` (not yet approved) leave for Rahul Mehta, used to demonstrate the change workflow.
