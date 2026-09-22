import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { ResolvePage } from './ResolvePage'

const session = {
  active_stage: 'resolve',
  assignments: [
    {
      id: 'weekly-1', title: 'Cello lesson', type: 'weekly_lesson', resourceId: 'R101',
      daysOfWeek: [1], startTime: '09:00:00', endTime: '10:00:00',
      extendedProps: { Instructor: 'Instructor 0002', Student: 'Student 0001' },
    },
    {
      id: 'studio-1', title: 'Composition studio', type: 'studio_class', resourceId: 'R102',
      daysOfWeek: [2], start: '2026-03-03T14:00:00', end: '2026-03-03T15:30:00',
      unresolved_issue_id: 'issue-2', extendedProps: { Instructor: 'Instructor 0010' },
    },
    {
      id: 'lecture-1', title: 'Academic lecture', type: 'lecture', resourceId: 'Hall-A',
      daysOfWeek: [3], startTime: '11:00', endTime: '12:00', locked: true,
      extendedProps: { Instructor: 'Staff Facilitator' },
    },
    {
      id: 'legacy-unplaced', title: 'Malformed legacy event', resourceId: 10,
      startTime: 'later', extendedProps: { Instructor: 'Archive import' },
    },
  ],
  issues: [
    {
      reason_code: 'room_conflict', label: 'Room conflict', count: 2,
      items: [
        { id: 'issue-1', reason_code: 'room_conflict', message: 'R101 is double booked', assignment_id: 'weekly-1', payload: { room: 'R101', start: '09:00' } },
        { id: 'issue-2', assignment_id: 'studio-1', reason_code: 'room_conflict', message: 'Instructor 0010 needs a studio room', payload: { raw_row: { Instructor: 'Instructor 0010', Room: 'R102', 'Class Time': '14:00-15:30' } } },
        {
          id: 'issue-3', source_request_id: 'source-row-3', reason_code: 'room_conflict',
          message: 'Unmapped source row', reason: 'No feasible room', type: 'weekly_lesson',
          instructor: 'Instructor 0003', course_code: 'MUS220 Cello', student_name: 'Student 0002', student_id: 'S220',
          instrument: 'Cello', duration_minutes: 60, original_day: 4, original_start: '13:00',
          original_end: '14:00', original_time: '13:00-14:00', original_date: null,
          preferred_venues: ['R101'], room_types: ['Instrumental'],
          payload: { source: 'legacy', raw_row: { 'Preferred Venue': 'R101' } },
        },
      ],
    },
  ],
  rooms: [{ id: 'R101' }, { id: 'R102' }, { id: 'Hall-A' }],
  instructors: ['Instructor 0002', 'Instructor 0010', 'Staff Facilitator'],
  draft: { dirty: true, can_undo: true, can_redo: false },
  metrics: { assigned: 137, unresolved: 2, source_gaps: 4 },
  warnings: [],
}

let resolutionWaiting = false
let assignmentBodies: Record<string, unknown>[] = []
let unassignBlockBodies: Record<string, unknown>[] = []
let leverageBodies: Record<string, unknown>[] = []
const envelope = (data: unknown, version = 'workspace-v17') => ({ data, workspace_version: version, warnings: [], error: null })
const resolutionAdvice = () => ({
  summary: { total: 3, cases: 1, place_now: 1, same_day_alternative: 0, blocked: 0, waiting: resolutionWaiting ? 1 : 0 },
  cases: [{
    id: 'case-source-thursday', instructor: 'Instructor 0003', day: 4, date: null,
    waiting: resolutionWaiting, waiting_note: '',
    issues: [{
      issue_id: 'issue-3', label: 'Student 0002', type: 'weekly_lesson', status: 'place_now', time_change_allowed: true,
      reason: 'Original time is available in a compatible room.',
      placement_group_id: 'weekly-group:Instructor 0003:4:issue-3',
      placement_group_size: 2,
      single_room: true,
      options: [{
        room: 'R101', day: 4, start: '13:00', end: '14:00', preferred: true,
        time_changed: false, requires_teacher_confirmation: false, shift_minutes: null,
      }, {
        room: 'R102', day: 4, start: '14:00', end: '15:00', preferred: false,
        time_changed: true, requires_teacher_confirmation: true, shift_minutes: 60,
      }],
    }],
  }],
  piano_leverage: [{
    id: 'piano-demo', instructor: 'Instructor 0005', target_room: 'R101', target_day: 5,
    target_start: '14:00', target_end: '21:00', gain: 4,
    moves: [{
      assignment_id: 'piano-block', label: 'Piano coaching block', from_room: 'R102',
      from_day: 4, from_start: '11:00', from_end: '18:00', to_room: 'R101',
      to_day: 5, to_start: '14:00', to_end: '21:00',
    }],
    fills: [{
      issue_id: 'issue-fill', label: 'Student 0007', instructor: 'Instructor 0009',
      room: 'R102', day: 4, start: '15:00', end: '16:00',
    }],
  }],
  pi_available: true,
  pi_runtime: {
    provider: 'openai-codex',
    model: 'gpt-5.6-luna',
    thinking_level: 'off',
    thinking_levels: ['off', 'minimal', 'low', 'medium', 'high', 'max'],
    choices: [
      { provider: 'deepseek', model: 'deepseek-flash' },
      { provider: 'kimi-coding', model: 'k3' },
      { provider: 'openai-codex', model: 'gpt-5.3-codex-spark' },
      { provider: 'openai-codex', model: 'gpt-5.6-luna' },
    ],
    allowed_models: ['deepseek-flash', 'gpt-5.3-codex-spark', 'gpt-5.6-luna', 'k3'],
  },
})
const server = setupServer(
  http.get('/api/scheduler/session', () => HttpResponse.json(envelope(session))),
  http.get('/api/scheduler/lectures', () => HttpResponse.json(envelope({ lectures: [] }))),
  http.get('/api/scheduler/resolution/advice', () => HttpResponse.json(
    envelope(resolutionAdvice(), resolutionWaiting ? 'workspace-v18' : 'workspace-v17'),
  )),
  http.post('/api/scheduler/resolution/cases/:caseId/waiting', async ({ request }) => {
    const body = await request.json() as { waiting: boolean }
    resolutionWaiting = body.waiting
    return HttpResponse.json(envelope(resolutionAdvice(), 'workspace-v18'))
  }),
  http.post('/api/scheduler/issues/:issueId/validate-assignment', async ({ request }) => {
    const body = await request.json() as { start: string }
    const changed = body.start !== '13:00'
    return HttpResponse.json(envelope({
      success: true, message: null, start_norm: body.start, end_norm: changed ? '15:00' : '14:00', specific_date: null,
      warnings: [], requires_teacher_confirmation: changed,
      teacher_confirmation_message: changed ? "Teacher confirmation is required before changing Instructor 0003's scheduled day or time." : null,
    }))
  }),
  http.post('/api/scheduler/issues/:issueId/assign', async ({ request }) => {
    assignmentBodies.push(await request.json() as Record<string, unknown>)
    return HttpResponse.json(envelope(session, 'workspace-v18'))
  }),
  http.post('/api/scheduler/resolution/piano-leverage/:proposalId/apply', async ({ request }) => {
    leverageBodies.push(await request.json() as Record<string, unknown>)
    return HttpResponse.json(envelope(session, 'workspace-v18'))
  }),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup(); resolutionWaiting = false; assignmentBodies = []; unassignBlockBodies = []; leverageBodies = []
  server.resetHandlers()
  window.localStorage.removeItem('pi.resolve.queueWidth.schedule')
  window.localStorage.removeItem('pi.resolve.queueWidth.reconciliation')
})
afterAll(() => server.close())

function renderPage(entry = '/schedule/resolve?workspace=schedule') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } })
  const router = createMemoryRouter(
    [{ path: '/schedule/resolve', element: <ResolvePage /> }],
    { initialEntries: [entry] },
  )
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return router
}

describe('ResolvePage', () => {
  const weekdayButton = (name: RegExp) => within(screen.getByRole('group', { name: 'Schedule weekday' })).getByRole('button', { name })
  it('shows last-staged ghosts and finalize intercept while editing diverges from validation authority', async () => {
    server.use(http.get('/api/scheduler/session', () => HttpResponse.json(envelope({
      ...session,
      schedule_authority: 'editing',
      validation_authority: [
        {
          ...session.assignments[0],
          resourceId: 'R102',
        },
        session.assignments[1],
      ],
    }))))
    renderPage()
    await screen.findByLabelText('Schedule grid')
    expect(screen.getByText('Editing')).toHaveAttribute('data-active', 'true')
    expect(screen.getByText('Stage before finalizing')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Finalize schedule' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Stage schedule' })).toBeEnabled()
    expect(screen.getByTestId('ghost-assignment')).toHaveTextContent('Last staged placement')
    fireEvent.click(screen.getByRole('button', { name: 'Teachers' }))
    expect(screen.queryByTestId('ghost-assignment')).toBeNull()
    expect(screen.queryByText('Last staged')).toBeNull()
  })

  it('keeps learning-record failures visible in the Step 4 workspace', async () => {
    server.use(http.get('/api/scheduler/session', () => HttpResponse.json(envelope({
      ...session,
      warnings: ['Optimizer learning evidence needs repair before research export.'],
    }))))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Optimizer learning evidence needs repair before research export.',
    )
    expect(screen.getByText('Workspace record needs attention')).toBeInTheDocument()
  })

  it('distinguishes weekly studio and locked assignments without color alone', async () => {
    renderPage()
    expect(await screen.findByRole('button', { name: /Weekly.*Cello lesson.*Instructor 0002/ })).toHaveAttribute('data-kind', 'weekly')
    fireEvent.click(weekdayButton(/Tuesday/))
    expect(screen.getByRole('button', { name: /Studio.*Composition studio.*Instructor 0010/ })).toHaveAttribute('data-kind', 'studio')
    fireEvent.click(weekdayButton(/Wednesday/))
    const lecture = screen.getByRole('button', { name: /Lecture.*Academic lecture/ })
    expect(lecture).toHaveAttribute('data-kind', 'locked')
    expect(lecture).toHaveAttribute('data-lecture', 'true')
    expect(lecture).toHaveTextContent('Lecture')
  })

  it('overlays imported lectures onto the resolve grid when they are absent from session assignments', async () => {
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope({
        ...session,
        assignments: session.assignments.filter((item) => item.id !== 'lecture-1'),
      }))),
      http.get('/api/scheduler/lectures', () => HttpResponse.json(envelope({
        lectures: [{
          id: 'lecture-imported',
          title: 'Imported theory lecture',
          type: 'lecture',
          resourceId: 'Hall-A',
          daysOfWeek: [3],
          startTime: '11:00',
          endTime: '12:00',
          locked: true,
        }],
      }))),
    )
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Wednesday/ }))
    const lecture = await screen.findByRole('button', { name: /Lecture.*Imported theory lecture/ })
    expect(lecture).toHaveAttribute('data-lecture', 'true')
    expect(lecture).toHaveAttribute('data-kind', 'locked')
    fireEvent.click(lecture)
    expect(screen.queryByRole('region', { name: 'Selected assignment' })).not.toBeInTheDocument()
  })

  it('opens the teacher-block inspector from a contiguous same-room segment', async () => {
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope({
        ...session,
        assignments: [
          session.assignments[0],
          {
            ...session.assignments[0],
            id: 'weekly-2',
            title: 'Cello lesson 2',
            startTime: '10:00:00',
            endTime: '11:00:00',
            extendedProps: { Instructor: 'Instructor 0002', Student: 'Student 0002' },
          },
          ...session.assignments.slice(1),
        ],
      }))),
      http.post('/api/scheduler/assignments/unassign-block', async ({ request }) => {
        unassignBlockBodies.push(await request.json() as Record<string, unknown>)
        return HttpResponse.json(envelope(session, 'workspace-v18'))
      }),
    )
    renderPage()
    await screen.findByLabelText('Schedule grid')
    fireEvent.click(screen.getByRole('button', { name: 'Teachers' }))
    fireEvent.click(screen.getByLabelText(/Teacher block, Instructor 0002/))
    const inspector = screen.getByTestId('reconciliation-inspector')
    expect(inspector).toHaveTextContent('Selected teacher block')
    expect(inspector).toHaveTextContent('Student 0001')
    expect(inspector).toHaveTextContent('Student 0002')
    fireEvent.click(within(inspector).getByRole('button', { name: 'Unassign this block' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm unassign' }))
    await waitFor(() => expect(unassignBlockBodies).toEqual([{
      assignment_ids: ['weekly-1', 'weekly-2'],
      expected_version: 'workspace-v17',
    }]))
  })

  it('exposes a queue splitter and restores stored widths per workspace mode', async () => {
    renderPage()
    await screen.findByLabelText('Schedule grid')
    const workspace = screen.getByTestId('resolve-workspace')
    expect(screen.getByRole('separator', { name: 'Resize issue queue' })).toBeVisible()
    expect(workspace.style.getPropertyValue('--resolve-queue-width')).toBe('300px')
    fireEvent.click(screen.getByRole('button', { name: /Reconciliation/ }))
    await waitFor(() => expect(workspace.style.getPropertyValue('--resolve-queue-width')).toBe('420px'))
    fireEvent.click(screen.getByRole('button', { name: 'Timetable' }))
    await waitFor(() => expect(workspace.style.getPropertyValue('--resolve-queue-width')).toBe('300px'))
  })

  it('keeps the schedule issue queue and editor visible with canonical metrics and state', async () => {
    renderPage()
    expect(await screen.findByLabelText('Schedule grid')).toBeVisible()
    expect(screen.getByTestId('schedule-pane')).toContainElement(screen.getByLabelText('Schedule legend and commands'))
    expect(screen.getByRole('region', { name: 'Needs resolution' })).toBeVisible()
    expect(screen.queryByRole('region', { name: 'Selected assignment' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Weekly.*Cello lesson/ }))
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toBeVisible()
    expect(screen.getByTestId('schedule-pane')).not.toContainElement(screen.getByRole('region', { name: 'Selected assignment' }))
    const metrics = screen.getByLabelText('Schedule metrics')
    expect(within(metrics).getByText('137')).toBeVisible()
    expect(within(metrics).getByText('2')).toBeVisible()
    expect(within(metrics).getByText('4')).toBeVisible()
    expect(screen.getByText('resolve')).toBeVisible()
    expect(screen.getByText('workspace-v17')).toBeVisible()
    expect(screen.getByLabelText('Schedule authority')).toBeVisible()
    expect(screen.getByText('Staged')).toHaveAttribute('data-active', 'true')
    expect(screen.getByText('Autosave active')).toBeVisible()
    expect(screen.queryByText('Unsaved draft')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stage schedule' })).toBeDisabled()
    expect(screen.getByText('Undo available')).toBeVisible()
    expect(screen.getByText('Redo unavailable')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Review 2 unresolved' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Finalize schedule' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Stage schedule' })).toBeDisabled()
    expect(screen.queryByText('Stage before finalizing')).not.toBeInTheDocument()
  })

  it('renders the V7 resolve geometry and integrated issue cause rail contract', async () => {
    renderPage()
    const pane = await screen.findByTestId('schedule-pane')
    expect(pane).toHaveAttribute('data-layout', 'timetable-footer')
    const rail = screen.getByRole('region', { name: 'Needs resolution' })
    expect(rail).toHaveAttribute('data-width', '286')
    const allRail = screen.getByRole('region', { name: 'Needs resolution' })
    expect(within(allRail).getByRole('button', { name: /Room conflict.*2/ })).toBeVisible()
    expect(within(allRail).getByText('FILTERED RESULTS')).toBeVisible()
  })

  it('opens Resolve on the reconciliation teacher workspace', async () => {
    renderPage('/schedule/resolve')
    expect(await screen.findByLabelText('PI 排课调查')).toBeVisible()
    expect(screen.getByRole('button', { name: /^Reconciliation/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Teachers' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('region', { name: 'Needs resolution' })).toHaveAttribute('data-width', '420')
    expect(screen.queryByRole('heading', { name: 'Weekly lessons' })).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Reconciliation queue' })).toBeNull()
    expect(within(screen.getByRole('group', { name: 'Reconciliation day' })).getByRole('button', { name: /Thursday.*1/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('opens reconciliation as a contextual split with the Pi workbench beside the timetable', async () => {
    const router = renderPage()
    await screen.findByLabelText('Schedule grid')
    fireEvent.click(screen.getByRole('button', { name: /^Reconciliation/ }))
    expect(await screen.findByLabelText('PI 排课调查')).toBeVisible()
    expect(screen.getByRole('region', { name: 'Needs resolution' })).toHaveAttribute('data-width', '420')
    expect(screen.getByLabelText('Schedule grid')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Teachers' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(screen.getByRole('group', { name: 'Reconciliation day' })).getByRole('button', { name: /Thursday.*1/ })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(router.state.location.search).toContain('workspace=reconciliation'))
  })

  it('exposes one whole-day investigation instead of the retired case and plan Pi cards', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /^Reconciliation/ }))
    expect(await screen.findByLabelText('Pi 模型')).toHaveValue('openai-codex::gpt-5.6-luna')
    expect(screen.getByRole('option', { name: 'deepseek / deepseek-flash' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'kimi-coding / k3' })).toBeInTheDocument()
    expect(screen.getByLabelText('思考强度')).toHaveValue('off')
    expect(screen.getByRole('button', { name: /调查周四的关联调整/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Investigate with Pi' })).toBeNull()
    expect(screen.queryByText('Plan-level Pi intervention')).toBeNull()
    expect(screen.queryByLabelText(/do not touch this time/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Inspect timetable' })).toBeNull()
  })

  it('restores selection from the URL and updates it when an assignment is clicked', async () => {
    const router = renderPage('/schedule/resolve?workspace=schedule&assignment=studio-1')
    const studio = await screen.findByRole('button', { name: /Studio.*Composition studio/ })
    expect(studio).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Composition studio')

    fireEvent.click(weekdayButton(/Monday/))
    fireEvent.click(screen.getByRole('button', { name: /Weekly.*Cello lesson/ }))
    await waitFor(() => {
      expect(router.state.location.search).toContain('workspace=schedule')
      expect(router.state.location.search).toContain('day=1')
      expect(router.state.location.search).toContain('assignment=weekly-1')
    })
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Cello lesson')

    fireEvent.click(screen.getByRole('button', { name: /Weekly.*Malformed legacy event.*Archive import/ }))
    await waitFor(() => {
      expect(router.state.location.search).toContain('assignment=legacy-unplaced')
      expect(router.state.location.search).toContain('workspace=schedule')
    })
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Malformed legacy event')
  })

  it('uses issue linkage and payload context to locate assignments and bind the editor', async () => {
    const router = renderPage()
    await screen.findByLabelText('Schedule grid')
    fireEvent.click(screen.getByRole('button', { name: /R101 is double booked/ }))
    expect(screen.getByRole('button', { name: /Weekly.*Cello lesson/ })).toHaveAttribute('data-issue-match', 'true')
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Cello lesson')
    await waitFor(() => {
      expect(router.state.location.search).toContain('assignment=weekly-1')
      expect(router.state.location.search).toContain('workspace=schedule')
    })

    fireEvent.click(screen.getByRole('button', { name: /Instructor 0010 needs a studio room/ }))
    expect(weekdayButton(/Tuesday/)).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /Studio.*Composition studio/ })).toHaveAttribute('data-issue-match', 'true')
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Composition studio')
  })

  it('opens the canonical assignment editor when an issue has no related assignment', async () => {
    const router = renderPage('/schedule/resolve?workspace=schedule&assignment=weekly-1')
    expect(await screen.findByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Cello lesson')

    const issue = screen.getByRole('button', { name: /Unmapped source row/ })
    fireEvent.click(issue)

    await waitFor(() => {
      expect(router.state.location.search).toContain('workspace=schedule')
      expect(router.state.location.search).not.toContain('assignment=weekly-1')
    })
    expect(issue).toHaveAttribute('aria-pressed', 'true')
    const editor = screen.getByRole('region', { name: 'Selected assignment' })
    expect(editor).toHaveTextContent('Resolve Issue')
    expect(editor).toHaveTextContent('Student 0002')
    expect(editor).toHaveTextContent('Instructor 0003')
    expect(editor).toHaveTextContent('MUS220 Cello')
    expect(editor).toHaveTextContent('No compatible room is available under the current scheduling rules.')
    fireEvent.click(within(editor).getByRole('button', { name: 'Adjust manually' }))
    expect(within(editor).getByLabelText('Room')).toHaveValue('R101')
    expect(within(editor).getByLabelText('Day')).toHaveValue('4')
    expect(within(editor).getByLabelText('Start time')).toHaveValue('13:00')
    expect(within(editor).getByLabelText('End time')).toHaveValue('14:00')
    expect(editor).toHaveTextContent('Thursday · 13:00-14:00')
    expect(editor).not.toHaveTextContent('Cello lesson')
  })

  it('persists the active day in the URL and clears a selection hidden by manual day change', async () => {
    const router = renderPage('/schedule/resolve?workspace=schedule&day=2&assignment=weekly-1')
    await screen.findByLabelText('Schedule grid')
    expect(weekdayButton(/Monday/)).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => {
      expect(router.state.location.search).toContain('workspace=schedule')
      expect(router.state.location.search).toContain('assignment=weekly-1')
      expect(router.state.location.search).toContain('day=1')
    })

    fireEvent.click(weekdayButton(/Tuesday/))

    await waitFor(() => {
      expect(router.state.location.search).toContain('day=2')
      expect(router.state.location.search).not.toContain('assignment=')
    })
    expect(screen.queryByRole('button', { name: /Cello lesson/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Selected assignment' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Composition studio/ })).toBeVisible()
  })

  it('shows honest loading error empty and stale URL states', async () => {
    let resolveRequest: ((response: Response) => void) | undefined
    server.use(http.get('/api/scheduler/session', () => new Promise<Response>((resolve) => { resolveRequest = resolve })))
    renderPage()
    expect(screen.getByRole('status')).toHaveTextContent('Loading schedule workspace')
    expect(screen.getByText('Loading schedule workspace')).toBeVisible()
    await waitFor(() => expect(resolveRequest).toBeTypeOf('function'))
    resolveRequest?.(HttpResponse.json(envelope({ ...session, assignments: [], issues: [], metrics: { assigned: 0, unresolved: 0, source_gaps: 0 } })))
    expect(await screen.findByText('No assignments in the current scheduler session.')).toBeVisible()
    cleanup()

    server.use(http.get('/api/scheduler/session', () => HttpResponse.json(
      { data: null, workspace_version: null, warnings: [], error: { code: 'READ_FAILED', message: 'Session unavailable' } },
      { status: 500 },
    )))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('Session unavailable')
    cleanup()

    server.use(http.get('/api/scheduler/session', () => HttpResponse.json(envelope(session))))
    renderPage('/schedule/resolve?workspace=schedule&assignment=retired-9')
    await waitFor(() => expect(screen.getByText(/retired-9 is no longer available/)).toBeVisible())
    expect(screen.queryByRole('region', { name: 'Selected assignment' })).not.toBeInTheDocument()
  })
})
