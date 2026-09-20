import path from 'node:path'
import { test, expect } from './fixtures'

async function expectScheduleMetrics(
  page: import('@playwright/test').Page,
  assigned: number,
  unresolved: number,
) {
  const metrics = page.getByLabel('Schedule metrics')
  await expect(metrics.locator('dd').nth(0)).toHaveText(String(assigned))
  await expect(metrics.locator('dd').nth(1)).toHaveText(String(unresolved))
}

async function fillIssueProposal(
  editor: import('@playwright/test').Locator,
  { day = '1', end, start }: { day?: string; end: string; start: string },
) {
  const manual = editor.getByRole('button', { name: 'Adjust manually' })
  if (await manual.count()) await manual.click()
  await editor.getByLabel('Room').selectOption('R103')
  await editor.locator('select').nth(1).selectOption(day)
  await editor.getByLabel('Start time').fill(start)
  await editor.getByLabel('End time').fill(end)
}

async function validateAndApproveTimeChange(
  editor: import('@playwright/test').Locator,
  buttonName: 'Validate move' | 'Check conflicts',
) {
  await editor.getByRole('button', { name: buttonName }).click()
  const success = editor.getByText(buttonName === 'Validate move' ? 'Move Validated.' : 'Placement clear')
  await expect(success).toBeVisible()
  const confirmation = editor.getByText('Teacher confirmation required')
  if (await confirmation.count()) {
    await expect(confirmation).toBeVisible()
    const checkbox = editor.getByLabel('The teacher confirmed this exact day and time')
    await checkbox.check()
    await expect(checkbox).toBeChecked()
    await editor.getByLabel('Confirmation note').fill('Confirmed in the E2E workflow')
    await expect(checkbox).toBeChecked()
    return
  }
}

async function importWorkbook(
  page: import('@playwright/test').Page,
  file: string,
) {
  const section = page.getByRole('region', { name: 'Scheduler workbook import' })
  await section.locator('input[type=file]').setInputFiles(file)
  await section.getByRole('button', { name: 'Preview workbook' }).click()
  await expect(section.getByRole('heading', { name: '6 Sheets Detected' })).toBeVisible()
  for (const role of ['Weekly Schedule', 'Studio Schedule', 'Student Info', 'Instructor', 'Room', 'Course Code']) {
    await expect(section.getByRole('button', { name: new RegExp(role) })).toBeVisible()
  }
  const weekly = section.getByRole('button', { name: /Weekly Schedule/ })
  await expect(weekly).toContainText('4 rows')
  await expect(weekly).toContainText('header 1')
  await expect(section.getByRole('table', { name: /Sample rows from Weekly Schedule/ })).toContainText('Preferred Venue')
  await expect(section.getByRole('table', { name: /Sample rows from Weekly Schedule/ })).toContainText('R103')
  const studio = section.getByRole('button', { name: /Studio Schedule/ })
  await expect(studio).toContainText('1 row')
  await expect(studio).toContainText('header 2')
  await studio.click()
  await expect(section.getByRole('table', { name: /Sample rows from Studio Schedule/ })).toContainText('R103')
  await section.getByRole('button', { name: 'Apply workbook' }).click()
  await expect(section.getByRole('status')).toContainText('4 Weekly rows, 1 Studio row')
}

test('import optimize resolve assign drag move unassign undo redo finalize and export', async ({ authenticatedPage: page, e2e }) => {
  test.setTimeout(90_000)
  await page.goto(`${e2e.baseURL}/schedule/lectures`)
  await page.getByLabel('Lecture CSV file').setInputFiles(path.join(e2e.uploadsDir, 'lectures.csv'))
  await expect(page.getByRole('status').filter({ hasText: '1 source rows · 1 candidate' })).toBeVisible()
  const lectureTitle = page.locator('input[aria-label^="Lecture title "]').first()
  await expect(lectureTitle).toHaveValue('🔒 E2E Theory (Reg)')
  await lectureTitle.fill('E2E Theory Edited')
  await page.getByRole('button', { name: 'Check Conflicts' }).click()
  await expect(page.getByText('No Lecture Conflicts Found.')).toBeVisible()
  await page.getByRole('button', { name: 'Save Lecture Locks' }).click()
  await expect(page.getByText('Lecture Locks Saved and Revalidated.')).toBeVisible()

  await page.getByRole('link', { name: /Import Sources/ }).click()
  await expect(page.getByRole('heading', { name: 'Import Sources' })).toBeVisible()
  await importWorkbook(page, path.join(e2e.uploadsDir, 'scheduler.xlsx'))

  await page.getByRole('link', { name: /Configure Rules/ }).click()
  await expect(page.getByRole('heading', { name: 'Scheduling Rules' })).toBeVisible()
  await page.getByRole('link', { name: /Rooms & Preferences/ }).click()
  await page.getByRole('button', { name: /Dr\. Piano/ }).click()
  const sourcePreference = page.getByLabel('Source preferences for Instructor 0001')
  await expect(sourcePreference).toContainText('R103')
  await expect(sourcePreference).toContainText('2 imported requests')

  await page.getByRole('link', { name: /Run Optimizer/ }).click()
  await page.getByRole('button', { name: 'Run Optimizer' }).click()
  await expect(page.getByText('3 assignments generated')).toBeVisible()
  await expect(page.getByText('2 unresolved lessons')).toBeVisible()
  await page.getByRole('link', { name: 'Continue to Resolve' }).click()
  await page.getByRole('button', { name: 'Timetable' }).click()
  await page.getByRole('button', { name: 'Lessons' }).click()

  const assignments = page.locator('[data-assignment-id]:not([data-lecture="true"])')
  const issueQueue = page.getByLabel('Needs resolution')
  const unresolvedIssues = issueQueue.locator('button[draggable="true"]')
  const editor = page.getByLabel('Selected assignment')
  await expect(page.locator('[data-assignment-id="seed-assignment"]')).toHaveCount(0)
  await expect(assignments).toHaveCount(3)
  await expect(page.locator('[data-kind="weekly"]')).toHaveCount(2)
  await expect(page.locator('[data-kind="studio"]')).toHaveCount(1)
  await expect(unresolvedIssues).toHaveCount(2)
  await expectScheduleMetrics(page, 3, 2)

  await unresolvedIssues.first().click()
  await expect(editor.getByRole('heading', { name: 'Resolve Issue' })).toBeVisible()
  await fillIssueProposal(editor, { start: '11:00', end: '12:00' })
  await validateAndApproveTimeChange(editor, 'Check conflicts')
  await editor.getByRole('button', { name: 'Place lesson' }).click()
  await expect(assignments).toHaveCount(4)
  await expect(unresolvedIssues).toHaveCount(1)
  await expectScheduleMetrics(page, 4, 1)
  await editor.getByRole('button', { name: 'Back to issues' }).click()
  await expect(issueQueue).toBeVisible()

  const canvas = page.getByTestId('schedule-grid-canvas')
  const canvasBox = await canvas.boundingBox()
  if (!canvasBox) throw new Error('Schedule grid canvas has no layout bounds')
  const visibleStart = Number((await canvas.getAttribute('data-time-start') ?? '09:00').slice(0, 2)) * 60
  const visibleEnd = Number((await canvas.getAttribute('data-time-end') ?? '22:00').slice(0, 2)) * 60
  const timeX = (hour: number, width = canvasBox.width) => 74 + ((hour * 60 - visibleStart) / (visibleEnd - visibleStart)) * (width - 74)
  const noonDropX = timeX(12)
  // The queue exposes a click-to-place fallback for browsers that do not
  // dispatch native HTML drag events reliably (notably WebKit in CI).
  await unresolvedIssues.first().click()
  await canvas.click({ position: { x: noonDropX, y: 45 } })
  await expect(editor.getByRole('heading', { name: 'Resolve Issue' })).toBeVisible()
  await editor.getByRole('button', { name: 'Adjust manually' }).click()
  await expect(editor.getByLabel('Room')).toHaveValue('R103')
  await expect(editor.locator('select').nth(1)).toHaveValue('1')
  await expect(editor.getByLabel('Start time')).toHaveValue('12:00')
  await expect(editor.getByLabel('End time')).toHaveValue('13:00')
  await validateAndApproveTimeChange(editor, 'Check conflicts')
  await editor.getByRole('button', { name: 'Place lesson' }).click()
  await expect(assignments).toHaveCount(5)
  await expect(unresolvedIssues).toHaveCount(0)
  await expectScheduleMetrics(page, 5, 0)

  const assignment = page.locator('[data-kind="weekly"]').first()
  const assignmentId = await assignment.getAttribute('data-assignment-id')
  if (!assignmentId) throw new Error('Weekly assignment has no canonical id')
  const assignmentBox = await assignment.boundingBox()
  if (!assignmentBox) throw new Error('Weekly assignment has no layout bounds')
  const assignmentCanvasBox = await canvas.boundingBox()
  if (!assignmentCanvasBox) throw new Error('Schedule grid canvas has no layout bounds')
  const threePmDropX = timeX(15, assignmentCanvasBox.width)
  await page.mouse.move(assignmentBox.x + 5, assignmentBox.y + 5)
  await page.mouse.down()
  await page.mouse.move(assignmentCanvasBox.x + threePmDropX + 5, assignmentCanvasBox.y + 40, { steps: 12 })
  await page.mouse.up()
  await expect(editor.getByRole('heading', { name: 'Selected Assignment' })).toBeVisible()
  await expect(editor.getByLabel('Start time')).toHaveValue('15:00')
  await expect(editor.getByLabel('End time')).toHaveValue('16:00')
  // dnd-kit deliberately quarantines click events for 50 ms after a pointer
  // drop so the release cannot re-select the dragged card. Wait for that
  // cleanup boundary before exercising the next independent control.
  await page.waitForTimeout(60)
  await validateAndApproveTimeChange(editor, 'Validate move')
  await editor.getByRole('button', { name: 'Move assignment' }).click()
  await expect(editor.getByRole('button', { name: 'Unlock assignment' })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`assignment=${encodeURIComponent(assignmentId)}`))
  await expect(editor.getByLabel('Start time')).toHaveValue('15:00')
  await editor.getByLabel('Start time').fill('14:00')
  await editor.getByLabel('End time').fill('15:00')
  await expect(editor.getByLabel('Start time')).toHaveValue('14:00')
  await expect(editor.getByLabel('End time')).toHaveValue('15:00')
  await editor.locator('select').nth(1).selectOption('2')
  await expect(editor.locator('select').nth(1)).toHaveValue('2')
  await validateAndApproveTimeChange(editor, 'Validate move')
  await editor.getByRole('button', { name: 'Move assignment' }).click()
  await expect(editor.locator('select').nth(1)).toHaveValue('2')
  await expect(editor.getByLabel('Start time')).toHaveValue('14:00')
  await expect(editor.getByLabel('End time')).toHaveValue('15:00')

  await editor.getByRole('button', { name: 'Unassign assignment' }).click()
  await expect(page.getByRole('dialog', { name: 'Unassign this assignment?' })).toBeVisible()
  await page.getByRole('button', { name: 'Confirm unassign' }).click()
  await expect(assignments).toHaveCount(0)
  await expect(unresolvedIssues).toHaveCount(1)
  await expectScheduleMetrics(page, 4, 1)
  await expect(editor.getByRole('heading', { name: 'Resolve Issue' })).toBeVisible()
  await fillIssueProposal(editor, { day: '2', start: '14:00', end: '15:00' })
  await validateAndApproveTimeChange(editor, 'Check conflicts')
  await editor.getByRole('button', { name: 'Place lesson' }).click()
  await expect(assignments).toHaveCount(1)
  await expect(unresolvedIssues).toHaveCount(0)
  await expectScheduleMetrics(page, 5, 0)

  await expect(page.getByRole('button', { name: 'Undo last schedule change' })).toBeEnabled()
  await page.getByRole('button', { name: 'Undo last schedule change' }).click()
  await expect(assignments).toHaveCount(0)
  await expect(unresolvedIssues).toHaveCount(1)
  await expectScheduleMetrics(page, 4, 1)
  await expect(page.getByRole('button', { name: 'Redo schedule change' })).toBeEnabled()
  await page.getByRole('button', { name: 'Redo schedule change' }).click()
  await expect(assignments).toHaveCount(1)
  await expect(unresolvedIssues).toHaveCount(0)
  await expectScheduleMetrics(page, 5, 0)

  await page.getByRole('button', { name: 'Stage schedule' }).click()
  await expect(page.getByLabel('Schedule authority').getByText('Staged')).toHaveAttribute('data-active', 'true')
  await page.getByRole('button', { name: 'Finalize schedule' }).click()
  await page.getByRole('button', { name: 'Confirm finalize' }).click()
  await expect(page).toHaveURL(/\/schedule\/export$/)
  await page.getByRole('button', { name: 'Build export files' }).click()
  await expect(page.getByRole('link', { name: /master schedule/i })).toBeVisible()
  await expect(page.getByRole('link', { name: /weekly schedule/i })).toBeVisible()
  await expect(page.getByRole('link', { name: /studio schedule/i })).toBeVisible()
})
