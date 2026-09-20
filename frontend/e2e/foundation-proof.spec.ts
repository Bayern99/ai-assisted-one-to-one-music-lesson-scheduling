import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from './fixtures'

const here = path.dirname(fileURLToPath(import.meta.url))
const artifactRoot = path.resolve(here, '../../artifacts/foundation-proof/after')
const scheduleGridAreaBaseline = {
  '1180x720': 314_164,
  '1440x900': 601_769,
} as const

function px(value: string) {
  return Number.parseFloat(value)
}

test('Foundation Proof loads Relative and preserves the dense native workspaces', async ({ authenticatedPage: page, e2e }) => {
  mkdirSync(artifactRoot, { recursive: true })
  const measurements: Record<string, unknown> = {}

  for (const viewport of [{ width: 1180, height: 720 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport)

    await page.goto(e2e.baseURL)
    const workspaceHeading = page.getByRole('heading', { name: 'Active Workspace', exact: true })
    await expect(workspaceHeading).toBeVisible()
    const standardHeadingSize = px(await workspaceHeading.evaluate((node) => getComputedStyle(node).fontSize))
    expect(await workspaceHeading.evaluate((node) => getComputedStyle(node).fontWeight)).toBe('500')
    await page.getByRole('button', { name: 'Increase interface text size' }).click()
    await expect(page.getByRole('button', { name: 'Reset interface text size' })).toHaveText('115%')
    expect(px(await workspaceHeading.evaluate((node) => getComputedStyle(node).fontSize))).toBeGreaterThan(standardHeadingSize)
    await page.getByRole('button', { name: 'Reset interface text size' }).click()
    await expect(page.getByRole('button', { name: 'Reset interface text size' })).toHaveText('100%')

    await page.goto(`${e2e.baseURL}/schedule/export`)
    const exportHeading = page.getByRole('heading', { name: 'Canonical Schedule Preview', exact: true })
    await expect(exportHeading).toBeVisible()
    expect(await exportHeading.evaluate((node) => ({
      family: getComputedStyle(node).fontFamily,
      weight: getComputedStyle(node).fontWeight,
    }))).toEqual({ family: expect.stringContaining('Relative'), weight: '500' })
    await page.screenshot({ path: path.join(artifactRoot, `export-headings-${viewport.width}x${viewport.height}.png`) })

    await page.goto(`${e2e.baseURL}/schedule/resolve?workspace=schedule`)
    await expect(page.getByRole('heading', { name: 'Resolve Schedule' })).toBeVisible()
    await expect(page.getByLabel('Schedule grid')).toBeVisible()
    await page.screenshot({ path: path.join(artifactRoot, `resolve-${viewport.width}x${viewport.height}.png`) })

    const assignment = page.locator('[data-assignment-id]').first()
    await assignment.click()
    const editor = page.getByRole('region', { name: 'Selected assignment' })
    await expect(editor.getByLabel('Room')).toBeVisible()
    const scheduleType = await page.evaluate(() => {
      const assignment = document.querySelector<HTMLElement>('[data-assignment-id] strong')
      const issue = document.querySelector<HTMLElement>('aside[aria-label="Needs resolution"] button small')
      const field = document.querySelector<HTMLElement>('section[aria-label="Selected assignment"] label > span')
      return {
        assignment: assignment ? getComputedStyle(assignment).fontSize : '0px',
        issue: issue ? getComputedStyle(issue).fontSize : '0px',
        field: field ? getComputedStyle(field).fontSize : '0px',
      }
    })
    expect(px(scheduleType.assignment)).toBeGreaterThanOrEqual(11.5)
    expect(px(scheduleType.issue)).toBeGreaterThanOrEqual(11.5)
    expect(px(scheduleType.field)).toBeGreaterThanOrEqual(11.5)

    const boxes = await page.evaluate(() => {
      const box = (selector: string) => {
        const rect = document.querySelector(selector)?.getBoundingClientRect()
        return rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height, area: rect.width * rect.height } : null
      }
      return {
        schedulePane: box('[data-testid="schedule-pane"]'),
        scheduleGrid: box('[aria-label="Schedule grid"]'),
        editor: box('[aria-label="Selected assignment"]'),
        issueQueue: box('aside[aria-label="Needs resolution"]'),
      }
    })
    const viewportKey = `${viewport.width}x${viewport.height}` as keyof typeof scheduleGridAreaBaseline
    measurements[viewportKey] = { scheduleType, boxes }
    expect(boxes.scheduleGrid?.area ?? 0).toBeGreaterThanOrEqual(scheduleGridAreaBaseline[viewportKey] * 0.98)
    expect((boxes.editor?.y ?? 0) + (boxes.editor?.height ?? 0)).toBeLessThanOrEqual(viewport.height)
    await page.screenshot({ path: path.join(artifactRoot, `resolve-selected-${viewport.width}x${viewport.height}.png`) })
  }

  writeFileSync(path.join(artifactRoot, 'measurements.json'), `${JSON.stringify(measurements, null, 2)}\n`, 'utf8')
})
