import { describe, expect, it } from 'vitest'
import { isCanonicalTime } from './timeInputUtils'

describe('isCanonicalTime', () => {
  it('accepts only complete 24-hour HH:MM values', () => {
    expect(isCanonicalTime('00:00')).toBe(true)
    expect(isCanonicalTime('23:59')).toBe(true)
    expect(isCanonicalTime('9:00')).toBe(false)
    expect(isCanonicalTime('24:00')).toBe(false)
    expect(isCanonicalTime('12:60')).toBe(false)
    expect(isCanonicalTime('12:')).toBe(false)
  })
})
