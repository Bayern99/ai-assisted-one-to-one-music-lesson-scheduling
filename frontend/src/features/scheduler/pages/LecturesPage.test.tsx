import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { LecturesPage } from './LecturesPage'

const session = {
  active_stage: 'lectures', assignments: [], issues: [],
  rooms: [{ id: 'R1' }, { id: 'R2' }], instructors: [], source_preferences: [],
  draft: { dirty: false, can_undo: false, can_redo: false },
  metrics: { assigned: 0, unresolved: 0, source_gaps: 0 }, warnings: [],
}

const lecture = {
  id: 'lecture-1', title: 'Aural Skills', resourceId: 'R1', daysOfWeek: [1],
  startTime: '09:00', endTime: '10:00', type: 'lecture', locked: true,
}

const importedLecture = {
  id: 'lecture-imported', title: 'Imported Theory', resourceId: 'R2', daysOfWeek: [2],
  startTime: '13:00:00', endTime: '15:00:00', type: 'lecture', locked: true,
}

const envelope = (data: unknown, version = 'workspace-v1', warnings: string[] = []) => ({
  data, workspace_version: version, warnings, error: null,
})

let savedBodies: unknown[] = []
let validationBodies: unknown[] = []

const server = setupServer(
  http.get('/api/scheduler/session', () => HttpResponse.json(envelope(session))),
  http.get('/api/scheduler/lectures', () => HttpResponse.json(envelope({ lectures: [lecture] }))),
  http.post('/api/scheduler/lectures/preview', async ({ request }) => {
    await request.arrayBuffer()
    return HttpResponse.json(envelope({
      file_name: 'registry.csv', lectures: [importedLecture], source_row_count: 2,
      skipped_rows: [{ row_number: 3, code: 'invalid_time', message: 'Invalid time', raw_value: 'TBD' }],
      duplicate_rows: [], warnings: ['Parsed 1 lecture. Skipped 1 invalid lecture row.'],
    }, 'workspace-preview', ['Parsed 1 lecture. Skipped 1 invalid lecture row.']))
  }),
  http.post('/api/scheduler/lectures/validate', async ({ request }) => {
    validationBodies.push(await request.json())
    return HttpResponse.json(envelope({ lectures: [lecture], conflicts: [] }))
  }),
  http.put('/api/scheduler/lectures', async ({ request }) => {
    savedBodies.push(await request.json())
    return HttpResponse.json(envelope({ lectures: [lecture] }, 'workspace-v2', ['Lecture locks saved.']))
  }),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => { cleanup(); server.resetHandlers(); savedBodies = []; validationBodies = [] })
afterAll(() => server.close())

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const router = createMemoryRouter([{ path: '/schedule/lectures', element: <LecturesPage /> }], {
    initialEntries: ['/schedule/lectures'],
  })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return { client }
}

describe('LecturesPage', () => {
  it('is an independent first-stage workspace with a bounded register and one selected inspector', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Lecture Locks', level: 1 })).toBeVisible()
    const table = await screen.findByRole('table', { name: 'Lecture locks' })
    expect(within(table).getByText('Aural Skills')).toBeVisible()
    expect(screen.getAllByLabelText('Lecture title lecture-1')).toHaveLength(1)
    expect(screen.queryByText('Scheduling Rules')).not.toBeInTheDocument()
  })

  it('requires confirmation before removing a lecture from the draft', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByLabelText('Lecture title lecture-1')

    await user.click(screen.getByRole('button', { name: 'Remove Lecture' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Remove this lecture?')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByLabelText('Lecture title lecture-1')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remove Lecture' }))
    await user.click(screen.getByRole('button', { name: 'Confirm remove' }))
    expect(screen.queryByLabelText('Lecture title lecture-1')).not.toBeInTheDocument()
  })

  it('requires the current draft to validate before saving the complete lecture body', async () => {
    const user = userEvent.setup()
    renderPage()
    const title = await screen.findByLabelText('Lecture title lecture-1')
    const save = screen.getByRole('button', { name: 'Save Lecture Locks' })
    expect(save).toBeDisabled()

    await user.clear(title)
    await user.type(title, 'Aural Skills II')
    await user.click(screen.getByRole('checkbox', { name: 'Tuesday for lecture-1' }))
    expect(save).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Check Conflicts' }))

    expect(await screen.findByText('No lecture conflicts found.')).toBeVisible()
    expect(save).toBeEnabled()
    await user.click(save)

    await waitFor(() => expect(savedBodies).toHaveLength(1))
    expect(validationBodies).toHaveLength(1)
    expect(savedBodies[0]).toEqual({
      expected_version: 'workspace-v1',
      lectures: [{ ...lecture, title: 'Aural Skills II', daysOfWeek: [1, 2] }],
    })
  })

  it('replaces the local draft from CSV preview and uses the preview version for save', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByLabelText('Lecture title lecture-1')

    await user.upload(screen.getByLabelText('Lecture CSV file'), new File(['registry'], 'registry.csv', { type: 'text/csv' }))

    expect(await screen.findByLabelText('Lecture title lecture-imported')).toHaveValue('Imported Theory')
    expect(screen.queryByLabelText('Lecture title lecture-1')).not.toBeInTheDocument()
    expect(screen.getByText('2 source rows · 1 candidates')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Check Conflicts' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save Lecture Locks' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Save Lecture Locks' }))

    await waitFor(() => expect(savedBodies).toHaveLength(1))
    expect(savedBodies[0]).toMatchObject({ expected_version: 'workspace-preview', lectures: [importedLecture] })
  })

  it('surfaces server conflict detail and keeps save unavailable', async () => {
    const user = userEvent.setup()
    server.use(http.post('/api/scheduler/lectures/validate', () => HttpResponse.json({
      data: null, workspace_version: 'workspace-v1', warnings: [],
      error: {
        code: 'LECTURE_CONFLICT', message: 'Lecture locks overlap existing weekly lessons',
        details: { conflicts: [{ lecture_id: 'lecture-1', message: 'Room R1 overlaps Piano lesson' }] },
      },
    }, { status: 400 })))
    renderPage()
    const title = await screen.findByLabelText('Lecture title lecture-1')
    await user.type(title, ' II')
    await user.click(screen.getByRole('button', { name: 'Check Conflicts' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Lecture locks overlap existing weekly lessons')
    expect(alert).toHaveTextContent('Room R1 overlaps Piano lesson')
    expect(screen.getByRole('button', { name: 'Save Lecture Locks' })).toBeDisabled()
  })
})
