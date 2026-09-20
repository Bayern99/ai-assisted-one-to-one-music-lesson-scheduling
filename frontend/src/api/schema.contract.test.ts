import { describe, expectTypeOf, it } from 'vitest'
import type { operations } from './schema'

type SchedulerApplyContent = operations[
  'apply_scheduler_import_api_scheduler_import_apply_post'
]['requestBody']['content']

describe('generated scheduler apply contract', () => {
  it('includes the legacy JSON and workbook multipart request bodies', () => {
    expectTypeOf<keyof SchedulerApplyContent>().toEqualTypeOf<
      'application/json' | 'multipart/form-data'
    >()
    expectTypeOf<SchedulerApplyContent['application/json']>().toMatchTypeOf<{
      preview_id: string
      expected_version: string
      fingerprint?: string | null
    }>()
    expectTypeOf<SchedulerApplyContent['multipart/form-data']>().toMatchTypeOf<{
      file: string
      preview_id: string
      fingerprint: string
      expected_version: string
    }>()
  })
})
