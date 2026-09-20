import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { ApiClientError } from '../../../api/client'
import {
  applyReconciliation,
  decideReconciliation,
  getOperation,
  investigateReconciliation,
  schedulerResolutionKey,
  schedulerSessionKey,
  type PiRuntime,
  type ResolutionAdvice,
} from '../api'
import styles from '../resolutionPanel.module.css'

type Investigation = NonNullable<ResolutionAdvice['pi_reconciliation']>
type Simulation = Investigation['simulations'][number]
type ChangeRow = Simulation['changes'][number]

const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

type Props = {
  activeDay: number
  disabled: boolean
  investigation: Investigation | null | undefined
  piRuntime?: PiRuntime | null
  workspaceVersion: string | null
}

type RuntimeChoice = { provider: string; model: string }

const DEFAULT_THINKING = ['off', 'minimal', 'low', 'medium', 'high', 'max'] as const

function choiceValue(item: RuntimeChoice): string {
  return `${item.provider}::${item.model}`
}

function parseChoice(value: string): RuntimeChoice {
  const split = value.indexOf('::')
  if (split < 0) return { provider: '', model: value }
  return { provider: value.slice(0, split), model: value.slice(split + 2) }
}

function runtimeChoices(runtime?: PiRuntime | null): RuntimeChoice[] {
  if (runtime?.choices?.length) return runtime.choices.filter((item) => item.provider && item.model)
  const models = (runtime?.allowed_models ?? []).filter(Boolean)
  const fallback = models.length ? models : (runtime?.model ? [runtime.model] : [])
  return fallback.map((model) => ({ provider: runtime?.provider ?? '', model }))
}

function clock(value: unknown): string {
  const text = String(value ?? '')
  return text.length >= 5 ? text.slice(0, 5) : text
}

function placement(value: ChangeRow['from']): string {
  if (!value) return '—'
  const day = typeof value.day === 'number' ? `${dayNames[value.day] ?? value.day} ` : ''
  const room = value.room ? String(value.room) : '未排'
  return `${day}${clock(value.start)}–${clock(value.end)} · ${room}`
}

function simulationHeadline(metrics: Record<string, unknown>): string {
  const parts = [
    `${Number(metrics.resolved_delta ?? 0)} 节新安排`,
    `${Number(metrics.remaining_unresolved ?? 0)} 节仍未排`,
  ]
  if (Number(metrics.moved_assignments ?? 0)) parts.push(`${Number(metrics.moved_assignments)} 节原有安排移动`)
  if (Number(metrics.room_switches ?? 0)) parts.push(`${Number(metrics.room_switches)} 次换房`)
  if (Number(metrics.sacrificed_assignments ?? 0)) parts.push(`${Number(metrics.sacrificed_assignments)} 节被牺牲`)
  return parts.join(' · ')
}

function remainingSummary(who: string, label: string): string {
  const name = String(label || '').replace(/^👤\s*/u, '').replace(/\s*\([^)]*\)\s*$/u, '').trim()
  if (who && name && (name === who || name.includes(who))) return who
  return [who, name].filter(Boolean).join(' · ')
}

type MoveSource = {
  action?: string
  teacher?: string | null
  from?: { room?: string | null; start?: string | null; end?: string | null } | null
  to?: { room?: string | null; start?: string | null; end?: string | null } | null
}

type TeacherMove = {
  action: string
  end: string
  fromRoom: string
  start: string
  teacher: string
  toRoom: string
}

function toMinutes(value: string): number | null {
  const match = clock(value).match(/^(\d{1,2}):(\d{2})$/)
  if (!match) return null
  return Number(match[1]) * 60 + Number(match[2])
}

function groupTeacherMoves(changes: MoveSource[] | undefined): TeacherMove[] {
  const rows = (changes ?? []).map((row) => {
    const withdrawn = row.action === 'withdraw'
    return {
      action: withdrawn ? 'withdraw' : row.action === 'place' ? 'place' : 'move',
      end: clock(row.from?.end ?? row.to?.end),
      fromRoom: withdrawn || row.from?.room ? String(row.from?.room || '未排') : '未排',
      start: clock(row.from?.start ?? row.to?.start),
      teacher: String(row.teacher || '—').trim() || '—',
      toRoom: withdrawn ? '未排' : String(row.to?.room || '未排'),
    }
  }).sort((left, right) => {
    if (left.teacher !== right.teacher) return left.teacher.localeCompare(right.teacher)
    return (toMinutes(left.start) ?? 0) - (toMinutes(right.start) ?? 0)
  })
  const merged: TeacherMove[] = []
  for (const row of rows) {
    const previous = merged.at(-1)
    if (
      previous
      && previous.teacher === row.teacher
      && previous.fromRoom === row.fromRoom
      && previous.toRoom === row.toRoom
      && previous.action === row.action
      && previous.end === row.start
    ) {
      previous.end = row.end
      continue
    }
    merged.push({ ...row })
  }
  return merged
}

function moveLine(move: TeacherMove): string {
  return `${move.teacher}  ${move.start}–${move.end}  ${move.fromRoom} → ${move.toRoom}`
}

function teacherMoveList(changes: MoveSource[] | undefined, label: string) {
  const moves = groupTeacherMoves(changes)
  if (!moves.length) return null
  return <ul aria-label={label} className={styles.remainingSummaries}>
    {moves.map((move) => <li key={`${move.teacher}:${move.start}:${move.fromRoom}:${move.toRoom}`}>{moveLine(move)}</li>)}
  </ul>
}

function remainingTeacherLines(
  items: Array<{ label?: string; subject_alias?: string; teacher_alias?: string | null }>,
  names: Record<string, string>,
): { key: string; text: string }[] {
  const groups = new Map<string, string[]>()
  for (const item of items) {
    const who = String(names[item.teacher_alias ?? ''] || item.teacher_alias || '—')
    const name = remainingSummary('', String(item.label || ''))
    const list = groups.get(who) ?? []
    if (name && !list.includes(name)) list.push(name)
    groups.set(who, list)
  }
  return [...groups.entries()].map(([who, labels]) => ({
    key: who,
    text: labels.length > 0 && labels.length <= 2 ? remainingSummary(who, labels.join('、')) : `${who} · ${Math.max(labels.length, 1)} 节`,
  }))
}

function publicTitle(title: string | undefined, fallback: string): string {
  const text = String(title || '').trim()
  if (!text || /\b(block|issue|teacher|assignment)-\d+\b/i.test(text)) return fallback
  return text
}

function pendingKindLabel(kind: string | undefined): string {
  if (kind === 'business_tradeoff') return '业务取舍'
  if (kind === 'missing_fact') return '缺少事实'
  if (kind === 'exception_authorization') return '需要例外授权'
  return '需要你决定'
}

function pendingList(
  pending: Array<{ kind?: string; detail?: string; teacher_alias?: string | null }> | undefined,
  names: Record<string, string>,
) {
  const items = pending ?? []
  if (!items.length) return null
  return <div>
    <small>需要你决定：</small>
    <ul>{items.map((item, index) => {
      const who = item.teacher_alias ? names[item.teacher_alias] : ''
      return <li key={`pending-${index}`}>{[pendingKindLabel(item.kind), who].filter(Boolean).join(' · ')}</li>
    })}</ul>
  </div>
}

export function PiReconciliationPanel({ activeDay, disabled, investigation, piRuntime, workspaceVersion }: Props) {
  const queryClient = useQueryClient()
  const choices = runtimeChoices(piRuntime)
  const defaultChoice = piRuntime?.provider && piRuntime?.model
    ? choiceValue({ provider: piRuntime.provider, model: piRuntime.model })
    : (choices[0] ? choiceValue(choices[0]) : '')
  const thinkingLevels = (piRuntime?.thinking_levels?.length ? piRuntime.thinking_levels : DEFAULT_THINKING)
    .filter(Boolean)
  const [choiceDraft, setChoice] = useState(defaultChoice)
  const [thinkingDraft, setThinking] = useState(piRuntime?.thinking_level || 'off')
  const allowedChoices = new Set(choices.map(choiceValue))
  const choice = allowedChoices.has(choiceDraft) ? choiceDraft : defaultChoice
  const thinkingDefault = piRuntime?.thinking_level || 'off'
  const thinking = thinkingLevels.includes(thinkingDraft) ? thinkingDraft : thinkingDefault
  const [operationId, setOperationId] = useState('')
  const [note, setNote] = useState('')
  const [goal, setGoal] = useState('')
  const [confirmedBySimulation, setConfirmedBySimulation] = useState<Record<string, string[]>>({})
  const [sacrificesBySimulation, setSacrificesBySimulation] = useState<Record<string, string[]>>({})
  const [fallbackForInvestigation, setFallbackForInvestigation] = useState('')
  const operationQuery = useQuery({
    queryKey: ['pi-reconciliation-operation', operationId],
    queryFn: ({ signal }) => getOperation(operationId, signal),
    enabled: Boolean(operationId),
    refetchInterval: (query) => {
      const status = query.state.data?.data?.status
      return status === 'queued' || status === 'running' ? 500 : false
    },
  })
  const operation = operationQuery.data?.data
  const startMutation = useMutation({
    mutationFn: () => {
      if (!workspaceVersion) throw new Error('Workspace version unavailable')
      const selected = parseChoice(choice)
      return investigateReconciliation(selected.model, workspaceVersion, activeDay, {
        goal,
        provider: selected.provider,
        thinkingLevel: thinking,
      })
    },
    onSuccess: (response) => {
      if (response.data) setOperationId(response.data.operation_id)
    },
  })
  const rejectMutation = useMutation({
    mutationFn: () => {
      if (!workspaceVersion || !investigation?.investigation_id) throw new Error('Investigation unavailable')
      return decideReconciliation(investigation.investigation_id, 'rejected', workspaceVersion, note)
    },
    onSuccess: (response) => {
      queryClient.setQueryData([...schedulerResolutionKey, response.workspace_version], response)
      void queryClient.invalidateQueries({ queryKey: schedulerResolutionKey })
    },
  })
  const applyMutation = useMutation({
    mutationFn: () => {
      if (!workspaceVersion || !investigation?.investigation_id) throw new Error('Investigation unavailable')
      const target = useFallback ? fallback : primary
      if (!target) throw new Error('No recommendation is available')
      const confirmationIds = (target.required_teacher_confirmations ?? [])
        .filter((item) => confirmed.includes(item.teacher_alias))
        .map((item) => item.confirmation_id)
      return applyReconciliation(
        investigation.investigation_id,
        target.simulation_id,
        workspaceVersion,
        confirmed,
        authorizedSacrifices,
        note,
        confirmationIds,
      )
    },
    onSuccess: (response) => {
      queryClient.setQueryData([...schedulerResolutionKey, response.workspace_version], response)
      void queryClient.invalidateQueries({ queryKey: schedulerSessionKey })
      setGoal('')
    },
  })

  useEffect(() => {
    if (operation?.status !== 'completed') return
    void queryClient.invalidateQueries({ queryKey: schedulerResolutionKey })
    void queryClient.invalidateQueries({ queryKey: schedulerSessionKey })
  }, [operation?.id, operation?.status, queryClient])

  const simulations = investigation?.simulations ?? []
  const brief = investigation?.brief
  const primary = simulations.find((item) => item.simulation_id === brief?.primary_simulation_id)
  const fallback = simulations.find((item) => item.simulation_id === brief?.fallback_simulation_id)
  const useFallback = fallbackForInvestigation === investigation?.investigation_id
  const recommended = useFallback && fallback ? fallback : primary
  const recommendedId = recommended?.simulation_id ?? ''
  const confirmed = confirmedBySimulation[recommendedId] ?? []
  const authorizedSacrifices = sacrificesBySimulation[recommendedId] ?? []
  const setConfirmed = (next: string[]) => setConfirmedBySimulation((current) => ({ ...current, [recommendedId]: next }))
  const setAuthorizedSacrifices = (next: string[]) => setSacrificesBySimulation((current) => ({ ...current, [recommendedId]: next }))
  const requiredAliases = (recommended?.required_teacher_confirmations ?? []).map((item) => item.teacher_alias)
  const requiredSacrifices = (recommended?.sacrifices ?? []).map((item) => item.subject_alias)
  const teacherNames = investigation?.teacher_display ?? {}
  const active = disabled
    || startMutation.isPending
    || rejectMutation.isPending
    || applyMutation.isPending
    || operation?.status === 'queued'
    || operation?.status === 'running'
  const error = (startMutation.error ?? rejectMutation.error ?? applyMutation.error ?? operationQuery.error) as ApiClientError | null
  const status = investigation?.status
  const interrupted = brief?.termination === 'budget_exhausted'
  const applied = status === 'applied'
  const applyResult = investigation?.apply_result ?? null
  const stale = Boolean(investigation?.stale) && !applied

  function toggle(list: string[], setList: (next: string[]) => void, value: string, checked: boolean) {
    setList(checked ? [...list, value] : list.filter((item) => item !== value))
  }

  function changeSide(simulation: Simulation | undefined) {
    if (!simulation?.changes?.length) return null
    return <>
      {teacherMoveList(simulation.changes, '教师调整')}
      <details className={styles.piHistory}>
        <summary>逐课明细</summary>
        <table className={styles.changeTable}>
          <caption>预期变更（{simulation.changes.length} 节课）</caption>
          <thead><tr><th>教师</th><th>课程</th><th>原安排</th><th>调整后</th><th>说明</th></tr></thead>
          <tbody>
            {simulation.changes.map((row) => <tr key={`${row.group_alias}-${row.subject_alias}`}>
              <td>{row.teacher || '—'}</td>
              <td>{row.label || row.subject_alias}{row.group_size > 1 ? <small>（教师日区块 {row.group_size} 节）</small> : null}</td>
              <td>{placement(row.from)}</td>
              <td>{row.action === 'withdraw' ? '回到未排（牺牲）' : placement(row.to)}</td>
              <td>{[
                row.action === 'place' ? '安排' : row.action === 'withdraw' ? '撤下' : '移动',
                row.room_changed && row.action !== 'withdraw' ? '换房' : '',
                row.time_changed ? '改时间（例外）' : '',
              ].filter(Boolean).join(' · ')}</td>
            </tr>)}
          </tbody>
        </table>
      </details>
    </>
  }

  function stopResult() {
    if (!brief || recommended) return null
    const remaining = brief.remaining_issues ?? []
    const stoppedByBudget = brief.termination === 'budget_exhausted'
    const needsException = (brief.pending_decisions ?? []).some((item) => item.kind === 'exception_authorization')
    return <article className={styles.piProposal} data-testid="reconciliation-stop-result">
      <header>
        <h4>{publicTitle(brief.title, stoppedByBudget ? '调查达到上限' : needsException ? '合法房间用尽，需要你决定例外' : '未找到可行整包方案')}</h4>
        <span>{brief.status === 'rejected' ? '已记录' : stoppedByBudget ? '调查中断' : needsException ? '需要例外授权' : '无可行方案'}</span>
      </header>
      {pendingList(brief.pending_decisions, teacherNames)}
      {remaining.length ? <div>
        <small>仍未解决：</small>
        <ul>{remainingTeacherLines(remaining, teacherNames).map((item) => (
          <li key={`stop-${item.key}`}>{item.text}</li>
        ))}</ul>
      </div> : null}
      {brief.status === 'proposed' ? <div className={styles.planActions}>
        <textarea aria-label="Reconciliation decision note" maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="决定备注（可选）" value={note} />
        <button disabled={active} onClick={() => rejectMutation.mutate()} type="button">记录并关闭</button>
      </div> : null}
    </article>
  }

  function recommendation() {
    if (!recommended) return null
    if (brief?.status === 'rejected') return <article className={styles.piProposal}>
      <header><h4>{brief.title}</h4><span>已标记不采用</span></header>
      <small>这条调查结论已记录为不采用{brief.decision_note ? `：${brief.decision_note}` : ''}。课表没有改变；需要时调整边界后重新调查。</small>
    </article>
    const pending = brief?.pending_decisions ?? []
    const remaining = brief?.remaining_issues ?? []
    const splits = recommended.split_teacher_days ?? []
    return <article className={styles.piProposal} data-testid="reconciliation-recommendation">
      <header>
        <h4>{publicTitle(brief?.title, simulationHeadline(recommended.metrics ?? {}))}</h4>
        <span>{useFallback ? '备选方案' : '主推荐'}</span>
      </header>
      <small>{groupTeacherMoves(recommended.changes).length} 项调整</small>
      {recommended.same_day_time_change ? <p className={styles.resolutionError}>这个方案包含改时间的例外条款，需要逐位教师确认后才可以应用。</p> : null}
      {changeSide(recommended)}
      {splits.length ? <small>代价：{splits.map((item) => `${teacherNames[item.teacher_alias] ?? item.teacher_alias} 当天将使用 ${(item.rooms ?? []).join(' / ')}`).join('；')}</small> : null}
      {pendingList(pending, teacherNames)}
      {remaining.length ? <div>
        <small>仍未排：</small>
        <ul className={styles.remainingSummaries}>{remainingTeacherLines(remaining, teacherNames).map((item) => (
          <li key={`remaining-${item.key}`}>{item.text}</li>
        ))}</ul>
      </div> : null}
      {requiredSacrifices.length ? <div>
        <small>这个方案会让下列已排区块回到未排，需要你单独授权：</small>
        {teacherMoveList(recommended.sacrifices.map((item) => ({
          action: 'withdraw',
          teacher: teacherNames[item.teacher_alias] ?? item.teacher_alias,
          from: { room: item.room, start: item.start, end: item.end },
        })), '拟撤回')}
      </div> : null}
      {requiredAliases.length ? <div>
        <small>应用前请确认这些教师已经同意具体变化：</small>
        {requiredAliases.map((alias) => <label key={alias}>
          <input
            checked={confirmed.includes(alias)}
            onChange={(event) => toggle(confirmed, setConfirmed, alias, event.target.checked)}
            type="checkbox"
          /> {teacherNames[alias] ?? alias} 已同意
        </label>)}
      </div> : null}
      <div className={styles.planActions}>
        {requiredSacrifices.map((alias) => {
          const item = recommended.sacrifices.find((row) => row.subject_alias === alias)
          const who = teacherNames[item?.teacher_alias ?? ''] ?? item?.teacher_alias ?? alias
          const when = item ? `${clock(item.start)}–${clock(item.end)}` : ''
          return <label key={alias}>
            <input
              checked={authorizedSacrifices.includes(alias)}
              onChange={(event) => toggle(authorizedSacrifices, setAuthorizedSacrifices, alias, event.target.checked)}
              type="checkbox"
            /> 授权牺牲 {who}{when ? ` ${when}` : ''}
          </label>
        })}
        <textarea
          aria-label="Reconciliation decision note"
          maxLength={500}
          onChange={(event) => setNote(event.target.value)}
          placeholder="决定备注（可选，会记入本次任务记录）"
          value={note}
        />
        <button
          disabled={active
            || requiredAliases.some((alias) => !confirmed.includes(alias))
            || requiredSacrifices.some((alias) => !authorizedSacrifices.includes(alias))}
          onClick={() => applyMutation.mutate()}
          type="button"
        >应用这个建议<span aria-hidden="true" className={styles.ctaIcon}>↗</span></button>
        <button disabled={active || applied} onClick={() => rejectMutation.mutate()} type="button">不采用</button>
      </div>
      {interrupted ? <small>调查被内部上限中断，未完成完整覆盖。已验证的方案仍可应用；未覆盖的部分需要另行调查。</small> : null}
    </article>
  }

  const lastInstruction = String(investigation?.task?.goal || '').trim()
  const followUp = Boolean(investigation)
  const remaining = investigation?.brief?.remaining_issues ?? []
  const appliedMoves = groupTeacherMoves(applyResult?.changes)

  return (
    <section className={styles.piIntervention} aria-label="Pi reconciliation investigation">
      <div className={styles.piWorkbenchHeading}>
        <div className={styles.piHeadingTitle}><h2>Pi reconciliation investigator</h2><small>整日委托 · 时间固定 · 保全优先 · 只做沙盒与建议</small></div>
        <div className={styles.piRuntimePickers}>
          <label>Pi model
            <select
              aria-label="Pi model"
              disabled={active || !choices.length}
              onChange={(event) => setChoice(event.target.value)}
              value={choices.some((item) => choiceValue(item) === choice) ? choice : defaultChoice}
            >
              {choices.map((item) => (
                <option key={choiceValue(item)} value={choiceValue(item)}>{`${item.provider} / ${item.model}`}</option>
              ))}
            </select>
          </label>
          <label>Thinking
            <select
              aria-label="Pi thinking"
              disabled={active || !thinkingLevels.length}
              onChange={(event) => setThinking(event.target.value)}
              value={thinkingLevels.includes(thinking) ? thinking : (piRuntime?.thinking_level || 'off')}
            >
              {thinkingLevels.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
      </div>
      <p className={styles.piPrivacy}>一次调查当天的未排与连带调整。Python 校验整包；Pi 不能改课表。不必先勾教师名单。</p>
      {stale ? <p className={styles.resolutionError}>课表已经变化，这份建议已过期；请重新调查后再应用。</p> : null}
      {operation?.status === 'failed' ? <p className={styles.resolutionError} role="alert">{operation.error ?? 'Pi 没有提交调查结论。'}</p> : null}
      {applied && remaining.length ? <ul aria-label="仍未排" className={styles.remainingSummaries}>
        {remainingTeacherLines(remaining, teacherNames).map((item) => (
          <li key={`left-${item.key}`}>{item.text}</li>
        ))}
      </ul> : null}
      <div className={styles.piTalk}>
        {lastInstruction ? <small>你上次说了：{lastInstruction}</small> : null}
        <input
          aria-label="对 Pi 说"
          disabled={active}
          maxLength={600}
          onChange={(event) => setGoal(event.target.value)}
          placeholder={followUp ? '接着说：不要动谁、可以改时、剩下的未排…' : '本次要办成什么（可留空）'}
          type="text"
          value={goal}
        />
        <button disabled={active || !workspaceVersion || !parseChoice(choice).model} onClick={() => startMutation.mutate()} type="button">
          {active ? 'Pi 正在调查…' : followUp
            ? <>按这句话再查<span aria-hidden="true" className={styles.ctaIcon}>↗</span></>
            : <>{`调查 ${dayNames[activeDay] ?? ''} 的连带调整`}<span aria-hidden="true" className={styles.ctaIcon}>↗</span></>}
        </button>
      </div>
      {applied && applyResult ? <article className={styles.piProposal} data-testid="reconciliation-applied">
        <header>
          <h4>已应用</h4>
          <span>{appliedMoves.length} 项调整</span>
        </header>
        {teacherMoveList(applyResult.changes, '已完成调整')}
        {(applyResult.changes ?? []).length ? <details className={styles.piHistory}>
          <summary>逐课明细</summary>
          <table className={styles.changeTable}>
            <caption>实际完成的变更</caption>
            <thead><tr><th>教师</th><th>课程</th><th>原安排</th><th>调整后</th></tr></thead>
            <tbody>
              {(applyResult.changes ?? []).map((row) => <tr key={`applied-${row.group_alias}-${row.subject_alias}`}>
                <td>{row.teacher || '—'}</td>
                <td>{row.label || row.subject_alias}</td>
                <td>{placement(row.from)}</td>
                <td>{row.action === 'withdraw' ? '回到未排（牺牲）' : placement(row.to)}</td>
              </tr>)}
            </tbody>
          </table>
        </details> : null}
        <small>需要修改时可以整体撤销这次应用（Undo），不会自动 Stage 或 Finalize。</small>
      </article> : null}
      {!applied && recommended ? recommendation() : null}
      {!applied && !recommended ? stopResult() : null}
      {!applied && fallback ? <details className={styles.planVariants}>
        <summary>另有备选：{Number(fallback.metrics?.resolved_delta ?? 0)} 节新安排 · {Number(fallback.metrics?.room_switches ?? 0)} 次换房（与主推荐的差别在取舍）</summary>
        <small>{fallback.status === 'conditional' ? '备选需要额外确认或授权。' : '备选可直接应用。'}</small>
        <button disabled={active} onClick={() => { setFallbackForInvestigation(investigation?.investigation_id ?? ''); setConfirmed([]); setAuthorizedSacrifices([]) }} type="button">改用备选</button>
        <button disabled={active || !useFallback} onClick={() => { setFallbackForInvestigation(''); setConfirmed([]); setAuthorizedSacrifices([]) }} type="button">回到主推荐</button>
      </details> : null}
      {error ? <p className={styles.resolutionError} role="alert">{error.message}</p> : null}
    </section>
  )
}
