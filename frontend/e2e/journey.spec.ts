/**
 * The complete operations-manager journey, against a freshly seeded backend:
 * generate → inspect coverage → create & identify a gap → apply a suggestion →
 * review & approve leave → re-optimise the window → compare versions → publish.
 */
import { expect, test, type Page } from '@playwright/test'

const SHOTS = '../docs/screenshots'
const RAHUL = 2   // E002, sole owner of Lumo Skincare (seed)
const RIYA = 23   // E023, Ember Candles, on approved leave 14–18 Dec (seed)

async function shot(page: Page, name: string) {
  await page.waitForTimeout(400) // let toasts/animations settle
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false })
}

async function nav(page: Page, name: string) {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name, exact: true }).click()
}

async function toast(page: Page, text: string | RegExp) {
  await expect(page.locator('[data-sonner-toast]').filter({ hasText: text }).first()).toBeVisible()
}

test.describe.configure({ mode: 'serial' })

test('operations manager journey', async ({ page }) => {
  await page.addInitScript(() => {
    if (!sessionStorage.getItem('e2e-init')) {
      localStorage.setItem('roster.plan', JSON.stringify({ year: 2026, month: 12, picks: {} }))
      localStorage.setItem('roster.actor', 'e2e.manager')
      sessionStorage.setItem('e2e-init', '1')
    }
  })

  // 1. Dashboard starts empty; generate the month.
  await page.goto('/')
  await expect(page.getByTestId('month-label')).toHaveText('December 2026')
  await expect(page.getByText('No roster for this month')).toBeVisible()
  await page.getByTestId('generate-roster').first().click()
  await toast(page, /Generated v1/)
  await expect(page.getByTestId('coverage-chart')).toBeVisible()
  await expect(page.locator('main').getByText('Partially covered').first()).toBeVisible()
  await shot(page, '01-dashboard')

  // 2. Roster grid (employee + process views) and coverage heatmap.
  await nav(page, 'Roster')
  await expect(page.getByTestId('roster-grid')).toBeVisible()
  await shot(page, '02-roster-employee-view')
  await page.getByRole('tab', { name: 'Process view' }).click()
  await expect(page.getByTestId('process-grid')).toBeVisible()
  await shot(page, '03-roster-process-view')
  await page.getByRole('tab', { name: 'Employee view' }).click()

  // 3a. A 409 is surfaced, not swallowed: try to roster Riya on her approved leave.
  await page.getByTestId(`cell-${RIYA}-2026-12-15`).click()
  await page.getByRole('radio', { name: 'Working' }).click()
  const firstDuty = page.getByRole('dialog').getByRole('checkbox').first()
  await firstDuty.click()
  await page.getByTestId('save-day').click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('on leave')
  await shot(page, '04-edit-rejected-409')
  await page.getByRole('button', { name: 'Cancel' }).click()

  // 3b. Manual change creates a gap: give Rahul (sole Lumo resource) an extra day off.
  const rahulWorkDay = page.locator(`[data-testid^="cell-${RAHUL}-2026-12-0"]`).filter({ hasText: 'GEN' }).first()
  const testId = await rahulWorkDay.getAttribute('data-testid')
  const gapDate = testId!.split('-').slice(2).join('-')
  await rahulWorkDay.click()
  await page.getByRole('radio', { name: 'Weekly off' }).click()
  await page.getByTestId('save-day').click()
  await toast(page, /Saved Rahul Mehta/)

  // 4. Identify the gap on the heatmap and apply a suggested replacement.
  await nav(page, 'Coverage')
  await expect(page.getByTestId('coverage-heatmap')).toBeVisible()
  await shot(page, '05-coverage-heatmap')
  await page.getByRole('combobox', { name: 'Brand' }).selectOption('Lumo Skincare')
  const gapCell = page.locator(`[data-testid$="-${gapDate}"][data-status="UNCOVERED"]`).first()
  await expect(gapCell).toBeVisible()
  await gapCell.click()
  await expect(page.getByTestId('gap-panel')).toBeVisible()
  await expect(page.getByTestId('suggestions')).toBeVisible()
  await shot(page, '06-gap-panel-suggestions')
  await page.getByTestId('apply-suggestion').first().click()
  await toast(page, /Gap resolved|assigned/)

  // 5. Conflicts panel: hard rules, gaps and preferences are separated.
  await nav(page, 'Conflicts')
  await expect(page.getByTestId('group-hard')).toBeVisible()
  await expect(page.getByTestId('group-gaps')).toContainText('Coverage gaps')
  await shot(page, '07-conflicts')

  // 6. Change management: review the pending leave, approve, re-optimise the window.
  await nav(page, 'Change management')
  await page.getByTestId('pending-leaves').getByRole('button', { name: 'Review impact' }).first().click()
  await expect(page.getByTestId('impact-result')).toContainText('Lumo Skincare')
  await shot(page, '08-change-impact-preview')
  await page.getByTestId('record-change').click()
  await toast(page, /flagged for re-check/)
  await expect(page.locator('main').getByText('Invalid').first()).toBeVisible() // roster has Rahul working on the leave days
  await page.getByTestId('open-reoptimize').click()
  await page.getByTestId('run-reoptimize').click()
  await expect(page.getByTestId('diff-view')).toBeVisible()
  await shot(page, '09-reoptimize-result')
  await page.getByTestId('open-new-version').click()
  await expect(page.getByTestId('version-picker')).toContainText('v2')

  // 7. Compare v1 and v2.
  await nav(page, 'Versions')
  await expect(page.getByTestId('versions-table')).toBeVisible()
  await expect(page.getByTestId('diff-view')).toBeVisible()
  await page.getByTestId('diff-view').scrollIntoViewIfNeeded()
  await shot(page, '10-versions-compare')

  // 8. Publish: blocked while gaps are open (409), then acknowledge and publish.
  await page.getByTestId('publish-2').click()
  await page.getByTestId('confirm-publish').click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('still open')
  await shot(page, '11-publish-blocked-409')
  await page.getByRole('button', { name: 'Cancel' }).click()

  await nav(page, 'Conflicts')
  await page.getByRole('button', { name: /Acknowledge open gaps/ }).click()
  await page.getByTestId('bulk-reason').fill('Clients informed of reduced cover on these days')
  await page.getByTestId('bulk-ack').click()
  await toast(page, /gap\(s\) acknowledged/)

  await nav(page, 'Versions')
  await page.getByTestId('publish-2').click()
  await page.getByTestId('confirm-publish').click()
  await toast(page, /v2 published/)
  await expect(page.getByTestId('versions-table')).toContainText('Published')
  await shot(page, '12-published')

  // Published versions are read-only in the grid.
  await nav(page, 'Roster')
  await page.locator(`[data-testid^="cell-${RAHUL}-"]`).first().click()
  await expect(page.getByText(/read-only/)).toBeVisible()
  await page.keyboard.press('Escape')

  // Audit trail recorded the whole journey under the operator's name.
  await nav(page, 'Audit log')
  await expect(page.getByTestId('audit-table')).toContainText('e2e.manager')
  await expect(page.getByTestId('audit-table')).toContainText('Publish')
  await shot(page, '13-audit-log')
})

test('management and availability screens load real data', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('roster.plan', JSON.stringify({ year: 2026, month: 12, picks: {} })))
  const screens: [string, string, string][] = [
    ['/availability', 'Leave, availability & comp-offs', '14-availability'],
    ['/employees', 'Rahul Mehta', '15-employees'],
    ['/pods', 'Pod Alpha', '16-pods'],
    ['/brands', 'Lumo Skincare', '17-brands'],
    ['/assignments', 'Lumo Skincare / CS', '18-assignments'],
    ['/holidays', 'Christmas', '19-holidays'],
  ]
  for (const [path, text, name] of screens) {
    await page.goto(path)
    await expect(page.getByText(text).first()).toBeVisible()
    await shot(page, name)
  }
  // Comp-off credits earned when v2 was published (365-day brands worked Christmas).
  await page.goto('/availability')
  await page.getByRole('tab', { name: 'Comp-offs' }).click()
  await expect(page.getByText('Worked Christmas').first()).toBeVisible()
  await shot(page, '20-comp-offs')
  // Brand configuration sheet.
  await page.goto('/brands')
  await page.getByRole('row', { name: /Glow Theory/ }).getByRole('button', { name: 'Configure' }).click()
  await expect(page.getByText('Shifts & minimum staff').first()).toBeVisible()
  await shot(page, '21-brand-configuration')
  // Mobile layout.
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Open navigation' })).toBeVisible()
  await expect(page.getByTestId('coverage-chart')).toBeVisible() // wait for data, not just the shell
  await shot(page, '22-mobile-dashboard')
})
