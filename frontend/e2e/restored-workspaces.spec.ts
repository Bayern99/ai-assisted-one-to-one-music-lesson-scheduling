import { test, expect } from './fixtures'

test('Source Data restores safe deletion and both recovery exports', async ({ authenticatedPage: page, e2e }) => {
  await page.goto(`${e2e.baseURL}/students/s1`)
  await expect(page.getByRole('heading', { name: 'Student 0001' })).toBeVisible()
  await page.getByRole('button', { name: 'Delete Student' }).click()
  await expect(page.getByRole('dialog', { name: /Delete Student 0001/ })).toBeVisible()
  await page.getByRole('button', { name: 'Confirm Delete' }).click()
  await expect(page).toHaveURL(/\/students$/)
  await expect(page.getByRole('link', { name: /Open student Student 0001/ })).toHaveCount(0)

  await page.getByRole('button', { name: /Import & Backup/ }).click()
  await page.getByRole('button', { name: 'Build Recovery Files' }).click()
  await expect(page.getByRole('link', { name: 'Save Source_Data_Backup.xlsx' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Save Student_Register.xlsx' })).toBeVisible()
})
