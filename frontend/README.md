# Smart Roster — frontend

React 19 + TypeScript + Vite + Tailwind CSS 4 + shadcn/ui (Base UI primitives), TanStack Query, Recharts.

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api to http://127.0.0.1:8000
npm run build      # type-check + production build
npm run lint
npm run e2e        # Playwright journey against the real backend (see below)
```

* All data comes from the FastAPI backend (`src/lib/api.ts`). There is no mock data, and no scheduling or validation logic runs in the browser. Statuses, gaps, suggestions and diffs are computed by the API.
* API errors use the backend's `{"error": {code, message, details}}` model. 409s (rejected edits, publishing with open gaps) are shown verbatim.
* `VITE_API_URL` sets the API base URL in production (see `.env.example`).

## End-to-end tests

The E2E suite drives the real UI against a real backend. Start from freshly seeded data:

```bash
cd ../backend && python -m app.cli seed && uvicorn app.main:app --port 8000
cd ../frontend && npm run e2e
```

`e2e/00-no-side-effects.spec.ts` runs first: it opens every screen and asserts that nothing is written (only GET requests, and no roster created). `e2e/journey.spec.ts` walks through the whole journey: generate → inspect coverage → a 409 on an illegal edit → create and resolve a gap with a suggestion → review and approve a pending leave → re-optimise the window → compare versions → publish (a 409 while gaps are open, then acknowledge) → audit trail. A second test loads every management screen. Screenshots are written to `../docs/screenshots/`.
