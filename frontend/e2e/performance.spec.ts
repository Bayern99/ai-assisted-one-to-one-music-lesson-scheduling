import { test, expect } from './fixtures'

test('local schedule content appears within two seconds', async ({ authenticatedPage: page, e2e }) => {
  const started = performance.now()
  await page.goto(`${e2e.baseURL}/schedule/resolve`)
  await expect(page.getByLabel('Schedule grid')).toBeVisible()
  expect(performance.now() - started).toBeLessThan(2_000)
})

test('cached assignment selection feedback appears within 150ms', async ({ authenticatedPage: page, e2e }) => {
  await page.goto(`${e2e.baseURL}/schedule/resolve?workspace=schedule`)
  await expect(page.locator('[data-assignment-id="seed-assignment"]')).toBeVisible()
  const elapsed = await page.evaluate(async () => {
    const assignment = document.querySelector<HTMLButtonElement>('[data-assignment-id="seed-assignment"]')
    if (!assignment) throw new Error('Schedule assignment is missing')
    const started = performance.now()
    assignment.click()
    const selected = () => document.querySelector('[aria-label="Selected assignment"]')?.textContent?.includes('Piano lesson')
    if (selected()) return performance.now() - started
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => { observer.disconnect(); reject(new Error('Selection feedback timed out')) }, 1_000)
      const observer = new MutationObserver(() => {
        if (!selected()) return
        window.clearTimeout(timeout)
        observer.disconnect()
        resolve()
      })
      observer.observe(document.body, { childList: true, subtree: true, characterData: true })
    })
    return performance.now() - started
  })
  expect(elapsed).toBeLessThan(150)
})
