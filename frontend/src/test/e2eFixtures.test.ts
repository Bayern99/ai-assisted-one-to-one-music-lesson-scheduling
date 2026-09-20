// @vitest-environment node
import { once } from 'node:events'
import { spawn } from 'node:child_process'
import { describe, expect, it } from 'vitest'
import { hasExited, waitForExit } from '../../e2e/fixtures'

describe('E2E child-process teardown helpers', () => {
  it('returns immediately when exit was already emitted', async () => {
    const child = spawn(process.execPath, ['-e', 'process.exit(0)'])
    await once(child, 'exit')

    expect(hasExited(child)).toBe(true)
    await expect(waitForExit(child, 1_000)).resolves.toBe(true)
  })

  it('recognizes a signal-only exit', async () => {
    const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'])
    child.kill('SIGTERM')
    await once(child, 'exit')

    expect(child.signalCode).toBe('SIGTERM')
    expect(hasExited(child)).toBe(true)
    await expect(waitForExit(child, 1_000)).resolves.toBe(true)
  })
})
