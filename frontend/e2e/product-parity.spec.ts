import { test, expect } from './fixtures'

test('dashboard continue-work and student edit use real API state', async ({ authenticatedPage: page, e2e }) => {
  await page.goto(e2e.baseURL)
  const continueLink = page.getByRole('link', { name: 'Continue schedule resolution' })
  await expect(continueLink).toBeVisible()
  await continueLink.click()
  await expect(page.getByLabel('Schedule grid')).toBeVisible()

  await page.goto(`${e2e.baseURL}/students`)
  await page.getByRole('link', { name: /Open student Student 0001/ }).click()
  await page.getByLabel('Instructor').fill('Dr. Updated')
  await page.getByRole('button', { name: 'Save student' }).click()
  await expect(page.getByText('Student record saved.', { exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Dr. Updated' })).toBeVisible()
})
