import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { StudentHubPage } from './StudentHubPage'

const meiLin = {
  student_id: '1001',
  name_en: 'Mei Lin',
  name_ch: '林美',
  display_name: 'Mei Lin 林美',
  year: 3,
  instructor: 'Daniel Wong',
  instrument: 'Piano',
  type: 'Piano',
  course_code: 'MUS3153',
  status: 'Active',
}

const kaiChen = {
  ...meiLin,
  student_id: '1002',
  name_en: 'Student 0001',
  name_ch: '学生甲',
  display_name: 'Student 0001 学生甲',
  instructor: 'Instructor 0001',
}

let detail = { ...meiLin }
let version = 'v1'
let listUrls: string[] = []
let patchBodies: unknown[] = []

const envelope = (data: unknown) => ({ data, workspace_version: version, warnings: [], error: null })
const server = setupServer(
  http.get('/api/students', ({ request }) => {
    listUrls.push(request.url)
    return HttpResponse.json(envelope([detail]))
  }),
  http.get('/api/students/:studentId', () => HttpResponse.json(envelope(detail))),
  http.patch('/api/students/:studentId', async ({ request }) => {
    const body = await request.json()
    patchBodies.push(body)
    detail = { ...detail, ...(body as object) }
    version = 'v2'
    return HttpResponse.json(envelope(detail))
  }),
  http.post('/api/students/bulk-delete', async ({ request }) => {
    const body = await request.json() as { student_ids: string[] }
    version = 'v2'
    return HttpResponse.json(envelope({ deleted_student_ids: body.student_ids }))
  }),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  detail = { ...meiLin }
  version = 'v1'
  listUrls = []
  patchBodies = []
  vi.useRealTimers()
})
afterAll(() => server.close())

function renderHub(path = '/students') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const router = createMemoryRouter(
    [{ path: '/students/:studentId?', element: <StudentHubPage /> }],
    { initialEntries: [path] },
  )
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { client, router }
}

describe('StudentHubPage', () => {
  it('bulk deletes selected visible students only after confirmation', async () => {
    const user = userEvent.setup()
    server.use(http.get('/api/students', () => HttpResponse.json(envelope([meiLin, kaiChen]))))
    renderHub()

    await user.click(await screen.findByLabelText('Select Mei Lin'))
    await user.click(screen.getByRole('button', { name: 'Delete 1 Selected' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete Selected Students?' })
    expect(dialog).toHaveTextContent('1 canonical student records')
    await user.click(within(dialog).getByRole('button', { name: 'Delete Students' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Delete 1 Selected' })).not.toBeInTheDocument()
  })

  it('renders the source list and a fixed preview inspector as one workbench', async () => {
    renderHub()

    expect(await screen.findByLabelText('Source data workbench')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Student Records' })).toBeInTheDocument()
    expect(screen.getByLabelText('Student record inspector')).toHaveTextContent('Select a Student Record')
  })

  it('shows six skeleton rows while the student list is loading', async () => {
    let resolveList: ((response: Response) => void) | undefined
    const pendingList = new Promise<Response>((resolve) => { resolveList = resolve })
    server.use(http.get('/api/students', () => pendingList))
    renderHub()

    expect(screen.getAllByRole('row', { name: 'Loading student' })).toHaveLength(6)
    resolveList?.(HttpResponse.json(envelope([detail])))
    expect(await screen.findByText('Mei Lin')).toBeInTheDocument()
    expect(screen.queryByRole('row', { name: 'Loading student' })).not.toBeInTheDocument()
  })

  it('keeps a list error actionable and recovers through Retry', async () => {
    const user = userEvent.setup()
    let attempts = 0
    server.use(
      http.get('/api/students', () => {
        attempts += 1
        return attempts === 1 ? HttpResponse.json(
          { data: null, workspace_version: null, warnings: [], error: { code: 'LIST_FAILED', message: 'Student list unavailable' } },
          { status: 500 },
        ) : HttpResponse.json(envelope([detail]))
      }),
    )
    renderHub()

    expect(await screen.findByRole('alert')).toHaveTextContent('Student list unavailable')
    await user.click(screen.getByRole('button', { name: 'Retry student list' }))
    expect(await screen.findByText('Mei Lin')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows the empty state when the workspace has no student records', async () => {
    server.use(http.get('/api/students', () => HttpResponse.json(envelope([]))))
    renderHub()

    expect(await screen.findByText('No student records match these filters.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument()
  })

  it('clears active empty filters and requests the unfiltered list again', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('/api/students', ({ request }) => {
        listUrls.push(request.url)
        return HttpResponse.json(envelope([]))
      }),
    )
    renderHub()
    await screen.findByText('No student records match these filters.')

    await user.type(screen.getByLabelText('Search'), 'Mei Lin')
    await user.type(screen.getByLabelText('Instrument'), 'Piano')
    await waitFor(() => expect(listUrls.length).toBeGreaterThan(1))
    await user.click(await screen.findByRole('button', { name: 'Clear filters' }))

    expect(screen.getByLabelText('Search')).toHaveValue('')
    expect(screen.getByLabelText('Instrument')).toHaveValue('')
    await waitFor(() => expect(listUrls.length).toBeGreaterThan(2))
    expect(new URL(listUrls.at(-1)!).search).toBe('')
  })

  it('debounces search for exactly 150ms and sends the instrument parameter', async () => {
    renderHub()
    await screen.findByText('Mei Lin')
    listUrls = []
    vi.useFakeTimers()

    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'Lin & Yu' } })
    fireEvent.change(screen.getByLabelText('Instrument'), { target: { value: 'Piano' } })
    await act(() => vi.advanceTimersByTimeAsync(149))
    expect(listUrls).toHaveLength(0)
    await act(() => vi.advanceTimersByTimeAsync(1))
    vi.useRealTimers()

    await waitFor(() => expect(listUrls).toHaveLength(1))
    expect(new URL(listUrls[0]).searchParams.get('query')).toBe('Lin & Yu')
    expect(new URL(listUrls[0]).searchParams.get('instrument')).toBe('Piano')
  })

  it('opens a student through the accessible row link and saves only the touched field and version', async () => {
    const user = userEvent.setup()
    const { router } = renderHub()
    const link = await screen.findByRole('link', { name: 'Open student Mei Lin (1001)' })
    link.focus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(router.state.location.pathname).toBe('/students/1001'))

    const instructor = await screen.findByLabelText('Instructor')
    await user.clear(instructor)
    await user.type(instructor, 'Instructor 0001')
    await user.click(screen.getByRole('button', { name: 'Save student' }))

    expect(await screen.findByText('Student record saved.')).toBeInTheDocument()
    expect(patchBodies).toEqual([{ instructor: 'Instructor 0001', expected_version: 'v1' }])
    expect(instructor).toHaveValue('Instructor 0001')
    await waitFor(() => expect(listUrls.length).toBeGreaterThan(1))
  })

  it('locks editor fields while a save is pending and restores the saved response', async () => {
    const user = userEvent.setup()
    let resolveSave: ((response: Response) => void) | undefined
    const pendingSave = new Promise<Response>((resolve) => { resolveSave = resolve })
    server.use(
      http.patch('/api/students/:studentId', async ({ request }) => {
        patchBodies.push(await request.json())
        return pendingSave
      }),
    )
    renderHub('/students/1001')

    const instructor = await screen.findByLabelText('Instructor')
    await user.clear(instructor)
    await user.type(instructor, 'Instructor 0001')
    await user.click(screen.getByRole('button', { name: 'Save student' }))
    await waitFor(() => expect(patchBodies).toHaveLength(1))

    const form = instructor.closest('form')
    expect(form).not.toBeNull()
    expect(form?.closest('aside')).toHaveAttribute('tabindex', '0')
    expect(form).toHaveAttribute('aria-busy', 'true')
    expect(instructor).toBeDisabled()
    expect(within(form!).getByRole('spinbutton', { name: /Study year/ })).toBeDisabled()
    await user.type(instructor, 'Ignored edit')
    expect(instructor).toHaveValue('Instructor 0001')

    resolveSave?.(HttpResponse.json({
      ...envelope({ ...detail, instructor: 'Instructor 0001' }),
      workspace_version: 'v2',
    }))
    await screen.findByText('Student record saved.')
    expect(form).toHaveAttribute('aria-busy', 'false')
    expect(instructor).toBeEnabled()
    expect(instructor).toHaveValue('Instructor 0001')
  })

  it('preserves touched draft through a 409 reload and retries with the fresh version', async () => {
    const user = userEvent.setup()
    let conflicted = false
    server.use(
      http.patch('/api/students/:studentId', async ({ request }) => {
        patchBodies.push(await request.json())
        if (!conflicted) {
          conflicted = true
          detail = { ...detail, name_ch: '林梅', instructor: 'External edit' }
          version = 'v2'
          return HttpResponse.json(
            { data: null, workspace_version: 'v2', warnings: [], error: { code: 'WORKSPACE_CONFLICT', message: 'Workspace changed' } },
            { status: 409 },
          )
        }
        detail = { ...detail, instructor: 'Instructor 0001' }
        version = 'v3'
        return HttpResponse.json(envelope(detail))
      }),
    )
    renderHub('/students/1001')

    const instructor = await screen.findByLabelText('Instructor')
    await user.clear(instructor)
    await user.type(instructor, 'Instructor 0001')
    await user.click(screen.getByRole('button', { name: 'Save student' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Workspace changed')
    expect(instructor).toHaveValue('Instructor 0001')

    await user.click(screen.getByRole('button', { name: 'Reload workspace' }))
    expect(await screen.findByLabelText('Chinese name')).toHaveValue('林梅')
    expect(instructor).toHaveValue('Instructor 0001')
    await user.click(screen.getByRole('button', { name: 'Save student' }))

    await screen.findByText('Student record saved.')
    expect(patchBodies).toEqual([
      { instructor: 'Instructor 0001', expected_version: 'v1' },
      { instructor: 'Instructor 0001', expected_version: 'v2' },
    ])
  })

  it('keeps the conflict and draft when reload fails, then retries with a fresh version', async () => {
    const user = userEvent.setup()
    let patchCount = 0
    let detailReloads = 0
    server.use(
      http.get('/api/students/:studentId', () => {
        detailReloads += 1
        if (detailReloads === 2) {
          return HttpResponse.json(
            { data: null, workspace_version: null, warnings: [], error: { code: 'READ_FAILED', message: 'Reload failed' } },
            { status: 500 },
          )
        }
        return HttpResponse.json(envelope(detail))
      }),
      http.patch('/api/students/:studentId', async ({ request }) => {
        patchBodies.push(await request.json())
        patchCount += 1
        if (patchCount === 1) {
          detail = { ...detail, name_ch: '林梅', instructor: 'External edit' }
          version = 'v2'
          return HttpResponse.json(
            { data: null, workspace_version: 'v2', warnings: [], error: { code: 'WORKSPACE_CONFLICT', message: 'Workspace changed' } },
            { status: 409 },
          )
        }
        detail = { ...detail, instructor: 'Instructor 0001' }
        version = 'v3'
        return HttpResponse.json(envelope(detail))
      }),
    )
    renderHub('/students/1001')

    const instructor = await screen.findByLabelText('Instructor')
    await user.clear(instructor)
    await user.type(instructor, 'Instructor 0001')
    await user.click(screen.getByRole('button', { name: 'Save student' }))
    await screen.findByRole('button', { name: 'Reload workspace' })

    await user.click(screen.getByRole('button', { name: 'Reload workspace' }))
    expect(await screen.findByRole('button', { name: 'Reload workspace' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Workspace changed')
    expect(screen.queryByText('Reload failed')).not.toBeInTheDocument()
    expect(instructor).toHaveValue('Instructor 0001')

    await user.click(screen.getByRole('button', { name: 'Reload workspace' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Reload workspace' })).not.toBeInTheDocument())
    expect(screen.getByLabelText('Chinese name')).toHaveValue('林梅')
    expect(instructor).toHaveValue('Instructor 0001')
    await user.click(screen.getByRole('button', { name: 'Save student' }))

    await screen.findByText('Student record saved.')
    expect(patchBodies.at(-1)).toEqual({ instructor: 'Instructor 0001', expected_version: 'v2' })
  })

  it.each(['resolve', 'fail'] as const)('isolates a pending student A save from student B when it %s', async (outcome) => {
    const user = userEvent.setup()
    let resolveStudentA: ((response: Response) => void) | undefined
    const pendingStudentA = new Promise<Response>((resolve) => { resolveStudentA = resolve })
    const requests: { id: string; body: unknown }[] = []
    server.use(
      http.get('/api/students', () => HttpResponse.json(envelope([detail, kaiChen]))),
      http.get('/api/students/:studentId', ({ params }) => {
        const record = params.studentId === '1002' ? kaiChen : detail
        return HttpResponse.json({ ...envelope(record), workspace_version: params.studentId === '1002' ? 'b-v1' : 'a-v1' })
      }),
      http.patch('/api/students/:studentId', async ({ params, request }) => {
        const body = await request.json()
        requests.push({ id: String(params.studentId), body })
        if (params.studentId === '1001') return pendingStudentA
        return HttpResponse.json({ ...envelope({ ...kaiChen, ...(body as object) }), workspace_version: 'b-v2' })
      }),
    )
    const { client, router } = renderHub('/students/1001')
    const instructorA = await screen.findByLabelText('Instructor')
    await user.clear(instructorA)
    await user.type(instructorA, 'Roy Zhang')
    await user.click(screen.getByRole('button', { name: 'Save student' }))
    await waitFor(() => expect(requests).toHaveLength(1))

    await router.navigate('/students/1002')
    await waitFor(() => expect(screen.getByLabelText('English name')).toHaveValue('Student 0001'))
    const instructorB = screen.getByLabelText('Instructor')
    expect(instructorB).toBeEnabled()
    await user.clear(instructorB)
    await user.type(instructorB, 'Instructor 0002')
    if (outcome === 'resolve') {
      resolveStudentA?.(HttpResponse.json({ ...envelope({ ...detail, instructor: 'Roy Zhang' }), workspace_version: 'a-v2' }))
    } else {
      resolveStudentA?.(HttpResponse.json(
        { data: null, workspace_version: null, warnings: [], error: { code: 'SAVE_FAILED', message: 'A failed' } },
        { status: 500 },
      ))
    }
    await waitFor(() => expect(screen.getByLabelText('English name')).toHaveValue('Student 0001'))
    expect(screen.getByLabelText('Instructor')).toHaveValue('Instructor 0002')
    expect(screen.queryByText('Student record saved.')).not.toBeInTheDocument()
    expect(screen.queryByText('A failed')).not.toBeInTheDocument()
    expect((client.getQueryData<{ data: typeof kaiChen }>(['student', '1002']))?.data.student_id).toBe('1002')
    if (outcome === 'resolve') {
      await waitFor(() => expect((client.getQueryData<{ data: typeof meiLin }>(['student', '1001']))?.data.instructor).toBe('Roy Zhang'))
    }

    await user.click(screen.getByRole('button', { name: 'Save student' }))
    await screen.findByText('Student record saved.')
    expect(requests.at(-1)).toEqual({ id: '1002', body: { instructor: 'Instructor 0002', expected_version: 'b-v1' } })
  })

  it('shows an explicit not found state for a missing student', async () => {
    server.use(
      http.get('/api/students/:studentId', () => HttpResponse.json(
        { data: null, workspace_version: null, warnings: [], error: { code: 'STUDENT_NOT_FOUND', message: 'Student not found' } },
        { status: 404 },
      )),
    )
    renderHub('/students/missing')

    expect(await screen.findByRole('heading', { name: 'Student Not Found' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Student not found')
  })

  it('keeps empty text and year zero in the touched payload', async () => {
    const user = userEvent.setup()
    renderHub('/students/1001')
    await user.clear(await screen.findByLabelText('Course code'))
    await user.clear(screen.getByRole('spinbutton', { name: /Study year/ }))
    await user.click(screen.getByRole('button', { name: 'Save student' }))

    await screen.findByText('Student record saved.')
    expect(patchBodies.at(-1)).toEqual({ course_code: '', year: 0, expected_version: 'v1' })
  })
})
