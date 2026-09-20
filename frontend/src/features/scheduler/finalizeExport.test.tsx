import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { readFileSync } from 'node:fs'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { ApiEnvelope } from '../../api/client'
import { ImportPage } from './pages/ImportPage'
import { ExportPage } from './pages/ExportPage'
import { ResolvePage } from './pages/ResolvePage'
import { schedulerSessionKey, type SchedulerSession } from './api'
import { draftState } from '../../test/draftState'

const schedulerCss = readFileSync('src/features/scheduler/schedulerWorkspace.module.css', 'utf8')

const resolvingSession: SchedulerSession = {
  active_stage: 'resolve',
  assignments: [{
    id: 'weekly-1', title: 'Cello lesson', type: 'weekly_lesson', resourceId: 'R101',
    daysOfWeek: [1], startTime: '09:00', endTime: '10:00',
    extendedProps: { Instructor: 'Instructor 0002', Student: 'Student 0001' },
  }],
  issues: [{
    reason_code: 'room_conflict', label: 'Room conflict', count: 2,
    items: [
      { id: 'issue-1', source_request_id: 'issue-1', reason_code: 'room_conflict', message: 'R101 is double booked', reason: 'R101 is double booked', type: 'weekly_lesson', duration_minutes: 60, assignment_id: 'weekly-1', payload: {} },
      { id: 'issue-2', source_request_id: 'issue-2', reason_code: 'room_conflict', message: 'Instructor overlap', reason: 'Instructor overlap', type: 'weekly_lesson', duration_minutes: 60, assignment_id: 'weekly-1', payload: {} },
    ],
  }],
  rooms: [{ id: 'R101' }],
  instructors: ['Instructor 0002'],
  draft: draftState({ dirty: true, can_undo: true, can_redo: false }),
  metrics: { assigned: 1, unresolved: 2, source_gaps: 0 },
  warnings: [],
}

const finalizableSession: SchedulerSession = {
  ...resolvingSession,
  metrics: { ...resolvingSession.metrics, unresolved: 0 },
}

const exportedSession: SchedulerSession = {
  ...resolvingSession,
  active_stage: 'export',
  issues: [],
  draft: draftState({ dirty: false, can_undo: false, can_redo: false }),
  metrics: { assigned: 1, unresolved: 0, source_gaps: 0 },
}

const dashboard = {
  counts: { bookings: 1, instructors: 1, rooms: 1, students: 1 },
  health: {}, workflow_state: {},
  session: { active_step: 'export', draft_dirty: false, round_committed: true },
}

function envelope<T>(data: T, version = 'workspace-v1', warnings: string[] = []): ApiEnvelope<T> {
  return { data, workspace_version: version, warnings, error: null }
}

let currentSession = finalizableSession
let currentVersion = 'workspace-v1'
let currentDashboard = dashboard

const server = setupServer(
  http.get('/api/scheduler/session', () => HttpResponse.json(envelope(currentSession, currentVersion))),
  http.get('/api/dashboard', () => HttpResponse.json(envelope(currentDashboard, currentVersion))),
  http.get('/api/scheduler/resolution/advice', () => HttpResponse.json(envelope({
    summary: { total: 0, cases: 0, place_now: 0, same_day_alternative: 0, blocked: 0, waiting: 0 },
    cases: [], piano_leverage: [],
  }, currentVersion))),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  currentSession = finalizableSession
  currentVersion = 'workspace-v1'
  currentDashboard = dashboard
  delete (window as Window & { piDesktop?: unknown }).piDesktop
})
afterAll(() => server.close())

function renderApp(entry: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } },
  })
  const router = createMemoryRouter([
    { path: '/schedule/resolve', element: <ResolvePage /> },
    { path: '/schedule/export', element: <ExportPage /> },
    { path: '/schedule/import', element: <ImportPage /> },
  ], { initialEntries: [entry] })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return { client, router }
}

async function openFinalize() {
  const trigger = await screen.findByRole('button', { name: 'Finalize schedule' })
  await userEvent.click(trigger)
  return { dialog: await screen.findByRole('dialog'), trigger }
}

function exportResult(version = 'workspace-v1') {
  return envelope({ artifacts: [{
    artifact_id: 'artifact-master',
    filename: 'Master_Schedule.xlsx',
    mime_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  }] }, version)
}

describe('finalize schedule', () => {
  it('allows finalize while unresolved lessons remain and explains export behavior', async () => {
    currentSession = resolvingSession
    renderApp('/schedule/resolve?workspace=schedule')
    const { dialog } = await openFinalize()
    expect(dialog).toHaveTextContent('2 lessons remain unresolved')
    expect(dialog).toHaveTextContent('include those lessons in export as unassigned rows')
  })

  it('traps focus and restores it when cancel closes the irreversible dialog', async () => {
    renderApp('/schedule/resolve?workspace=schedule')
    const { dialog, trigger } = await openFinalize()

    expect(dialog).toHaveTextContent('commits the current scheduling round')
    expect(dialog).toContainElement(document.activeElement as HTMLElement)
    await userEvent.tab()
    await userEvent.tab()
    expect(dialog).toContainElement(document.activeElement as HTMLElement)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('confirms with the version captured on open and blocks duplicate submission', async () => {
    let requestCount = 0
    let body: unknown
    let finish: ((response: Response) => void) | undefined
    server.use(http.post('/api/scheduler/finalize', async ({ request }) => {
      requestCount += 1
      body = await request.json()
      return new Promise<Response>((resolve) => { finish = resolve })
    }))
    const { client } = renderApp('/schedule/resolve?workspace=schedule')
    const { dialog } = await openFinalize()
    client.setQueryData(schedulerSessionKey, envelope(finalizableSession, 'workspace-v2'))

    const confirm = within(dialog).getByRole('button', { name: 'Confirm finalize' })
    fireEvent.click(confirm)
    fireEvent.click(confirm)

    await waitFor(() => expect(requestCount).toBe(1))
    expect(body).toEqual({ expected_version: 'workspace-v1' })
    expect(confirm).toBeDisabled()
    finish?.(HttpResponse.json(envelope(exportedSession, 'workspace-v3')))
  })

  it('preserves the draft and focuses Needs resolution when two conflicts block finalize', async () => {
    server.use(http.post('/api/scheduler/finalize', () => HttpResponse.json({
      data: null, workspace_version: 'workspace-v1', warnings: [],
      error: {
        code: 'SCHEDULER_FINALIZE_CONFLICT',
        message: 'Schedule has conflicts that must be resolved before finalizing',
        details: { conflicts: [{ conflict: { reason: 'room' } }, { conflict: { reason: 'instructor' } }], warnings: ['Resolve overlaps first'] },
      },
    }, { status: 400 })))
    const { client } = renderApp('/schedule/resolve?workspace=schedule')
    const { dialog } = await openFinalize()
    const before = client.getQueryData(schedulerSessionKey)

    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm finalize' }))

    expect(await screen.findByText('2 conflicts block finalization')).toBeVisible()
    expect(screen.getByText('Schedule has conflicts that must be resolved before finalizing')).toBeVisible()
    expect(screen.getByText('room')).toBeVisible()
    expect(screen.getByText('instructor')).toBeVisible()
    expect(screen.getByText('Resolve overlaps first')).toBeVisible()
    expect(screen.getByRole('region', { name: 'Needs resolution' })).toHaveFocus()
    expect(screen.getByText('Autosave active')).toBeVisible()
    expect(client.getQueryData(schedulerSessionKey)).toEqual(before)
  })

  it('atomically caches success, invalidates dashboard, persists warnings, and navigates to Export once', async () => {
    let dashboardReads = 0
    const finalized = envelope(exportedSession, 'workspace-v2', ['Studio export excludes an incomplete source row.'])
    server.use(
      http.post('/api/scheduler/finalize', () => HttpResponse.json(finalized)),
      http.get('/api/dashboard', () => { dashboardReads += 1; return HttpResponse.json(envelope(dashboard, 'workspace-v2')) }),
    )
    const { client, router } = renderApp('/schedule/resolve?workspace=schedule')
    client.setQueryData(['dashboard'], envelope(currentDashboard, 'workspace-v1'))
    const { dialog } = await openFinalize()

    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm finalize' }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/schedule/export'))
    expect(client.getQueryData(schedulerSessionKey)).toEqual(finalized)
    expect(await screen.findByText('Studio export excludes an incomplete source row.')).toBeVisible()
    expect(dashboardReads).toBe(1)
  })

  it('keeps the workspace mounted through a failed 409 reload and clears the error only after success', async () => {
    let reads = 0
    server.use(
      http.get('/api/scheduler/session', () => {
        reads += 1
        if (reads === 1) return HttpResponse.json(envelope(finalizableSession))
        if (reads === 2) return HttpResponse.json({
          data: null, workspace_version: null, warnings: [],
          error: { code: 'READ_FAILED', message: 'Workspace reload failed' },
        }, { status: 500 })
        return HttpResponse.json(envelope(finalizableSession, 'workspace-v3'))
      }),
      http.post('/api/scheduler/finalize', () => HttpResponse.json({
        data: null, workspace_version: 'workspace-v2', warnings: [],
        error: { code: 'WORKSPACE_CONFLICT', message: 'The workspace changed on disk' },
      }, { status: 409 })),
    )
    renderApp('/schedule/resolve?workspace=schedule')
    const { dialog } = await openFinalize()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm finalize' }))

    await userEvent.click(await screen.findByRole('button', { name: 'Reload workspace' }))
    expect(await screen.findByText('Reload failed: Workspace reload failed')).toBeVisible()
    expect(screen.getByText('Autosave active')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Reload workspace' })).toBeVisible()

    await userEvent.click(screen.getByRole('button', { name: 'Reload workspace' }))
    await waitFor(() => expect(screen.queryByText('The workspace changed on disk')).not.toBeInTheDocument())
    expect(screen.getByText('workspace-v3')).toBeVisible()
  })

  it('keeps a 500 failure and its operation id visible', async () => {
    server.use(http.post('/api/scheduler/finalize', () => HttpResponse.json({
      data: null, workspace_version: 'workspace-v1', warnings: [],
      error: { code: 'SCHEDULER_FINALIZE_FAILED', message: 'Commit could not be written', operation_id: 'op-finalize-500' },
    }, { status: 500 })))
    renderApp('/schedule/resolve?workspace=schedule')
    const { dialog } = await openFinalize()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm finalize' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Commit could not be written')
    expect(screen.getByText('Operation op-finalize-500')).toBeVisible()
  })

  it('keeps a pending finalize modal and blocks every background schedule mutation', async () => {
    let finishFinalize: ((response: Response) => void) | undefined
    let backgroundPosts = 0
    server.use(
      http.post('/api/scheduler/finalize', () => new Promise<Response>((resolve) => { finishFinalize = resolve })),
      http.post('/api/scheduler/assignments/weekly-1/unassign', () => { backgroundPosts += 1; return HttpResponse.json(envelope(resolvingSession)) }),
      http.post('/api/scheduler/draft/undo', () => { backgroundPosts += 1; return HttpResponse.json(envelope(resolvingSession)) }),
    )
    renderApp('/schedule/resolve?workspace=schedule')
    await userEvent.click(await screen.findByRole('button', { name: /Cello lesson/ }))
    const { dialog } = await openFinalize()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm finalize' }))
    expect(await within(dialog).findByRole('button', { name: 'Finalizing schedule' })).toBeDisabled()

    await userEvent.keyboard('{Escape}')
    expect(screen.getByRole('dialog')).toBeVisible()
    const overlay = document.querySelector('[class*="dialogOverlay"]')
    expect(overlay).not.toBeNull()
    fireEvent.pointerDown(overlay!)
    fireEvent.pointerUp(overlay!)
    fireEvent.click(overlay!)
    expect(screen.getByRole('dialog')).toBeVisible()

    const undo = screen.getByRole('button', { name: 'Undo last schedule change', hidden: true })
    const assignment = screen.getByRole('button', { name: /Cello lesson/, hidden: true })
    const unassign = screen.getByRole('button', { name: 'Unassign assignment', hidden: true })
    expect(undo).toBeDisabled()
    expect(assignment).toHaveAttribute('aria-disabled', 'true')
    expect(unassign).toBeDisabled()
    fireEvent.click(undo)
    fireEvent.click(unassign)
    expect(backgroundPosts).toBe(0)

    finishFinalize?.(HttpResponse.json(envelope(exportedSession, 'workspace-v2')))
  })

  it('blocks finalize while a schedule command is pending', async () => {
    let finishCommand: ((response: Response) => void) | undefined
    const finalize = vi.fn()
    server.use(
      http.post('/api/scheduler/assignments/weekly-1/unassign', () => new Promise<Response>((resolve) => { finishCommand = resolve })),
      http.post('/api/scheduler/finalize', finalize),
    )
    renderApp('/schedule/resolve?workspace=schedule')
    await userEvent.click(await screen.findByRole('button', { name: /Cello lesson/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Unassign assignment' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm unassign' }))

    const finalizeButton = screen.getByRole('button', { name: 'Finalize schedule' })
    await waitFor(() => expect(finalizeButton).toBeDisabled())
    fireEvent.click(finalizeButton)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(finalize).not.toHaveBeenCalled()
    finishCommand?.(HttpResponse.json(envelope(resolvingSession, 'workspace-v2')))
  })

  it('blocks finalize after a schedule command reports a version conflict', async () => {
    const finalize = vi.fn()
    server.use(
      http.post('/api/scheduler/assignments/weekly-1/unassign', () => HttpResponse.json({
        data: null, workspace_version: 'workspace-v2', warnings: [],
        error: { code: 'WORKSPACE_CONFLICT', message: 'The workspace changed on disk' },
      }, { status: 409 })),
      http.post('/api/scheduler/finalize', finalize),
    )
    renderApp('/schedule/resolve?workspace=schedule')
    await userEvent.click(await screen.findByRole('button', { name: /Cello lesson/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Unassign assignment' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm unassign' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The workspace changed on disk')
    const finalizeButton = screen.getByRole('button', { name: 'Finalize schedule' })
    expect(finalizeButton).toBeDisabled()
    fireEvent.click(finalizeButton)
    expect(finalize).not.toHaveBeenCalled()
  })

  it('blocks finalize when a cached scheduler read can no longer be refreshed', async () => {
    const finalize = vi.fn()
    const { client } = renderApp('/schedule/resolve?workspace=schedule')
    expect(await screen.findByRole('button', { name: 'Finalize schedule' })).toBeEnabled()
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json({
        data: null, workspace_version: null, warnings: [],
        error: { code: 'READ_FAILED', message: 'Workspace refresh failed' },
      }, { status: 500 })),
      http.post('/api/scheduler/finalize', finalize),
    )

    await client.refetchQueries({ queryKey: schedulerSessionKey })

    const finalizeButton = screen.getByRole('button', { name: 'Finalize schedule' })
    await waitFor(() => expect(finalizeButton).toBeDisabled())
    fireEvent.click(finalizeButton)
    expect(finalize).not.toHaveBeenCalled()
  })

  it('clears a blocked finalize banner after a successful command advances the canonical version', async () => {
    server.use(
      http.post('/api/scheduler/finalize', () => HttpResponse.json({
        data: null, workspace_version: 'workspace-v1', warnings: [],
        error: {
          code: 'SCHEDULER_FINALIZE_CONFLICT', message: 'Resolve the remaining conflict',
          details: { conflicts: [{ reason: 'room' }] },
        },
      }, { status: 400 })),
      http.post('/api/scheduler/assignments/weekly-1/unassign', () => HttpResponse.json(envelope(resolvingSession, 'workspace-v2'))),
    )
    renderApp('/schedule/resolve?workspace=schedule')
    const { dialog } = await openFinalize()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm finalize' }))
    expect(await screen.findByText('Resolve the remaining conflict')).toBeVisible()

    await userEvent.click(screen.getByRole('button', { name: /Cello lesson/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Unassign assignment' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm unassign' }))

    await waitFor(() => expect(screen.getByText('workspace-v2')).toBeVisible())
    expect(screen.queryByText('Resolve the remaining conflict')).not.toBeInTheDocument()
  })
})

describe('export ledger', () => {
  it('loads session and dashboard together and renders a canonical schedule table', async () => {
    currentSession = exportedSession
    renderApp('/schedule/export')

    expect(await screen.findByText('Canonical Schedule Preview')).toBeVisible()
    expect(screen.getByRole('table', { name: 'Canonical schedule preview' })).toHaveTextContent('Cello lesson')
    expect(screen.getByText('export')).toBeVisible()
    expect(screen.getByText('workspace-v1')).toBeVisible()
    expect(screen.getByText('Committed')).toBeVisible()
    expect(screen.getByText('No draft changes')).toBeVisible()
  })

  it('builds exports once without polling and exposes only authenticated opaque-id links', async () => {
    currentSession = exportedSession
    let builds = 0
    let operationReads = 0
    server.use(
      http.post('/api/scheduler/exports/build', () => { builds += 1; return HttpResponse.json(exportResult()) }),
      http.get('/api/operations/:id', () => { operationReads += 1; return HttpResponse.json({}) }),
    )
    renderApp('/schedule/export')

    await userEvent.click(await screen.findByRole('button', { name: 'Build export files' }))

    const link = await screen.findByRole('link', { name: 'Master Schedule' })
    expect(link).toHaveAttribute('href', '/api/scheduler/exports/artifact-master')
    expect(link).toHaveAttribute('download', 'Master_Schedule.xlsx')
    expect(screen.getByText('Master_Schedule.xlsx')).toBeVisible()
    expect(screen.getByText('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')).toBeVisible()
    expect(builds).toBe(1)
    expect(operationReads).toBe(0)
    expect(document.body).not.toHaveTextContent('/Users/')
  })

  it('blocks Build and Round 2 until scheduler and dashboard versions agree', async () => {
    currentSession = exportedSession
    let builds = 0
    let roundStarts = 0
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope(exportedSession, 'workspace-v1'))),
      http.get('/api/dashboard', () => HttpResponse.json(envelope(dashboard, 'workspace-v2'))),
      http.post('/api/scheduler/exports/build', () => { builds += 1; return HttpResponse.json(exportResult()) }),
      http.post('/api/scheduler/rounds/start', () => { roundStarts += 1; return HttpResponse.json(envelope({ locked_assignments: [] })) }),
    )
    renderApp('/schedule/export')

    const buildButton = await screen.findByRole('button', { name: 'Build export files' })
    const roundButton = screen.getByRole('button', { name: 'Start Round 2' })
    expect(buildButton).toBeDisabled()
    expect(roundButton).toBeDisabled()
    expect(screen.getByRole('status', { name: 'Export is not ready' })).toHaveTextContent('versions do not match')
    fireEvent.click(buildButton)
    fireEvent.click(roundButton)
    expect(builds).toBe(0)
    expect(roundStarts).toBe(0)
  })

  it('rejects artifacts built from a different version and refetches both canonical reads', async () => {
    currentSession = exportedSession
    let sessionReads = 0
    let dashboardReads = 0
    server.use(
      http.get('/api/scheduler/session', () => { sessionReads += 1; return HttpResponse.json(envelope(exportedSession, 'workspace-v1')) }),
      http.get('/api/dashboard', () => { dashboardReads += 1; return HttpResponse.json(envelope(dashboard, 'workspace-v1')) }),
      http.post('/api/scheduler/exports/build', () => HttpResponse.json(exportResult('workspace-v2'))),
    )
    renderApp('/schedule/export')

    await userEvent.click(await screen.findByRole('button', { name: 'Build export files' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Export build version changed')
    expect(screen.queryByRole('link', { name: 'Master Schedule' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry export workspace' })).toBeVisible()
    await waitFor(() => expect(sessionReads).toBeGreaterThan(1))
    expect(dashboardReads).toBeGreaterThan(1)
  })

  it('rejects a matching build response when canonical reads advance during the request', async () => {
    currentSession = exportedSession
    let version = 'workspace-v1'
    let finishBuild: ((response: Response) => void) | undefined
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope(exportedSession, version))),
      http.get('/api/dashboard', () => HttpResponse.json(envelope(dashboard, version))),
      http.post('/api/scheduler/exports/build', () => new Promise<Response>((resolve) => { finishBuild = resolve })),
    )
    const { client } = renderApp('/schedule/export')
    fireEvent.click(await screen.findByRole('button', { name: 'Build export files' }))
    await waitFor(() => expect(finishBuild).toBeTypeOf('function'))

    version = 'workspace-v2'
    await Promise.all([
      client.refetchQueries({ queryKey: schedulerSessionKey }),
      client.refetchQueries({ queryKey: ['dashboard'] }),
    ])
    finishBuild?.(HttpResponse.json(exportResult('workspace-v1')))

    expect(await screen.findByRole('alert')).toHaveTextContent('Export build version changed')
    expect(screen.queryByRole('link', { name: 'Master Schedule' })).not.toBeInTheDocument()
  })

  it('invalidates generated artifacts only after both canonical reads advance coherently', async () => {
    currentSession = exportedSession
    let version = 'workspace-v1'
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope(exportedSession, version))),
      http.get('/api/dashboard', () => HttpResponse.json(envelope(dashboard, version))),
      http.post('/api/scheduler/exports/build', () => HttpResponse.json(exportResult('workspace-v1'))),
    )
    const { client } = renderApp('/schedule/export')
    await userEvent.click(await screen.findByRole('button', { name: 'Build export files' }))
    expect(await screen.findByRole('link', { name: 'Master Schedule' })).toBeVisible()

    version = 'workspace-v2'
    await Promise.all([
      client.refetchQueries({ queryKey: schedulerSessionKey }),
      client.refetchQueries({ queryKey: ['dashboard'] }),
    ])

    await waitFor(() => expect(screen.queryByRole('link', { name: 'Master Schedule' })).not.toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent('Generated artifacts are stale')
    expect(screen.getByRole('button', { name: 'Build export files' })).toBeEnabled()
  })

  it.each(['scheduler', 'dashboard'])('invalidates v1 artifacts as soon as the %s read alone advances to v2', async (source) => {
    currentSession = exportedSession
    let sessionVersion = 'workspace-v1'
    let dashboardVersion = 'workspace-v1'
    server.use(
      http.get('/api/scheduler/session', () => HttpResponse.json(envelope(exportedSession, sessionVersion))),
      http.get('/api/dashboard', () => HttpResponse.json(envelope(dashboard, dashboardVersion))),
      http.post('/api/scheduler/exports/build', () => HttpResponse.json(exportResult('workspace-v1'))),
    )
    const { client } = renderApp('/schedule/export')
    await userEvent.click(await screen.findByRole('button', { name: 'Build export files' }))
    expect(await screen.findByRole('link', { name: 'Master Schedule' })).toBeVisible()

    if (source === 'scheduler') sessionVersion = 'workspace-v2'
    else dashboardVersion = 'workspace-v2'
    await client.refetchQueries({ queryKey: source === 'scheduler' ? schedulerSessionKey : ['dashboard'] })

    await waitFor(() => expect(screen.queryByRole('link', { name: 'Master Schedule' })).not.toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent('Generated artifacts are stale')
  })

  it.each([
    ['the scheduler is still in Resolve', resolvingSession, dashboard, 'Return to Resolve'],
    ['the round is not committed', exportedSession, { ...dashboard, session: { ...dashboard.session, round_committed: false } }, 'Return to Resolve'],
    ['the canonical draft is dirty', { ...exportedSession, draft: { ...exportedSession.draft, dirty: true } }, dashboard, 'Return to Resolve'],
  ])('blocks export when %s and explains the recovery path', async (_case, session, dashboardState, recoveryLabel) => {
    currentSession = session
    currentDashboard = dashboardState
    const build = vi.fn()
    server.use(http.post('/api/scheduler/exports/build', build))
    renderApp('/schedule/export')

    const button = await screen.findByRole('button', { name: 'Build export files' })
    expect(button).toBeDisabled()
    expect(screen.getByRole('status', { name: 'Export is not ready' })).toBeVisible()
    expect(screen.getByRole('link', { name: recoveryLabel })).toHaveAttribute('href', '/schedule/resolve')
    fireEvent.click(button)
    expect(build).not.toHaveBeenCalled()
  })

  it.each(['scheduler', 'dashboard'])('blocks export and Round 2 when the cached %s read fails, then recovers', async (source) => {
    currentSession = exportedSession
    let failRefresh = true
    let roundStarts = 0
    server.use(
      http.post('/api/scheduler/exports/build', () => HttpResponse.json(exportResult())),
      http.post('/api/scheduler/rounds/start', () => {
        roundStarts += 1
        return HttpResponse.json(envelope({ locked_assignments: exportedSession.assignments }, 'workspace-v2'))
      }),
    )
    const { client } = renderApp('/schedule/export')
    await userEvent.click(await screen.findByRole('button', { name: 'Build export files' }))
    expect(await screen.findByRole('link', { name: 'Master Schedule' })).toBeVisible()

    const queryKey = source === 'scheduler' ? schedulerSessionKey : ['dashboard']
    const refreshHandler = source === 'scheduler'
      ? http.get('/api/scheduler/session', () => failRefresh
        ? HttpResponse.json({
          data: null, workspace_version: null, warnings: [],
          error: { code: 'READ_FAILED', message: 'Scheduler refresh failed' },
        }, { status: 500 })
        : HttpResponse.json(envelope(exportedSession)))
      : http.get('/api/dashboard', () => failRefresh
        ? HttpResponse.json({
          data: null, workspace_version: null, warnings: [],
          error: { code: 'DASHBOARD_FAILED', message: 'Dashboard refresh failed' },
        }, { status: 500 })
        : HttpResponse.json(envelope(dashboard)))
    server.use(refreshHandler)

    await client.refetchQueries({ queryKey })

    const buildButton = screen.getByRole('button', { name: 'Build export files' })
    const roundButton = screen.getByRole('button', { name: 'Start Round 2' })
    await waitFor(() => expect(buildButton).toBeDisabled())
    expect(roundButton).toBeDisabled()
    expect(screen.getByRole('status', { name: 'Export is not ready' })).toHaveTextContent('Refresh the export workspace')
    expect(screen.getByRole('link', { name: 'Master Schedule' })).toBeVisible()
    expect(screen.getByRole('table', { name: 'Canonical schedule preview' })).toHaveTextContent('Cello lesson')
    fireEvent.click(roundButton)
    expect(roundStarts).toBe(0)

    failRefresh = false
    await userEvent.click(screen.getByRole('button', { name: 'Retry export workspace' }))

    await waitFor(() => expect(roundButton).toBeEnabled())
    expect(buildButton).toBeEnabled()
    expect(screen.queryByRole('status', { name: 'Export is not ready' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Master Schedule' })).toBeVisible()
  })

  it('bounds only the canonical preview table while preserving its sticky header', async () => {
    currentSession = {
      ...exportedSession,
      assignments: Array.from({ length: 92 }, (_, index) => ({
        ...exportedSession.assignments[0], id: `weekly-${index}`, title: `Lesson ${index + 1}`,
      })),
    }
    server.use(http.post('/api/scheduler/exports/build', () => HttpResponse.json(exportResult())))
    renderApp('/schedule/export')

    const canonicalFrame = (await screen.findByRole('table', { name: 'Canonical schedule preview' })).parentElement
    await userEvent.click(screen.getByRole('button', { name: 'Build export files' }))
    const artifactFrame = (await screen.findByRole('table', { name: 'Generated export artifacts' })).parentElement
    expect(canonicalFrame?.className).toMatch(/canonicalPreviewFrame/)
    expect(artifactFrame?.className ?? '').not.toMatch(/canonicalPreviewFrame/)
    expect(schedulerCss).toMatch(/\.canonicalPreviewFrame\s*\{[^}]*overflow-y:\s*auto[^}]*max-height:\s*250px/s)
    expect(schedulerCss).toMatch(/\.canonicalPreviewFrame thead th\s*\{[^}]*position:\s*sticky[^}]*top:\s*0/s)
    expect(schedulerCss.match(/@media \(max-height: 760px\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? '').toMatch(/\.canonicalPreviewFrame\s*\{[^}]*max-height:\s*112px/s)
  })

  it('shows failed assignments beside generated artifacts instead of hiding incomplete output', async () => {
    currentSession = exportedSession
    server.use(http.post('/api/scheduler/exports/build', () => HttpResponse.json(envelope({
      artifacts: [{
        artifact_id: 'artifact-bundle',
        filename: 'Instructor_Schedules.zip',
        mime_type: 'application/zip',
      }],
      failed_assignments: [{
        stable_issue_id: 'issue-1',
        reason: 'No compatible room remained',
        raw_row: { 'Student Name': 'Student 0001', Instructor: 'Instructor 0008', 'Course Code': 'MUS101' },
      }],
    }))))
    renderApp('/schedule/export')

    await userEvent.click(await screen.findByRole('button', { name: 'Build export files' }))

    expect(await screen.findByRole('link', { name: 'Instructor Schedules' })).toBeVisible()
    const failures = screen.getByRole('table', { name: 'Failed schedule assignments' })
    expect(failures).toHaveTextContent('Student 0001')
    expect(failures).toHaveTextContent('Instructor 0008')
    expect(failures).toHaveTextContent('No compatible room remained')
  })

  it('prevents duplicate builds while the synchronous request is pending', async () => {
    currentSession = exportedSession
    let builds = 0
    let finish: ((response: Response) => void) | undefined
    server.use(http.post('/api/scheduler/exports/build', () => {
      builds += 1
      return new Promise<Response>((resolve) => { finish = resolve })
    }))
    renderApp('/schedule/export')
    const button = await screen.findByRole('button', { name: 'Build export files' })

    fireEvent.click(button)
    fireEvent.click(button)

    await waitFor(() => expect(builds).toBe(1))
    expect(button).toBeDisabled()
    expect(button).toHaveTextContent('Building export files')
    finish?.(HttpResponse.json(exportResult()))
  })

  it('passes only the opaque id to the desktop bridge and keeps save failures visible', async () => {
    currentSession = exportedSession
    const saveArtifact = vi.fn().mockRejectedValue(new Error('Desktop save was cancelled'))
    window.piDesktop = { saveArtifact }
    server.use(http.post('/api/scheduler/exports/build', () => HttpResponse.json(exportResult())))
    renderApp('/schedule/export')
    await userEvent.click(await screen.findByRole('button', { name: 'Build export files' }))

    await userEvent.click(await screen.findByRole('link', { name: 'Master Schedule' }))

    expect(saveArtifact).toHaveBeenCalledWith('artifact-master')
    expect(saveArtifact).toHaveBeenCalledTimes(1)
    expect(await screen.findByRole('alert')).toHaveTextContent('Desktop save was cancelled')
  })

  it('opens only one desktop save for rapid clicks on the same artifact', async () => {
    currentSession = exportedSession
    let finishSave: (() => void) | undefined
    const saveArtifact = vi.fn(() => new Promise<void>((resolve) => { finishSave = resolve }))
    window.piDesktop = { saveArtifact }
    server.use(http.post('/api/scheduler/exports/build', () => HttpResponse.json(exportResult())))
    renderApp('/schedule/export')
    await userEvent.click(await screen.findByRole('button', { name: 'Build export files' }))
    const link = await screen.findByRole('link', { name: 'Master Schedule' })

    fireEvent.click(link)
    fireEvent.click(link)

    expect(saveArtifact).toHaveBeenCalledTimes(1)
    finishSave?.()
  })

  it('starts Round 2 only when committed and clean, then carries the locked message to Import', async () => {
    currentSession = exportedSession
    let body: unknown
    server.use(http.post('/api/scheduler/rounds/start', async ({ request }) => {
      body = await request.json()
      return HttpResponse.json(envelope({ locked_assignments: exportedSession.assignments }, 'workspace-v2'))
    }))
    const { router } = renderApp('/schedule/export')

    await userEvent.click(await screen.findByRole('button', { name: 'Start Round 2' }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/schedule/import'))
    expect(body).toEqual({ expected_version: 'workspace-v1' })
    expect(await screen.findByText('Committed assignments remain locked')).toBeVisible()
  })

  it('starts Round 2 only once during rapid clicks', async () => {
    currentSession = exportedSession
    let starts = 0
    let finish: ((response: Response) => void) | undefined
    server.use(http.post('/api/scheduler/rounds/start', () => {
      starts += 1
      return new Promise<Response>((resolve) => { finish = resolve })
    }))
    renderApp('/schedule/export')
    const button = await screen.findByRole('button', { name: 'Start Round 2' })

    fireEvent.click(button)
    fireEvent.click(button)

    await waitFor(() => expect(starts).toBe(1))
    finish?.(HttpResponse.json(envelope({ locked_assignments: exportedSession.assignments }, 'workspace-v2')))
  })

  it('disables Round 2 outside the committed-clean gate and preserves export state on 409', async () => {
    currentSession = { ...exportedSession, draft: { ...exportedSession.draft, dirty: true } }
    const first = renderApp('/schedule/export')
    expect(await screen.findByRole('button', { name: 'Start Round 2' })).toBeDisabled()
    first.client.clear()
    cleanup()

    currentSession = exportedSession
    server.use(
      http.post('/api/scheduler/exports/build', () => HttpResponse.json(exportResult())),
      http.post('/api/scheduler/rounds/start', () => HttpResponse.json({
        data: null, workspace_version: 'workspace-v2', warnings: [],
        error: { code: 'WORKSPACE_CONFLICT', message: 'Workspace changed before Round 2' },
      }, { status: 409 })),
    )
    renderApp('/schedule/export')
    await userEvent.click(await screen.findByRole('button', { name: 'Build export files' }))
    expect(await screen.findByRole('link', { name: 'Master Schedule' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Start Round 2' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Workspace changed before Round 2')
    expect(screen.getByRole('link', { name: 'Master Schedule' })).toBeVisible()
    expect(screen.getByRole('table', { name: 'Canonical schedule preview' })).toHaveTextContent('Cello lesson')
    expect(screen.getByRole('button', { name: 'Reload scheduler state' })).toBeVisible()
  })

  it('shows honest loading, read error with retry, and empty artifact states', async () => {
    currentSession = exportedSession
    let finish: ((response: Response) => void) | undefined
    server.use(http.get('/api/dashboard', () => new Promise<Response>((resolve) => { finish = resolve })))
    renderApp('/schedule/export')
    expect(screen.getByRole('status')).toHaveTextContent('Loading export workspace')
    await waitFor(() => expect(finish).toBeTypeOf('function'))
    finish?.(HttpResponse.json(envelope(dashboard)))
    expect(await screen.findByText('Canonical Schedule Preview')).toBeVisible()
    cleanup()

    server.use(http.get('/api/dashboard', () => HttpResponse.json({
      data: null, workspace_version: null, warnings: [],
      error: { code: 'DASHBOARD_FAILED', message: 'Dashboard unavailable' },
    }, { status: 500 })))
    renderApp('/schedule/export')
    expect(await screen.findByRole('alert')).toHaveTextContent('Dashboard unavailable')
    expect(screen.getByRole('button', { name: 'Retry export workspace' })).toBeVisible()
    cleanup()

    server.use(
      http.get('/api/dashboard', () => HttpResponse.json(envelope(dashboard))),
      http.post('/api/scheduler/exports/build', () => HttpResponse.json(envelope({ artifacts: [] }))),
    )
    renderApp('/schedule/export')
    await userEvent.click(await screen.findByRole('button', { name: 'Build export files' }))
    expect(await screen.findByText('No export artifacts were generated.')).toBeVisible()
  })
})
