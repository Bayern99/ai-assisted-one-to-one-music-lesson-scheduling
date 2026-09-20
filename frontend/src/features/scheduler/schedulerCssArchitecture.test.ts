import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const schedulerRoot = 'src/features/scheduler'
const pageRoot = `${schedulerRoot}/pages`
const sharedFile = `${schedulerRoot}/schedulerWorkspace.module.css`
const moduleFiles = [
  sharedFile,
  `${schedulerRoot}/SchedulerLayout.module.css`,
  `${schedulerRoot}/OperationProgress.module.css`,
  `${pageRoot}/ImportPage.module.css`,
  `${pageRoot}/LecturesPage.module.css`,
  `${pageRoot}/RulesPage.module.css`,
  `${pageRoot}/OptimizerPage.module.css`,
  `${pageRoot}/ExportPage.module.css`,
]

function cssFiles() {
  return [
    ...readdirSync(schedulerRoot).filter((file) => file.endsWith('.module.css')).map((file) => `${schedulerRoot}/${file}`),
    ...readdirSync(pageRoot).filter((file) => file.endsWith('.module.css')).map((file) => `${pageRoot}/${file}`),
  ]
}

describe('Scheduler CSS architecture', () => {
  it('keeps page ownership explicit and removes the monolith', () => {
    expect(existsSync(`${schedulerRoot}/scheduler.module.css`)).toBe(false)
    expect(moduleFiles.every(existsSync)).toBe(true)
    expect(moduleFiles.every((file) => readFileSync(file, 'utf8').split('\n').length <= 700)).toBe(true)
    expect(moduleFiles.reduce((total, file) => total + readFileSync(file, 'utf8').split('\n').length, 0)).toBeLessThan(2307)
    expect(readFileSync(sharedFile, 'utf8')).toMatch(/\.workspacePage\b/)
    expect(readFileSync(sharedFile, 'utf8')).toMatch(/\.dialog(Content|Overlay|Actions)\b/)
  })

  it('does not reintroduce dead color or focus-ring declarations', () => {
    const css = cssFiles().map((file) => readFileSync(file, 'utf8')).join('\n')
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/)
    expect(css).not.toMatch(/outline[^;{}]*var\(--focus-ring\)/)
  })

  it('has no remaining imports of the deleted stylesheet', () => {
    const imports = readdirSync(schedulerRoot, { withFileTypes: true })
      .filter((entry) => entry.isFile() && /\.(ts|tsx)$/.test(entry.name) && entry.name !== 'schedulerCssArchitecture.test.ts')
      .map((entry) => `${schedulerRoot}/${entry.name}`)
    const pageImports = readdirSync(pageRoot)
      .filter((file) => /\.(ts|tsx)$/.test(file))
      .map((file) => `${pageRoot}/${file}`)
    expect([...imports, ...pageImports].every((file) => !/import .*scheduler\.module\.css/.test(readFileSync(file, 'utf8')))).toBe(true)
  })
})
