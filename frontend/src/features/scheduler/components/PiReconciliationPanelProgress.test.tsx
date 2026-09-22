import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
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
  queryClient: QueryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
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

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  window.localStorage.removeItem('pi-reconciliation-locale')
})

describe('PiReconciliationPanel operational progress', () => {
  it('运行中只展示人可读的阶段，原始事件收进折叠的调查过程', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-21T00:00:02.000+00:00'))
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
    expect(screen.getByText(/正在验证方案/)).toBeVisible()
    expect(screen.getByText(/已用时 2\.0 秒/)).toBeVisible()
    // 原始事件列表不在主区域，收进折叠的调查过程
    expect(screen.getByTestId('pi-progress')).not.toHaveTextContent('provider_retry')
    const evidence = screen.getByTestId('reconciliation-evidence-running')
    expect(evidence).not.toHaveAttribute('open')
    expect(evidence).toHaveTextContent('inspection_completed')
    expect(evidence).toHaveTextContent('provider_retry')
  })

  it('检查阶段尚未进入验证时显示正在检查全天安排', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-21T00:00:01.000+00:00'))
    vi.mocked(getOperation).mockResolvedValue(envelope(operation({
      events: [
        progressEvent(1, 'investigation_started', 'python', { day: 1 }),
        progressEvent(2, 'inspection_started', 'python', {}),
      ],
    })) as never)

    renderPanel(null, ['/schedule/resolve?pi_operation=op-1'])

    expect(await screen.findByTestId('pi-progress')).toBeVisible()
    expect(screen.getByText(/正在检查全天安排/)).toBeVisible()
  })

  it('完成后展示终止原因与中文指标', async () => {
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

    expect((await screen.findByTestId('pi-progress')).textContent).toContain('超出运行时限')
    expect(screen.getByText(/已用时 180\.0 秒/)).toBeVisible()
    expect(screen.getByText(/2 次验证/)).toBeVisible()
    expect(screen.getByText(/1 个可行方案/)).toBeVisible()
    expect(screen.getByText(/1 个被 Python 否决/)).toBeVisible()
    expect(screen.getByText(/3 次工具调用/)).toBeVisible()
  })

  it('探索上限与运行时限的终止文案不同', async () => {
    vi.mocked(getOperation).mockResolvedValue(envelope(operation({
      status: 'completed',
      phase: 'completed',
      result: { termination: 'budget_exhausted', latency_ms: 4000, tool_calls: 20 },
    })) as never)

    renderPanel(null, ['/schedule/resolve?pi_operation=op-1'])

    expect((await screen.findByTestId('pi-progress')).textContent).toContain('已达探索上限')
    expect(screen.queryByText(/超出运行时限/)).toBeNull()
  })

  it('刷新后从 URL 重新附着正在运行的调查', async () => {
    vi.mocked(getOperation).mockResolvedValue(envelope(operation({ id: 'op-9' })) as never)

    renderPanel(null, ['/schedule/resolve?pi_operation=op-9'])

    await waitFor(() => expect(getOperation).toHaveBeenCalledWith('op-9', expect.anything()))
    expect(await screen.findByTestId('pi-progress')).toBeVisible()
  })

  it('调查记录不存在时清除持久的操作句柄', async () => {
    vi.mocked(getOperation).mockRejectedValue(
      new ApiClientError(404, { code: 'OPERATION_NOT_FOUND', message: 'not found' }),
    )

    renderPanel(null, ['/schedule/resolve?pi_operation=op-gone'])

    await waitFor(() => expect(screen.getByTestId('op-param').textContent).toBe(''))
    expect(screen.queryByTestId('pi-progress')).toBeNull()
  })

  it('把局限与中断提示放在折叠的调查过程中呈现', async () => {
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
        focus_question: '有可用方案，但调查被中断',
        rationale: 'The runtime bound stopped the search.',
        limitations: ['Stopped by the runtime bound after 3 exploration calls.'],
        pending_decisions: [],
        remaining_issues: [],
      },
    } as unknown as Investigation
    vi.mocked(getOperation).mockResolvedValue(envelope(null))

    renderPanel(investigation)

    expect(screen.getByText('调查中断 · 有可用方案')).toBeVisible()
    const evidence = screen.getByTestId('reconciliation-evidence')
    expect(evidence).not.toHaveAttribute('open')
    expect(evidence).toHaveTextContent('Stopped by the runtime bound after 3 exploration calls.')
  })

  it('运行中的调查动态累计用时，终止后锁定用时', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-21T00:00:02.000+00:00'))

    const op = operation({
      id: 'op-dynamic',
      status: 'running',
      started_at: '2026-09-21T00:00:00.000+00:00',
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    queryClient.setQueryData(['pi-reconciliation-operation', 'op-dynamic'], envelope(op))
    vi.mocked(getOperation).mockResolvedValue(envelope(op) as never)

    renderPanel(null, ['/schedule/resolve?pi_operation=op-dynamic'], queryClient)
    expect(screen.getByTestId('pi-progress')).toBeVisible()
    expect(screen.getByText(/已用时 2\.0 秒/)).toBeVisible()

    // Advance time by 3 seconds
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(screen.getByText(/已用时 5\.0 秒/)).toBeVisible()

    // Terminal operation locks to latency_ms regardless of current time
    cleanup()
    const termOp = operation({
      id: 'op-term',
      status: 'completed',
      phase: 'completed',
      result: { termination: 'recommendation_ready', latency_ms: 3200 },
      started_at: '2026-09-21T00:00:00.000+00:00',
    })
    const termClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    termClient.setQueryData(['pi-reconciliation-operation', 'op-term'], envelope(termOp))
    vi.mocked(getOperation).mockResolvedValue(envelope(termOp) as never)

    renderPanel(null, ['/schedule/resolve?pi_operation=op-term'], termClient)
    expect(screen.getByText(/已用时 3\.2 秒/)).toBeVisible()

    // Even if time advances by 100 seconds, terminal took 3.2s remains locked
    act(() => {
      vi.advanceTimersByTime(100000)
    })
    expect(screen.getByText(/已用时 3\.2 秒/)).toBeVisible()
  })

  it('超时不显示误导性的“调查完成”', () => {
    const timeoutOp = operation({
      id: 'op-timeout',
      status: 'timeout',
      phase: 'completed',
      result: { termination: 'runtime_timeout', latency_ms: 60000 },
    })
    const client1 = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client1.setQueryData(['pi-reconciliation-operation', 'op-timeout'], envelope(timeoutOp))
    renderPanel(null, ['/schedule/resolve?pi_operation=op-timeout'], client1)

    expect(screen.getByTestId('pi-progress')).toBeVisible()
    expect(screen.queryByText('调查完成')).toBeNull()
    expect(screen.getByText(/调查中断 · 超出运行时限/)).toBeVisible()

    cleanup()

    const budgetOp = operation({
      id: 'op-budget',
      status: 'completed',
      phase: 'completed',
      result: { termination: 'budget_exhausted', latency_ms: 45000 },
    })
    const client2 = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client2.setQueryData(['pi-reconciliation-operation', 'op-budget'], envelope(budgetOp))
    renderPanel(null, ['/schedule/resolve?pi_operation=op-budget'], client2)

    expect(screen.getByTestId('pi-progress')).toBeVisible()
    expect(screen.queryByText('调查完成')).toBeNull()
    expect(screen.getByText(/调查中断 · 已达探索上限/)).toBeVisible()
  })
})
