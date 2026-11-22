# Architecture

```
frontend (React + TS + Vite + Tailwind + shadcn/ui, TanStack Query)
   │  REST /api
backend (FastAPI)
   ├── app/api/          routers, error mapping, X-Actor dependency
   ├── app/services/     versioning, validated edits, publish, comp-offs, staleness, audit, dashboard
   ├── app/services/engine_adapter.py            DB ⇄ engine dataclasses, persistence
   ├── app/scheduling/   (pure Python, no DB)    the scheduling engine
   │     types.py        immutable inputs/outputs
   │     calendar.py     operating calendar + employee availability, requirement resolution
   │     presolve.py     unavoidable gaps, master-data warnings
   │     solver.py       CP-SAT model
   │     validator.py    independent rule checker + classification
   │     reoptimize.py   window/scope-locked re-solve + diff
   │     suggestions.py  ranked gap resolutions
   └── app/models + alembic/                     PostgreSQL schema & migrations
```

The engine has no database or web imports. Inputs arrive as dataclasses, results leave as dataclasses, and its 42 unit tests run in about 5 seconds without a database.

## Data model (key relationships)

```
pods 1─* employees ─* assignments *─1 brand_processes *─1 brands
                       (PRIMARY|BACKUP,          │  operating_days_mask, operates_on_holidays
                        load_pct, shift?,        1─* brand_process_shifts (slot: shift + default min)
                        effective dates)               1─* coverage_requirements (weekday/date override)

roster_plans 1─* roster_versions 1─* roster_entries 1─* roster_duties *─1 assignments
   (year,month)   (DRAFT/PUBLISHED/…,   (employee, date,    (slot, shift, PRIMARY|BACKUP,
                   validation status)    status, shift)      source, locked)
                        ├─* roster_coverage   (per slot-day: required/staffed/status)
                        ├─* roster_conflicts  (typed, severity, explanation, suggestions)
                        └─* audit_log
```

Database-enforced guarantees:

| Guarantee | Mechanism |
|---|---|
| A duty only references a **WORK** entry with the same version, employee, date and shift | Composite FK `(entry_id, version_id, employee_id, date, shift_id, entry_status)` → `roster_entries`, with `entry_status` CHECKed = `'WORK'`; `ON UPDATE RESTRICT` blocks changing an entry to any non-WORK status or another shift while duties exist |
| A duty's shift is one its slot runs | Composite FK `(brand_process_shift_id, brand_process_id, shift_id)` |
| The authorising assignment belongs to the same employee and brand-process, and duty_type = role | Composite FK `(assignment_id, employee_id, brand_process_id, duty_type)` |
| No double counting | `UNIQUE (version_id, employee_id, date, brand_process_id)` |
| Assignment is effective on the date, allows the shift, and everything is active | Trigger `trg_roster_duty_eligibility` |
| No ambiguous overlapping assignments | GiST exclusion on `(employee_id, brand_process_id, daterange)` |
| A shift is set if and only if the status is WORK | CHECK on `roster_entries` |
| One published version per month, unlimited drafts | Partial unique index |

## Scheduling engine

1. **Calendar expansion.** `Context.required(slot, date)` resolves each slot's minimum headcount: 0 if the process isn't operating, then a specific-date override, then a weekday override, then the default. Employee availability (leave, comp-off, unavailability, fixed off days, own holiday calendar) is computed separately.
2. **Pre-solve.** For each required slot-day, count the eligible people who can work. If that is below the requirement, the gap is proven unavoidable. Master-data warnings are also produced here (over-allocation, incompatible primary shifts, slots with nobody assigned).
3. **CP-SAT model.**
   * Variables:
     * `x[e,d,slot]` exists only for candidates. Because of the exclusion constraint, each candidate maps to exactly one assignment, and therefore to one role and one `load_pct`.
     * `work[e,d]`, `sh[e,d,shift]`, and `short[slot,d] ∈ [0, required]`.
   * Hard constraints:
     * A duty only on a work day, in the day's single shift; no work day without a duty.
     * The load cap (primary duties, and cap + stretch with backups).
     * Absence and fixed offs.
     * Minimum offs per week, maximum consecutive days, minimum rest hours. The month boundary uses history.
     * Locks, passed as assumption literals.
   * Coverage: `Σx + short ≥ required`. This keeps the model feasible, so impossible coverage becomes explicit, explained shortfall instead of a silently invalid roster.
   * Objective weights, in strict priority order: shortfall 100000 ≫ excess offs 2000 ≫ primary continuity 1000 ≫ backup activation 300 ≫ holiday work 200 ≫ preferred off 50×priority ≫ stability 60 (re-optimisation only) ≫ weekend fairness 20.
   * Solver settings: fixed seed, 1 worker and `linearization_level=2`, so results are reproducible and optimal solutions are proven quickly. The seeded month (32 people, about 2,750 candidates) solves to proven optimality in about 1–3 s.
4. **Validation (independent).** The validator re-derives every rule from the rows:
   * Integrity: duplicates, duty on a non-WORK day, shift mismatches, ineligible assignments.
   * Employee rules: absence, fixed off, load, weekly rest, consecutive days, rest hours.
   * Coverage, counted as distinct employees over valid duties only.
   * Preferences and configuration warnings.
5. **Classification.**

| Status | Rule |
|---|---|
| `FULLY_COVERED` | every required slot MET and zero integrity / employee-rule issues |
| `PARTIALLY_COVERED` | rules intact, ≥1 slot UNDERSTAFFED/UNCOVERED (each tagged UNAVOIDABLE or TRADE_OFF and explained) |
| `INVALID` | any integrity or employee-rule issue (only from edits/data changes; a test asserts solver output is never INVALID) |
| `INFEASIBLE` | CP-SAT *proved* locked rows contradict mandatory rules; culprit rows named via `sufficient_assumptions_for_infeasibility` |
| `SOLVER_TIMEOUT` | limit reached with no solution (never conflated with INFEASIBLE) |
| `STALE` | inputs changed after validation (set by services) |

Slot roll-up precedence: **UNCOVERED > UNDERSTAFFED > MET > NOT_REQUIRED**. Coverage % = Σ min(staffed, required) / Σ required, so overstaffing in one slot can't hide a gap in another.

6. **Re-optimisation.** Only rows inside `[from, to]` *and* the affected scope (the changed employee plus everyone on the brand-processes they touch) are free. Everything else is locked and copied back verbatim. Manual rows stay locked unless they are listed in `override_manual`. The result includes a diff.
7. **Suggestions.** For each gap, candidates are ranked into actions: `ADD_DUTY` (already on the shift with headroom), `WORK_ON_OFF_DAY` (with a gap-free swap day in the same week), or `CHANGE_SHIFT` (listing the duties it drops and any gaps that would open).

## API and services (Phase 3)

106 REST operations (OpenAPI at `/docs`). Key behaviours:

* **Versioning.** Generate, re-optimise and clone always create a new `DRAFT`. Only drafts are editable. Publishing moves the previous `PUBLISHED` version to `SUPERSEDED`. Published history is immutable.
* **Validated edits.** `PUT /versions/{id}/entries/{entry_id}` replaces an employee-day atomically: delete duties → change entry → insert duties, in one transaction.
  * Rejected with 409: shift clash, no eligible assignment, load cap, rostering someone on an approved absence.
  * Allowed but flagged: rest-rule breaches make the version `INVALID`, which blocks publishing.
  * Edited rows become `MANUAL` + locked, so re-optimisation preserves them.
* **Staleness.** Leave approval or cancellation, unavailability, comp-off consumption, holiday edits and master-data changes mark overlapping live versions `STALE`. The next read re-validates them.
  * Conflict rows are synchronised by (type, date, employee, slot), so ids and acknowledgements survive and vanished issues become `RESOLVED`.
* **Publishing.**
  * Allowed for `FULLY_COVERED`.
  * Allowed for `PARTIALLY_COVERED` only when every coverage gap is acknowledged with a reason. Rule violations cannot be acknowledged.
  * Publishing earns `PENDING` comp-off credits for public-holiday work and reverses credits whose work was removed.
* **Change workflow.**
  1. `POST /impact-preview` is a read-only what-if: the gaps that would open, plus ranked cover.
  2. Approving a leave returns the stale versions and a `reoptimize_hint`.
  3. `POST /versions/{id}/reoptimize` re-plans only that window and scope, and returns a diff.
  4. Alternatively, `POST /conflicts/{id}/apply-suggestion` applies a single fix.
* **Comp-offs.** `PENDING → AVAILABLE` (expiry `COMP_OFF_EXPIRY_DAYS` after approval) `→ CONSUMED` through an approved request; also `REJECTED`, `EXPIRED` and `REVERSED`. Cancelling an approved request restores the credit.
* **Audit.** Every write records actor (`X-Actor` header), before/after JSON and reason in `audit_log`.
* **Errors.** Uniform `{"error": {"code", "message", "details"}}`. Database constraint names are mapped to plain-language 409 messages.

## Frontend (Phase 4)

* **Thin client.** Every status, gap, suggestion, diff and coverage figure comes from the API. The browser only displays data and inverts duties for the process view.
* **Server state.** TanStack Query, with one mutation helper that refreshes all roster-derived queries and surfaces 409 messages verbatim.
* **Plan context.** The selected month and version are shared by all month-scoped screens. The default is the published version, else the newest draft.
* **Central screens.** The roster grid (day editor, gap panel, day panel) and the change-management workflow (what-if → record → re-optimise window → diff).
* **Tests.** A Playwright E2E test runs the full journey against the real backend.

## Status of implementation

| Phase | Scope | State |
|---|---|---|
| 0 | Scaffold, env, health endpoint, frontend shell | done |
| 1 | Models, migration (FKs, exclusion, trigger), seed | done |
| 2 | Engine, validator, re-optimiser, suggestions, CLI, tests | done |
| 3 | REST API, services (versioning, comp-off lifecycle, audit, edits, change workflow) | done: 78 tests passing |
| 4 | Frontend: dashboard, roster grid (employee/process views), coverage heatmap, conflicts, versions (generate/clone/re-optimise/compare/publish), change management, availability and comp-offs, setup screens, audit log | done: E2E journey passing |
| 5–6 | Polish, export, remaining optional features | next |
| 7 | Docs (8 questions), deployment | planned |
