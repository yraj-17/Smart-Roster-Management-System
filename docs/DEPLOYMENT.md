# Deployment

Target: **Vercel** (frontend, static) → **Render** (FastAPI web service) → **Neon** (PostgreSQL).
Total cost: €0 on free tiers.

## Why these providers

| Option | Database persistence | Sleeping / cold start | Usage limits | Verdict |
|---|---|---|---|---|
| **Neon Free** (Postgres) | Permanent; no expiry | Compute suspends after 5 min idle; first query wakes it in ~1 s | 1 GB storage/project, 100 CU-hours/month, 5 GB egress | **Chosen DB.** The seed plus many rosters is a few MB |
| Render Free Postgres | **Deleted 30 days after creation** (14-day grace), no backups | — | — | Rejected: data would vanish |
| Supabase Free | Persistent | Project **paused after ~1 week inactivity** | 500 MB | Viable fallback; the pause is risky for a reviewer link |
| **Render Free web service** | n/a (stateless; data lives in Neon) | **Spins down after 15 min idle; ~1 min cold start** | 512 MB RAM, fractional CPU, monthly instance-hours cap | **Chosen API host.** Native Python, health checks, Blueprint, auto-deploy from GitHub |
| Railway | — | No sleep | Trial credit only, then paid | Rejected: not free beyond the trial |
| Fly.io | Volumes | Machines can auto-stop | No free allowance for new orgs; card required | Rejected: cost and setup |
| Koyeb Free | — | Scales to zero | 1 small instance | Viable fallback for the API |
| **Vercel Hobby** (static) | n/a | None for static assets (global CDN) | ~100 GB transfer/month; non-commercial use | **Chosen frontend.** Fine for an assessment demo |

**Limits to accept**

- **Cold start.** The first request after 15 idle minutes waits about a minute while Render starts the API. The UI just shows its loading state. Open `/api/health` a minute before a demo.
- **Slower solver.** Render's free CPU is a fraction of a core, so solving is slower. `SOLVER_WALL_TIME_LIMIT=300` gives CP-SAT headroom, and the deterministic budget keeps results reproducible. A month typically solves in tens of seconds.
- **Persistence.** All data is in Neon, so API restarts and redeploys lose nothing.

## Architecture & configuration

```
Browser ──HTTPS──> Vercel (static React build; VITE_API_URL baked in at build time)
   └────HTTPS + CORS──> Render: uvicorn app.main:app  ──TLS──> Neon Postgres
                         start: alembic upgrade head && seed --if-empty && uvicorn
```

| Where | Variable | Value | Secret? |
|---|---|---|---|
| Render | `DATABASE_URL` | Neon **direct** connection string (`postgresql://…neon.tech/…?sslmode=require`) | **Yes.** Set only in the Render dashboard |
| Render | `CORS_ORIGINS` | The Vercel production URL, e.g. `https://smart-roster.vercel.app` | No |
| Render | `PYTHON_VERSION`, `SOLVER_*`, `COMP_OFF_EXPIRY_DAYS` | Set by `render.yaml` | No |
| Vercel | `VITE_API_URL` | The Render URL, e.g. `https://smart-roster-api.onrender.com` | No. It is a public URL and ends up in the JS bundle, by design |

The frontend contains **no credentials**. Its only setting is the public API URL. The database URL exists only in Render's environment.

**Startup is idempotent.** `alembic upgrade head` is a no-op once migrated. `seed --if-empty` loads the fictional dataset only when the `employees` table is empty, so redeploys never duplicate or wipe data. The destructive `seed` (without the flag) is for local development only.

**Health check.** `GET /api/health` returns `{"status":"ok","database":"ok","version":…,"commit":…}`, or **HTTP 503** if the database is unreachable. Render uses it as `healthCheckPath`, so a broken deploy is not promoted.

Use Neon's **direct** endpoint, not the `-pooler` one. psycopg 3 uses prepared statements, which transaction-mode PgBouncer does not support.

## Step-by-step (one-time, ~15 minutes)

1. **Neon.** Sign up at neon.tech with GitHub. Create a project named `smart-roster` with Postgres 17 or 18 in region **AWS Asia Pacific (Singapore)**. Copy the **direct** connection string from *Connect* (turn "Connection pooling" off). Don't paste it anywhere except Render.
2. **Render.** Sign up at render.com with GitHub. Choose **New → Blueprint**, select this repository, and Render reads `render.yaml`. When prompted, set `DATABASE_URL` to the Neon string and set `CORS_ORIGINS` to `https://placeholder.invalid` for now. Click **Apply**. The first deploy builds, migrates and seeds. Then check `https://<service>.onrender.com/api/health`.
3. **Vercel.** Sign up at vercel.com with GitHub. Choose **Add New → Project**, import this repository, and set **Root Directory** to `frontend` (the framework is auto-detected). Add the environment variable `VITE_API_URL=https://<service>.onrender.com` and click **Deploy**.
4. **Connect them.** In Render, set `CORS_ORIGINS` to the Vercel production URL (no trailing slash) and save. Render restarts the service with the new setting.

## Verification (run against the public URLs)

```bash
# 1. External health check
curl -s https://<service>.onrender.com/api/health

# 2. Full browser journey on fresh production data (no December roster yet)
cd frontend
E2E_BASE_URL=https://<app>.vercel.app E2E_API_URL=https://<service>.onrender.com npm run e2e
```

3. **Persistence.** Note the roster versions, restart the Render service (*Manual Deploy → Restart*), then confirm `/api/health` is ok and the same versions, entries and audit history are still listed.

## Resetting the demo data

`seed --if-empty` never resets. To restore the pristine dataset (this deletes all rosters and changes), run it once with the production `DATABASE_URL` from a trusted machine or a Render Shell:

```bash
DATABASE_URL='<neon direct url>' python -m app.cli seed
```
