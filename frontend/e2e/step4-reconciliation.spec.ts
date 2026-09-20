import { test, expect } from './fixtures'

test('Step 4 provides a full reconciliation workspace and a bounded time-change pool', async ({ authenticatedPage: page, e2e }) => {
  await page.goto(`${e2e.baseURL}/schedule/rules/resolution`)
  await expect(page.getByRole('heading', { name: 'Time-change Proposal Pool' })).toBeVisible()
  const eligibility = page.getByRole('checkbox', { name: 'Allow time changes for Instructor 0001' })
  await expect(eligibility).toBeChecked()
  await eligibility.uncheck()
  await page.getByRole('button', { name: 'Save Rules' }).click()
  await expect(page.getByText('Scheduling Rules Saved.')).toBeVisible()

  await page.goto(`${e2e.baseURL}/schedule/rules/rooms`)
  const roomHeader = page.getByRole('columnheader', { name: 'Piano' })
  await expect(roomHeader).toBeVisible()
  expect(await roomHeader.evaluate((node) => getComputedStyle(node).position)).toBe('sticky')

  await page.goto(`${e2e.baseURL}/schedule/resolve`)
  await expect(page.getByLabel('Schedule grid')).toBeVisible()
  await expect(page.getByLabel('Pi reconciliation investigation')).toBeVisible()
  await expect(page.getByLabel('Needs resolution')).toHaveAttribute('data-width', '420')
  expect(await page.getByLabel('Needs resolution').evaluate((node) => getComputedStyle(node).display)).toBe('flex')
  await expect(page.getByRole('button', { name: 'Teachers' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByLabel('Schedule grid')).toBeVisible()
})
