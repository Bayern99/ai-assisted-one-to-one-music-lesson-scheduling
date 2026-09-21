import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { ApiClientError } from '../../../api/client'
import {
  applyReconciliation,
  decideReconciliation,
  getOperation,
  investigateReconciliation,
  schedulerResolutionKey,
  schedulerSessionKey,
  type Operation,
  type PiRuntime,
  type ResolutionAdvice,
} from '../api'
import { PHASE_LABELS } from '../operationPhases'
import styles from '../resolutionPanel.module.css'

type Investigation = NonNullable<ResolutionAdvice['pi_reconciliation']>
type Simulation = Investigation['simulations'][number]
type ChangeRow = Simulation['changes'][number]
type OperationEvent = Operation['events'][number]

const PI_OPERATION_PARAM = 'pi_operation'

const TERMINATION_LABELS: Record<string, string> = {
  recommendation_ready: 'Investigation complete',
  no_feasible_package_found: 'No feasible package found',
  budget_exhausted: 'Exploration limit reached',
  runtime_timeout: 'Runtime limit reached',
  crash: 'Pi process exited unexpectedly',
  interrupted: 'Investigation interrupted',
  error: 'Investigation failed',
}

const TOOL_LABELS: Record<string, string> = {
  inspect_reconciliation: 'inspect occupancy',
  simulate_reconciliation_package: 'simulate package',
  submit_reconciliation_brief: 'submit brief',
}

function progressEventLabel(event: OperationEvent): string {
  const detail = event.detail ?? {}
  switch (event.type) {
    case 'investigation_started': return 'Investigation started'
    case 'process_spawned': return 'Pi process started'
    case 'first_agent_activity': return 'Pi first response'
    case 'agent_alive': return 'Pi agent started'
    case 'turn_activity': return 'Model working'
    case 'model_tool_request': return `Model requested ${TOOL_LABELS[String(detail.tool)] ?? String(detail.tool ?? 'tool')}`
    case 'model_tool_end': return 'Tool execution finished'
    case 'provider_retry': return `Provider retry ${Number(detail.attempt ?? 0)}/${Number(detail.max_attempts ?? 0)}`
    case 'provider_retry_end': return `Provider retry ${detail.success ? 'succeeded' : 'failed'}`
    case 'inspection_started': return "Analyzing the day's schedule"
    case 'inspection_completed': return 'Occupancy inspected'
    case 'inspection_rejected': return `Inspection rejected by Python: ${String(detail.reason ?? '')}`
    case 'simulation_started': return 'Simulating a candidate package'
    case 'simulation_rejected': return `Package rejected by Python validation: ${String(detail.reason ?? '')}`
    case 'first_valid_candidate': return 'Found a valid candidate'
    case 'simulation_completed': return detail.feasible ? 'Candidate package is feasible' : 'Candidate package not feasible'
    case 'brief_submitted': return 'Brief submitted'
    case 'investigation_closed': return 'Investigation closed at a bound'
    case 'investigation_interrupted': return 'Investigation stopped at a runtime bound'
    case 'agent_settled': return 'Pi finished'
    default: return event.label || event.type
  }
}

function elapsedSeconds(operation: Operation): string {
  if (!operation.started_at) return ''
  const end = operation.last_activity_at ?? operation.started_at
  const ms = Date.parse(end) - Date.parse(operation.started_at)
  if (!Number.isFinite(ms) || ms < 0) return ''
  return (ms / 1000).toFixed(1)
}

function resultNumber(result: Operation['result'], key: string): number | null {
  const value = result?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function operationMetrics(operation: Operation): string {
  const count = (key: string): number | null => resultNumber(operation.result, key)
  const plural = (value: number | null, singular: string): string | null =>
    value === null ? null : `${value} ${singular}${value === 1 ? '' : 's'}`
  const parts = [
    count('latency_ms') !== null ? `took ${(count('latency_ms')! / 1000).toFixed(1)}s` : null,
    plural(count('tool_calls'), 'tool call'),
    plural(count('simulation_count'), 'candidate package'),
    count('rejected_candidates') ? `${count('rejected_candidates')} rejected by Python` : null,
    plural(count('valid_candidates'), 'usable candidate'),
  ]
  return parts.filter(Boolean).join(' · ')
}

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
  const room = value.room ? String(value.room) : 'Unplaced'
  return `${day}${clock(value.start)}–${clock(value.end)} · ${room}`
}

function simulationHeadline(metrics: Record<string, unknown>): string {
  const parts = [
    `${Number(metrics.resolved_delta ?? 0)} newly placed`,
    `${Number(metrics.remaining_unresolved ?? 0)} still unplaced`,
  ]
  if (Number(metrics.moved_assignments ?? 0)) parts.push(`${Number(metrics.moved_assignments)} moved`)
  if (Number(metrics.room_switches ?? 0)) parts.push(`${Number(metrics.room_switches)} room switches`)
  if (Number(metrics.sacrificed_assignments ?? 0)) parts.push(`${Number(metrics.sacrificed_assignments)} sacrificed`)
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
      fromRoom: withdrawn || row.from?.room ? String(row.from?.room || 'Unplaced') : 'Unplaced',
      start: clock(row.from?.start ?? row.to?.start),
      teacher: String(row.teacher || '—').trim() || '—',
      toRoom: withdrawn ? 'Unplaced' : String(row.to?.room || 'Unplaced'),
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
    text: labels.length > 0 && labels.length <= 2 ? remainingSummary(who, labels.join(', ')) : `${who} · ${Math.max(labels.length, 1)} lessons`,
  }))
}

function publicTitle(title: string | undefined, fallback: string): string {
  const text = String(title || '').trim()
  if (!text || /\b(block|issue|teacher|assignment)-\d+\b/i.test(text)) return fallback
  return text
}

function pendingKindLabel(kind: string | undefined): string {
  if (kind === 'business_tradeoff') return 'Business trade-off'
  if (kind === 'missing_fact') return 'Missing fact'
  if (kind === 'exception_authorization') return 'Exception authorization'
  return 'Needs your decision'
}

function pendingList(
  pending: Array<{ kind?: string; detail?: string; teacher_alias?: string | null }> | undefined,
  names: Record<string, string>,
) {
  const items = pending ?? []
  if (!items.length) return null
  return <div>
    <small>Decisions needed:</small>
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
  const [searchParams, setSearchParams] = useSearchParams()
  const [operationId, setOperationId] = useState(() => searchParams.get(PI_OPERATION_PARAM) ?? '')
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
  const operationNotFound = (operationQuery.error as ApiClientError | null)?.code === 'OPERATION_NOT_FOUND'
  const operation = operationNotFound ? undefined : operationQuery.data?.data
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
      if (!response.data) return
      setOperationId(response.data.operation_id)
      setSearchParams((current) => {
        const next = new URLSearchParams(current)
        next.set(PI_OPERATION_PARAM, response.data!.operation_id)
        return next
      }, { replace: true })
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

  useEffect(() => {
    // Only a missing operation drops the durable handle; a completed or failed
    // investigation keeps it so the final timeline stays visible after remounts.
    if (!operationId || !operationNotFound) return
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.delete(PI_OPERATION_PARAM)
      return next
    }, { replace: true })
  }, [operationId, operationNotFound, setSearchParams])

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
  const error = (startMutation.error ?? rejectMutation.error ?? applyMutation.error ?? (operationNotFound ? null : operationQuery.error)) as ApiClientError | null
  const status = investigation?.status
  const interrupted = brief?.termination === 'budget_exhausted'
  const interruptedHint = status === 'timeout'
    ? 'The investigation was cut off by the runtime limit. Verified packages remain applicable; the uncovered part needs a new investigation.'
    : 'The investigation was cut off by the internal limit before full coverage. Verified packages remain applicable; the uncovered part needs a new investigation.'
  const applied = status === 'applied'
  const applyResult = investigation?.apply_result ?? null
  const stale = Boolean(investigation?.stale) && !applied

  function toggle(list: string[], setList: (next: string[]) => void, value: string, checked: boolean) {
    setList(checked ? [...list, value] : list.filter((item) => item !== value))
  }

  function changeSide(simulation: Simulation | undefined) {
    if (!simulation?.changes?.length) return null
    return <>
      {teacherMoveList(simulation.changes, 'Teacher adjustments')}
      <details className={styles.piHistory}>
        <summary>Per-lesson details</summary>
        <table className={styles.changeTable}>
          <caption>Expected changes ({simulation.changes.length} lessons)</caption>
          <thead><tr><th>Teacher</th><th>Lesson</th><th>From</th><th>To</th><th>Notes</th></tr></thead>
          <tbody>
            {simulation.changes.map((row) => <tr key={`${row.group_alias}-${row.subject_alias}`}>
              <td>{row.teacher || '—'}</td>
              <td>{row.label || row.subject_alias}{row.group_size > 1 ? <small> (teacher-day block of {row.group_size} lessons)</small> : null}</td>
              <td>{placement(row.from)}</td>
              <td>{row.action === 'withdraw' ? 'Back to unplaced (sacrificed)' : placement(row.to)}</td>
              <td>{[
                row.action === 'place' ? 'Place' : row.action === 'withdraw' ? 'Withdraw' : 'Move',
                row.room_changed && row.action !== 'withdraw' ? 'room change' : '',
                row.time_changed ? 'time change (exception)' : '',
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
        <h4>{publicTitle(brief.title, stoppedByBudget ? 'Investigation limit reached' : needsException ? 'No legal rooms left; an exception decision is needed' : 'No feasible complete package found')}</h4>
        <span>{brief.status === 'rejected' ? 'Recorded' : stoppedByBudget ? 'Interrupted' : needsException ? 'Exception needed' : 'No feasible package'}</span>
      </header>
      {pendingList(brief.pending_decisions, teacherNames)}
      {brief.limitations?.length ? <small>Limitations: {brief.limitations.join('; ')}</small> : null}
      {remaining.length ? <div>
        <small>Still unresolved:</small>
        <ul>{remainingTeacherLines(remaining, teacherNames).map((item) => (
          <li key={`stop-${item.key}`}>{item.text}</li>
        ))}</ul>
      </div> : null}
      {brief.status === 'proposed' ? <div className={styles.planActions}>
        <textarea aria-label="Reconciliation decision note" maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="Decision note (optional)" value={note} />
        <button disabled={active} onClick={() => rejectMutation.mutate()} type="button">Record and close</button>
      </div> : null}
    </article>
  }

  function recommendation() {
    if (!recommended) return null
    if (brief?.status === 'rejected') return <article className={styles.piProposal}>
      <header><h4>{brief.title}</h4><span>Marked as not pursued</span></header>
      <small>This conclusion was recorded as not pursued{brief.decision_note ? `: ${brief.decision_note}` : ''}. The schedule is unchanged; adjust the boundaries and investigate again when needed.</small>
    </article>
    const pending = brief?.pending_decisions ?? []
    const remaining = brief?.remaining_issues ?? []
    const splits = recommended.split_teacher_days ?? []
    return <article className={styles.piProposal} data-testid="reconciliation-recommendation">
      <header>
        <h4>{publicTitle(brief?.title, simulationHeadline(recommended.metrics ?? {}))}</h4>
        <span>{useFallback ? 'Alternative' : 'Primary'}</span>
      </header>
      <small>{groupTeacherMoves(recommended.changes).length} adjustments</small>
      {recommended.same_day_time_change ? <p className={styles.resolutionError}>This package contains a time-change exception; every listed teacher must confirm before it can be applied.</p> : null}
      {changeSide(recommended)}
      {splits.length ? <small>Cost: {splits.map((item) => `${teacherNames[item.teacher_alias] ?? item.teacher_alias} will use ${(item.rooms ?? []).join(' / ')}`).join('; ')}</small> : null}
      {pendingList(pending, teacherNames)}
      {brief?.limitations?.length ? <small>Limitations: {brief.limitations.join('; ')}</small> : null}
      {remaining.length ? <div>
        <small>Still unplaced:</small>
        <ul className={styles.remainingSummaries}>{remainingTeacherLines(remaining, teacherNames).map((item) => (
          <li key={`remaining-${item.key}`}>{item.text}</li>
        ))}</ul>
      </div> : null}
      {requiredSacrifices.length ? <div>
        <small>This package returns the following scheduled lessons to unplaced; authorize each separately:</small>
        {teacherMoveList(recommended.sacrifices.map((item) => ({
          action: 'withdraw',
          teacher: teacherNames[item.teacher_alias] ?? item.teacher_alias,
          from: { room: item.room, start: item.start, end: item.end },
        })), 'To withdraw')}
      </div> : null}
      {requiredAliases.length ? <div>
        <small>Confirm each teacher has agreed to the exact change before applying:</small>
        {requiredAliases.map((alias) => <label key={alias}>
          <input
            checked={confirmed.includes(alias)}
            onChange={(event) => toggle(confirmed, setConfirmed, alias, event.target.checked)}
            type="checkbox"
          /> {teacherNames[alias] ?? alias} has agreed
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
            /> Authorize sacrifice {who}{when ? ` ${when}` : ''}
          </label>
        })}
        <textarea
          aria-label="Reconciliation decision note"
          maxLength={500}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Decision note (optional, recorded in this task record)"
          value={note}
        />
        <button
          disabled={active
            || requiredAliases.some((alias) => !confirmed.includes(alias))
            || requiredSacrifices.some((alias) => !authorizedSacrifices.includes(alias))}
          onClick={() => applyMutation.mutate()}
          type="button"
        >Apply this recommendation<span aria-hidden="true" className={styles.ctaIcon}>↗</span></button>
        <button disabled={active || applied} onClick={() => rejectMutation.mutate()} type="button">Reject</button>
      </div>
      {interrupted ? <small>{interruptedHint}</small> : null}
    </article>
  }

  const lastInstruction = String(investigation?.task?.goal || '').trim()
  const followUp = Boolean(investigation)
  const remaining = investigation?.brief?.remaining_issues ?? []
  const appliedMoves = groupTeacherMoves(applyResult?.changes)

  return (
    <section className={styles.piIntervention} aria-label="Pi reconciliation investigation">
      <div className={styles.piWorkbenchHeading}>
        <div className={styles.piHeadingTitle}><h2>Pi reconciliation investigator</h2><small>Whole-day delegation · fixed times · preserve-first · sandbox and advice only</small></div>
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
      <p className={styles.piPrivacy}>One investigation covers the day's unplaced lessons and their linked adjustments. Python validates every package; Pi cannot edit the schedule. No teacher checklist needed first.</p>
      {stale ? <p className={styles.resolutionError}>The schedule changed; this recommendation is stale. Investigate again before applying.</p> : null}
      {operation?.status === 'failed' ? <p className={styles.resolutionError} role="alert">{operation.error ?? 'Pi did not submit an investigation brief.'}</p> : null}
      {operation ? (
        <div className={styles.piProgress} data-testid="pi-progress">
          <small>
            {operation.phase === 'completed'
              ? 'Investigation complete'
              : operation.phase === 'failed'
                ? 'Investigation failed'
                : PHASE_LABELS[operation.phase] ?? operation.phase}
            {elapsedSeconds(operation) ? ` · elapsed ${elapsedSeconds(operation)}s` : ''}
            {operation.status === 'completed'
              && operation.result?.termination
              && operation.result.termination !== 'recommendation_ready'
              ? ` · ${TERMINATION_LABELS[String(operation.result.termination)] ?? String(operation.result.termination)}`
              : ''}
          </small>
          {operation.events.length ? (
            <ol className={styles.piProgressEvents}>
              {operation.events.slice(-6).map((event) => (
                <li key={event.seq}>{progressEventLabel(event)}</li>
              ))}
            </ol>
          ) : null}
          {operation.status === 'completed' && operationMetrics(operation) ? (
            <small className="meta">{operationMetrics(operation)}</small>
          ) : null}
        </div>
      ) : null}
      {applied && remaining.length ? <ul aria-label="Still unplaced" className={styles.remainingSummaries}>
        {remainingTeacherLines(remaining, teacherNames).map((item) => (
          <li key={`left-${item.key}`}>{item.text}</li>
        ))}
      </ul> : null}
      <div className={styles.piTalk}>
        {lastInstruction ? <small>Your last instruction: {lastInstruction}</small> : null}
        <input
          aria-label="Message to Pi"
          disabled={active}
          maxLength={600}
          onChange={(event) => setGoal(event.target.value)}
          placeholder={followUp ? 'Continue: who not to touch, time-change exceptions, the remaining unplaced…' : 'What should this run achieve? (optional)'}
          type="text"
          value={goal}
        />
        <button disabled={active || !workspaceVersion || !parseChoice(choice).model} onClick={() => startMutation.mutate()} type="button">
          {active ? 'Pi is investigating…' : followUp
            ? <>Investigate again with this<span aria-hidden="true" className={styles.ctaIcon}>↗</span></>
            : <>{`Investigate ${dayNames[activeDay] ?? ''}'s linked adjustments`}<span aria-hidden="true" className={styles.ctaIcon}>↗</span></>}
        </button>
      </div>
      {applied && applyResult ? <article className={styles.piProposal} data-testid="reconciliation-applied">
        <header>
          <h4>Applied</h4>
          <span>{appliedMoves.length} adjustments</span>
        </header>
        {teacherMoveList(applyResult.changes, 'Applied adjustments')}
        {(applyResult.changes ?? []).length ? <details className={styles.piHistory}>
          <summary>Per-lesson details</summary>
          <table className={styles.changeTable}>
            <caption>Changes actually applied</caption>
            <thead><tr><th>Teacher</th><th>Lesson</th><th>From</th><th>To</th></tr></thead>
            <tbody>
              {(applyResult.changes ?? []).map((row) => <tr key={`applied-${row.group_alias}-${row.subject_alias}`}>
                <td>{row.teacher || '—'}</td>
                <td>{row.label || row.subject_alias}</td>
                <td>{placement(row.from)}</td>
                <td>{row.action === 'withdraw' ? 'Back to unplaced (sacrificed)' : placement(row.to)}</td>
              </tr>)}
            </tbody>
          </table>
        </details> : null}
        <small>You can undo this application as a whole if needed; it does not auto-Stage or Finalize.</small>
      </article> : null}
      {!applied && recommended ? recommendation() : null}
      {!applied && !recommended ? stopResult() : null}
      {!applied && fallback ? <details className={styles.planVariants}>
        <summary>Alternative: {Number(fallback.metrics?.resolved_delta ?? 0)} newly placed · {Number(fallback.metrics?.room_switches ?? 0)} room switches (different trade-offs from the primary)</summary>
        <small>{fallback.status === 'conditional' ? 'The alternative needs extra confirmations or authorization.' : 'The alternative can be applied directly.'}</small>
        <button disabled={active} onClick={() => { setFallbackForInvestigation(investigation?.investigation_id ?? ''); setConfirmed([]); setAuthorizedSacrifices([]) }} type="button">Use alternative</button>
        <button disabled={active || !useFallback} onClick={() => { setFallbackForInvestigation(''); setConfirmed([]); setAuthorizedSacrifices([]) }} type="button">Back to primary</button>
      </details> : null}
      {error ? <p className={styles.resolutionError} role="alert">{error.message}</p> : null}
    </section>
  )
}
