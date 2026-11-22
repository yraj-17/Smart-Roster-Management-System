/**
 * Regression guard: opening the app and browsing every screen must never write.
 * Runs first (alphabetical order, one worker) against freshly seeded data, before
 * journey.spec.ts generates the first roster.
 */
import { expect, test } from '@playwright/test'

const API = (process.env.E2E_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')

const ROUTES = ['/', '/roster', '/coverage', '/conflicts', '/versions', '/changes', '/availability',
  '/employees', '/pods', '/brands', '/assignments', '/holidays', '/audit']

test('startup and browsing send only GET requests and create no roster', async ({ page, request }) => {
  const writes: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/api/') && r.method() !== 'GET') writes.push(`${r.method()} ${r.url()}`)
  })
  await page.addInitScript(() => localStorage.setItem('roster.plan', JSON.stringify({ year: 2026, month: 12, picks: {} })))

  for (const path of ROUTES) {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
  }
  // Month navigation also only reads.
  await page.goto('/')
  await page.getByRole('button', { name: 'Previous month' }).click()
  await page.getByRole('button', { name: 'Next month' }).click()
  await page.waitForLoadState('networkidle')

  expect(writes, 'no create/update/delete may happen without a user action').toEqual([])
  for (const month of [11, 12]) {
    const versions = await (await request.get(`${API}/api/roster-plans/2026/${month}/versions`)).json()
    expect(versions, `no roster version may exist for 2026-${month} after browsing`).toEqual([])
  }
  const audit = await (await request.get(`${API}/api/audit-log?entity_type=roster_version`)).json()
  expect(audit).toEqual([])
})
