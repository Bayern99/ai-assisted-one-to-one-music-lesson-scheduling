import { test, expect } from './fixtures'

const routes = [
  ['Overview', '/', 'Overview'],
  ['Source Data', '/students', 'Source Data'],
  ['Lecture Locks', '/schedule/lectures', 'Lecture Locks'],
  ['Import Sources', '/schedule/import', 'Import Sources'],
  ['Scheduling Rules', '/schedule/rules', 'Scheduling Rules'],
  ['Optimizer', '/schedule/optimize', 'Optimizer'],
  ['Resolve Schedule', '/schedule/resolve', 'Resolve Schedule'],
  ['Schedule Export', '/schedule/export', 'Schedule Export'],
] as const

test('Relative is the complete UI family and no visible interface copy falls below the craft floor', async ({ authenticatedPage: page, e2e }) => {
  for (const [name, route, heading] of routes) {
    await page.goto(`${e2e.baseURL}${route}`)
    await expect(page.getByRole('heading', { name: heading, exact: true }).first()).toBeVisible()
    await page.evaluate(async () => { await document.fonts.ready })

    expect(await page.evaluate(() => ({
      book: document.fonts.check('400 13px Relative'),
      medium: document.fonts.check('500 13px Relative'),
      bold: document.fonts.check('700 27px Relative'),
      body: getComputedStyle(document.body).fontFamily,
    })), `${name} font family`).toEqual({
      book: true,
      medium: true,
      bold: true,
      body: expect.stringContaining('Relative'),
    })

    const visibleCopy = await page.locator('body').innerText()
    expect(visibleCopy, `${name} exposes a full workspace hash`).not.toMatch(/\b[a-f0-9]{20,}\b/i)
    expect(visibleCopy, `${name} exposes internal implementation copy`).not.toMatch(/React V7|Python scheduling|Streamlit|Local API|SQLite|pandas|openpyxl|xlsxwriter|Step 4: Interactive Editor/i)

    const undersized = await page.evaluate(() => [...document.body.querySelectorAll<HTMLElement>('*')]
      .filter((node) => {
        if (node.children.length || !node.textContent?.trim()) return false
        const style = getComputedStyle(node)
        const rect = node.getBoundingClientRect()
        return style.display !== 'none'
          && style.visibility !== 'hidden'
          && Number(style.opacity) > 0
          && rect.width > 0
          && rect.height > 0
          && Number.parseFloat(style.fontSize) < 10.5
      })
      .slice(0, 30)
      .map((node) => ({
        className: node.className,
        size: getComputedStyle(node).fontSize,
        text: node.textContent?.trim().slice(0, 80),
      })))
    expect(undersized, `${name} contains undersized visible copy`).toEqual([])
  }
})
