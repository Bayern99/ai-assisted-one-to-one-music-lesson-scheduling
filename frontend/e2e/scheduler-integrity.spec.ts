import path from 'node:path'
import { test, expect } from './fixtures'

test('scheduler integrity shows canonical final occupancy before Step 4 commit', async ({ authenticatedPage: page, e2e }) => {
  await page.goto(`${e2e.baseURL}/schedule/import`)
  const section = page.getByRole('region', { name: 'Scheduler workbook import' })
  await section.locator('input[type=file]').setInputFiles(path.join(e2e.uploadsDir, 'scheduler.xlsx'))
  await section.getByRole('button', { name: 'Preview workbook' }).click()
  await expect(section.getByRole('heading', { name: '6 Sheets Detected' })).toBeVisible()
  await section.getByRole('button', { name: 'Apply workbook' }).click()
  await expect(section.getByRole('status')).toContainText('Workbook applied atomically')

  await page.goto(`${e2e.baseURL}/schedule/optimize`)
  await page.getByRole('button', { name: 'Run Optimizer' }).click()
  await expect(page.getByText('3 assignments generated')).toBeVisible()
  await expect(page.getByText('2 unresolved lessons')).toBeVisible()
  await page.getByRole('link', { name: 'Continue to Resolve' }).click()
  await page.getByRole('button', { name: 'Timetable' }).click()
  await page.getByRole('button', { name: 'Lessons' }).click()

  const issues = page.getByLabel('Needs resolution').locator('button[draggable="true"]')
  await issues.first().click()
  const editor = page.getByLabel('Selected assignment')
  const manual = editor.getByRole('button', { name: 'Adjust manually' })
  if (await manual.count()) await manual.click()
  await editor.getByLabel('Room').selectOption('R103')
  await editor.locator('select').nth(1).selectOption('1')
  await editor.getByLabel('Start time').fill('11:30')
  await editor.getByLabel('End time').fill('12:30')
  await editor.getByRole('button', { name: 'Check conflicts' }).click()
  await expect(editor.getByText('Placement clear')).toBeVisible()
  await expect(editor.getByText('Final occupancy: 11:00–13:00')).toBeVisible()

  await editor.getByLabel('End time').fill('12:00')
  await expect(editor.getByRole('button', { name: 'Check conflicts' })).toBeEnabled()
  await editor.getByRole('button', { name: 'Check conflicts' }).click()
  await expect(editor.getByRole('alert')).toContainText('Invalid course time: use a one-hour :00 or :30 proposal.')
})
