import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyReconciliation, investigateReconciliation, schedulerSessionKey, type PiRuntime } from '../api'
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

type Investigation = NonNullable<Parameters<typeof PiReconciliationPanel>[0]['investigation']>
type Simulation = Investigation['simulations'][number]

const changeRows = [
  {
    subject_alias: 'assignment-1',
    group_alias: 'block-1',
    group_size: 2,
    kind: 'block' as const,
    action: 'move' as const,
    teacher: 'Instructor 0009',
    label: 'Bach: Anna',
    from: { room: 'R1', day: 1, start: '10:00', end: '11:00' },
    to: { room: 'R2', day: 1, start: '10:00', end: '11:00' },
    time_changed: false,
    room_changed: true,
    is_sacrifice: false,
  },
  {
    subject_alias: 'issue-2',
    group_alias: 'issue-2',
    group_size: 1,
    kind: 'issue' as const,
    action: 'place' as const,
    teacher: 'Instructor 0008',
    label: 'Demo: Alpha',
    from: { room: null, day: 1, start: '10:00', end: '11:00' },
    to: { room: 'R1', day: 1, start: '10:00', end: '11:00' },
    time_changed: false,
    room_changed: true,
    is_sacrifice: false,
  },
]

const simulation: Simulation = {
  simulation_id: 'sim-primary',
  snapshot_id: 'snap-1',
  snapshot_hash: 'hash-1',
  status: 'feasible',
  feasible: true,
  normalized_changes: [],
  package_hash: 'pkg-1',
  metrics: { resolved_delta: 1, remaining_unresolved: 0, moved_assignments: 2, room_switches: 2, sacrificed_assignments: 0 },
  required_teacher_confirmations: [],
  warnings: [],
  failure_codes: [],
  sacrifices: [],
  changes: changeRows,
  split_teacher_days: [],
  same_day_time_change: false,
  requires_sacrifice_authorization: false,
  state_after: {},
}

function investigationWith(overrides: Partial<Investigation> = {}, simulationOverrides: Partial<Simulation> = {}): Investigation {
  const sim = { ...simulation, ...simulationOverrides }
  return {
    investigation_id: 'inv-1',
    snapshot_id: 'snap-1',
    snapshot_hash: 'hash-1',
    workspace_version: 'v1',
    scope_type: 'day',
    scope_id: 'day-1',
    day: 1,
    stale: false,
    status: 'completed',
    created_at: '2026-09-16T00:00:00+00:00',
    tool_calls: 2,
    coverage: { subjects_inspected: 1, subjects_total: 1, uninspected_count: 0, simulation_count: 1 },
    task: {
      goal: '把这一节排进去',
      scope_type: 'day',
      scope_id: 'day-1',
      day: 1,
      time_is_fixed: true,
      protect_teacher_aliases: [],
      protect_subject_aliases: [],
      time_change_exception_teacher_aliases: [],
      locked_room_days: [],
      tool_calls_used: 2,
      tool_call_budget: 20,
      sacrifice_requires_authorization: true,
      prior_decisions: [],
    },
    teacher_display: { 'teacher-1': 'Instructor 0008', 'teacher-2': 'Instructor 0009' },
    brief: {
      brief_id: 'brief-1',
      investigation_id: 'inv-1',
      snapshot_id: 'snap-1',
      status: 'proposed',
      termination: 'recommendation_ready',
      primary_simulation_id: 'sim-primary',
      title: '换房后安置 A 的课',
      rationale: '把 B 的教师日区块移到 R2，R1 就能安置 A。',
      trade_offs: ['教师 B 当天换一次房。'],
      limitations: ['只搜索了当天。'],
      coverage: { subjects_inspected: 1, subjects_total: 1, uninspected_count: 0, simulation_count: 1 },
      created_at: '2026-09-16T00:00:01+00:00',
      sacrifices: [],
      requires_sacrifice_authorization: false,
      same_day_time_change: false,
      pending_decisions: [],
      remaining_issues: [],
    },
    simulations: [sim],
    apply_result: null,
    ...overrides,
  } as unknown as Investigation
}

const runtime: PiRuntime = {
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
}

function renderPanel(investigation: Investigation, disabled = false, piRuntime: PiRuntime = runtime) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <PiReconciliationPanel
        activeDay={1}
        disabled={disabled}
        investigation={investigation}
        piRuntime={piRuntime}
        workspaceVersion="v1"
      />
    </QueryClientProvider>,
  )
}

afterEach(cleanup)

describe('PiReconciliationPanel', () => {
  it('presents one recommendation with a complete change list instead of many cards', () => {
    renderPanel(investigationWith())

    expect(screen.getByText('换房后安置 A 的课')).toBeVisible()
    expect(screen.getByLabelText('教师调整')).toHaveTextContent(/Instructor 0009\s+10:00–11:00\s+R1 → R2/)
    expect(screen.getByLabelText('教师调整')).toHaveTextContent(/Instructor 0008\s+10:00–11:00\s+未排 → R1/)
    expect(screen.getByText('逐课明细')).toBeVisible()
    expect(screen.queryByRole('table', { name: /预期变更/ })).not.toBeNull()
    expect(screen.queryByText('把 B 的教师日区块移到 R2，R1 就能安置 A。')).toBeNull()
    expect(screen.queryByText('只搜索了当天。')).toBeNull()
    expect(screen.getByRole('button', { name: '应用这个建议' })).toBeEnabled()
    expect(screen.getByText('你上次说了：把这一节排进去')).toBeVisible()
  })

  it('shows a completed no-package result without an Apply action', () => {
    const stopped = investigationWith({
      simulations: [],
      coverage: { subjects_inspected: 1, subjects_total: 1, uninspected_count: 0, simulation_count: 0 },
      brief: {
        ...investigationWith().brief!,
        termination: 'no_feasible_package_found',
        primary_simulation_id: undefined,
        title: '没有可行整包方案',
        rationale: '固定时间下没有可用房间。',
        coverage: { subjects_inspected: 1, subjects_total: 1, uninspected_count: 0, simulation_count: 0 },
        remaining_issues: [{ subject_alias: 'issue-1', teacher_alias: 'teacher-1', label: 'Demo: Alpha', reason: '没有可用房间' }],
      },
    })

    renderPanel(stopped)

    expect(screen.getByTestId('reconciliation-stop-result')).toBeVisible()
    expect(screen.queryByText(/覆盖：检查/)).toBeNull()
    expect(screen.getByText(/Instructor 0008 · Demo: Alpha/)).toBeVisible()
    expect(screen.queryByRole('button', { name: '应用这个建议' })).not.toBeInTheDocument()
  })

  it('shows an emergency room-type exception as a human decision', () => {
    const stopped = investigationWith({
      simulations: [],
      coverage: { subjects_inspected: 1, subjects_total: 1, uninspected_count: 0, simulation_count: 0 },
      brief: {
        ...investigationWith().brief!,
        termination: 'no_feasible_package_found',
        primary_simulation_id: undefined,
        title: 'Voice still needs a room-type exception',
        pending_decisions: [{
          kind: 'exception_authorization',
          detail: 'R107B is empty but Voice is not allowed; use it only as an emergency.',
          teacher_alias: 'teacher-1',
        }],
        remaining_issues: [{ subject_alias: 'issue-1', teacher_alias: 'teacher-1', label: 'Demo: Alpha', reason: '没有合法声乐房' }],
      },
    })

    renderPanel(stopped)

    expect(screen.getByText('需要例外授权 · Instructor 0008')).toBeVisible()
    expect(screen.queryByText(/R107B is empty/)).toBeNull()
    expect(screen.queryByRole('button', { name: '应用这个建议' })).not.toBeInTheDocument()
  })

  it('discloses a same-day time change and asks for that teacher', () => {
    renderPanel(investigationWith({}, {
      same_day_time_change: true,
      required_teacher_confirmations: [{ teacher_alias: 'teacher-2', confirmation_id: 'confirm-2' }],
      changes: [{ ...changeRows[0], time_changed: true, to: { room: 'R1', day: 1, start: '11:00', end: '12:00' } }],
    }))

    expect(screen.getByText(/改时间的例外条款/)).toBeVisible()
    expect(screen.getByLabelText('Instructor 0009 已同意')).toBeVisible()
    expect(screen.getByRole('button', { name: '应用这个建议' })).toBeDisabled()

    fireEvent.click(screen.getByLabelText('Instructor 0009 已同意'))
    expect(screen.getByRole('button', { name: '应用这个建议' })).toBeEnabled()
  })

  it('names remaining work and sacrifices with real people, not aliases', () => {
    const sacrifice = {
      subject_alias: 'assignment-1',
      teacher_alias: 'teacher-2',
      label: 'Bach: Anna',
      day: 1,
      start: '10:00',
      end: '11:00',
      room: 'R1',
    }
    renderPanel(investigationWith({
      brief: {
        ...investigationWith().brief!,
        remaining_issues: [
          { subject_alias: 'issue-2', reason: 'Needs a business decision.', teacher_alias: 'teacher-1', label: 'Demo: Alpha' },
        ],
      },
    }, {
      sacrifices: [sacrifice],
      requires_sacrifice_authorization: true,
      metrics: { resolved_delta: 1, remaining_unresolved: 1, sacrificed_assignments: 1 },
    }))

    expect(screen.getByText('Instructor 0008 · Demo: Alpha')).toBeVisible()
    expect(screen.queryByText(/Needs a business decision/)).toBeNull()
    expect(screen.getByLabelText('授权牺牲 Instructor 0009 10:00–11:00')).toBeVisible()
  })

  it('blocks apply until each sacrifice is authorized separately', () => {
    const sacrifice = { subject_alias: 'assignment-1', teacher_alias: 'teacher-2', label: '', day: 1, start: '10:00', end: '11:00', room: 'R1' }
    renderPanel(investigationWith({}, {
      sacrifices: [sacrifice],
      requires_sacrifice_authorization: true,
      metrics: { resolved_delta: 1, remaining_unresolved: 1, sacrificed_assignments: 1 },
    }))

    expect(screen.getByText(/需要你单独授权/)).toBeVisible()
    expect(screen.getByRole('button', { name: '应用这个建议' })).toBeDisabled()

    fireEvent.click(screen.getByLabelText('授权牺牲 Instructor 0009 10:00–11:00'))
    expect(screen.getByRole('button', { name: '应用这个建议' })).toBeEnabled()
  })

  it('lets the operator pick a catalog model and thinking level without a teacher whitelist', () => {
    renderPanel(investigationWith())

    expect(screen.getByLabelText('对 Pi 说')).toBeVisible()
    expect(screen.getByLabelText('Pi model')).toHaveValue('openai-codex::gpt-5.6-luna')
    expect(screen.getByRole('option', { name: 'deepseek / deepseek-flash' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'kimi-coding / k3' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'openai-codex / gpt-5.3-codex-spark' })).toBeInTheDocument()
    expect(screen.getByLabelText('Pi thinking')).toHaveValue('off')
    expect(screen.getByRole('option', { name: 'high' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Instructor 0009 本次不要动')).toBeNull()
    expect(screen.queryByLabelText('Instructor 0009 允许同日改时（最后例外）')).toBeNull()
    expect(screen.getByRole('button', { name: '按这句话再查' })).toBeEnabled()
  })

  it('posts the selected provider, model, and thinking level', async () => {
    vi.mocked(investigateReconciliation).mockResolvedValue({
      data: { operation_id: 'op-1', status: 'queued' },
      workspace_version: 'v1',
    } as never)
    renderPanel(investigationWith())

    fireEvent.change(screen.getByLabelText('Pi model'), { target: { value: 'deepseek::deepseek-flash' } })
    fireEvent.change(screen.getByLabelText('Pi thinking'), { target: { value: 'high' } })
    fireEvent.click(screen.getByRole('button', { name: '按这句话再查' }))

    await waitFor(() => expect(investigateReconciliation).toHaveBeenCalledWith('deepseek-flash', 'v1', 1, {
      goal: '',
      provider: 'deepseek',
      thinkingLevel: 'high',
    }))
  })

  it('sends a follow-up instruction as the next investigation goal', async () => {
    vi.mocked(investigateReconciliation).mockResolvedValue({
      data: { operation_id: 'op-2', status: 'queued' },
      workspace_version: 'v1',
    } as never)
    renderPanel(investigationWith())

    fireEvent.change(screen.getByLabelText('对 Pi 说'), { target: { value: '不要动 Instructor 0009，那两节 Voice 可以改时' } })
    fireEvent.click(screen.getByRole('button', { name: '按这句话再查' }))

    await waitFor(() => expect(investigateReconciliation).toHaveBeenCalledWith('gpt-5.6-luna', 'v1', 1, {
      goal: '不要动 Instructor 0009，那两节 Voice 可以改时',
      provider: 'openai-codex',
      thinkingLevel: 'off',
    }))
  })

  it('marks an interrupted investigation while keeping a verified package usable', () => {
    renderPanel(investigationWith({
      brief: { ...investigationWith().brief!, termination: 'budget_exhausted' },
    }))

    expect(screen.getByText(/调查被内部上限中断/)).toBeVisible()
    expect(screen.getByRole('button', { name: '应用这个建议' })).toBeEnabled()
  })

  it('refetches the schedule session after apply so the grid updates like a manual assign', async () => {
    vi.mocked(applyReconciliation).mockResolvedValue({
      data: { pi_reconciliation: investigationWith({ status: 'applied' }) },
      workspace_version: 'v2',
      warnings: [],
      error: null,
    } as never)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    render(
      <QueryClientProvider client={queryClient}>
        <PiReconciliationPanel
          activeDay={1}
          disabled={false}
          investigation={investigationWith()}
          piRuntime={runtime}
          workspaceVersion="v1"
        />
      </QueryClientProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: '应用这个建议' }))

    await waitFor(() => expect(applyReconciliation).toHaveBeenCalled())
    expect(invalidate).toHaveBeenCalledWith({ queryKey: schedulerSessionKey })
  })

  it('shows the applied change list and hides the recommendation once applied', () => {
    const investigation = investigationWith({
      status: 'applied',
      brief: {
        ...investigationWith().brief!,
        remaining_issues: [
          { subject_alias: 'issue-9', teacher_alias: 'teacher-1', label: 'Demo: Alpha', reason: '仍未排' },
        ],
      },
      apply_result: {
        simulation_id: 'sim-primary',
        metrics: { resolved_delta: 1, remaining_unresolved: 1, sacrificed_assignments: 1 },
        changes: [changeRows[0]],
        sacrifices: [],
        split_teacher_days: [],
        authorized_sacrifice_aliases: [],
        applied_at: '2026-09-16T01:00:00+00:00',
      },
    })
    investigation.task.prior_thread = { goal: '把这一节排进去', goals: ['先把木管挪开', '把这一节排进去'], termination: 'recommendation_ready' }
    renderPanel(investigation)

    expect(screen.getByRole('heading', { name: 'Pi reconciliation investigator' })).toBeVisible()
    expect(screen.getByText('已应用')).toBeVisible()
    expect(screen.getByLabelText('已完成调整')).toHaveTextContent(/Instructor 0009\s+10:00–11:00\s+R1 → R2/)
    expect(screen.getByLabelText('仍未排')).toHaveTextContent('Instructor 0008 · Demo: Alpha')
    expect(screen.getByText('逐课明细')).toBeVisible()
    expect(screen.queryByText('此前 1 次委托')).toBeNull()
    fireEvent.click(screen.getByText('逐课明细'))
    expect(screen.getByRole('table', { name: /实际完成的变更/ })).toBeVisible()
    expect(screen.queryByRole('button', { name: '应用这个建议' })).toBeNull()
    expect(screen.getByLabelText('对 Pi 说')).toBeVisible()
    expect(screen.getByRole('button', { name: '按这句话再查' })).toBeEnabled()
  })

  it('records a rejected recommendation without applying anything', () => {
    renderPanel(investigationWith({
      brief: {
        ...investigationWith().brief!,
        status: 'rejected',
        decision_note: '这个代价不能接受。',
      },
    }))

    expect(screen.getByText('已标记不采用')).toBeVisible()
    expect(screen.getByText(/这个代价不能接受/)).toBeVisible()
    expect(screen.queryByRole('button', { name: '应用这个建议' })).toBeNull()
  })
})
