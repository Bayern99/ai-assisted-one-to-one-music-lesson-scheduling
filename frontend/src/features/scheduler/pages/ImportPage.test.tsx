import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { ImportPage } from './ImportPage'

const session = {
  active_stage: 'import', assignments: [], issues: [], rooms: [], instructors: [],
  draft: { dirty: false, can_undo: false, can_redo: false },
  metrics: { assigned: 0, unresolved: 0, source_gaps: 0 }, warnings: [],
}

const envelope = (data: unknown, workspace_version = 'workspace-v1') => ({
  data, workspace_version, warnings: [], error: null,
})

let previewRequests: { slot: string | null; body: string; contentType: string | null }[] = []
let applyBodies: unknown[] = []
let applyUploads: { fingerprint: string; bytes: string }[] = []

async function captureApply(request: Request) {
  const body = new TextDecoder().decode(await request.arrayBuffer())
  const field = (name: string) => body.match(new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r]+)`))?.[1] ?? ''
  applyBodies.push({
    preview_id: field('preview_id'),
    expected_version: field('expected_version'),
  })
  applyUploads.push({
    fingerprint: field('fingerprint'),
    bytes: body.includes('workbook') ? 'workbook' : '',
  })
}

const workbookPreview = {
  preview_id: 'workbook-preview-1',
  file_name: 'scheduler.xlsx',
  file_size: 1234,
  fingerprint: 'fingerprint-1',
  warnings: [],
  blocking_errors: [],
  instructor_conflicts: [],
  sheets: [
    {
      sheet_name: 'Weekly Schedule', normalized_name: 'Weekly Schedule', role: 'Weekly Schedule',
      header_row: 1, row_count: 148,
      columns: ['Instructor', 'Student No', 'Day of Week', 'Class Time', 'Preferred Venue'],
      sample_rows: [{ Instructor: 'Instructor 0001', 'Student No': 'S001', 'Preferred Venue': 'R103' }],
      warnings: [], blocking_errors: [],
    },
    {
      sheet_name: 'Studio Schedule ', normalized_name: 'Studio Schedule', role: 'Studio Schedule',
      header_row: 2, row_count: 22,
      columns: ['Instructor', 'Studio 1 Date', 'Studio 1 Time', 'Preferred Venue'],
      sample_rows: [{ Instructor: 'Instructor 0004', 'Preferred Venue': 'R103' }],
      warnings: [], blocking_errors: [],
    },
    ...['Student Info', 'Instructor', 'Room', 'Course Code'].map((role) => ({
      sheet_name: role, normalized_name: role, role, header_row: 1, row_count: 1,
      columns: [role], sample_rows: [{ [role]: `${role} sample` }], warnings: [], blocking_errors: [],
    })),
  ],
}

const appliedWorkbook = {
  state_keys: ['wk_df', 'stu_df'],
  sheet_names: { weekly: 'Weekly Schedule', studio: 'Studio Schedule ' },
  row_counts: { weekly: 148, studio: 22 },
  fingerprint: 'fingerprint-1',
  sync_results: {},
  session,
}

const server = setupServer(
  http.get('/api/scheduler/session', () => HttpResponse.json(envelope(session))),
  http.post('/api/scheduler/import/preview', async ({ request }) => {
    const body = new TextDecoder().decode(await request.arrayBuffer())
    previewRequests.push({
      slot: new URL(request.url).searchParams.get('slot'),
      body,
      contentType: request.headers.get('content-type'),
    })
    return HttpResponse.json(envelope(workbookPreview))
  }),
  http.post('/api/scheduler/import/apply', async ({ request }) => {
    await captureApply(request)
    return HttpResponse.json(envelope(appliedWorkbook, 'workspace-v2'))
  }),
  http.post('/api/scheduler/reset', () => HttpResponse.json(envelope(session, 'workspace-v2'))),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  previewRequests = []
  applyBodies = []
  applyUploads = []
})
afterAll(() => server.close())

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const router = createMemoryRouter([{ path: '/schedule/import', element: <ImportPage /> }], {
    initialEntries: ['/schedule/import'],
  })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return { client }
}

describe('ImportPage', () => {
  it('defaults to one complete-workbook workspace and exposes all six sheet summaries', async () => {
    const user = userEvent.setup()
    renderPage()
    const apply = screen.getByRole('button', { name: 'Apply workbook' })
    expect(apply).toBeDisabled()
    expect(screen.getAllByLabelText('Scheduler workbook')).toHaveLength(1)
    expect(screen.queryByLabelText('Weekly workbook')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Studio workbook')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Complete Workbook' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Weekly Only' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Studio Only' })).toBeVisible()
    expect(screen.queryByRole('button', { name: /Preview Weekly/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Preview Studio/ })).not.toBeInTheDocument()

    const file = new File(['workbook'], 'scheduler.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    await user.upload(screen.getByLabelText('Scheduler workbook'), file)
    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))

    expect(await screen.findByText('6 Sheets Detected')).toBeInTheDocument()
    for (const role of ['Weekly Schedule', 'Studio Schedule', 'Student Info', 'Instructor', 'Room', 'Course Code']) {
      expect(screen.getByRole('button', { name: new RegExp(role) })).toBeInTheDocument()
    }
    expect(screen.getByText('148 rows')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Studio Schedule/ }))
    expect(screen.getByText('Header row 2')).toBeInTheDocument()
    expect(screen.getByText('Instructor 0004')).toBeInTheDocument()
    expect(apply).toBeEnabled()
    expect(previewRequests).toHaveLength(1)
    expect(previewRequests[0].slot).toBeNull()
    expect(previewRequests[0].body).toContain('name="file"')
    expect(previewRequests[0].body).toContain('filename=')
    expect(previewRequests[0].contentType).toMatch(/^multipart\/form-data; boundary=/)
  })

  it('restores bounded Weekly-only source replacement without stacking another upload page', async () => {
    const user = userEvent.setup()
    server.use(
      http.post('/api/scheduler/import/preview', async ({ request }) => {
        const body = new TextDecoder().decode(await request.arrayBuffer())
        previewRequests.push({
          slot: new URL(request.url).searchParams.get('slot'),
          body,
          contentType: request.headers.get('content-type'),
        })
        return HttpResponse.json(envelope({
          preview_id: 'weekly-preview-1', slot: 'weekly', file_name: 'weekly.csv',
          sheet_name: 'Weekly Schedule', row_count: 148,
          columns: ['Instructor', 'Student No', 'Day of Week', 'Class Time'],
          instructor_conflicts: [], blocking_errors: [],
        }, 'workspace-weekly'))
      }),
      http.post('/api/scheduler/import/apply', async ({ request }) => {
        applyBodies.push(await request.json())
        return HttpResponse.json(envelope({
          state_key: 'wk_df', sheet_name: 'Weekly Schedule', row_count: 148,
          workbook_digest: 'digest', sync_results: {}, session,
        }, 'workspace-v2'))
      }),
    )
    renderPage()
    await user.click(screen.getByRole('button', { name: 'Weekly Only' }))

    expect(screen.queryByLabelText('Scheduler workbook')).not.toBeInTheDocument()
    const input = screen.getByLabelText('Weekly Lesson Source file')
    await user.upload(input, new File(['weekly'], 'weekly.csv', { type: 'text/csv' }))
    await user.click(screen.getByRole('button', { name: 'Preview Weekly' }))

    expect(await screen.findByText('Weekly Schedule')).toBeVisible()
    expect(screen.getByText('148')).toBeVisible()
    expect(previewRequests[0].slot).toBe('weekly')
    await user.click(screen.getByRole('button', { name: 'Apply Weekly' }))

    expect(await screen.findByText('Weekly Lesson Source applied — 148 rows from Weekly Schedule.')).toBeVisible()
    expect(applyBodies).toEqual([{ preview_id: 'weekly-preview-1', expected_version: 'workspace-weekly' }])
  })

  it('applies the unified preview atomically and clears the file without browser persistence', async () => {
    const user = userEvent.setup()
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem')
    renderPage()
    await user.upload(screen.getByLabelText('Scheduler workbook'), new File(['workbook'], 'scheduler.xlsx'))
    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))
    await screen.findByText('6 Sheets Detected')

    await user.click(screen.getByRole('button', { name: 'Apply workbook' }))
    await screen.findByText('Workbook applied atomically - 148 Weekly rows, 22 Studio rows, and available Student Info, Instructor, Room and Course Code sheets synchronized.')
    expect(applyBodies).toEqual([{ preview_id: 'workbook-preview-1', expected_version: 'workspace-v1' }])
    expect(applyUploads).toEqual([{ fingerprint: 'fingerprint-1', bytes: 'workbook' }])
    expect(screen.getByLabelText('Scheduler workbook')).toHaveValue('')
    expect(storageSpy).not.toHaveBeenCalled()
    storageSpy.mockRestore()
  })

  it('keeps the bound file and preview when a successful envelope has no complete apply result', async () => {
    const user = userEvent.setup()
    let applies = 0
    server.use(http.post('/api/scheduler/import/apply', async ({ request }) => {
      await captureApply(request)
      applies += 1
      if (applies === 1) return HttpResponse.json(envelope(null, 'workspace-v2'))
      if (applies === 2) {
        return HttpResponse.json(envelope({
          ...appliedWorkbook,
          row_counts: { weekly: 148 },
        }, 'workspace-v2'))
      }
      return HttpResponse.json(envelope(appliedWorkbook, 'workspace-v2'))
    }))
    renderPage()
    const input = screen.getByLabelText('Scheduler workbook') as HTMLInputElement
    const apply = screen.getByRole('button', { name: 'Apply workbook' })
    await user.upload(input, new File(['workbook'], 'scheduler.xlsx'))
    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))
    await screen.findByText('6 Sheets Detected')

    await user.click(apply)
    expect(await screen.findByRole('alert')).toHaveTextContent('incomplete workbook apply result')
    expect(input.files?.[0]?.name).toBe('scheduler.xlsx')
    expect(screen.getByText('6 Sheets Detected')).toBeInTheDocument()
    expect(apply).toBeEnabled()

    await user.click(apply)
    expect(await screen.findByRole('alert')).toHaveTextContent('incomplete workbook apply result')
    expect(input.files?.[0]?.name).toBe('scheduler.xlsx')
    expect(screen.getByText('6 Sheets Detected')).toBeInTheDocument()
    expect(apply).toBeEnabled()

    await user.click(apply)
    await screen.findByText('Workbook applied atomically - 148 Weekly rows, 22 Studio rows, and available Student Info, Instructor, Room and Course Code sheets synchronized.')
    expect(applies).toBe(3)
    expect(screen.getByLabelText('Scheduler workbook')).toHaveValue('')
  })

  it('binds apply to the workspace version returned with the preview token', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope(session, 'workspace-old'))),
      http.post('/api/scheduler/import/preview', () => HttpResponse.json(envelope({
        ...workbookPreview,
        preview_id: 'preview-at-new-version',
      }, 'workspace-preview'))),
    )
    renderPage()
    await user.upload(screen.getByLabelText('Scheduler workbook'), new File(['workbook'], 'scheduler.xlsx'))
    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))
    await screen.findByText('6 Sheets Detected')

    await user.click(screen.getByRole('button', { name: 'Apply workbook' }))
    await waitFor(() => expect(applyBodies).toHaveLength(1))
    expect(applyBodies[0]).toEqual({
      preview_id: 'preview-at-new-version',
      expected_version: 'workspace-preview',
    })
  })

  it('clears a 409 and applies a fresh preview token without reloading the page', async () => {
    const user = userEvent.setup()
    let previews = 0
    let applies = 0
    server.use(
      http.post('/api/scheduler/import/preview', () => {
        previews += 1
        return HttpResponse.json(envelope({
          ...workbookPreview,
          preview_id: `preview-${previews}`,
        }, `workspace-${previews}`))
      }),
      http.post('/api/scheduler/import/apply', async ({ request }) => {
        await captureApply(request)
        applies += 1
        if (applies === 1) {
          return HttpResponse.json({
            data: null, workspace_version: 'workspace-2', warnings: [],
            error: { code: 'WORKSPACE_CHANGED', message: 'Workspace changed; reload before saving' },
          }, { status: 409 })
        }
        return HttpResponse.json(envelope(appliedWorkbook, 'workspace-3'))
      }),
    )
    renderPage()
    await user.upload(screen.getByLabelText('Scheduler workbook'), new File(['workbook'], 'scheduler.xlsx'))
    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))
    await screen.findByText('6 Sheets Detected')
    await user.click(screen.getByRole('button', { name: 'Apply workbook' }))
    expect(await screen.findByText('This preview is stale. Preview the workbook again.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))
    await waitFor(() => expect(previews).toBe(2))
    expect(screen.queryByText('This preview is stale. Preview the workbook again.')).not.toBeInTheDocument()
    expect(screen.queryByText('Workspace changed; reload before saving')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Apply workbook' }))

    await screen.findByText('Workbook applied atomically - 148 Weekly rows, 22 Studio rows, and available Student Info, Instructor, Room and Course Code sheets synchronized.')
    expect(applyBodies).toEqual([
      { preview_id: 'preview-1', expected_version: 'workspace-1' },
      { preview_id: 'preview-2', expected_version: 'workspace-2' },
    ])
  })

  it('shows workbook blockers and keeps apply disabled', async () => {
    const user = userEvent.setup()
    server.use(http.post('/api/scheduler/import/preview', () => HttpResponse.json(envelope({
      ...workbookPreview,
      blocking_errors: ['Studio Schedule is missing Instructor and a matching Studio date/time pair.'],
      sheets: workbookPreview.sheets.map((sheet) => sheet.role === 'Studio Schedule'
        ? { ...sheet, blocking_errors: ['Missing required Studio columns.'] }
        : sheet),
    }))))
    renderPage()
    await user.upload(screen.getByLabelText('Scheduler workbook'), new File(['bad'], 'bad.xlsx'))
    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Studio Schedule is missing Instructor')
    expect(screen.getByRole('button', { name: 'Apply workbook' })).toBeDisabled()
    expect(applyBodies).toHaveLength(0)
  })

  it('warns about possible reordered instructor names before workbook apply', async () => {
    const user = userEvent.setup()
    server.use(http.post('/api/scheduler/import/preview', () => HttpResponse.json(envelope({
      ...workbookPreview,
      possible_instructor_duplicates: [['Instructor 0004 Alt', 'Instructor 0004']],
    }))))
    renderPage()
    await user.upload(screen.getByLabelText('Scheduler workbook'), new File(['workbook'], 'scheduler.xlsx'))
    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))

    const warning = await screen.findByRole('status', { name: 'Possible duplicate instructor names' })
    expect(warning).toHaveTextContent('Instructor 0004 Alt')
    expect(warning).toHaveTextContent('Instructor 0004')
    expect(warning).toHaveTextContent('Review the workbook before applying')
    expect(screen.getByRole('button', { name: 'Apply workbook' })).toBeEnabled()
  })

  it('shows teacher conflicts in an individual source preview and blocks apply', async () => {
    const user = userEvent.setup()
    server.use(http.post('/api/scheduler/import/preview', () => HttpResponse.json(envelope({
      preview_id: 'weekly-conflict', slot: 'weekly', file_name: 'weekly.xlsx',
      sheet_name: 'Weekly', row_count: 2,
      columns: ['Instructor', 'Day of Week', 'Class Time', 'Student No'],
      instructor_conflicts: [{ instructor: 'Dr. Conflict', day: 1, start: '10:30', end: '11:00' }],
      blocking_errors: ['Instructor time conflict: Dr. Conflict on weekday 1 at 10:30-11:00.'],
    }))))
    renderPage()
    await user.click(screen.getByRole('button', { name: 'Weekly Only' }))
    await user.upload(screen.getByLabelText('Weekly Lesson Source file'), new File(['weekly'], 'weekly.xlsx'))
    await user.click(screen.getByRole('button', { name: 'Preview Weekly' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('One teacher cannot teach two lessons at the same time')
    expect(screen.getByRole('button', { name: 'Apply Weekly' })).toBeDisabled()
  })

  it('discards a stale preview when the selected file changes before the response returns', async () => {
    const user = userEvent.setup()
    let resolveFirst: ((response: Response) => void) | undefined
    let requests = 0
    server.use(http.post('/api/scheduler/import/preview', () => {
      requests += 1
      if (requests === 1) return new Promise<Response>((resolve) => { resolveFirst = resolve })
      return HttpResponse.json(envelope({ ...workbookPreview, preview_id: 'workbook-preview-b', file_name: 'scheduler-b.xlsx' }))
    }))
    const { client } = renderPage()
    const input = screen.getByLabelText('Scheduler workbook')
    const apply = screen.getByRole('button', { name: 'Apply workbook' })

    await user.upload(input, new File(['a'], 'scheduler-a.xlsx'))
    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))
    await waitFor(() => expect(requests).toBe(1))
    await user.upload(input, new File(['b'], 'scheduler-b.xlsx'))

    resolveFirst?.(HttpResponse.json(envelope({ ...workbookPreview, preview_id: 'workbook-preview-a', file_name: 'scheduler-a.xlsx' })))
    await waitFor(() => expect(client.isMutating()).toBe(0))
    expect(screen.queryByText('6 Sheets Detected')).not.toBeInTheDocument()
    expect(apply).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))
    expect(await screen.findByText('6 Sheets Detected')).toBeInTheDocument()
    expect(apply).toBeEnabled()
    await user.click(apply)
    await waitFor(() => expect(applyBodies).toHaveLength(1))
    expect(applyBodies[0]).toEqual({ preview_id: 'workbook-preview-b', expected_version: 'workspace-v1' })
  })

  it('marks the preview stale after a workspace conflict and requires a new preview', async () => {
    const user = userEvent.setup()
    server.use(http.post('/api/scheduler/import/apply', () => HttpResponse.json({
      data: null, workspace_version: 'workspace-v2', warnings: [],
      error: { code: 'WORKSPACE_CHANGED', message: 'Workspace changed; reload before saving' },
    }, { status: 409 })))
    renderPage()
    await user.upload(screen.getByLabelText('Scheduler workbook'), new File(['workbook'], 'scheduler.xlsx'))
    await user.click(screen.getByRole('button', { name: 'Preview workbook' }))
    await screen.findByText('6 Sheets Detected')
    await user.click(screen.getByRole('button', { name: 'Apply workbook' }))

    expect(await screen.findByText('This preview is stale. Preview the workbook again.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Apply workbook' })).toBeDisabled()
  })

  it('requires keyboard-confirmed reset before clearing the scheduling workspace', async () => {
    const user = userEvent.setup()
    let resets = 0
    server.use(http.post('/api/scheduler/reset', async ({ request }) => {
      resets += 1
      expect(await request.json()).toEqual({ expected_version: 'workspace-v1' })
      return HttpResponse.json(envelope(session, 'workspace-v2'))
    }))
    renderPage()
    await screen.findByRole('button', { name: 'Reset scheduling workspace' })

    await user.click(screen.getByRole('button', { name: 'Reset scheduling workspace' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('clears imported scheduling sources, drafts, and generated Weekly/Studio bookings')
    await user.keyboard('{Escape}')
    expect(resets).toBe(0)

    await user.click(screen.getByRole('button', { name: 'Reset scheduling workspace' }))
    await user.click(screen.getByRole('button', { name: 'Reset workspace' }))
    await waitFor(() => expect(resets).toBe(1))
    expect(await screen.findByText('Scheduling workspace reset.')).toBeInTheDocument()
  })
})
