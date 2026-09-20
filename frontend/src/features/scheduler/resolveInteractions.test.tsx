import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { readFileSync } from 'node:fs'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { ApiEnvelope } from '../../api/client'
import type { SchedulerSession } from './api'
import { mapDropToMoveTarget, mapIssueDropToTarget } from './components/ScheduleGrid'
import type { MoveTarget } from './hooks/useAssignmentCommands'
import { ResolvePage } from './pages/ResolvePage'
import { draftState } from '../../test/draftState'

const resolveCss = [
  'resolve.module.css',
  'scheduleGrid.module.css',
  'assignmentEditor.module.css',
].map((name) => readFileSync(`src/features/scheduler/${name}`, 'utf8')).join('\n')

const baseSession: SchedulerSession = {
  active_stage: 'resolve',
  assignments: [
    {
      id: 'a-1', title: 'Cello lesson', type: 'weekly_lesson', resourceId: 'R104',
      daysOfWeek: [1], startTime: '09:00', endTime: '10:00',
      extendedProps: { Instructor: 'Instructor 0002' },
    },
    {
      id: 'a-2', title: 'Piano lesson', type: 'weekly_lesson', resourceId: 'R104',
      daysOfWeek: [2], startTime: '09:00', endTime: '10:00',
      extendedProps: { Instructor: 'Instructor 0001' },
    },
    {
      id: 'a-3', title: 'Piano coaching', type: 'weekly_lesson', resourceId: 'R104',
      daysOfWeek: [1], startTime: '10:15', endTime: '11:00',
      extendedProps: { Instructor: 'Instructor 0001' },
    },
    {
      id: 'locked-1', title: 'Committed weekly', type: 'weekly_lesson', resourceId: 'R107B',
      daysOfWeek: [1], startTime: '11:00', endTime: '12:00', locked: true,
      extendedProps: { Instructor: 'Staff Facilitator' },
    },
  ],
  issues: [],
  rooms: [{ id: 'R104' }, { id: 'R107B' }],
  instructors: ['Instructor 0002', 'Instructor 0001', 'Staff Facilitator'],
  draft: draftState({ dirty: true, can_undo: true, can_redo: true }),
  metrics: { assigned: 4, unresolved: 0, source_gaps: 0 },
  warnings: [],
}

const unresolvedIssue: SchedulerSession['issues'][number]['items'][number] = {
  id: 'issue-source-1',
  source_request_id: 'source-request-1',
  reason_code: 'no_time_feasible_room',
  message: 'No feasible room',
  reason: 'No feasible room',
  assignment_id: null,
  instructor: 'Instructor 0002',
  course_code: 'MUS101 Piano',
  student_name: 'Student 0001',
  student_id: 'S100',
  type: 'weekly_lesson',
  instrument: 'Piano',
  duration_minutes: 60,
  original_day: 1,
  original_start: '09:00',
  original_end: '10:00',
  original_time: '09:00-10:00',
  original_date: null,
  preferred_venues: ['R104'],
  room_types: ['Piano'],
  payload: { raw_row: { 'Preferred Venue': 'R104', Instructor: 'Instructor 0002' } },
}

const overnightStudioIssue: SchedulerSession['issues'][number]['items'][number] = {
  ...unresolvedIssue,
  id: 'issue-studio-overnight',
  source_request_id: 'source-studio-overnight',
  student_name: 'Overnight studio',
  type: 'studio_class',
  duration_minutes: 120,
  original_day: 3,
  original_start: '23:00',
  original_end: '01:00',
  original_time: '23:00-01:00',
  original_date: '2026-03-04',
}

function sessionWithIssue(): SchedulerSession {
  return {
    ...baseSession,
    issues: [{
      reason_code: unresolvedIssue.reason_code,
      label: 'No time feasible room',
      count: 1,
      items: [unresolvedIssue],
    }],
    metrics: { ...baseSession.metrics, unresolved: 1 },
  }
}

function sessionWithStudioIssue(): SchedulerSession {
  return {
    ...baseSession,
    issues: [{
      reason_code: overnightStudioIssue.reason_code,
      label: 'No time feasible room',
      count: 1,
      items: [overnightStudioIssue],
    }],
    metrics: { ...baseSession.metrics, unresolved: 1 },
  }
}

function sessionWithAssignedIssue(target = { room: 'R107B', day: 3, start: '14:00', end: '15:00' }): SchedulerSession {
  return {
    ...baseSession,
    assignments: [
      ...baseSession.assignments,
      {
        id: unresolvedIssue.source_request_id,
        source_request_id: unresolvedIssue.source_request_id,
        title: 'Student 0001 piano lesson',
        type: 'weekly_lesson',
        resourceId: target.room,
        daysOfWeek: [target.day],
        startTime: target.start,
        endTime: target.end,
        extendedProps: { Instructor: unresolvedIssue.instructor },
      },
    ],
    issues: [],
    metrics: { assigned: baseSession.metrics.assigned + 1, unresolved: 0, source_gaps: 0 },
    draft: draftState({ dirty: true, can_undo: true, can_redo: false }),
  }
}

function envelope(data: SchedulerSession, version = 'workspace-v1'): ApiEnvelope<SchedulerSession> {
  return { data, workspace_version: version, warnings: [], error: null }
}

const server = setupServer(
  http.get('/api/scheduler/session', () => HttpResponse.json(envelope(baseSession))),
  http.get('/api/scheduler/resolution/advice', () => HttpResponse.json({
    data: {
      summary: { total: 0, cases: 0, place_now: 0, same_day_alternative: 0, blocked: 0, waiting: 0 },
      cases: [], piano_leverage: [],
    },
    workspace_version: 'workspace-v1', warnings: [], error: null,
  })),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(async () => {
  cleanup()
  await new Promise((resolve) => setTimeout(resolve, 0))
  server.resetHandlers()
})
afterAll(() => server.close())

function renderPage(entry = '/schedule/resolve?workspace=schedule') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } })
  const router = createMemoryRouter([{ path: '/schedule/resolve', element: <ResolvePage /> }], { initialEntries: [entry] })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return { client, router }
}

async function openAssignment(name = /Weekly.*Cello lesson.*Instructor 0002/) {
  const button = await screen.findByRole('button', { name })
  fireEvent.click(button)
  const editor = screen.getByRole('region', { name: 'Selected assignment' })
  await within(editor).findByLabelText('Start time')
  return editor
}

async function fillMove(room = 'R107B') {
  const editor = await openAssignment()
  await userEvent.selectOptions(within(editor).getByLabelText('Room'), room)
  return editor
}

async function openIssueFields(editor: HTMLElement) {
  const toggle = within(editor).queryByRole('button', { name: /Adjust manually|Try another room/ })
  if (toggle) await userEvent.click(toggle)
  await within(editor).findByLabelText('Room')
  return editor
}

function allowMoveValidation(version = 'workspace-v1') {
  server.use(http.post('/api/scheduler/assignments/:assignmentId/validate-move', async ({ request }) => {
    const proposal = await request.json() as MoveTarget
    return HttpResponse.json({
      data: { success: true, message: null, start_norm: proposal.start, end_norm: proposal.end, specific_date: null, warnings: [] },
      workspace_version: version, warnings: [], error: null,
    })
  }))
}

async function validateAndCommitMove(editor: HTMLElement) {
  await userEvent.click(within(editor).getByRole('button', { name: 'Validate move' }))
  const move = within(editor).getByRole('button', { name: 'Move assignment' })
  await waitFor(() => expect(move).toBeEnabled())
  await userEvent.click(move)
}

function movedSession(room = 'R107B'): SchedulerSession {
  return {
    ...baseSession,
    assignments: baseSession.assignments.map((assignment) => assignment.id === 'a-1'
      ? { ...assignment, resourceId: room }
      : assignment),
  }
}

function canonicalAssignmentSession(
  room: string,
  start: string,
  end: string,
  overrides: Partial<SchedulerSession> = {},
): SchedulerSession {
  return {
    ...baseSession,
    assignments: baseSession.assignments.map((assignment) => assignment.id === 'a-1'
      ? { ...assignment, resourceId: room, startTime: start, endTime: end }
      : assignment),
    ...overrides,
  }
}

describe('schedule editing interactions', () => {
  it('keeps the editor docked in the desktop viewport and delegates narrow time space to internal grid scrolling', () => {
    expect(resolveCss).toMatch(/\.resolveWorkspace\s*\{[^}]*height:\s*0;[^}]*flex:\s*1 1 0;[^}]*overflow:\s*hidden;/)
    expect(resolveCss).toMatch(/\.schedulePane\s*\{[^}]*height:\s*100%;[^}]*grid-template-rows:\s*minmax\(190px, 1fr\) auto;/)
    expect(resolveCss).toMatch(/\.resolveWorkspace\.reconciliationWithInspector,\s*\.resolveWorkspace\.reconciliationMode\.reconciliationWithInspector\s*\{[^}]*grid-template-columns:\s*var\(--resolve-queue-width\) 8px minmax\(920px, 1fr\) 300px;[^}]*overflow:\s*hidden;/)
    expect(resolveCss).toMatch(/\[data-reconciliation-inspector\][^{]*\.assignmentEditor\s*\{[^}]*height:\s*100%;[^}]*max-height:\s*none;/)
    expect(resolveCss).not.toMatch(/webkit-scrollbar[^}]*display:\s*none;/)
    expect(resolveCss).toMatch(/@container resolve-page \(max-width: 1519px\)/)
    expect(resolveCss).toMatch(/\.gridScroller\s*\{[^}]*overflow:\s*auto;/)
    expect(resolveCss).toMatch(/\.gridCanvas\s*\{[^}]*min-width:\s*920px;[^}]*grid-template-columns:\s*74px minmax\(846px, 1fr\);/)
  })

  it('moves focus spatially with arrows and opens the focused assignment with Enter', async () => {
    const { router } = renderPage()
    const first = await screen.findByRole('button', { name: /Weekly.*Cello lesson.*Instructor 0002/ })
    first.focus()

    await userEvent.keyboard('{ArrowRight}{Enter}')

    expect(screen.getByRole('button', { name: /Weekly.*Piano coaching.*Instructor 0001/ })).toHaveFocus()
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Instructor 0001')
    await waitFor(() => expect(router.state.location.search).toContain('assignment=a-3'))
  })

  it('keeps the canonical block in place until the move response succeeds', async () => {
    let resolveValidation: ((response: Response) => void) | undefined
    let resolveMove: ((response: Response) => void) | undefined
    server.use(
      http.post('/api/scheduler/assignments/a-1/validate-move', () => new Promise<Response>((resolve) => { resolveValidation = resolve })),
      http.post('/api/scheduler/assignments/a-1/move', () => new Promise<Response>((resolve) => { resolveMove = resolve })),
    )
    renderPage()
    const editor = await fillMove()

    const validate = within(editor).getByRole('button', { name: 'Validate move' })
    const commit = within(editor).getByRole('button', { name: 'Move assignment' })
    expect(commit).toBeDisabled()
    await userEvent.click(validate)
    expect(screen.getByRole('button', { name: /Cello lesson/ })).toHaveAttribute('data-room', 'R104')
    await waitFor(() => expect(resolveValidation).toBeTypeOf('function'))
    resolveValidation?.(HttpResponse.json({
      data: { success: true, message: null, start_norm: '09:00', end_norm: '10:00', specific_date: null, warnings: [] },
      workspace_version: 'workspace-v1', warnings: [], error: null,
    }))
    expect(await within(editor).findByText('Move validated.')).toBeVisible()
    expect(commit).toBeEnabled()

    await userEvent.click(commit)
    expect(screen.getByRole('button', { name: /Cello lesson/ })).toHaveAttribute('data-room', 'R104')
    expect(commit).toBeDisabled()
    await waitFor(() => expect(resolveMove).toBeTypeOf('function'))

    resolveMove?.(HttpResponse.json(envelope(movedSession(), 'workspace-v2')))
    await waitFor(() => expect(screen.getByRole('button', { name: /Cello lesson/ })).toHaveAttribute('data-room', 'R107B'))
    expect(screen.getByText('workspace-v2')).toBeVisible()
  })

  it('preserves every field when a move draft is edited in one interaction burst', async () => {
    let body: Record<string, unknown> | null = null
    server.use(http.post('/api/scheduler/assignments/a-1/move', async ({ request }) => {
      body = await request.json() as Record<string, unknown>
      return HttpResponse.json(envelope(canonicalAssignmentSession('R104', '14:00', '15:00'), 'workspace-v2'))
    }))
    allowMoveValidation()
    renderPage()
    const editor = await openAssignment()

    fireEvent.change(within(editor).getByLabelText('Start time'), { target: { value: '14:00' } })
    fireEvent.change(within(editor).getByLabelText('End time'), { target: { value: '15:00' } })
    fireEvent.change(within(editor).getByLabelText('Day'), { target: { value: '2' } })

    expect(within(editor).getByLabelText('Start time')).toHaveValue('14:00')
    expect(within(editor).getByLabelText('End time')).toHaveValue('15:00')
    expect(within(editor).getByLabelText('Day')).toHaveValue('2')
    await validateAndCommitMove(editor)
    await waitFor(() => expect(body).toMatchObject({ day: 2, start: '14:00', end: '15:00' }))
  })

  it('adopts one canonical move response across grid metrics issues editor and history before the next submit', async () => {
    const bodies: Array<Record<string, unknown>> = []
    const refreshIssue = { ...unresolvedIssue, id: 'canonical-refresh-issue', source_request_id: 'canonical-refresh-source', message: 'Canonical refresh issue' }
    const canonical = canonicalAssignmentSession('R107B', '14:00', '15:00', {
      issues: [{ reason_code: refreshIssue.reason_code, label: 'Refresh', count: 1, items: [refreshIssue] }],
      metrics: { assigned: 9, unresolved: 1, source_gaps: 2 },
      draft: draftState({ dirty: true, can_undo: true, can_redo: false }),
    })
    server.use(http.post('/api/scheduler/assignments/a-1/move', async ({ request }) => {
      bodies.push(await request.json() as Record<string, unknown>)
      const version = bodies.length === 1 ? 'workspace-v2' : 'workspace-v3'
      return HttpResponse.json(envelope(canonical, version))
    }))
    allowMoveValidation()
    renderPage()
    const editor = await openAssignment()
    await userEvent.selectOptions(within(editor).getByLabelText('Room'), 'R107B')
    fireEvent.change(within(editor).getByLabelText('Start time'), { target: { value: '14:00' } })
    fireEvent.change(within(editor).getByLabelText('End time'), { target: { value: '15:00' } })
    await validateAndCommitMove(editor)
    await waitFor(() => expect(screen.getByText('workspace-v2')).toBeVisible())
    expect(screen.getByRole('button', { name: /Cello lesson/ })).toHaveAttribute('data-room', 'R107B')
    expect(within(screen.getByLabelText('Schedule metrics')).getByText('9')).toBeVisible()
    expect(screen.getByRole('button', { name: /Canonical refresh issue/ })).toBeVisible()
    expect(screen.getByText('Undo available')).toBeVisible()
    expect(screen.getByText('Redo unavailable')).toBeVisible()
    expect(within(editor).getByLabelText('Room')).toHaveValue('R107B')
    expect(within(editor).getByLabelText('Start time')).toHaveValue('14:00')
    expect(within(editor).getByLabelText('End time')).toHaveValue('15:00')

    await userEvent.selectOptions(within(editor).getByLabelText('Room'), 'R104')
    allowMoveValidation('workspace-v2')
    await validateAndCommitMove(editor)
    await waitFor(() => expect(bodies).toHaveLength(2))
    expect(bodies[1]).toMatchObject({ expected_version: 'workspace-v2', room: 'R104', start: '14:00', end: '15:00' })
    expect(await screen.findByText('workspace-v3')).toBeVisible()
  })

  it('replaces local editor draft and version with canonical undo and redo responses', async () => {
    const moveBodies: Array<Record<string, unknown>> = []
    const undone = canonicalAssignmentSession('R107B', '12:00', '13:00', {
      draft: draftState({ dirty: true, can_undo: false, can_redo: true }),
    })
    const redone = canonicalAssignmentSession('R104', '16:00', '17:00', {
      draft: draftState({ dirty: true, can_undo: true, can_redo: false }),
    })
    server.use(
      http.post('/api/scheduler/draft/undo', () => HttpResponse.json(envelope(undone, 'workspace-v2'))),
      http.post('/api/scheduler/draft/redo', () => HttpResponse.json(envelope(redone, 'workspace-v3'))),
      http.post('/api/scheduler/assignments/a-1/move', async ({ request }) => {
        moveBodies.push(await request.json() as Record<string, unknown>)
        return HttpResponse.json(envelope(redone, 'workspace-v4'))
      }),
    )
    renderPage()
    const editor = await openAssignment()
    await userEvent.selectOptions(within(editor).getByLabelText('Room'), 'R107B')
    await userEvent.clear(within(editor).getByLabelText('Start time'))
    await userEvent.type(within(editor).getByLabelText('Start time'), '10:30')
    await userEvent.clear(within(editor).getByLabelText('End time'))
    await userEvent.type(within(editor).getByLabelText('End time'), '11:30')

    await userEvent.click(screen.getByRole('button', { name: 'Undo last schedule change' }))
    await waitFor(() => expect(screen.getByText('workspace-v2')).toBeVisible())
    expect(within(editor).getByLabelText('Room')).toHaveValue('R107B')
    expect(within(editor).getByLabelText('Start time')).toHaveValue('12:00')
    expect(within(editor).getByLabelText('End time')).toHaveValue('13:00')

    await userEvent.click(screen.getByRole('button', { name: 'Redo schedule change' }))
    await waitFor(() => expect(screen.getByText('workspace-v3')).toBeVisible())
    expect(within(editor).getByLabelText('Room')).toHaveValue('R104')
    expect(within(editor).getByLabelText('Start time')).toHaveValue('16:00')
    expect(within(editor).getByLabelText('End time')).toHaveValue('17:00')

    await userEvent.selectOptions(within(editor).getByLabelText('Room'), 'R107B')
    allowMoveValidation('workspace-v3')
    await validateAndCommitMove(editor)
    await waitFor(() => expect(moveBodies).toHaveLength(1))
    expect(moveBodies[0]).toMatchObject({ expected_version: 'workspace-v3', room: 'R107B', start: '16:00', end: '17:00' })
    expect(await screen.findByText('workspace-v4')).toBeVisible()
  })

  it('keeps the original position and focuses a persistent server error after rejection', async () => {
    server.use(http.post('/api/scheduler/assignments/a-1/move', () => HttpResponse.json({
      data: null, workspace_version: 'workspace-v1', warnings: [],
      error: { code: 'MOVE_CONFLICT', message: 'R107B is already occupied', details: { room: 'R107B', conflict: 'Piano lesson' } },
    }, { status: 400 })))
    allowMoveValidation()
    renderPage()
    const editor = await fillMove()

    await validateAndCommitMove(editor)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('R107B is already occupied')
    expect(alert).toHaveTextContent('Piano lesson')
    expect(alert).toHaveFocus()
    expect(screen.getByRole('button', { name: /Cello lesson/ })).toHaveAttribute('data-room', 'R104')
    expect(within(editor).getByLabelText('Room')).toHaveValue('R107B')
  })

  it('preserves a stale move draft on 409 and only adopts the reloaded canonical version explicitly', async () => {
    const bodies: unknown[] = []
    let reads = 0
    server.use(
      http.get('/api/scheduler/session', () => {
        reads += 1
        return HttpResponse.json(envelope(reads === 1 ? baseSession : movedSession('R107B'), reads === 1 ? 'workspace-v1' : 'workspace-v3'))
      }),
      http.post('/api/scheduler/assignments/a-1/move', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({
          data: null, workspace_version: 'workspace-v3', warnings: [],
          error: { code: 'WORKSPACE_CONFLICT', message: 'The workspace changed on disk', details: { path: 'data/session.json' } },
        }, { status: 409 })
      }),
    )
    const { client } = renderPage()
    await fillMove()
    client.setQueryData(['scheduler-session'], envelope(baseSession, 'workspace-v2'))
    await waitFor(() => expect(screen.getByText('workspace-v2')).toBeVisible())
    const editor = screen.getByRole('region', { name: 'Selected assignment' })
    await userEvent.clear(within(editor).getByLabelText('Start time'))
    await userEvent.type(within(editor).getByLabelText('Start time'), '10:30')
    await userEvent.clear(within(editor).getByLabelText('End time'))
    await userEvent.type(within(editor).getByLabelText('End time'), '11:30')

    allowMoveValidation('workspace-v2')
    await validateAndCommitMove(editor)
    expect(await screen.findByRole('alert')).toHaveTextContent('workspace changed')
    expect(within(editor).getByLabelText('Start time')).toHaveValue('10:30')
    expect(within(editor).getByRole('button', { name: 'Move assignment' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Undo last schedule change' })).toBeDisabled()
    expect(bodies[0]).toMatchObject({ expected_version: 'workspace-v2', start: '10:30' })

    await userEvent.click(screen.getByRole('button', { name: 'Reload workspace' }))
    await waitFor(() => expect(screen.getByText('workspace-v3')).toBeVisible())
    expect(within(screen.getByRole('region', { name: 'Selected assignment' })).getByLabelText('Room')).toHaveValue('R107B')
  })

  it('keeps a conflicted move draft mounted when reload fails and adopts canonical data after retry', async () => {
    let reads = 0
    server.use(
      http.get('/api/scheduler/session', () => {
        reads += 1
        if (reads === 1) return HttpResponse.json(envelope(baseSession))
        if (reads === 2) return HttpResponse.json({
          data: null, workspace_version: null, warnings: [],
          error: { code: 'READ_FAILED', message: 'Workspace reload failed' },
        }, { status: 500 })
        return HttpResponse.json(envelope(movedSession('R107B'), 'workspace-v3'))
      }),
      http.post('/api/scheduler/assignments/a-1/move', () => HttpResponse.json({
        data: null, workspace_version: 'workspace-v2', warnings: [],
        error: { code: 'WORKSPACE_CONFLICT', message: 'The workspace changed on disk' },
      }, { status: 409 })),
    )
    allowMoveValidation()
    renderPage()
    const editor = await fillMove()
    await userEvent.clear(within(editor).getByLabelText('Start time'))
    await userEvent.type(within(editor).getByLabelText('Start time'), '10:30')
    await userEvent.clear(within(editor).getByLabelText('End time'))
    await userEvent.type(within(editor).getByLabelText('End time'), '11:30')
    await validateAndCommitMove(editor)

    await userEvent.click(await screen.findByRole('button', { name: 'Reload workspace' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Workspace reload failed')
    expect(screen.getByRole('button', { name: 'Reload workspace' })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toBe(editor)
    expect(within(editor).getByLabelText('Start time')).toHaveValue('10:30')
    expect(screen.getByRole('button', { name: /Cello lesson/ })).toHaveAttribute('data-room', 'R104')

    await userEvent.click(screen.getByRole('button', { name: 'Reload workspace' }))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.getByText('workspace-v3')).toBeVisible()
    expect(within(screen.getByRole('region', { name: 'Selected assignment' })).getByLabelText('Room')).toHaveValue('R107B')
  })

  it('makes every schedule command read-only when a cached session refresh fails', async () => {
    let reads = 0
    server.use(http.get('/api/scheduler/session', () => {
      reads += 1
      if (reads === 1) return HttpResponse.json(envelope(baseSession))
      return HttpResponse.json({
        data: null, workspace_version: null, warnings: [],
        error: { code: 'READ_FAILED', message: 'Cached session refresh failed' },
      }, { status: 500 })
    }))
    const { client } = renderPage()
    const editor = await openAssignment()

    await client.refetchQueries({ queryKey: ['scheduler-session'] })

    expect(client.getQueryState(['scheduler-session'])?.status).toBe('error')
    expect(await screen.findByRole('alert')).toHaveTextContent('Cached session refresh failed')
    expect(within(editor).getByRole('button', { name: 'Move assignment' })).toBeDisabled()
    expect(within(editor).getByRole('button', { name: 'Unassign assignment' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Undo last schedule change' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Redo schedule change' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Finalize schedule' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Weekly.*Cello lesson/ })).toHaveAttribute('aria-disabled', 'true')
  })

  it('sends unassign unlock undo and redo with canonical versions and atomically replaces cache envelopes', async () => {
    const calls: Array<{ path: string; body: unknown }> = []
    let version = 1
    const handlers = [
      '/api/scheduler/assignments/a-1/unassign',
      '/api/scheduler/assignments/locked-1/unlock',
      '/api/scheduler/draft/undo',
      '/api/scheduler/draft/redo',
    ].map((path) => http.post(path, async ({ request }) => {
      calls.push({ path: new URL(request.url).pathname, body: await request.json() })
      version += 1
      return HttpResponse.json(envelope(baseSession, `workspace-v${version}`))
    }))
    server.use(...handlers)
    const { client } = renderPage()

    let editor = await openAssignment()
    await userEvent.click(within(editor).getByRole('button', { name: 'Unassign assignment' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm unassign' }))
    await waitFor(() => expect(screen.getByText('workspace-v2')).toBeVisible())

    await userEvent.click(screen.getByRole('button', { name: /Locked.*Committed weekly/ }))
    editor = screen.getByRole('region', { name: 'Selected assignment' })
    await userEvent.click(within(editor).getByRole('button', { name: 'Unlock assignment' }))
    await waitFor(() => expect(screen.getByText('workspace-v3')).toBeVisible())

    await userEvent.click(screen.getByRole('button', { name: 'Undo last schedule change' }))
    await waitFor(() => expect(screen.getByText('workspace-v4')).toBeVisible())
    await userEvent.click(screen.getByRole('button', { name: 'Redo schedule change' }))
    await waitFor(() => expect(screen.getByText('workspace-v5')).toBeVisible())

    expect(calls).toEqual([
      { path: '/api/scheduler/assignments/a-1/unassign', body: { expected_version: 'workspace-v1' } },
      { path: '/api/scheduler/assignments/locked-1/unlock', body: { expected_version: 'workspace-v2' } },
      { path: '/api/scheduler/draft/undo', body: { expected_version: 'workspace-v3' } },
      { path: '/api/scheduler/draft/redo', body: { expected_version: 'workspace-v4' } },
    ])
    expect(client.getQueryData(['scheduler-session'])).toEqual(envelope(baseSession, 'workspace-v5'))
  })

  it('rebinds the editor to the canonical issue returned by unassign', async () => {
    const returnedIssue = {
      ...unresolvedIssue,
      id: 'a-1',
      source_request_id: 'a-1',
      message: 'Manually unassigned',
      reason: 'Manually unassigned',
      student_name: 'Cello lesson',
    }
    const unassignedSession: SchedulerSession = {
      ...baseSession,
      assignments: baseSession.assignments.filter((assignment) => assignment.id !== 'a-1'),
      issues: [{ reason_code: 'unknown', label: 'Unknown', count: 1, items: [returnedIssue] }],
      metrics: { assigned: baseSession.metrics.assigned - 1, unresolved: 1, source_gaps: 0 },
      draft: draftState({ dirty: true, can_undo: true, can_redo: false }),
    }
    server.use(http.post(
      '/api/scheduler/assignments/a-1/unassign',
      () => HttpResponse.json(envelope(unassignedSession, 'workspace-v2')),
    ))
    renderPage()
    const editor = await openAssignment()

    await userEvent.click(within(editor).getByRole('button', { name: 'Unassign assignment' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm unassign' }))

    await waitFor(() => expect(screen.getByText('workspace-v2')).toBeVisible())
    expect(screen.getByRole('button', { name: /Manually unassigned/ })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Resolve Issue')
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Cello lesson')
  })

  it('keeps unexpected server failures persistent with their operation id', async () => {
    server.use(http.post('/api/scheduler/assignments/a-1/move', () => HttpResponse.json({
      data: null, workspace_version: 'workspace-v1', warnings: [],
      error: { code: 'COMMAND_FAILED', message: 'The scheduler command failed', operation_id: 'op-500' },
    }, { status: 500 })))
    allowMoveValidation()
    renderPage()
    const editor = await fillMove()

    await validateAndCommitMove(editor)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The scheduler command failed')
    expect(alert).toHaveTextContent('Operation op-500')
    expect(screen.getByRole('button', { name: /Cello lesson/ })).toHaveAttribute('data-room', 'R104')
  })

  it('maps a drop coordinate to a presentation target while preserving duration', () => {
    expect(mapDropToMoveTarget({
      assignment: baseSession.assignments[0],
      activeDay: 4,
      bounds: { left: 100, top: 50, width: 600, height: 168 },
      pointer: { x: 100 + 74 + (600 - 74) / 2, y: 50 + 30 + ((168 - 30) / 2) * 1.5 },
      rooms: baseSession.rooms,
      timeBounds: { start: 480, end: 1200 },
    })).toEqual({ room: 'R107B', day: 4, start: '14:00', end: '15:00' })
  })

  it('maps an unresolved issue drop to the shared proposal without applying scheduling rules', () => {
    expect(mapIssueDropToTarget({
      activeDay: 4,
      bounds: { left: 100, top: 50, width: 600, height: 168 },
      durationMinutes: 90,
      pointer: { x: 100 + 74 + (600 - 74) / 2, y: 50 + 30 + ((168 - 30) / 2) * 1.5 },
      rooms: baseSession.rooms,
      timeBounds: { start: 480, end: 1200 },
    })).toEqual({ room: 'R107B', day: 4, start: '14:00', end: '15:30' })
  })

  it('populates the issue editor proposal when an issue is dragged onto the grid', async () => {
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope(sessionWithIssue()))),
      http.post('/api/scheduler/issues/issue-source-1/validate-assignment', () => HttpResponse.json({
        data: { success: true, message: null, start_norm: '14:00', end_norm: '15:00', specific_date: null, warnings: [] },
        workspace_version: 'workspace-v1', warnings: [], error: null,
      })),
    )
    renderPage()
    const issue = await screen.findByRole('button', { name: /No feasible room/ })
    const canvas = screen.getByTestId('schedule-grid-canvas')
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      bottom: 218, height: 168, left: 100, right: 700, top: 50, width: 600, x: 100, y: 50, toJSON: () => ({}),
    })
    const dataTransfer = { effectAllowed: 'none', setData: vi.fn() }

    fireEvent.dragStart(issue, { dataTransfer })
    fireEvent(canvas, new MouseEvent('drop', {
      bubbles: true,
      clientX: 100 + 74 + (600 - 74) * (5 / 13),
      clientY: 50 + 30 + ((168 - 30) / 2) * 1.5,
    }))

    const editor = screen.getByRole('region', { name: 'Selected assignment' })
    await openIssueFields(editor)
    expect(within(editor).getByLabelText('Room')).toHaveValue('R107B')
    expect(within(editor).getByLabelText('Day')).toHaveValue('1')
    expect(within(editor).getByLabelText('Start time')).toHaveValue('14:00')
    expect(within(editor).getByLabelText('End time')).toHaveValue('15:00')
    expect(dataTransfer.setData).toHaveBeenCalledWith('application/x-scheduler-issue', 'issue-source-1')
  })

  it('lets studio day edits reach the Python validator instead of using a React gate', async () => {
    let validationBody: MoveTarget | null = null
    const validateSpy = vi.fn(async ({ request }: { request: Request }) => {
      validationBody = await request.json() as MoveTarget
      return HttpResponse.json({
        data: { success: false, message: `Studio date policy rejected day ${validationBody?.day}.`, start_norm: null, end_norm: null, specific_date: null, warnings: [] },
        workspace_version: 'workspace-v2', warnings: [], error: null,
      })
    })
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope(sessionWithStudioIssue()))),
      http.post('/api/scheduler/issues/issue-studio-overnight/validate-assignment', validateSpy),
    )
    renderPage()
    const issue = await screen.findByRole('button', { name: /No feasible room/ })
    fireEvent.click(issue)
    let editor = screen.getByRole('region', { name: 'Selected assignment' })
    await openIssueFields(editor)
    expect(within(editor).getByLabelText('Day')).toBeEnabled()
    expect(within(editor).getByLabelText('Day')).toHaveValue('3')

    const canvas = screen.getByTestId('schedule-grid-canvas')
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      bottom: 218, height: 168, left: 100, right: 700, top: 50, width: 600, x: 100, y: 50, toJSON: () => ({}),
    })
    const dataTransfer = { effectAllowed: 'none', setData: vi.fn() }
    fireEvent.dragStart(issue, { dataTransfer })
    fireEvent(canvas, new MouseEvent('drop', {
      bubbles: true,
      clientX: 100 + 86 + (600 - 86) / 2,
      clientY: 50 + 44 + 62 + 31,
    }))

    editor = screen.getByRole('region', { name: 'Selected assignment' })
    await openIssueFields(editor)
    expect(within(editor).getByLabelText('Day')).toBeEnabled()
    await userEvent.selectOptions(within(editor).getByLabelText('Day'), '1')
    await userEvent.click(within(editor).getByRole('button', { name: 'Check conflicts' }))
    await waitFor(() => expect(validateSpy).toHaveBeenCalled())
    expect(validationBody).toMatchObject({ day: 1 })
    expect(within(editor).getByRole('alert')).toHaveTextContent('Studio date policy rejected day 1.')
  })

  it('validates and explicitly commits an issue proposal from one canonical response', async () => {
    const validationBodies: unknown[] = []
    const assignBodies: unknown[] = []
    let resolveAssign: ((response: Response) => void) | undefined
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope(sessionWithIssue()))),
      http.post('/api/scheduler/issues/issue-source-1/validate-assignment', async ({ request }) => {
        validationBodies.push(await request.json())
        return HttpResponse.json({
          data: { success: true, message: null, start_norm: '14:00', end_norm: '15:00', specific_date: null, warnings: ['Room Type Mismatch'] },
          workspace_version: 'workspace-v1', warnings: ['Room Type Mismatch'], error: null,
        })
      }),
      http.post('/api/scheduler/issues/issue-source-1/assign', async ({ request }) => {
        assignBodies.push(await request.json())
        return new Promise<Response>((resolve) => { resolveAssign = resolve })
      }),
      http.post('/api/scheduler/draft/undo', () => HttpResponse.json(envelope(sessionWithIssue(), 'workspace-v3'))),
      http.post('/api/scheduler/draft/redo', () => HttpResponse.json(envelope(sessionWithAssignedIssue(), 'workspace-v4'))),
    )
    renderPage()
    const issue = await screen.findByRole('button', { name: /No feasible room/ })

    issue.focus()
    await userEvent.keyboard('{Enter}')
    const editor = screen.getByRole('region', { name: 'Selected assignment' })
    await openIssueFields(editor)
    await userEvent.selectOptions(within(editor).getByLabelText('Room'), 'R107B')
    await userEvent.selectOptions(within(editor).getByLabelText('Day'), '3')
    await userEvent.clear(within(editor).getByLabelText('Start time'))
    await userEvent.type(within(editor).getByLabelText('Start time'), '14:00')
    await userEvent.clear(within(editor).getByLabelText('End time'))
    await userEvent.type(within(editor).getByLabelText('End time'), '15:00')

    expect(within(editor).getByRole('button', { name: 'Place lesson' })).toBeDisabled()
    await userEvent.click(within(editor).getByRole('button', { name: 'Check conflicts' }))

    expect(await within(editor).findByText('Room Type Mismatch')).toBeVisible()
    expect(validationBodies).toEqual([{ room: 'R107B', day: 3, start: '14:00', end: '15:00' }])
    const commit = within(editor).getByRole('button', { name: 'Place lesson' })
    expect(commit).toBeEnabled()
    await userEvent.click(commit)

    expect(screen.getByRole('button', { name: /No feasible room/ })).toBeVisible()
    expect(screen.getByLabelText('Schedule metrics')).toHaveTextContent('1')
    await waitFor(() => expect(resolveAssign).toBeTypeOf('function'))
    expect(assignBodies).toEqual([{
      room: 'R107B', day: 3, start: '14:00', end: '15:00', expected_version: 'workspace-v1',
      teacher_confirmed: false, teacher_confirmation_note: '',
    }])

    resolveAssign?.(HttpResponse.json(envelope(sessionWithAssignedIssue(), 'workspace-v2')))
    await waitFor(() => expect(screen.queryByRole('button', { name: /No feasible room/ })).not.toBeInTheDocument())
    expect(screen.getByText('workspace-v2')).toBeVisible()
    expect(await screen.findByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Student 0001 piano lesson')
    expect(screen.getByLabelText('Schedule metrics')).toHaveTextContent('0')

    await userEvent.click(screen.getByRole('button', { name: 'Undo last schedule change' }))
    await waitFor(() => expect(screen.getByText('workspace-v3')).toBeVisible())
    expect(screen.getByRole('button', { name: /No feasible room/ })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Resolve Issue')

    await userEvent.click(screen.getByRole('button', { name: 'Redo schedule change' }))
    await waitFor(() => expect(screen.getByText('workspace-v4')).toBeVisible())
    expect(screen.queryByRole('button', { name: /No feasible room/ })).not.toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Selected assignment' })).toHaveTextContent('Student 0001 piano lesson')
  })

  it('shows Python validation errors without committing or optimistic success', async () => {
    const assignSpy = vi.fn()
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope(sessionWithIssue()))),
      http.post('/api/scheduler/issues/issue-source-1/validate-assignment', () => HttpResponse.json({
        data: { success: false, message: 'Conflict with Existing lesson', start_norm: null, end_norm: null, specific_date: null, warnings: [] },
        workspace_version: 'workspace-v1', warnings: [], error: null,
      })),
      http.post('/api/scheduler/issues/issue-source-1/assign', assignSpy),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /No feasible room/ }))
    const editor = screen.getByRole('region', { name: 'Selected assignment' })
    await openIssueFields(editor)

    await userEvent.click(within(editor).getByRole('button', { name: 'Check conflicts' }))

    expect(await within(editor).findByRole('alert')).toHaveTextContent('Conflict with Existing lesson')
    expect(within(editor).getByRole('button', { name: 'Place lesson' })).toBeDisabled()
    expect(assignSpy).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /No feasible room/ })).toBeVisible()
  })

  it('preserves an issue proposal on 409 and adopts the fresh canonical issue only after reload', async () => {
    let reads = 0
    const refreshed = {
      ...sessionWithIssue(),
      issues: [{ ...sessionWithIssue().issues[0], items: [{ ...unresolvedIssue, original_start: '11:00', original_end: '12:00' }] }],
    }
    server.use(
      http.get('/api/scheduler/session', () => {
        reads += 1
        return HttpResponse.json(envelope(reads === 1 ? sessionWithIssue() : refreshed, reads === 1 ? 'workspace-v1' : 'workspace-v3'))
      }),
      http.post('/api/scheduler/issues/issue-source-1/validate-assignment', () => HttpResponse.json({
        data: { success: true, message: null, start_norm: '14:00', end_norm: '15:00', specific_date: null, warnings: [] },
        workspace_version: 'workspace-v1', warnings: [], error: null,
      })),
      http.post('/api/scheduler/issues/issue-source-1/assign', () => HttpResponse.json({
        data: null, workspace_version: 'workspace-v3', warnings: [],
        error: { code: 'WORKSPACE_CHANGED', message: 'The workspace changed on disk' },
      }, { status: 409 })),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /No feasible room/ }))
    const editor = screen.getByRole('region', { name: 'Selected assignment' })
    await openIssueFields(editor)
    await userEvent.clear(within(editor).getByLabelText('Start time'))
    await userEvent.type(within(editor).getByLabelText('Start time'), '14:00')
    await userEvent.clear(within(editor).getByLabelText('End time'))
    await userEvent.type(within(editor).getByLabelText('End time'), '15:00')
    await userEvent.click(within(editor).getByRole('button', { name: 'Check conflicts' }))
    await userEvent.click(within(editor).getByRole('button', { name: 'Place lesson' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('workspace changed')
    expect(within(editor).getByLabelText('Start time')).toHaveValue('14:00')
    expect(screen.getByRole('button', { name: /No feasible room/ })).toBeVisible()

    await userEvent.click(screen.getByRole('button', { name: 'Reload workspace' }))

    await waitFor(() => expect(screen.getByText('workspace-v3')).toBeVisible())
    const refreshedEditor = screen.getByRole('region', { name: 'Selected assignment' })
    await openIssueFields(refreshedEditor)
    expect(within(refreshedEditor).getByLabelText('Start time')).toHaveValue('11:00')
    expect(within(refreshedEditor).getByLabelText('End time')).toHaveValue('12:00')
  })

  it('rejects drop coordinates outside the time and room surface', () => {
    const input = {
      activeDay: 1,
      assignment: baseSession.assignments[0],
      bounds: { left: 100, top: 50, width: 600, height: 168 },
      rooms: baseSession.rooms,
      timeBounds: { start: 480, end: 1200 },
    }

    expect(mapDropToMoveTarget({ ...input, pointer: { x: 173, y: 125 } })).toBeNull()
    expect(mapDropToMoveTarget({ ...input, pointer: { x: 400, y: 79 } })).toBeNull()
    expect(mapDropToMoveTarget({ ...input, pointer: { x: 701, y: 125 } })).toBeNull()
    expect(mapDropToMoveTarget({ ...input, pointer: { x: 400, y: 219 } })).toBeNull()
  })

  it('blocks duplicate submissions while one canonical command is pending', async () => {
    let resolveMove: ((response: Response) => void) | undefined
    const requestSpy = vi.fn()
    server.use(http.post('/api/scheduler/assignments/a-1/move', () => {
      requestSpy()
      return new Promise<Response>((resolve) => { resolveMove = resolve })
    }))
    allowMoveValidation()
    renderPage()
    const editor = await fillMove()
    fireEvent.click(within(editor).getByRole('button', { name: 'Validate move' }))
    const move = within(editor).getByRole('button', { name: 'Move assignment' })
    await waitFor(() => expect(move).toBeEnabled())

    fireEvent.click(move)
    fireEvent.click(move)

    await waitFor(() => expect(requestSpy).toHaveBeenCalledTimes(1))
    resolveMove?.(HttpResponse.json(envelope(movedSession(), 'workspace-v2')))
  })

  it('shows a Python validation rejection without moving the canonical block', async () => {
    let requestBody: unknown
    const moveSpy = vi.fn()
    server.use(
      http.post('/api/scheduler/assignments/a-1/validate-move', async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json({
          data: { success: false, message: 'Move rejected by scheduler', start_norm: null, end_norm: null, specific_date: null, warnings: [] },
          workspace_version: 'workspace-v1', warnings: [], error: null,
        })
      }),
      http.post('/api/scheduler/assignments/a-1/move', moveSpy),
    )
    renderPage()
    const editor = await openAssignment()
    fireEvent.change(within(editor).getByLabelText('Start time'), { target: { value: '09:30' } })
    fireEvent.change(within(editor).getByLabelText('End time'), { target: { value: '10:30' } })
    await userEvent.click(within(editor).getByRole('button', { name: 'Validate move' }))
    expect(await within(editor).findByRole('alert')).toHaveTextContent('Move rejected by scheduler')
    expect(requestBody).toMatchObject({ room: expect.any(String), day: 1, start: expect.any(String), end: expect.any(String) })
    expect(moveSpy).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /Cello lesson/ })).toHaveAttribute('data-room', 'R104')
  })

  it('clears an outside drag without posting or moving the canonical block', async () => {
    const requestSpy = vi.fn()
    server.use(http.post('/api/scheduler/assignments/a-1/move', requestSpy))
    renderPage()
    const assignment = await screen.findByRole('button', { name: /Cello lesson/ })
    vi.spyOn(screen.getByTestId('schedule-grid-canvas'), 'getBoundingClientRect').mockReturnValue({
      bottom: 218, height: 168, left: 100, right: 700, top: 50, width: 600, x: 100, y: 50, toJSON: () => ({}),
    })
    vi.spyOn(assignment, 'getBoundingClientRect').mockReturnValue({
      bottom: 64, height: 54, left: 20, right: 100, top: 10, width: 80, x: 20, y: 10, toJSON: () => ({}),
    })

    fireEvent.pointerDown(assignment, { button: 0, buttons: 1, clientX: 30, clientY: 20, isPrimary: true, pointerId: 2 })
    fireEvent.pointerMove(document, { buttons: 1, clientX: 50, clientY: 30, isPrimary: true, pointerId: 2 })
    expect(await screen.findByTestId('assignment-drag-preview')).toBeVisible()
    fireEvent.pointerUp(document, { button: 0, clientX: 50, clientY: 30, isPrimary: true, pointerId: 2 })

    await waitFor(() => expect(screen.queryByTestId('assignment-drag-preview')).not.toBeInTheDocument())
    expect(requestSpy).not.toHaveBeenCalled()
    expect(assignment).toHaveAttribute('data-room', 'R104')
  })
})
