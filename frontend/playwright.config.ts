import { defineConfig, devices } from '@playwright/test'

// End-to-end tests drive the real UI against a real FastAPI backend (no mocks).
//
// Local (default):   cd backend && python -m app.cli seed && uvicorn app.main:app --port 8000
//                    cd frontend && npm run e2e            (starts the Vite dev server)
// Public deployment: E2E_BASE_URL=https://<frontend> E2E_API_URL=https://<backend> npm run e2e
//                    (the journey expects freshly seeded data with no December 2026 roster yet)
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const REMOTE = !!process.env.E2E_BASE_URL

export default defineConfig({
  testDir: './e2e',
  // Hosted free tiers are slower (cold starts, fractional CPU for the solver).
  timeout: REMOTE ? 600_000 : 120_000,
  expect: { timeout: Number(process.env.E2E_EXPECT_TIMEOUT ?? (REMOTE ? 120_000 : 20_000)) },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1600, height: 1000 },
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 1000 } } }],
  webServer: REMOTE ? undefined : {
    command: 'npm run dev -- --port 5173 --strictPort',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
