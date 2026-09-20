import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { OptimizerPage } from './OptimizerPage'

const session = {
  active_stage: 'optimize', assignments: [], issues: [], rooms: [{ id: 'R1' }], instructors: [],
  draft: { dirty: false, can_undo: false, can_redo: false },
  metrics: { assigned: 0, unresolved: 0, source_gaps: 0 }, warnings: [],
}
const envelope = (data: unknown, version: string | null = 'workspace-v1') => ({
  data, workspace_version: version, warnings: [], error: null,
})
const learningRecord = {
  latest: {
    run_id: 'recorded-run-1',
    status: 'finalized',
    started_at: '2026-07-30T09:00:00+00:00',
    completed_at: '2026-07-30T09:00:02+00:00',
    finalized_at: '2026-07-30T09:10:00+00:00',
    duration_ms: 2000,
    input_workspace_version: 'workspace-v0',
    dashboard_version: '4.2.0',
    baseline: {
      assigned: 8, unresolved: 2, duplicates: 0,
      allocation_rate: 0.8, failure_counts: { no_room: 2 },
    },
    outcome: {
      assigned: 10, unresolved: 0, duplicates: 0,
      allocation_rate: 1, failure_counts: {},
      assigned_change: 2, unresolved_change: -2,
      allocation_rate_change: 0.2, intervention_count: 2,
      decision_note_count: 2, finalize_warning_count: 0,
    },
  },
  total_runs: 3, finalized_runs: 2, open_runs: 0,
}
let optimizeBodies: unknown[] = []
let polls = 0
let pollTimes: number[] = []
let sessionReads = 0

const server = setupServer(
  http.get('/api/scheduler/session', () => { sessionReads += 1; return HttpResponse.json(envelope(session)) }),
  http.get('/api/scheduler/optimize/preflight', () => HttpResponse.json(envelope({
    rules_health: {}, room_health: {}, instructor_conflicts: [], issues: [], is_blocked: false,
  }))),
  http.get('/api/scheduler/optimize/records', () => HttpResponse.json(envelope(learningRecord))),
  http.post('/api/scheduler/optimize', async ({ request }) => {
    optimizeBodies.push(await request.json())
    return HttpResponse.json(envelope({ operation_id: 'operation-1', status: 'queued' }), { status: 202 })
  }),
  http.get('/api/operations/:operationId', () => {
    polls += 1
    pollTimes.push(Date.now())
    const operation = polls === 1
      ? { id: 'operation-1', kind: 'optimizer', status: 'running', phase: 'optimizing', result: null, error: null }
      : { id: 'operation-1', kind: 'optimizer', status: 'completed', phase: 'completed', result: { assignment_count: 128, unassigned_count: 3 }, error: null }
    return HttpResponse.json(envelope(operation, null))
  }),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup(); server.resetHandlers(); optimizeBodies = []; polls = 0; pollTimes = []; sessionReads = 0
  vi.useRealTimers()
})
afterAll(() => server.close())

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } })
  const router = createMemoryRouter([
    { path: '/schedule/optimize', element: <OptimizerPage /> },
    { path: '/schedule/resolve', element: <p>Resolve route</p> },
  ], { initialEntries: ['/schedule/optimize'] })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return { client, router }
}

describe('OptimizerPage', () => {
  it('submits once, polls only active states at exactly 500ms, reports counts, and refreshes the session once', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    renderPage()
    const run = await screen.findByRole('button', { name: 'Run optimizer' })
    await waitFor(() => expect(run).toBeEnabled())
    fireEvent.click(run)
    fireEvent.click(run)
    await act(() => vi.advanceTimersByTimeAsync(0))

    expect(optimizeBodies).toEqual([{ expected_version: 'workspace-v1' }])
    expect(run).toBeDisabled()
    expect(await screen.findByText('Optimizing room assignments')).toBeInTheDocument()
    expect(polls).toBe(1)
    await act(() => vi.advanceTimersByTimeAsync(500))

    expect(await screen.findByText('128 assignments generated')).toBeInTheDocument()
    expect(pollTimes[1] - pollTimes[0]).toBe(500)
    expect(screen.getByText('3 unresolved lessons')).toBeInTheDocument()
    expect(screen.getByText('Source + Rules Snapshot')).toBeInTheDocument()
    expect(screen.getByText('Run started')).toBeInTheDocument()
    expect(screen.getByText('Result version')).toBeInTheDocument()
    expect(screen.getByText('Learning record')).toBeInTheDocument()
    expect(screen.getByText('80.0%')).toBeInTheDocument()
    expect(screen.getByText('+20.0 pp')).toBeInTheDocument()
    expect(screen.getByText('Recorded interventions')).toBeInTheDocument()
    expect(screen.getAllByText('workspace-v1').length).toBeGreaterThan(1)
    expect(screen.getByRole('link', { name: 'Continue to resolve' })).toHaveAttribute('href', '/schedule/resolve')
    await act(() => vi.advanceTimersByTimeAsync(2_000))
    expect(polls).toBe(2)
    await waitFor(() => expect(sessionReads).toBe(2))
  })

  it('stops polling and offers Retry when the operation fails', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    server.use(http.get('/api/operations/:operationId', () => {
      polls += 1
      return HttpResponse.json(envelope({
        id: 'operation-1', kind: 'optimizer', status: 'failed', phase: 'failed',
        result: null, error: 'Room inventory is incomplete',
      }, null))
    }))
    renderPage()
    const run = await screen.findByRole('button', { name: 'Run optimizer' })
    await waitFor(() => expect(run).toBeEnabled())
    fireEvent.click(run)
    await act(() => vi.advanceTimersByTimeAsync(0))

    expect(await screen.findByRole('alert')).toHaveTextContent('Room inventory is incomplete')
    expect(screen.getAllByText(/operation-1/).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Retry optimizer' })).toBeEnabled()
    await act(() => vi.advanceTimersByTimeAsync(2_000))
    expect(polls).toBe(1)
  })

  it('shows a completed optimizer learning-record failure outside the log', async () => {
    server.use(http.get('/api/operations/:operationId', () => HttpResponse.json(envelope({
      id: 'operation-1', kind: 'optimizer', status: 'completed', phase: 'completed',
      result: {
        assignment_count: 128,
        unassigned_count: 3,
        learning_record_warning: 'Optimizer learning evidence needs repair.',
      },
      error: null,
    }, null))))
    renderPage()
    const run = await screen.findByRole('button', { name: 'Run optimizer' })
    await waitFor(() => expect(run).toBeEnabled())
    fireEvent.click(run)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Optimizer learning evidence needs repair.',
    )
    expect(screen.getByText('Learning record needs attention')).toBeInTheDocument()
  })

  it('retries only operation status after a polling transport error', async () => {
    let statusReads = 0
    server.use(http.get('/api/operations/:operationId', () => {
      statusReads += 1
      if (statusReads === 1) return HttpResponse.json({ detail: 'offline' }, { status: 503 })
      return HttpResponse.json(envelope({
        id: 'operation-1', kind: 'optimizer', status: 'running', phase: 'optimizing', result: null, error: null,
      }, null))
    }))
    renderPage()
    const run = await screen.findByRole('button', { name: 'Run optimizer' })
    await waitFor(() => expect(run).toBeEnabled())
    fireEvent.click(run)
    const retry = await screen.findByRole('button', { name: 'Retry operation status' })
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByRole('alert')).toHaveTextContent('Operation status unavailable')
    expect(optimizeBodies).toHaveLength(1)
    fireEvent.click(retry)
    expect(await screen.findByText('Optimizing room assignments')).toBeInTheDocument()
    expect(optimizeBodies).toHaveLength(1)
    expect(statusReads).toBe(2)
  })

  it('publishes result version and root causes only after the canonical session refresh succeeds', async () => {
    let optimizerCompleted = false
    let resolveRefresh: ((response: Response) => void) | undefined
    const refreshed = {
      ...session,
      issues: [{ reason_code: 'no_room', label: 'No compatible room', count: 2, items: [] }],
      metrics: { assigned: 128, unresolved: 2, source_gaps: 0 },
    }
    server.use(
      http.get('/api/scheduler/session', () => {
        if (!optimizerCompleted) return HttpResponse.json(envelope(session, 'workspace-v1'))
        return new Promise<Response>((resolve) => { resolveRefresh = resolve })
      }),
      http.get('/api/operations/:operationId', () => {
        optimizerCompleted = true
        return HttpResponse.json(envelope({
          id: 'operation-1', kind: 'optimizer', status: 'completed', phase: 'completed',
          result: { assignment_count: 128, unassigned_count: 2 }, error: null,
        }, null))
      }),
    )
    renderPage()
    const run = await screen.findByRole('button', { name: 'Run optimizer' })
    await waitFor(() => expect(run).toBeEnabled())
    await act(async () => { fireEvent.click(run) })
    await waitFor(() => expect(optimizeBodies).toHaveLength(1))

    expect(await screen.findByText('Optimizer run completed')).toBeInTheDocument()
    expect(screen.getByText('Refreshing')).toBeInTheDocument()
    expect(screen.queryByText('Unresolved Causes')).not.toBeInTheDocument()
    expect(screen.queryByText('workspace-v2')).not.toBeInTheDocument()
    await waitFor(() => expect(resolveRefresh).toBeTypeOf('function'))

    resolveRefresh?.(HttpResponse.json(envelope(refreshed, 'workspace-v2')))
    expect(await screen.findAllByText('workspace-v2')).toHaveLength(2)
    expect(screen.getByText('No compatible room')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Unresolved Causes' })).toBeInTheDocument()
  })

  it('reports a failed result refresh without labeling baseline data as the optimizer result', async () => {
    let optimizerCompleted = false
    server.use(
      http.get('/api/scheduler/session', () => {
        return !optimizerCompleted
          ? HttpResponse.json(envelope(session, 'workspace-v1'))
          : HttpResponse.json({ detail: 'refresh unavailable' }, { status: 503 })
      }),
      http.get('/api/operations/:operationId', () => {
        optimizerCompleted = true
        return HttpResponse.json(envelope({
          id: 'operation-1', kind: 'optimizer', status: 'completed', phase: 'completed',
          result: { assignment_count: 128, unassigned_count: 2 }, error: null,
        }, null))
      }),
    )
    renderPage()
    const run = await screen.findByRole('button', { name: 'Run optimizer' })
    await waitFor(() => expect(run).toBeEnabled())
    await act(async () => { fireEvent.click(run) })
    await waitFor(() => expect(optimizeBodies).toHaveLength(1))

    expect(await screen.findByText('Result unavailable')).toBeInTheDocument()
    expect(screen.getByText('Optimizer result refresh failed')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Unresolved Causes' })).not.toBeInTheDocument()
    expect(screen.getAllByText('workspace-v1')).toHaveLength(2)
  })
})
