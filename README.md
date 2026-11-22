# Smart Roster Management System

**Constraint-based monthly rostering for multi-brand customer-operations teams: generate, validate, explain and repair rosters without rebuilding them by hand.**

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](backend/requirements.txt)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](backend/app/main.py)
[![OR-Tools](https://img.shields.io/badge/OR--Tools-CP--SAT-4285F4)](backend/app/scheduling/solver.py)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](frontend/package.json)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](frontend/tsconfig.json)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-4169E1?logo=postgresql&logoColor=white)](backend/alembic/versions)
[![Tests](https://img.shields.io/badge/tests-80%20backend%20%2B%203%20E2E-brightgreen)](#-running-tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Live demo](https://img.shields.io/badge/demo-live-success?logo=vercel)](https://smart-roster-management-system-lyart.vercel.app/)
<!-- TODO: add a CI build-status badge once a workflow exists (no .github/workflows yet) -->

**Live demo:** [smart-roster-management-system-lyart.vercel.app](https://smart-roster-management-system-lyart.vercel.app/) · **API docs:** [smart-roster-api.onrender.com/docs](https://smart-roster-api.onrender.com/docs)

> The API runs on Render's free tier and sleeps after 15 idle minutes. The first request after that can take about a minute while it wakes up. Open the [health check](https://smart-roster-api.onrender.com/api/health) first if the app seems slow to load.

![Monthly roster grid](docs/screenshots/02-roster-employee-view.png)

<details>
<summary><b>Table of contents</b></summary>

- [Overview](#overview)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Running the Project](#running-the-project)
- [Usage](#usage)
- [Running Tests](#-running-tests)
- [Design Decisions & Approach](#design-decisions--approach)
- [Roadmap / Known Limitations](#roadmap--known-limitations)
- [Contributing](#contributing)
- [License](#license)
- [Contact / Author](#contact--author)

</details>

## Overview

Smart Roster plans a month of work for a team that supports many D2C brands. Each brand-process (Customer Support, Abandoned Cart Conversions, NDR and so on) has its own operating calendar and per-shift staffing minimums. Each employee has their own leave, rest rules and assignments.

A Google OR-Tools CP-SAT model assigns every employee their working days, shift and duties. An independent validator then re-checks the result and classifies it as **fully covered**, **partially covered**, **invalid**, **infeasible** or **solver timeout**. Every gap comes with an explanation and ranked replacements. When availability changes after publishing, only the affected window is re-planned.

It is built for operations managers and pod leads who need defensible rosters instead of hand-maintained spreadsheets.

## Key Features

- **Constraint solver.** Assigns employees to individual brand-process shifts each day. Hard rules are never relaxed: leave, fixed offs, weekly rest, consecutive-day caps, minimum rest between shifts, one shift per day, and load caps. Coverage is maximised; gaps become explicit, explained shortfalls.
- **Independent validation.** A separate validator re-derives every rule from the stored rows. A roster is never marked fully covered while mandatory coverage is missing.
- **Shift-level coverage.** Requirements are set per brand-process, shift and date, with weekday or specific-date overrides (an override of 0 switches a shift off).
- **Explained gaps.** Each gap is tagged *unavoidable* or *trade-off*, lists why every eligible person is not covering, and offers server-ranked fixes (add duty, work on an off day with a swap, change shift).
- **Change management.** A what-if impact preview, leave and unavailability approval that flags affected rosters as stale, and window-scoped re-optimisation that keeps manual edits unless explicitly overridden, returning a diff.
- **Versioning.** Unlimited drafts per month, one published version, immutable history, version comparison, and publish guards (open gaps must be resolved or acknowledged with a reason).
- **Comp-offs.** Credits are earned automatically for public-holiday work on publish, then approved, consumed, expired or reversed, with a full audit trail.
- **Database-enforced integrity.** Composite foreign keys, a WORK-only duty constraint, a GiST exclusion constraint against overlapping assignments, an eligibility trigger, and a no-double-counting unique key.
- **Operations UI.** Dashboard, roster grid (employee and process views), coverage heatmap, conflicts panel, versions, change-management workflow, availability, setup screens and audit log.

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Frontend** | React 19, TypeScript, Vite 6 | SPA and build tooling |
| | Tailwind CSS 4, shadcn/ui (Base UI), Lucide | Design system and components |
| | TanStack Query, React Router 7 | Server state and routing |
| | Recharts | Dashboard coverage chart |
| **Backend** | Python 3.13, FastAPI, Pydantic v2 | REST API (106 operations) and input validation |
| | Google OR-Tools (CP-SAT) | Roster optimisation |
| | SQLAlchemy 2, Alembic | ORM and migrations |
| **Database** | PostgreSQL (psycopg 3) | Persistence; uses `btree_gist`, JSONB, partial indexes and a PL/pgSQL trigger |
| **DevOps / Tools** | pytest, Playwright | Backend tests and browser E2E tests |
| | Render, Neon, Vercel (configured) | Deployment targets: [`render.yaml`](render.yaml), [`frontend/vercel.json`](frontend/vercel.json) |

## Architecture

The scheduling engine is pure Python with no database or web imports. It takes immutable dataclasses in and returns dataclasses out, so it is unit-tested without a database. The API layer loads data, runs the engine, persists versions and synchronises conflicts. The frontend is a thin client: every status, gap, suggestion and diff comes from the API.

```mermaid
flowchart LR
    UI["React SPA<br/>(Vite, TanStack Query)"] -->|"REST /api + X-Actor"| API["FastAPI routers"]
    API --> SVC["Services<br/>versioning · edits · publish · comp-offs · staleness · audit"]
    SVC --> ADP["Engine adapter<br/>DB ⇄ dataclasses"]
    ADP --> ENG["Scheduling engine<br/>calendar · presolve · CP-SAT solver<br/>validator · re-optimiser · suggestions"]
    SVC --> DB[("PostgreSQL<br/>constraints · trigger · audit_log")]
    ADP --> DB
```

<details>
<summary><b>Project structure</b></summary>

```text
.
├── backend/
│   ├── app/
│   │   ├── scheduling/        # Pure engine: types, calendar, presolve, solver, validator, reoptimize, suggestions
│   │   ├── services/          # Roster versioning, edits, publish, availability/comp-offs, staleness, audit, dashboard
│   │   ├── api/               # FastAPI routers, dependencies (X-Actor), error mapping
│   │   ├── models/            # SQLAlchemy models (24 tables)
│   │   ├── seed/              # Fictional sample dataset + editable data/holidays.json
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── cli.py             # seed / generate / validate commands
│   │   └── main.py            # App factory, CORS, /api/health
│   ├── alembic/               # Migrations (schema, exclusion constraint, eligibility trigger)
│   ├── tests/                 # engine/ (no DB), db/ (PostgreSQL guarantees), api/ (HTTP workflows)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/             # Dashboard, Roster, Coverage, Conflicts, Versions, Changes, setup screens, Audit
│   │   ├── components/roster/ # Roster grid, day editor, gap panel, re-optimise dialog, diff view
│   │   ├── components/ui/     # shadcn/ui components
│   │   ├── hooks/queries.ts   # API queries and mutations
│   │   └── lib/               # API client, types, plan context, formatting
│   ├── e2e/                   # Playwright: no-side-effects guard + full manager journey
│   └── vercel.json
├── docs/                      # ARCHITECTURE, ASSUMPTIONS, DEPLOYMENT, investigations, screenshots
├── render.yaml                # Render Blueprint for the API
└── LICENSE                    # MIT
```

</details>

## Prerequisites

| Software | Version | Notes |
|---|---|---|
| Python | 3.13 | Tested with 3.13.7 |
| Node.js | 22 | Tested with 22.18; npm 10 |
| PostgreSQL | 18 | Tested with 18.1. The `btree_gist` extension must be available (bundled with standard builds). <!-- TODO: confirm minimum supported PostgreSQL version --> |
| Git | any recent | |

## Installation & Setup

**1. Clone the repository**

```bash
git clone https://github.com/yraj-17/Smart-Roster-Management-System.git
cd Smart-Roster-Management-System
```

**2. Create the backend virtual environment and install dependencies**

macOS / Linux:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**3. Configure environment variables**

macOS / Linux:
```bash
cp .env.example .env
```

Windows (PowerShell):
```powershell
Copy-Item .env.example .env
```

Then edit `backend/.env` and set `DATABASE_URL`.

| Variable | Where | Description | Example | Required |
|---|---|---|---|---|
| `DATABASE_URL` | backend | PostgreSQL connection (psycopg 3). `postgres://` URLs are also accepted | `postgresql+psycopg://postgres:secret@localhost:5432/smart_roster` | Yes |
| `CORS_ORIGINS` | backend | Comma-separated origins allowed to call the API | `http://localhost:5173` | No (default shown) |
| `SOLVER_DETERMINISTIC_TIME` | backend | CP-SAT deterministic-time budget (reproducible results) | `30` | No |
| `SOLVER_WALL_TIME_LIMIT` | backend | Wall-clock safety limit in seconds; hitting it with no solution yields `SOLVER_TIMEOUT` | `60` | No |
| `COMP_OFF_EXPIRY_DAYS` | backend | Days an approved comp-off credit stays usable | `60` | No |
| `VITE_API_URL` | frontend | API base URL baked into production builds. Leave empty in development (Vite proxies `/api`) | `https://api.example.com` | Production only |
| `TEST_DATABASE_URL` | tests | Test database; its name **must end in `_test`** (it is dropped and rebuilt) | `postgresql+psycopg://postgres:secret@localhost:5432/smart_roster_test` | For DB/API tests |
| `E2E_BASE_URL`, `E2E_API_URL` | E2E | Run Playwright against a deployed frontend and API instead of local servers | `https://app.example.com` | No |

**4. Create the database and run migrations**

```bash
psql -U postgres -c "CREATE DATABASE smart_roster;"
alembic upgrade head
```

**5. Load the sample dataset**

The dataset is fictional: 32 employees, 4 pods and 26 brands (21 single-resource), with deliberate stress cases in December 2026.

```bash
python -m app.cli seed            # resets the database and loads the dataset (destructive)
python -m app.cli seed --if-empty # deployment-safe: seeds only an empty database
```

**6. Install the frontend**

```bash
cd ../frontend
npm install
```

## Running the Project

### Development

```bash
# Terminal 1: API on http://localhost:8000 (interactive docs at /docs)
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: UI on http://localhost:5173 (proxies /api to 127.0.0.1:8000)
cd frontend
npm run dev
```

The UI opens on the next calendar month. Use the month picker to switch to **December 2026**, where the sample leaves and stress cases live.

### Production

```bash
# API
cd backend
alembic upgrade head && python -m app.cli seed --if-empty
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend (static build in frontend/dist; serve with any static host)
cd frontend
VITE_API_URL=https://your-api.example.com npm run build
npm run preview   # local preview of the production build
```

On Windows PowerShell, set the build variable first with `$env:VITE_API_URL="https://your-api.example.com"`.

Deployment to **Render (API) + Neon (PostgreSQL) + Vercel (frontend)** is configured in [`render.yaml`](render.yaml) and [`frontend/vercel.json`](frontend/vercel.json). [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) covers the provider comparison, free-tier limits and step-by-step setup.

**Live deployment**

| Component | URL |
|---|---|
| Web app (Vercel) | https://smart-roster-management-system-lyart.vercel.app/ |
| API (Render) | https://smart-roster-api.onrender.com |
| Interactive API docs | https://smart-roster-api.onrender.com/docs |
| Health check | https://smart-roster-api.onrender.com/api/health |
| Database | Neon PostgreSQL (Singapore), direct connection; credentials are held only in Render's environment |

### Docker

No Docker setup is provided.

## Usage

### Generate a roster (CLI)

```bash
cd backend
python -m app.cli generate --month 2026-12 --save
```

```text
Status: PARTIALLY_COVERED
Solver: OPTIMAL OPTIMAL in 1.01s  candidates=2758
Coverage: 98.64%  gaps=20  hard rule violations=0
  CONFIG         INCOMPATIBLE_PRIMARY_SHIFTS  1
  CONFIG         OVER_ALLOCATED               1
  COVERAGE       UNCOVERED_SHIFT              18
  COVERAGE       UNDERSTAFFED_SHIFT           2
  ...
Coverage gaps:
  [UNAVOIDABLE] Ember Candles/CS GEN on 14 Dec: nobody scheduled (needs 1).
      - Riya Saxena (primary): on approved leave
  [UNAVOIDABLE] Petal Florals/CS GEN on 24 Dec: 1 of 2 staffed.
      - Vikram Desai (backup): on approved leave
  ...
```

Every remaining gap in the sample month is a deliberate scenario, documented in [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md).

### Generate and inspect through the API

All write requests accept an optional `X-Actor` header, which is recorded in the audit log.

```bash
curl -X POST http://localhost:8000/api/roster-plans/2026/12/generate \
     -H "Content-Type: application/json" -H "X-Actor: ops.manager" -d '{}'
```

```json
{
  "id": 1,
  "version_no": 1,
  "kind": "GENERATED",
  "status": "DRAFT",
  "validation_status": "PARTIALLY_COVERED",
  "coverage_pct": 98.64,
  "summary": { "gaps": 20, "uncovered": 18, "understaffed": 2, "hard_rule_violations": 0, "soft_issues": 42, "required_slot_days": 1456 },
  "year": 2026,
  "month": 12
}
```

```bash
curl "http://localhost:8000/api/versions/1/roster?view=brand&ref_id=<brand_id>"  # roster grid data (company|pod|brand|process|employee)
curl "http://localhost:8000/api/versions/1/coverage"                             # slot × day statuses
curl "http://localhost:8000/api/versions/1/conflicts?category=COVERAGE&status=OPEN"
curl "http://localhost:8000/api/conflicts/<conflict_id>/suggestions"             # ranked replacements
```

Brand ids come from `GET /api/brands`.

<details>
<summary><b>Change management: what-if → approve → re-optimise → publish</b></summary>

```bash
# 1. Read-only impact of an absence
curl -X POST http://localhost:8000/api/impact-preview -H "Content-Type: application/json" \
     -d '{"employee_id": 2, "date_from": "2026-12-30", "date_to": "2026-12-31"}'

# 2. Approve a leave: affected versions become STALE; the response includes a re-optimise window
curl -X POST http://localhost:8000/api/leaves/<leave_id>/approve
# → {"stale_version_ids": [1], "reoptimize_hint": {"employee_ids": [2], "date_from": "2026-12-30", "date_to": "2026-12-31"}, ...}

# 3. Re-plan only that window; creates a new draft and returns a diff
curl -X POST http://localhost:8000/api/versions/1/reoptimize -H "Content-Type: application/json" \
     -d '{"employee_ids": [2], "date_from": "2026-12-30", "date_to": "2026-12-31", "reason": "Leave approved"}'

# 4. Publish; refused while gaps are open
curl -X POST http://localhost:8000/api/versions/2/publish
# → 409 {"error": {"code": "open_gaps", "message": "22 coverage gap(s) are still open. Resolve or acknowledge each one (with a reason) before publishing.", ...}}
```

With the sample data, approving Rahul Mehta's requested leave (30–31 Dec) makes the draft `INVALID`, because he is still rostered on those days. Re-optimising that window changes exactly 2 entries and activates his trained backup, Ananya Rao, for all three Lumo Skincare processes.

</details>

| | |
|---|---|
| ![Coverage heatmap](docs/screenshots/05-coverage-heatmap.png) | ![Gap panel](docs/screenshots/06-gap-panel-suggestions.png) |
| ![Change impact](docs/screenshots/08-change-impact-preview.png) | ![Re-optimise result](docs/screenshots/09-reoptimize-result.png) |

All 22 screenshots are in [docs/screenshots](docs/screenshots).

## 🧪 Running Tests

**Engine tests** (no database needed, ~5 s):

```bash
cd backend
pytest tests/engine
```

**All backend tests** (engine + PostgreSQL + API). Point `TEST_DATABASE_URL` at a database whose name ends in `_test`; it is rebuilt from the migrations.

macOS / Linux:
```bash
TEST_DATABASE_URL=postgresql+psycopg://postgres:secret@localhost:5432/smart_roster_test pytest
```

Windows (PowerShell):
```powershell
$env:TEST_DATABASE_URL="postgresql+psycopg://postgres:secret@localhost:5432/smart_roster_test"; pytest
```

**Browser E2E tests** (require the API running on freshly seeded data; the Vite dev server starts automatically):

```bash
cd backend && python -m app.cli seed && uvicorn app.main:app --port 8000
cd frontend && npm run e2e
```

| Suite | Covers |
|---|---|
| `tests/engine` | Single- and multi-resource brands, shared processes, multi-duty days without double counting, load caps and backup stretch, incompatible shifts, night→morning rest, holiday calendars, preference vs coverage priority, INFEASIBLE vs SOLVER_TIMEOUT, window re-optimisation and manual-row preservation, determinism |
| `tests/db` | Composite foreign keys, WORK-only duties, overlap exclusion, eligibility trigger, single published version, idempotent seeding |
| `tests/api` | CRUD and validation, views, validated edits (409s), suggestions, publish guards, leave → re-optimise workflow, comp-off lifecycle, dashboard |
| `frontend/e2e` | Browsing never writes; full manager journey; every management screen |

As of the latest run: **80 backend tests** and **3 Playwright tests** pass.

## Design Decisions & Approach

### 1. How are employees, brands, processes, pods and their relationships modelled?
Employees belong to a **pod**. A pod lead is an employee referenced by the pod. A **brand** has many **brand-processes**, each with its own operating calendar (a 7-bit weekday mask plus "operates on holidays"). The brand's holiday calendar is shared by all its processes.

Each brand-process runs one or more shifts (`brand_process_shifts`). That shift is the unit of coverage, with a default minimum headcount and optional weekday or date overrides.

**Assignments** link an employee to a brand-process as PRIMARY or BACKUP, with a workload percentage, an optional shift restriction and effective dates. A GiST exclusion constraint allows only one assignment per employee per brand-process at any date.

Rosters are stored as versions. Each version has one `roster_entries` row per employee-day (status and shift) and `roster_duties` rows for what they actually do.

### 2. How does the system generate a roster and verify it satisfies the constraints?
The CP-SAT model decides, per employee and day, whether they work, which single shift they take, and which eligible brand-process shifts they cover. Employee rules are hard constraints: absences, fixed offs, weekly rest, maximum consecutive days, minimum rest hours and load caps.

Coverage uses a shortfall variable with a dominant penalty. Lower-weight objectives then cover idle offs, primary continuity, backup use, holiday work, preferences and fairness. The solver uses a fixed seed and a single worker, so results are reproducible.

An **independent validator** then re-checks every rule from the stored rows. It counts only valid duties, one per person per slot, and classifies the version. Fully covered requires zero shortfall and zero hard violations.

### 3. How are single-resource brands handled differently from multi-employee brands?
There is no special-casing; the difference comes from the data. A single owner must still take weekly rest, so their off days create gaps unless a trained **backup** exists.

The solver activates backup duties only when needed, within a stretch allowance above the backup's normal load cap. Multi-employee brands cover each other through shared assignments. Shift-specific minimums (for example day plus night) are enforced per shift.

### 4. What happens when the sole employee for a brand is unavailable on a required day?
Every required shift of that brand becomes a gap. If no eligible person can work that day, the gap is tagged **unavoidable**; otherwise it is a **trade-off**, and the explanation lists each eligible person and why they are not covering.

Ranked suggestions offer concrete fixes. If the absence is recorded after generation, the roster is flagged stale. The manager can preview the impact and re-optimise only that window, which activates the backup if one exists.

### 5. How are conflicting requirements or insufficient staffing handled?
Coverage is soft: the model always returns a roster that respects employee rules, with explicit shortfalls, rather than failing or silently breaking a rule.

The result is **INFEASIBLE** only when locked or manual rows contradict hard rules. CP-SAT then names the culprit rows through assumption literals. A timeout without a solution is reported separately as **SOLVER_TIMEOUT**. Master-data problems (over-allocation, incompatible primary shifts, unstaffed slots) appear as configuration warnings.

### 6. What is automated, and what stays under human control?
**Automated:**
- generation, validation and gap explanations
- suggestion ranking and staleness detection
- window re-optimisation
- comp-off earning and reversal on publish

**Human:**
- approving leave, requests and comp-off credits
- choosing and applying fixes
- manual edits, which are locked against re-optimisation unless overridden
- acknowledging gaps with a reason
- publishing

Accepting reduced cover is a business and client decision, so the system explains and recommends but never accepts on the manager's behalf.

### 7. If the team and brand count doubled, what would change?
The model grows roughly linearly in candidate duties, and the sample month (32 people, about 2,750 candidates) solves to proven optimality in seconds. At larger scale:
- **Solving:** run generation as a background job with progress reporting, and use multi-worker CP-SAT.
- **Decomposition:** split the problem by pod where pods do not share backups.
- **Writes:** bulk-insert roster rows.
- **Web tier:** paginate the roster grid, and add authentication with role-based access per pod.

### 8. With one more week, what would be improved first?
1. Authentication and roles (pod lead vs operations manager), replacing the `X-Actor` header.
2. Background solving with progress reporting.
3. Undo for manual edits.
4. Notifications when a published roster changes.
5. Fairness reporting across months.
6. A CI pipeline running the backend and E2E suites.

## Roadmap / Known Limitations

- **No authentication.** The operator name comes from the `X-Actor` header and is recorded for audit only.
- **One shift per employee per day.** Split shifts are intentionally out of scope.
- **Headcount coverage.** Coverage counts heads, not FTE load.
- **Synchronous generation.** Roster generation runs inside the HTTP request.
- **Sample-data assumptions.** Movable festival dates are approximate.
- **No CI workflow or Docker setup yet.**
- **Free-tier hosting.** The free-tier deployment sleeps when idle (about 1-minute cold start). See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Contributing

1. Create a feature branch.
2. Keep scheduling logic in `backend/app/scheduling/` (no database or web imports) and add engine tests for behaviour changes.
3. Run `pytest` (with `TEST_DATABASE_URL`), `npm run build`, `npm run lint` and `npm run e2e` before opening a pull request.
4. Document new assumptions in [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md).

External contributions are welcome. Please open an issue first for substantial changes, then submit a pull request from a feature branch following the guidelines above.

## License

Released under the [MIT License](LICENSE).

## Contact / Author

- **Name:** Raj Yadav
- **LinkedIn:** [linkedin.com/in/raj-yadav-706b60397](https://www.linkedin.com/in/raj-yadav-706b60397)
- **Email:** ryadav.tech17@gmail.com

Built as a submission for the DataStraw Tech Internship Assessment.
