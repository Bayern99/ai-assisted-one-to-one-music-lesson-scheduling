import { appendFileSync } from 'node:fs'
import path from 'node:path'
import { test, expect } from './fixtures'

test('external workspace change yields 409 and cached outage remains read-only', async ({ authenticatedPage: page, e2e }) => {
  await page.goto(`${e2e.baseURL}/schedule/resolve?workspace=schedule`)
  await page.locator('[data-assignment-id="seed-assignment"]').click()
  await page.getByLabel('Selected assignment').getByLabel('Start time').fill('10:00')
  await page.getByLabel('Selected assignment').getByLabel('End time').fill('11:00')
  await page.getByRole('button', { name: 'Validate move' }).click()
  await page.getByLabel('The teacher confirmed this exact day and time').check()
  await page.getByLabel('Confirmation note').fill('Confirmed before conflict simulation')
  await expect(page.getByRole('button', { name: 'Move assignment' })).toBeEnabled()
  appendFileSync(path.join(e2e.dataDir, 'bookings.json'), '\n')
  await page.getByRole('button', { name: 'Move assignment' }).click()
  await expect(page.getByRole('alert')).toContainText('Workspace conflict')

  await page.route('**/api/scheduler/session', (route) => route.abort('connectionrefused'))
  await page.getByRole('button', { name: 'Reload workspace' }).click()
  await expect(page.getByRole('alert')).toContainText('Reload failed')
  await expect(page.getByRole('button', { name: 'Move assignment' })).toBeDisabled()
  await expect(page.locator('[data-assignment-id="seed-assignment"]')).toBeVisible()
})
