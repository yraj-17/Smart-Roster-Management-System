# Investigation: December roster present before the first E2E run

**Date:** 2026-11-22 · **Status:** closed. Application code ruled out; regression test added.

## Observation

During the first Playwright run, the journey test expected an empty December 2026 and failed: a version `v1` already existed. It had `kind = GENERATED` and `created_by = ops.manager`, with a matching `generated` audit row at **02:10:33 IST**.

## Timeline (file timestamps, IST)

| Time | Event |
|---|---|
| ~02:08 | Dev database reseeded (`app.cli seed` truncates every table) and API started; `@playwright/test` installed 02:08:12 |
| **02:10:33** | **`v1` created** |
| 02:10:49 | Chromium download for Playwright finished |
| 02:11:47 | `playwright.config.ts` written; the first E2E run started after this |

The roster existed **before any test browser, test file or Playwright config existed**. The E2E test did not create it.

## Code audit

* **The only creator of `GENERATED` versions** is `POST /api/roster-plans/{year}/{month}/generate`, which calls `roster_service.generate_version`. The CLI (`app.cli generate --save`) also generates, but records `created_by = "cli"`.
* **`created_by = ops.manager`** is the default actor. The API applies it when the `X-Actor` header is missing, and the UI sends it when no operator name is stored in the browser. The test browser stores `e2e.manager`, so the request came from a different client.
* **No automatic paths exist.** There are no FastAPI startup or lifespan hooks or middleware that write. The seed script never creates versions. In the frontend, `/generate` is called only from `GenerateButton`'s click handler, and no `useEffect` sends a write request.

## Empirical checks

1. Reseeded, then restarted the API: **0 versions, 0 audit rows** after startup plus 15 s idle.
2. A new E2E test, `frontend/e2e/00-no-side-effects.spec.ts`, runs first on fresh data. It opens every screen and changes months, then asserts that **no non-GET API request** was sent, that **no version exists** for Nov or Dec 2026, and that the roster-version audit log is empty. It passes.
3. API access log of the full E2E run: the first 48 requests are GETs. **The first write is the journey test's own `POST .../2026/12/generate`.**

## Conclusion

The roster was created by an explicit HTTP `POST` to the generate endpoint from a client other than the test runner. The most likely source is the UI opened in another browser session against the dev server (the default operator name matches) during the ~2 minutes between API start and the first test run. The original request evidence (access log, trace) no longer exists, so the exact client cannot be identified.

**Application startup, seeding and browsing do not create or modify rosters**, and the regression test above now enforces this.

## Practice going forward

E2E tests assume freshly seeded data (`python -m app.cli seed`), with no other client using the same API while they run.
