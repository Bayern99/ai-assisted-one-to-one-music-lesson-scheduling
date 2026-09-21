import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useSearchParams } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClientError } from '../../../api/client'
import { getOperation, type Operation, type ResolutionAdvice } from '../api'
import { PiReconciliationPanel } from './PiReconciliationPanel'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    getOperation: vi.fn(),
    investigateReconciliation: vi.fn(),
    decideReconciliation: vi.fn(),
    applyReconciliation: vi.fn(),
  }
})

type Investigation = NonNullable<ResolutionAdvice['pi_reconciliation']>
type OperationEvent = Operation['events'][number]

function progressEvent(seq: number, type: string, source: string, detail: Record<string, unknown>): OperationEvent {
  return {
    seq,
    type,
    source,
    label: type,
    detail,
    at: `2026-09-21T00:00:0${Math.min(seq, 9)}.000+00:00`,
    elapsed_ms: seq * 100,
  }
}

function operation(overrides: Partial<Operation> = {}): Operation {
  return {
    id: 'op-1',
    kind: 'pi_reconciliation',
    status: 'running',
    phase: 'investigating',
    result: null,
    error: null,
    started_at: '2026-09-21T00:00:00.000+00:00',
    last_activity_at: '2026-09-21T00:00:02.000+00:00',
    events: [],
    ...overrides,
  }
}

function envelope(data: Operation | null) {
  return { data, workspace_version: 'v1', warnings: [], error: null }
}

function renderPanel(
  investigation: Investigation | null,
  initialEntries: string[] = ['/schedule/resolve'],
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <QueryClientProvider client={queryClient}>
        <LocationProbe />
        <PiReconciliationPanel
          activeDay={1}
          disabled={false}
          investigation={investigation}
          piRuntime={null}
          workspaceVersion="v1"
        />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

function LocationProbe() {
  const [params] = useSearchParams()
  return <span data-testid="op-param">{params.get('pi_operation') ?? ''}</span>
}

afterEach(cleanup)

describe('PiReconciliationPanel operational progress', () => {
  it('renders real progress events instead of a bare loading label', async () => {
    vi.mocked(getOperation).mockResolvedValue(envelope(operation({
      events: [
        progressEvent(1, 'investigation_started', 'python', { day: 1 }),
        progressEvent(2, 'inspection_started', 'python', {}),
        progressEvent(3, 'inspection_completed', 'python', { subjects: 1 }),
        progressEvent(4, 'simulation_rejected', 'python', { reason: 'Unknown reconciliation subject alias: issue-9' }),
        progressEvent(5, 'first_valid_candidate', 'python', { simulation_id: 'sim-1' }),
        progressEvent(6, 'provider_retry', 'pi_rpc', { attempt: 2, max_attempts: 3 }),
      ],
    })) as never)

    renderPanel(null, ['/schedule/resolve?pi_operation=op-1'])

    expect(await screen.findByTestId('pi-progress')).toBeVisible()
    expect(screen.getByText('Occupancy inspected')).toBeVisible()
    expect(screen.getByText(/Package rejected by Python validation: Unknown reconciliation subject alias: issue-9/)).toBeVisible()
    expect(screen.getByText('Found a valid candidate')).toBeVisible()
    expect(screen.getByText(/Provider retry 2\/3/)).toBeVisible()
    expect(screen.getByText(/elapsed 2\.0s/)).toBeVisible()
  })

  it('shows the completion termination and turn metrics', async () => {
    vi.mocked(getOperation).mockResolvedValue(envelope(operation({
      status: 'completed',
      phase: 'completed',
      result: {
        termination: 'runtime_timeout',
        latency_ms: 180000,
        provider: 'stub-provider',
        model: 'stub-model',
        usage: { input: 500, output: 10 },
        tool_calls: 3,
        tool_call_budget: 20,
        simulation_count: 2,
        valid_candidates: 1,
        rejected_candidates: 1,
        first_valid_candidate_ms: 2400,
      },
    })) as never)

    renderPanel(null, ['/schedule/resolve?pi_operation=op-1'])

    expect((await screen.findByTestId('pi-progress')).textContent).toContain('Runtime limit reached')
    expect(screen.getByText(/took 180\.0s/)).toBeVisible()
    expect(screen.getByText(/3 tool calls/)).toBeVisible()
    expect(screen.getByText(/1 rejected by Python/)).toBeVisible()
  })

  it('labels tool budget exhaustion differently from a runtime timeout', async () => {
    vi.mocked(getOperation).mockResolvedValue(envelope(operation({
      status: 'completed',
      phase: 'completed',
      result: { termination: 'budget_exhausted', latency_ms: 4000, tool_calls: 20 },
    })) as never)

    renderPanel(null, ['/schedule/resolve?pi_operation=op-1'])

    expect((await screen.findByTestId('pi-progress')).textContent).toContain('Exploration limit reached')
    expect(screen.queryByText(/Runtime limit reached/)).toBeNull()
  })

  it('re-attaches a running investigation from the URL after a reload', async () => {
    vi.mocked(getOperation).mockResolvedValue(envelope(operation({ id: 'op-9' })) as never)

    renderPanel(null, ['/schedule/resolve?pi_operation=op-9'])

    await waitFor(() => expect(getOperation).toHaveBeenCalledWith('op-9', expect.anything()))
    expect(await screen.findByTestId('pi-progress')).toBeVisible()
  })

  it('clears the durable handle when the operation no longer exists', async () => {
    vi.mocked(getOperation).mockRejectedValue(
      new ApiClientError(404, { code: 'OPERATION_NOT_FOUND', message: 'not found' }),
    )

    renderPanel(null, ['/schedule/resolve?pi_operation=op-gone'])

    await waitFor(() => expect(screen.getByTestId('op-param').textContent).toBe(''))
    expect(screen.queryByTestId('pi-progress')).toBeNull()
  })

  it('surfaces the brief limitations and the timeout hint', async () => {
    const investigation = {
      investigation_id: 'inv-1',
      status: 'timeout',
      simulations: [{
        simulation_id: 'sim-1',
        status: 'feasible',
        feasible: true,
        metrics: { resolved_delta: 1, remaining_unresolved: 0 },
        required_teacher_confirmations: [],
        sacrifices: [],
        changes: [],
        split_teacher_days: [],
        same_day_time_change: false,
        requires_sacrifice_authorization: false,
      }],
      coverage: {},
      created_at: '2026-09-21T00:00:00+00:00',
      tool_calls: 3,
      teacher_display: {},
      brief: {
        status: 'proposed',
        termination: 'budget_exhausted',
        primary_simulation_id: 'sim-1',
        title: 'Bounded search complete',
        rationale: 'The runtime bound stopped the search.',
        limitations: ['Stopped by the runtime bound after 3 exploration calls.'],
        pending_decisions: [],
        remaining_issues: [],
      },
    } as unknown as Investigation
    vi.mocked(getOperation).mockResolvedValue(envelope(null))

    renderPanel(investigation)


    expect(await screen.findByText(/Stopped by the runtime bound after 3 exploration calls/)).toBeVisible()
    expect(screen.getByText(/cut off by the runtime limit/)).toBeVisible()
  })
})
