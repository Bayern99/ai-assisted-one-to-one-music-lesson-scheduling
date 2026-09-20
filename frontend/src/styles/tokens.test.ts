import { readFileSync } from 'node:fs'
import { globSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const tokenFile = 'src/styles/tokens.css'
const tokenSource = readFileSync(tokenFile, 'utf8')
const defined = new Set([...tokenSource.matchAll(/--([\w-]+)\s*:/g)].map((match) => match[1]))
const cssFiles = globSync('src/**/*.css').filter((file) => file !== tokenFile)

describe('CSS token contract', () => {
  it('defines every referenced token, including only documented local custom properties', () => {
    const references = new Set(cssFiles.flatMap((file) => [...readFileSync(file, 'utf8').matchAll(/var\(--([\w-]+)/g)].map((match) => match[1])))
    const localProperties = new Set(['hour-count', 'room-count', 'resolve-queue-width'])
    expect([...references].filter((name) => !defined.has(name) && !localProperties.has(name))).toEqual([])
  })

  it('keeps colors in tokens.css and uses focus rings as shadows', () => {
    const hardcoded = cssFiles.flatMap((file) => [...readFileSync(file, 'utf8').matchAll(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g)].map((match) => `${file}:${match[0]}`))
    expect(hardcoded).toEqual([])
    expect(cssFiles.flatMap((file) => readFileSync(file, 'utf8').split('\n').filter((line) => /outline[^;]*var\(--focus-ring\)/.test(line)))).toEqual([])
  })
})
