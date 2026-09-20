import { describe, expect, it } from 'vitest'
import { PAGE_TITLES, SECTION_TITLES, WORKFLOW_LABELS, workspaceRevisionLabel } from './productLanguage'

describe('product language', () => {
  it('keeps product-facing titles in Title Case', () => {
    const titles = [...Object.values(PAGE_TITLES), ...Object.values(SECTION_TITLES), ...Object.values(WORKFLOW_LABELS)]
    const minorWords = new Set(['a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'in', 'of', 'on', 'or', 'the', 'to'])
    for (const title of titles) {
      for (const [index, word] of title.split(/[\s-]+/).entries()) {
        if (index > 0 && minorWords.has(word)) continue
        expect(word[0]).toBe(word[0].toUpperCase())
      }
    }
  })

  it('keeps short revisions useful and abbreviates production hashes', () => {
    expect(workspaceRevisionLabel('workspace-v1')).toBe('workspace-v1')
    expect(workspaceRevisionLabel('0123456789abcdef0123456789abcdef')).toBe('Revision 01234567…')
  })
})
