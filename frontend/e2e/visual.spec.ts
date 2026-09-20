import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'
import { test, expect } from './fixtures'

test.use({ browserName: 'webkit' })

const visualNow = new Date('2026-07-13T12:30:00+08:00')
const visualViewports = [
  { width: 1180, height: 720 },
  { width: 1440, height: 900 },
  { width: 1728, height: 1117 },
  { width: 2048, height: 1280 },
]

type Landmark = { kind: 'heading' | 'label'; name: string }
type VisualRoute = { key: string; route: string; landmark: Landmark }

const visualRoutes: VisualRoute[] = [
  { key: 'dashboard', route: '/', landmark: { kind: 'heading', name: 'Workspace Health' } },
  { key: 'source-data', route: '/students', landmark: { kind: 'label', name: 'Source data workbench' } },
  { key: 'lecture-locks', route: '/schedule/lectures', landmark: { kind: 'heading', name: 'Lecture Locks' } },
  { key: 'import-source', route: '/schedule/import', landmark: { kind: 'label', name: 'Scheduler workbook import' } },
  { key: 'configure-rules', route: '/schedule/rules', landmark: { kind: 'heading', name: 'Scheduling Rules' } },
  { key: 'run-optimizer', route: '/schedule/optimize', landmark: { kind: 'heading', name: 'Workspace Readiness' } },
  { key: 'resolve', route: '/schedule/resolve', landmark: { kind: 'label', name: 'Schedule grid' } },
  { key: 'export', route: '/schedule/export', landmark: { kind: 'heading', name: 'Canonical Schedule Preview' } },
  // Workspace Rules deliberately reuses Configure rules and its canonical route/data source.
  { key: 'rules', route: '/schedule/rules', landmark: { kind: 'heading', name: 'Scheduling Rules' } },
]

const axeRoutes = [
  ...visualRoutes.filter((item) => item.key !== 'rules'),
  { key: 'student-detail', route: '/students/s1', landmark: { kind: 'heading' as const, name: 'Student 0001' } },
]

function landmarkLocator(page: Page, landmark: Landmark) {
  return landmark.kind === 'heading'
    ? page.getByRole('heading', { name: landmark.name })
    : page.getByLabel(landmark.name)
}

async function freezeVisualClock(page: Page) {
  await page.clock.setFixedTime(visualNow)
}

async function settleVisualPage(page: Page, landmark: Landmark) {
  await expect(landmarkLocator(page, landmark)).toBeVisible()
  await page.evaluate(async () => { await document.fonts.ready })
  await page.waitForLoadState('networkidle')
  await expect(page.getByText(/Loading|Refreshing/)).toHaveCount(0)
  expect(await page.locator('body').innerText()).not.toMatch(
    /React V7|Python scheduling|Streamlit|Local API|SQLite|pandas|openpyxl|xlsxwriter|Step 4: Interactive Editor/i,
  )
  // Normalize only the temporary absolute data root; keep the source path visible and unmasked.
  await page.evaluate(() => {
    document.querySelectorAll('strong').forEach((node) => {
      if (node.textContent?.includes('scheduling_rules.json')) node.textContent = 'data/scheduling_rules.json'
    })
    document.querySelectorAll<HTMLElement>('body *').forEach((node) => {
      if (node.children.length) return
      if (node.textContent?.includes('Canonical scheduling workspace')) {
        node.textContent = 'Canonical scheduling workspace'
      }
      if (node.textContent && /[a-f0-9]{20,}/i.test(node.textContent)) {
        node.textContent = node.textContent.replace(/[a-f0-9]{20,}/gi, 'workspace-version')
      }
    })
  })
}

async function captureCommittedFrame(page: Page) {
  await page.waitForTimeout(100)
  return page.screenshot({ animations: 'allow' })
}

test('schedule editor stays usable for existing and unresolved bookings in the native minimum viewport', async ({ authenticatedPage: page, e2e }) => {
  await page.setViewportSize({ width: 1180, height: 720 })
  await page.addInitScript(() => { document.documentElement.dataset.piDesktop = 'macos' })
  await freezeVisualClock(page)
  await page.goto(`${e2e.baseURL}/schedule/resolve?workspace=schedule`)
  await settleVisualPage(page, { kind: 'label', name: 'Schedule grid' })

  const assignment = page.locator('[data-assignment-id]').first()
  await expect(assignment).toContainText(/\d{2}:\d{2}–\d{2}:\d{2}/)
  await assignment.click()
  const editor = page.getByRole('region', { name: 'Selected assignment' })
  await expect(editor.getByRole('button', { name: 'Validate move' })).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Move assignment' })).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Unassign assignment' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Needs resolution' })).toBeHidden()
  await expect(page.getByTestId('schedule-pane')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Schedule inspector' })).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Back to issues' })).toBeVisible()
  const assignedBounds = await editor.boundingBox()
  expect(assignedBounds).not.toBeNull()
  expect((assignedBounds?.y ?? 0) + (assignedBounds?.height ?? 0)).toBeLessThanOrEqual(720)
  await editor.getByRole('button', { name: 'Back to issues' }).click()
  await expect(page.getByRole('region', { name: 'Needs resolution' })).toBeVisible()

  const issue = page.locator('aside[aria-label="Needs resolution"] button[draggable="true"]').first()
  await issue.click()
  await expect(page.getByRole('heading', { name: 'Resolve Issue' })).toBeVisible()
  await editor.getByRole('button', { name: 'Adjust manually' }).click()
  await expect(editor.getByRole('button', { name: 'Check conflicts' })).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Place lesson' })).toBeVisible()
  const issueBounds = await editor.boundingBox()
  expect(issueBounds).not.toBeNull()
  expect((issueBounds?.y ?? 0) + (issueBounds?.height ?? 0)).toBeLessThanOrEqual(720)
})

for (const viewport of visualViewports.filter(({ width }) => width === 1180 || width === 1440)) {
  test(`selected issue editor is vertically accessible at ${viewport.width}x${viewport.height}`, async ({ authenticatedPage: page, e2e }) => {
    await page.setViewportSize(viewport)
    await freezeVisualClock(page)
    await page.goto(`${e2e.baseURL}/schedule/resolve?workspace=schedule`)
    await settleVisualPage(page, { kind: 'label', name: 'Schedule grid' })
    await page.locator('aside[aria-label="Needs resolution"] button[draggable="true"]').first().click()
    await expect(page.getByRole('heading', { name: 'Resolve Issue' })).toBeVisible()
    await page.getByRole('button', { name: 'Adjust manually' }).click()
    await expect(page.getByRole('button', { name: 'Place lesson' })).toBeVisible()
    // The editor switches the timetable into a different scroll/compositing
    // layout. Let WebKit present that frame before taking the regression
    // image; this does not add any delay to the product interaction itself.
    await page.waitForTimeout(350)
    expect(await page.evaluate(() => ({
      documentContained: document.documentElement.scrollWidth === document.documentElement.clientWidth,
      bodyContained: document.body.scrollWidth <= document.documentElement.clientWidth,
    }))).toEqual({ documentContained: true, bodyContained: true })
    const screenshot = await captureCommittedFrame(page)
    expect(screenshot).toMatchSnapshot(`resolve-issue-${viewport.width}x${viewport.height}.png`, {
      maxDiffPixelRatio: 0.003,
    })
  })
}

test('primary routes have no serious or critical Axe violations', async ({ authenticatedPage: page, e2e }) => {
  await freezeVisualClock(page)
  for (const item of axeRoutes) {
    await page.goto(`${e2e.baseURL}${item.route}`)
    await settleVisualPage(page, item.landmark)
    const results = await new AxeBuilder({ page }).analyze()
    const blocking = results.violations.filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    expect(blocking, `${item.route}: ${blocking.map((violation) => violation.id).join(', ')}`).toEqual([])
  }
})

for (const viewport of visualViewports) {
  test(`all V7 workspaces are contained and visually stable at ${viewport.width}x${viewport.height}`, async ({ authenticatedPage: page, e2e }) => {
    await page.setViewportSize(viewport)
    await freezeVisualClock(page)
    for (const item of visualRoutes) {
      await page.goto(`${e2e.baseURL}${item.route}`)
      await settleVisualPage(page, item.landmark)
      expect(await page.evaluate(() => ({
        documentContained: document.documentElement.scrollWidth === document.documentElement.clientWidth,
        bodyContained: document.body.scrollWidth <= document.documentElement.clientWidth,
      })), `${item.key} overflows at ${viewport.width}x${viewport.height}`).toEqual({ documentContained: true, bodyContained: true })
      const screenshot = await captureCommittedFrame(page)
      expect(screenshot).toMatchSnapshot(`${item.key}-${viewport.width}x${viewport.height}.png`, {
        maxDiffPixelRatio: 0.003,
      })
    }
  })
}
