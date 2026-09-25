import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyReconciliation, investigateReconciliation, schedulerSessionKey, type PiRuntime } from '../api'
import { extractOperatorConstraints, PiReconciliationPanel } from './PiReconciliationPanel'

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
type DecisionBrief = NonNullable<Investigation['decision_brief']>

const changeRows = [
  {
    subject_alias: 'assignment-1',
    group_alias: 'block-1',
    group_size: 2,
    kind: 'block' as const,
    action: 'move' as const,
    teacher: 'Teacher B',
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
    teacher: 'Teacher A',
    label: 'Mozart: Li',
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

const decisionBrief: DecisionBrief = {
  focus: { question: '把 Teacher B 的区块换到 R2，好安置 Teacher A 吗？', status: 'ready' },
  options: [
    {
      option_id: 'a',
      source: 'primary',
      simulation_id: 'sim-primary',
      changes: changeRows,
      diffs: changeRows,
      metrics: { resolved_delta: 1, remaining_unresolved: 0, moved_assignments: 2, room_switches: 2, sacrificed_assignments: 0 },
      required_teacher_aliases: [],
      sacrifice_aliases: [],
    },
  ],
  common: null,
  comparison: [],
  revision: null,
  teacher_days: [
    {
      teacher: 'teacher-1',
      rows: [{ start: '10:00', end: '11:00', room: 'R1', label: 'Mozart: Li', state: 'placed', variants: {} }],
    },
    {
      teacher: 'teacher-2',
      rows: [{ start: '10:00', end: '11:00', room: 'R2', label: 'Bach: Anna', state: 'moved', variants: {} }],
    },
  ],
  room_views: [
    { room: 'CC407', accepts: ['Voice'], busy: [{ start: '14:00', end: '16:00', label: 'Choir' }] },
  ],
  unknowns: [],
  agent_note: '',
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
    teacher_display: { 'teacher-1': 'Teacher A', 'teacher-2': 'Teacher B' },
    brief: {
      brief_id: 'brief-1',
      investigation_id: 'inv-1',
      snapshot_id: 'snap-1',
      status: 'proposed',
      termination: 'recommendation_ready',
      primary_simulation_id: 'sim-primary',
      title: '换房后安置 A 的课',
      focus_question: '把 Teacher B 的区块换到 R2，好安置 Teacher A 吗？',
      rationale: '把 B 的教师日区块移到 R2，R1 就能安置 A。',
      trade_offs: ['教师 B 当天换一次房。'],
      limitations: ['Searched only that day.'],
      coverage: { subjects_inspected: 1, subjects_total: 1, uninspected_count: 0, simulation_count: 1 },
      created_at: '2026-09-16T00:00:01+00:00',
      agent_note: '',
      sacrifices: [],
      requires_sacrifice_authorization: false,
      same_day_time_change: false,
      pending_decisions: [],
      remaining_issues: [],
    },
    decision_brief: decisionBrief,
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

function renderPanel(investigation: Investigation, disabled = false, piRuntime: PiRuntime = runtime, onHighlightChange?: (highlight: any) => void) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <PiReconciliationPanel
          activeDay={1}
          disabled={disabled}
          investigation={investigation}
          onHighlightChange={onHighlightChange}
          piRuntime={piRuntime}
          workspaceVersion="v1"
        />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  window.localStorage.removeItem('pi-reconciliation-locale')
})

describe('PiReconciliationPanel', () => {
  it('把决定作为页面最强标题，事实来自 decision_brief 而非标题', () => {
    renderPanel(investigationWith())

    expect(screen.getByRole('heading', { name: '把 Teacher B 的区块换到 R2，好安置 Teacher A 吗？' })).toBeVisible()
    expect(screen.getByText('可以直接执行')).toBeVisible()
    // 旧的模型标题不再作为标题展示
    expect(screen.queryByText('换房后安置 A 的课')).not.toBeInTheDocument()
    // 相关背景：教师当天行与教室信息（收纳在“相关教师与琴房安排”折叠层中）
    const contextDisclosure = screen.getByTestId('reconciliation-context-disclosure')
    fireEvent.click(contextDisclosure.querySelector('summary')!)
    expect(screen.getAllByText('Teacher A').length).toBeGreaterThan(0)
    expect(screen.getByText('CC407')).toBeVisible()
    expect(screen.getByText('可排 Voice')).toBeVisible()
    expect(screen.getByText(/占用：14:00–16:00 Choir/)).toBeVisible()
    // 方案变更行
    expect(screen.getByRole('list', { name: '方案 A 变更' })).toHaveTextContent(/Teacher B\s+10:00–11:00\s+R1 → R2/)
    expect(screen.getByRole('list', { name: '方案 A 变更' })).toHaveTextContent(/Teacher A\s+10:00–11:00\s+未排 → R1/)
    expect(screen.getByRole('button', { name: '应用' })).toBeEnabled()
    const refineDisclosure = screen.getByTestId('reconciliation-refine')
    fireEvent.click(refineDisclosure.querySelector('summary')!)
    expect(screen.getByText('上一次的指示:把这一节排进去')).toBeVisible()
    expect(screen.getByText('暂不处理')).toBeVisible()
  })

  it('模型理由与取舍收进折叠的调查过程，不占主区域', () => {
    renderPanel(investigationWith())

    const evidence = screen.getByTestId('reconciliation-evidence')
    expect(evidence).not.toHaveAttribute('open')
    expect(evidence).toHaveTextContent('把 B 的教师日区块移到 R2，R1 就能安置 A。')
    expect(evidence).toHaveTextContent('教师 B 当天换一次房。')
    expect(evidence).toHaveTextContent('Searched only that day.')
    // 逐节明细属于“查看详情”检查层，默认折叠
    const inspect = screen.getByText('查看详情').closest('details')
    expect(inspect).not.toHaveAttribute('open')
    const table = screen.getByRole('table', { name: /方案 A 逐节明细/, hidden: true })
    expect(table).not.toBeVisible()
    // 模型原文只在折叠的调查过程层
    expect(screen.getByText(/把 B 的教师日区块移到 R2，R1 就能安置 A。/)).not.toBeVisible()
  })

  it('无方案结果使用同一骨架，展示未排课与可读的待决定项', () => {
    const stopped = investigationWith({
      simulations: [],
      decision_brief: {
        ...decisionBrief,
        focus: { question: '固定时间下没有可用房间，是否放开 Voice 限制？', status: 'no_package' },
        options: [],
      },
      coverage: { subjects_inspected: 1, subjects_total: 1, uninspected_count: 0, simulation_count: 0 },
      brief: {
        ...investigationWith().brief!,
        termination: 'no_feasible_package_found',
        primary_simulation_id: undefined,
        focus_question: '固定时间下没有可用房间，是否放开 Voice 限制？',
        remaining_issues: [{ subject_alias: 'issue-1', teacher_alias: 'teacher-1', label: 'Mozart: Li', reason: '没有可用房间' }],
      },
    })

    renderPanel(stopped)

    expect(screen.getByTestId('reconciliation-stop-result')).toBeVisible()
    expect(screen.getByText('当前没有可行方案')).toBeVisible()
    expect(screen.getByRole('heading', { name: '固定时间下没有可用房间，是否放开 Voice 限制？' })).toBeVisible()
    expect(screen.getByText(/Teacher A · Mozart: Li/)).toBeVisible()
    expect(screen.queryByRole('button', { name: '应用' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '记录并关闭' })).toBeVisible()
  })

  it('把房间类型例外呈现为可读的授权决定', () => {
    const stopped = investigationWith({
      simulations: [],
      decision_brief: {
        ...decisionBrief,
        focus: { question: 'CC104B 空着但不允许排 Voice，要用例外吗？', status: 'missing_info' },
        options: [],
      },
      brief: {
        ...investigationWith().brief!,
        termination: 'no_feasible_package_found',
        primary_simulation_id: undefined,
        focus_question: 'CC104B 空着但不允许排 Voice，要用例外吗？',
        pending_decisions: [{
          kind: 'exception_authorization',
          detail: 'CC104B 空着但 Voice 不允许；仅在应急时使用。',
          teacher_alias: 'teacher-1',
        }],
        remaining_issues: [{ subject_alias: 'issue-1', teacher_alias: 'teacher-1', label: 'Mozart: Li', reason: '没有合法声乐房' }],
      },
    })

    renderPanel(stopped)

    expect(screen.getByText('例外授权 · Teacher A')).toBeVisible()
    expect(screen.getAllByText(/CC104B 空着但 Voice 不允许/).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: '应用' })).not.toBeInTheDocument()
  })

  it('同日改时例外需征得该老师同意后应用按钮才可用', () => {
    renderPanel(investigationWith({
      decision_brief: {
        ...decisionBrief,
        options: [{
          ...decisionBrief.options![0],
          required_teacher_aliases: ['teacher-2'],
          changes: [{ ...changeRows[0], time_changed: true, to: { room: 'R1', day: 1, start: '11:00', end: '12:00' } }],
        }],
      },
    }, {
      same_day_time_change: true,
      required_teacher_confirmations: [{ teacher_alias: 'teacher-2', confirmation_id: 'confirm-2' }],
      changes: [{ ...changeRows[0], time_changed: true, to: { room: 'R1', day: 1, start: '11:00', end: '12:00' } }],
    }))

    expect(screen.getByText(/包含同日改时例外/)).toBeVisible()
    expect(screen.getByLabelText('已征得 Teacher B 同意')).toBeVisible()
    expect(screen.getByRole('button', { name: '应用' })).toBeDisabled()

    fireEvent.click(screen.getByLabelText('已征得 Teacher B 同意'))
    expect(screen.getByRole('button', { name: '应用' })).toBeEnabled()
  })

  it('牺牲授权逐项勾选后才允许应用', () => {
    const sacrifice = { subject_alias: 'assignment-1', teacher_alias: 'teacher-2', label: 'Bach: Anna', day: 1, start: '10:00', end: '11:00', room: 'R1' }
    renderPanel(investigationWith({
      decision_brief: {
        ...decisionBrief,
        options: [{ ...decisionBrief.options![0], sacrifice_aliases: ['assignment-1'] }],
      },
    }, {
      sacrifices: [sacrifice],
      requires_sacrifice_authorization: true,
      metrics: { resolved_delta: 1, remaining_unresolved: 1, sacrificed_assignments: 1 },
    }))

    expect(screen.getByText(/以下已排课程将退回未排，需逐项授权/)).toBeVisible()
    expect(screen.getByLabelText('授权牺牲 Teacher B 10:00–11:00')).toBeVisible()
    expect(screen.getByRole('button', { name: '应用' })).toBeDisabled()

    fireEvent.click(screen.getByLabelText('授权牺牲 Teacher B 10:00–11:00'))
    expect(screen.getByRole('button', { name: '应用' })).toBeEnabled()
  })

  it('让操作者选择目录模型和思考强度，无需教师白名单', () => {
    renderPanel(investigationWith())

    const refineDisclosure = screen.getByTestId('reconciliation-refine')
    fireEvent.click(refineDisclosure.querySelector('summary')!)
    expect(screen.getByLabelText('给 Pi 的留言')).toBeVisible()
    expect(screen.getByLabelText('Pi 模型')).toHaveValue('openai-codex::gpt-5.6-luna')
    expect(screen.getByRole('option', { name: 'deepseek / deepseek-flash' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'kimi-coding / k3' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'openai-codex / gpt-5.3-codex-spark' })).toBeInTheDocument()
    expect(screen.getByLabelText('思考强度')).toHaveValue('off')
    expect(screen.getByRole('option', { name: 'high' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Teacher B 本次不要动')).toBeNull()
    expect(screen.queryByLabelText('Teacher B 允许同日改时（最后例外）')).toBeNull()
    expect(screen.getByRole('button', { name: '用这些条件重新调查' })).toBeEnabled()
  })

  it('提交所选的 provider、模型和思考强度', async () => {
    vi.mocked(investigateReconciliation).mockResolvedValue({
      data: { operation_id: 'op-1', status: 'queued' },
      workspace_version: 'v1',
    } as never)
    renderPanel(investigationWith())

    fireEvent.change(screen.getByLabelText('Pi 模型'), { target: { value: 'deepseek::deepseek-flash' } })
    fireEvent.change(screen.getByLabelText('思考强度'), { target: { value: 'high' } })
    fireEvent.click(screen.getByRole('button', { name: '用这些条件重新调查' }))

    await waitFor(() => expect(investigateReconciliation).toHaveBeenCalledWith('deepseek-flash', 'v1', 1, {
      goal: '',
      provider: 'deepseek',
      thinkingLevel: 'high',
      protectInstructors: [],
      allowTimeChangeInstructors: [],
    }))
  })

  it('把补充指示作为下一次调查的 goal 发送', async () => {
    vi.mocked(investigateReconciliation).mockResolvedValue({
      data: { operation_id: 'op-2', status: 'queued' },
      workspace_version: 'v1',
    } as never)
    renderPanel(investigationWith())

    fireEvent.change(screen.getByLabelText('给 Pi 的留言'), { target: { value: '不要动 Teacher A，Teacher B 可以改时' } })
    fireEvent.click(screen.getByRole('button', { name: '用这些条件重新调查' }))

    await waitFor(() => expect(investigateReconciliation).toHaveBeenCalledWith('gpt-5.6-luna', 'v1', 1, {
      goal: '不要动 Teacher A，Teacher B 可以改时',
      provider: 'openai-codex',
      thinkingLevel: 'off',
      protectInstructors: ['Teacher A'],
      allowTimeChangeInstructors: ['Teacher B'],
    }))
  })

  it('中断的调查保留可用方案并给出中文提示', () => {
    renderPanel(investigationWith({
      brief: { ...investigationWith().brief!, termination: 'budget_exhausted' },
    }))

    expect(screen.getByText('调查中断 · 有可用方案')).toBeVisible()
    expect(screen.getByText(/调查在完整覆盖前达到内部上限/)).toBeVisible()
    expect(screen.getByRole('button', { name: '应用' })).toBeEnabled()
  })

  it('应用所选方案时携带 scope=option 并刷新课表会话', async () => {
    vi.mocked(applyReconciliation).mockResolvedValue({
      data: { pi_reconciliation: investigationWith({ status: 'applied' }) },
      workspace_version: 'v2',
      warnings: [],
      error: null,
    } as never)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <PiReconciliationPanel
            activeDay={1}
            disabled={false}
            investigation={investigationWith()}
            piRuntime={runtime}
            workspaceVersion="v1"
          />
        </QueryClientProvider>
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole('button', { name: '应用' }))

    await waitFor(() => expect(applyReconciliation).toHaveBeenCalledWith('inv-1', 'sim-primary', 'v1', [], [], '', [], 'option'))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: schedulerSessionKey })
  })

  it('课表变化后提示建议已失效', () => {
    renderPanel(investigationWith({ stale: true }))

    expect(screen.getByText(/此建议已失效/)).toBeVisible()
    expect(screen.getByRole('button', { name: '应用' })).toBeInTheDocument()
  })

  it('应用后展示已生效的调整与剩余未排课', () => {
    const investigation = investigationWith({
      status: 'applied',
      brief: {
        ...investigationWith().brief!,
        remaining_issues: [
          { subject_alias: 'issue-9', teacher_alias: 'teacher-1', label: 'Mozart: Li', reason: 'Still unplaced' },
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
    renderPanel(investigation)

    expect(screen.getByRole('heading', { name: 'PI 排课调查' })).toBeVisible()
    expect(screen.getByText('方案已应用到课表')).toBeVisible()
    expect(screen.getByRole('list', { name: '已应用的调整' })).toHaveTextContent(/Teacher B\s+10:00–11:00\s+R1 → R2/)
    expect(screen.getByRole('list', { name: '仍未安排' })).toHaveTextContent('Teacher A · Mozart: Li')
    const appliedDetails = screen.getByText('查看详情').closest('details')
    expect(appliedDetails).not.toHaveAttribute('open')
    expect(screen.getByRole('table', { name: /实际生效的逐节变更/, hidden: true })).not.toBeVisible()
    expect(screen.queryByRole('button', { name: '应用' })).toBeNull()
    expect(screen.getByLabelText('给 Pi 的留言')).toBeVisible()
    expect(screen.getByRole('button', { name: '用这些条件重新调查' })).toBeEnabled()
  })

  it('记录不采纳的结论，不应用任何变更', () => {
    renderPanel(investigationWith({
      brief: {
        ...investigationWith().brief!,
        status: 'rejected',
        decision_note: '这个代价不能接受。',
      },
    }))

    expect(screen.getByText(/这个结论已记录为不采纳：这个代价不能接受/)).toBeVisible()
    expect(screen.queryByRole('button', { name: '应用' })).toBeNull()
  })

  it('真实案例形态：两个方案 + 共同部分只列一次，变体房间与模型倾向安静呈现', async () => {
    vi.mocked(applyReconciliation).mockResolvedValue({
      data: { pi_reconciliation: investigationWith({ status: 'applied' }) },
      workspace_version: 'v2',
      warnings: [],
      error: null,
    } as never)
    const commonChange = {
      ...changeRows[1],
      subject_alias: 'issue-3',
      group_alias: 'issue-3',
      teacher: 'Teacher A',
      label: 'Mozart: Li',
      from: { room: null, day: 1, start: '09:00', end: '10:00' },
      to: { room: 'CC407', day: 1, start: '09:00', end: '10:00' },
    }
    const optionChangeA = { ...changeRows[0], to: { room: 'CC407', day: 1, start: '10:00', end: '11:00' } }
    const optionChangeB = { ...changeRows[0], to: { room: 'CC408', day: 1, start: '10:00', end: '11:00' } }
    const realCase: Investigation = investigationWith({
      decision_brief: {
        focus: { question: 'CC407 和 CC408 都能安置，选哪一个？', status: 'choice' },
        options: [
          {
            option_id: 'a',
            source: 'primary',
            simulation_id: 'sim-a',
            changes: [commonChange, optionChangeA],
            diffs: [optionChangeA],
            metrics: { resolved_delta: 2, remaining_unresolved: 0, moved_assignments: 1, room_switches: 1, sacrificed_assignments: 0 },
            required_teacher_aliases: [],
            sacrifice_aliases: [],
          },
          {
            option_id: 'b',
            source: 'fallback',
            simulation_id: 'sim-b',
            changes: [commonChange, optionChangeB],
            diffs: [optionChangeB],
            metrics: { resolved_delta: 2, remaining_unresolved: 0, moved_assignments: 1, room_switches: 1, sacrificed_assignments: 0 },
            required_teacher_aliases: [],
            sacrifice_aliases: [],
          },
        ],
        common: { changes: [commonChange], required_teacher_aliases: ['teacher-1'], sacrifice_aliases: [] },
        comparison: [{ label: 'Teacher B 10:00–11:00', values: ['CC407', 'CC408'] }],
        teacher_days: [
          {
            teacher: 'teacher-1',
            rows: [{ start: '10:00', end: '11:00', room: 'CC407', label: 'Mozart: Li', state: 'placed', variants: { a: 'CC407', b: 'CC408' } }],
          },
        ],
        room_views: [
          { room: 'CC407', accepts: ['Voice', 'Piano'], busy: [] },
          { room: 'CC408', accepts: ['Voice'], busy: [{ start: '15:00', end: '16:00', label: 'Violin' }] },
        ],
        unknowns: [{ subject: 'Teacher C 是否接受改时', note: '尚未确认' }],
        agent_note: '两个方案都可行，A 对当天下午影响更小。',
      },
      simulations: [
        { ...simulation, simulation_id: 'sim-a', changes: [optionChangeA] },
        { ...simulation, simulation_id: 'sim-b', changes: [optionChangeB] },
      ],
    })

    renderPanel(realCase)

    expect(screen.getByText('需要你做业务选择')).toBeVisible()
    const compare = screen.getByRole('table', { name: '方案比较' })
    expect(compare).toHaveTextContent('Teacher B 10:00–11:00')
    expect(compare).toHaveTextContent('CC407')
    expect(compare).toHaveTextContent('CC408')
    expect(compare).not.toHaveTextContent('本次共排好')
    expect(compare).not.toHaveTextContent('涉及房间数')
    expect(screen.getByRole('list', { name: '方案 A 变更' })).toHaveTextContent(/→ CC407/)
    expect(screen.getByRole('list', { name: '方案 A 变更' })).not.toHaveTextContent('09:00–10:00')
    expect(screen.getByRole('list', { name: '方案 B 变更' })).toHaveTextContent(/→ CC408/)
    expect(screen.getByRole('list', { name: '方案 B 变更' })).not.toHaveTextContent('09:00–10:00')
    // 教师当天行以变体标出分歧房间
    const contextDisclosure = screen.getByTestId('reconciliation-context-disclosure')
    fireEvent.click(contextDisclosure.querySelector('summary')!)
    expect(screen.getByText('方案 B → CC408')).toBeVisible()
    // 模型倾向安静呈现，只出现一次
    expect(screen.getByText('Pi 的倾向:两个方案都可行，A 对当天下午影响更小。')).toBeVisible()
    // 未核实信息不作为事实
    expect(screen.getByText(/⚠ 未核实：Teacher C 是否接受改时/)).toBeVisible()
    // 共同部分只列一次，且有独立的应用入口
    expect(screen.getAllByRole('list', { name: '共同变更' })).toHaveLength(1)
    expect(screen.getByTestId('reconciliation-common')).toHaveTextContent(/Teacher A\s+09:00–10:00\s+未排 → CC407/)
    // 切换到方案 B 再切回，确认选择可用
    fireEvent.click(screen.getByLabelText('选择方案 B'))
    expect(screen.getByLabelText('选择方案 B')).toBeChecked()
    fireEvent.click(screen.getByLabelText('选择方案 A'))
    // 共同部分需要先征得老师同意
    expect(screen.getByRole('button', { name: '先执行共同部分' })).toBeDisabled()
    fireEvent.click(screen.getByLabelText('已征得 Teacher A 同意'))
    expect(screen.getByRole('button', { name: '先执行共同部分' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: '先执行共同部分' }))
    await waitFor(() => expect(applyReconciliation).toHaveBeenCalledWith('inv-1', '', 'v1', ['teacher-1'], [], '', [], 'common'))
  })

  it('渲染展开阅读与返回课表切换', () => {
    const onToggle = vi.fn()
    const { rerender } = render(
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <PiReconciliationPanel
            activeDay={1}
            disabled={false}
            investigation={investigationWith()}
            piRuntime={null}
            workspaceVersion="v1"
            isReadingExpanded={false}
            onToggleReadingExpanded={onToggle}
          />
        </QueryClientProvider>
      </MemoryRouter>,
    )

    const expandBtn = screen.getByRole('button', { name: '展开阅读' })
    expect(expandBtn).toBeVisible()
    fireEvent.click(expandBtn)
    expect(onToggle).toHaveBeenCalledTimes(1)

    rerender(
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <PiReconciliationPanel
            activeDay={1}
            disabled={false}
            investigation={investigationWith()}
            piRuntime={null}
            workspaceVersion="v1"
            isReadingExpanded={true}
            onToggleReadingExpanded={onToggle}
          />
        </QueryClientProvider>
      </MemoryRouter>,
    )

    expect(screen.getByRole('button', { name: '返回课表' })).toBeVisible()
  })

  it('方案差集为空时只提示与共同部分相同，不重复共同变更', () => {
    const commonChange = {
      ...changeRows[1],
      subject_alias: 'issue-3',
      group_alias: 'issue-3',
      teacher: 'Teacher A',
      label: 'Mozart: Li',
      from: { room: null, day: 1, start: '09:00', end: '10:00' },
      to: { room: 'CC407', day: 1, start: '09:00', end: '10:00' },
    }
    const uniqueA = { ...changeRows[0], to: { room: 'CC407', day: 1, start: '10:00', end: '11:00' } }
    renderPanel(investigationWith({
      decision_brief: {
        ...decisionBrief,
        focus: { question: '共同部分之外，方案 A 还要换房吗？', status: 'choice' },
        options: [
          {
            option_id: 'a',
            source: 'primary',
            simulation_id: 'sim-a',
            changes: [commonChange, uniqueA],
            diffs: [uniqueA],
            metrics: {},
            required_teacher_aliases: [],
            sacrifice_aliases: [],
          },
          {
            option_id: 'b',
            source: 'fallback',
            simulation_id: 'sim-b',
            changes: [commonChange],
            diffs: [],
            metrics: {},
            required_teacher_aliases: [],
            sacrifice_aliases: [],
          },
        ],
        common: { changes: [commonChange], required_teacher_aliases: [], sacrifice_aliases: [] },
        comparison: [{ label: '仍未安排', values: ['无', 'Teacher B 1 节'] }],
      },
      simulations: [
        { ...simulation, simulation_id: 'sim-a', changes: [commonChange, uniqueA] },
        { ...simulation, simulation_id: 'sim-b', changes: [commonChange] },
      ],
    }))

    expect(screen.getByRole('list', { name: '共同变更' })).toHaveTextContent(/09:00–10:00/)
    expect(screen.getByRole('list', { name: '方案 A 变更' })).toHaveTextContent(/→ CC407/)
    expect(screen.queryByRole('list', { name: '方案 B 变更' })).toBeNull()
    expect(screen.getByTestId('reconciliation-option-b')).toHaveTextContent('与共同部分相同')
    expect(screen.getByRole('table', { name: '方案比较' })).toHaveTextContent('仍未安排')
    expect(screen.getByRole('table', { name: '方案比较' })).not.toHaveTextContent('本次共排好')
  })

  it('继续调查时展示 Python 算出的修订效果', () => {
    renderPanel(investigationWith({
      decision_brief: {
        ...decisionBrief,
        revision: {
          instruction: '不要动 Teacher B',
          protect_teachers: ['Teacher B'],
          allow_time_change_teachers: [],
          effects: [{ code: 'protect_applied', text: '已转为硬约束：保护 Teacher B 当天已有安排。' }],
        },
      },
    }))

    const revision = screen.getByTestId('reconciliation-revision')
    expect(revision).toHaveTextContent('本轮指示：不要动 Teacher B')
    expect(revision).toHaveTextContent('已转为硬约束：保护 Teacher B 当天已有安排。')
  })

  it('仅切换 PI 面板语言，默认中文并写入 localStorage', () => {
    renderPanel(investigationWith())
    expect(screen.getByRole('heading', { name: 'PI 排课调查' })).toBeVisible()
    expect(screen.getByRole('button', { name: '应用' })).toBeVisible()
    fireEvent.click(screen.getByTestId('pi-locale-toggle'))
    expect(screen.getByRole('heading', { name: 'PI Reconciliation' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Apply' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Defer' })).toBeVisible()
    expect(window.localStorage.getItem('pi-reconciliation-locale')).toBe('en')
  })

  it('鼠标悬停在变更行时触发 onHighlightChange 并提供老师、起止时间与房间', () => {
    const onHighlightChange = vi.fn()
    renderPanel(investigationWith(), false, runtime, onHighlightChange)

    const list = screen.getByRole('list', { name: '方案 A 变更' })
    const items = within(list).getAllByRole('listitem')
    const changeItem = items.find((item) => item.textContent?.includes('Teacher B'))!
    fireEvent.mouseEnter(changeItem)
    expect(onHighlightChange).toHaveBeenCalledWith({
      teacher: 'Teacher B',
      fromRoom: 'R1',
      toRoom: 'R2',
      start: '10:00',
      end: '11:00',
    })

    fireEvent.mouseLeave(changeItem)
    expect(onHighlightChange).toHaveBeenLastCalledWith(null)
  })

  it('A/B 对比表悬停单元格时分别为 Option A 和 Option B 触发各自真实的目的地房间（非硬编码 CC405）', () => {
    const onHighlightChange = vi.fn()
    const changeA = {
      subject_alias: 'assign-18-a',
      group_alias: 'group-18',
      group_size: 1,
      kind: 'block' as const,
      action: 'move' as const,
      teacher: 'Teacher018',
      label: 'Lesson 18',
      from: { room: 'CC322', day: 1, start: '10:00', end: '13:00' },
      to: { room: 'CC405', day: 1, start: '10:00', end: '13:00' },
      time_changed: false,
      room_changed: true,
      is_sacrifice: false,
    }
    const changeB = {
      subject_alias: 'assign-18-b',
      group_alias: 'group-18',
      group_size: 1,
      kind: 'block' as const,
      action: 'move' as const,
      teacher: 'Teacher018',
      label: 'Lesson 18',
      from: { room: 'CC322', day: 1, start: '10:00', end: '13:00' },
      to: { room: 'CC407', day: 1, start: '10:00', end: '13:00' },
      time_changed: false,
      room_changed: true,
      is_sacrifice: false,
    }

    renderPanel(investigationWith({
      decision_brief: {
        ...decisionBrief,
        focus: { question: '比较两个方案', status: 'choice' },
        options: [
          {
            option_id: 'a',
            source: 'primary',
            simulation_id: 'sim-a',
            changes: [changeA],
            diffs: [changeA],
            metrics: {},
            required_teacher_aliases: [],
            sacrifice_aliases: [],
          },
          {
            option_id: 'b',
            source: 'fallback',
            simulation_id: 'sim-b',
            changes: [changeB],
            diffs: [changeB],
            metrics: {},
            required_teacher_aliases: [],
            sacrifice_aliases: [],
          },
        ],
        comparison: [
          { label: 'Teacher018', values: ['CC320 ➔ CC405', 'CC322 ➔ CC407'] },
        ],
      },
      simulations: [
        { ...simulation, simulation_id: 'sim-a', changes: [changeA] },
        { ...simulation, simulation_id: 'sim-b', changes: [changeB] },
      ],
    }), false, runtime, onHighlightChange)

    const table = screen.getByRole('table', { name: '方案比较' })
    const cells = within(table).getAllByRole('cell')
    // cells[0]: label 'Teacher018', cells[1]: Option A value, cells[2]: Option B value
    expect(cells[1]).toHaveTextContent('CC320 ➔ CC405')
    expect(cells[2]).toHaveTextContent('CC322 ➔ CC407')

    // Hover Option A cell
    fireEvent.mouseEnter(cells[1])
    expect(onHighlightChange).toHaveBeenCalledWith(expect.objectContaining({
      teacher: 'Teacher018',
      toRoom: 'CC405',
    }))

    // Hover Option B cell -> must highlight CC407, NOT CC405
    fireEvent.mouseEnter(cells[2])
    expect(onHighlightChange).toHaveBeenCalledWith(expect.objectContaining({
      teacher: 'Teacher018',
      toRoom: 'CC407',
    }))

    fireEvent.mouseLeave(cells[2])
    expect(onHighlightChange).toHaveBeenLastCalledWith(null)
  })
})

describe('extractOperatorConstraints', () => {
  it('按子句绑定老师，不把保护套到所有人', () => {
    expect(extractOperatorConstraints('不要动 Zhao，WANG 可以改时', ['Zhao', 'WANG', 'Marco'])).toEqual({
      protect: ['Zhao'],
      allow: ['WANG'],
    })
    expect(extractOperatorConstraints('不要动 Teacher B', ['Teacher A', 'Teacher B'])).toEqual({
      protect: ['Teacher B'],
      allow: [],
    })
  })
})
