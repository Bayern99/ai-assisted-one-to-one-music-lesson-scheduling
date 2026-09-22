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
import styles from '../resolutionPanel.module.css'
import {
  COPY,
  fmt,
  localizeFocusQuestion,
  localizeRevisionEffect,
  localizeServerLabel,
  localizeServerValue,
  readPiLocale,
  writePiLocale,
  type PiLocale,
} from './piReconciliationCopy'

type Copy = (typeof COPY)[PiLocale]

type Investigation = NonNullable<ResolutionAdvice['pi_reconciliation']>
type Simulation = Investigation['simulations'][number]
type ChangeRow = Simulation['changes'][number]
type DecisionBrief = NonNullable<Investigation['decision_brief']>
type DecisionOption = NonNullable<DecisionBrief['options']>[number]

const PI_OPERATION_PARAM = 'pi_operation'

type Props = {
  activeDay: number
  disabled: boolean
  investigation: Investigation | null | undefined
  isReadingExpanded?: boolean
  onToggleReadingExpanded?: () => void
  piRuntime?: PiRuntime | null
  workspaceVersion: string | null
}

function statusLabel(c: Copy, key: string): string {
  return ({
    ready: c.statusReady,
    choice: c.statusChoice,
    missing_info: c.statusMissing,
    no_package: c.statusNoPackage,
  }[key] ?? key)
}

function optionLabelFor(c: Copy, optionId: string): string {
  if (optionId === 'a') return c.optionA
  if (optionId === 'b') return c.optionB
  return fmt(c.optionGeneric, { id: optionId.toUpperCase() })
}

function terminationLabel(c: Copy, key: string): string {
  return ({
    recommendation_ready: c.termReady,
    no_feasible_package_found: c.termNoPackage,
    budget_exhausted: c.termBudget,
    runtime_timeout: c.termTimeout,
    crash: c.termCrash,
    interrupted: c.termInterrupted,
    error: c.termError,
  }[key] ?? key)
}

function phaseLabel(c: Copy, key: string): string {
  return ({
    queued: c.phaseQueued,
    preflight: c.phasePreflight,
    investigating: c.phaseInvestigating,
    saving_reconciliation: c.phaseSaving,
    completed: c.phaseCompleted,
    failed: c.phaseFailed,
  }[key] ?? key)
}

function pendingKindLabel(c: Copy, kind: string | undefined): string {
  return ({
    business_tradeoff: c.pendingTradeoff,
    missing_fact: c.pendingFact,
    exception_authorization: c.pendingException,
  }[kind ?? ''] ?? c.pendingDefault)
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

function elapsedSeconds(operation: Operation, now = Date.now()): string {
  if (!operation.started_at) return ''
  const startedMs = Date.parse(operation.started_at)
  if (!Number.isFinite(startedMs)) return ''

  const isTerminal = operation.status === 'completed' || operation.status === 'failed' || operation.phase === 'completed' || operation.phase === 'failed'
  if (isTerminal) {
    const latencyMs = resultNumber(operation.result, 'latency_ms')
    if (latencyMs !== null && latencyMs >= 0) {
      return (latencyMs / 1000).toFixed(1)
    }
    const end = operation.last_activity_at ?? operation.started_at
    const endMs = Date.parse(end)
    if (Number.isFinite(endMs) && endMs >= startedMs) {
      return ((endMs - startedMs) / 1000).toFixed(1)
    }
    return ''
  }

  const ms = Math.max(0, now - startedMs)
  return (ms / 1000).toFixed(1)
}

function resultNumber(result: Operation['result'], key: string): number | null {
  const value = result?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** Latest human-meaningful phase derived from raw events. */
function humanPhase(operation: Operation, c: Copy): string {
  const events = operation.events
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const type = events[index].type
    if (type === 'simulation_started' || type === 'simulation_rejected' || type === 'first_valid_candidate' || type === 'simulation_completed') {
      return c.validating
    }
    if (type === 'inspection_started' || type === 'inspection_completed') {
      return c.inspecting
    }
  }
  return phaseLabel(c, operation.phase)
}

function operationStatusLabel(operation: Operation, c: Copy): string {
  const isCompleted = operation.status === 'completed' || operation.phase === 'completed'
  if (isCompleted) {
    const termination = operation.result?.termination ? String(operation.result.termination) : ''
    return termination ? terminationLabel(c, termination) : c.termReady
  }
  if (operation.status === 'failed' || operation.phase === 'failed') return c.phaseFailed
  if (operation.status === 'timeout') return c.termTimeout
  return humanPhase(operation, c)
}

function operationMetrics(operation: Operation, c: Copy): string {
  const count = (key: string): number | null => resultNumber(operation.result, key)
  const parts = [
    count('simulation_count') !== null ? fmt(c.metricsSim, { n: count('simulation_count') ?? 0 }) : null,
    count('valid_candidates') !== null ? fmt(c.metricsValid, { n: count('valid_candidates') ?? 0 }) : null,
    count('rejected_candidates') ? fmt(c.metricsRejected, { n: count('rejected_candidates') ?? 0 }) : null,
    count('tool_calls') !== null ? fmt(c.metricsTools, { n: count('tool_calls') ?? 0 }) : null,
  ]
  return parts.filter(Boolean).join(' · ')
}

function clock(value: unknown): string {
  const text = String(value ?? '')
  return text.length >= 5 ? text.slice(0, 5) : text
}

function roomLabel(room: unknown, unplaced: string): string {
  const text = String(room ?? '').trim()
  return text || unplaced
}

function placement(value: ChangeRow['from'], c: Copy): string {
  if (!value) return c.unplacedLesson
  return `${clock(value.start)}–${clock(value.end)} · ${roomLabel(value.room, c.unplaced)}`
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

function groupTeacherMoves(changes: ChangeRow[] | undefined, c: Copy): TeacherMove[] {
  const rows = (changes ?? []).map((row) => {
    const withdrawn = row.action === 'withdraw'
    return {
      action: withdrawn ? 'withdraw' : row.action === 'place' ? 'place' : 'move',
      end: clock(row.from?.end ?? row.to?.end),
      fromRoom: roomLabel(row.from?.room, c.unplaced),
      start: clock(row.from?.start ?? row.to?.start),
      teacher: String(row.teacher || '—').trim() || '—',
      toRoom: withdrawn ? c.withdrawn : roomLabel(row.to?.room, c.unplaced),
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

function changeList(changes: ChangeRow[] | undefined, label: string, c: Copy) {
  const moves = groupTeacherMoves(changes, c)
  if (!moves.length) return null
  return <ul aria-label={label} className={styles.remainingSummaries}>
    {moves.map((move) => <li key={`${move.teacher}:${move.start}:${move.fromRoom}:${move.toRoom}`}>{moveLine(move)}</li>)}
  </ul>
}

function remainingTeacherLines(
  items: Array<{ label?: string; subject_alias?: string; teacher_alias?: string | null }>,
  names: Record<string, string>,
  c: Copy,
): { key: string; text: string }[] {
  const groups = new Map<string, string[]>()
  for (const item of items) {
    const who = String(names[item.teacher_alias ?? ''] || item.teacher_alias || '—')
    const name = String(item.label || '').replace(/^👤\s*/u, '').replace(/\s*\([^)]*\)\s*$/u, '').trim()
    const list = groups.get(who) ?? []
    if (name && !list.includes(name)) list.push(name)
    groups.set(who, list)
  }
  return [...groups.entries()].map(([who, labels]) => ({
    key: who,
    text: labels.length > 0 && labels.length <= 2 ? [who, ...labels].filter(Boolean).join(' · ') : `${who} · ${Math.max(labels.length, 1)} ${c.lessons}`,
  }))
}

const NAME_SKIP = new Set(['mr', 'ms', 'mrs', 'dr', 'miss'])

function nameMentioned(text: string, name: string): boolean {
  const folded = text.toLowerCase()
  if (folded.includes(name.toLowerCase())) return true
  return name.split(/[\s.]+/).some((part) => part.length >= 3 && !NAME_SKIP.has(part.toLowerCase()) && folded.includes(part.toLowerCase()))
}

export function extractOperatorConstraints(text: string, teachers: string[]): { protect: string[]; allow: string[] } {
  const names = [...new Set(teachers.map((item) => item.trim()).filter(Boolean))].sort((left, right) => right.length - left.length)
  const protect: string[] = []
  const allow: string[] = []
  const source = text.trim()
  if (!source || !names.length) return { protect, allow }
  const clauses = source.split(/[，。；;\n]+/).map((item) => item.trim()).filter(Boolean)
  for (const clause of clauses.length ? clauses : [source]) {
    const folded = clause.toLowerCase()
    const full = names.filter((name) => folded.includes(name.toLowerCase()))
    const hits = full.length ? full : names.filter((name) => nameMentioned(clause, name))
    const mentioned = hits.filter((name) => !hits.some((other) => other !== name && other.toLowerCase().includes(name.toLowerCase())))
    if (!mentioned.length) continue
    if (/不要动|别动|不许动|保护|先不动/.test(clause)) {
      for (const name of mentioned) if (!protect.includes(name)) protect.push(name)
    }
    if (/改时|改时间/.test(clause)) {
      for (const name of mentioned) if (!allow.includes(name)) allow.push(name)
    }
  }
  return { protect, allow }
}

/**
 * Older investigations may predate decision_brief. Synthesize the same shape
 * from the verified simulations so one render path covers both.
 */
function resolveDecisionBrief(investigation: Investigation | null | undefined): DecisionBrief | null {
  if (!investigation) return null
  if (investigation.decision_brief) return investigation.decision_brief
  const brief = investigation.brief
  const candidates = (investigation.simulations ?? []).filter((sim) => sim.feasible)
  if (!brief || !candidates.length) return null
  const options = candidates.slice(0, 2).map((sim, index): DecisionOption => ({
    option_id: index === 0 ? 'a' : 'b',
    source: index === 0 ? 'primary' : 'fallback',
    simulation_id: sim.simulation_id,
    changes: sim.changes ?? [],
    diffs: sim.changes ?? [],
    metrics: sim.metrics ?? {},
    required_teacher_aliases: (sim.required_teacher_confirmations ?? []).map((item) => item.teacher_alias),
    sacrifice_aliases: (sim.sacrifices ?? []).map((item) => item.subject_alias),
  }))
  return {
    focus: {
      question: brief.focus_question || '如何安排当天剩余的课？',
      status: options.length > 1 ? 'choice' : 'ready',
    },
    options,
    common: null,
    comparison: [],
    revision: null,
    teacher_days: [],
    room_views: [],
    unknowns: [],
    agent_note: brief.agent_note ?? '',
  }
}

export function PiReconciliationPanel({
  activeDay,
  disabled,
  investigation,
  isReadingExpanded,
  onToggleReadingExpanded,
  piRuntime,
  workspaceVersion,
}: Props) {
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
  const [locale, setLocale] = useState<PiLocale>(readPiLocale)
  const c = COPY[locale]
  const [goal, setGoal] = useState('')
  const [chosenOptionId, setChosenOptionId] = useState('')
  const [confirmedByTarget, setConfirmedByTarget] = useState<Record<string, string[]>>({})
  const [sacrificesByTarget, setSacrificesByTarget] = useState<Record<string, string[]>>({})
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
  const isOperationActive = operation?.status === 'queued' || operation?.status === 'running'
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!isOperationActive) return
    setNow(Date.now())
    const interval = setInterval(() => {
      setNow(Date.now())
    }, 100)
    return () => clearInterval(interval)
  }, [isOperationActive, operation?.id])

  const startMutation = useMutation({
    mutationFn: () => {
      if (!workspaceVersion) throw new Error('Workspace version unavailable')
      const selected = parseChoice(choice)
      const names = Object.values(investigation?.teacher_display ?? {}).filter(Boolean)
      const converted = extractOperatorConstraints(goal, names)
      return investigateReconciliation(selected.model, workspaceVersion, activeDay, {
        goal,
        provider: selected.provider,
        thinkingLevel: thinking,
        protectInstructors: converted.protect,
        allowTimeChangeInstructors: converted.allow,
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

  const decisionBrief = resolveDecisionBrief(investigation)
  const brief = investigation?.brief
  const simulations = investigation?.simulations ?? []
  const options = decisionBrief?.options ?? []
  const common = decisionBrief?.common ?? null
  const chosenOption = options.find((item) => item.option_id === chosenOptionId) ?? options[0]
  const teacherNames = investigation?.teacher_display ?? {}
  const teacherName = (alias: string) => teacherNames[alias] ?? alias

  const optionTargetKey = (option: DecisionOption) => `option:${option.option_id}`
  const commonTargetKey = 'common'
  const confirmedFor = (key: string) => confirmedByTarget[key] ?? []
  const sacrificesFor = (key: string) => sacrificesByTarget[key] ?? []
  const setConfirmedFor = (key: string, next: string[]) => setConfirmedByTarget((current) => ({ ...current, [key]: next }))
  const setSacrificesFor = (key: string, next: string[]) => setSacrificesByTarget((current) => ({ ...current, [key]: next }))

  function requiredTeachers(option: DecisionOption): string[] {
    if (option.required_teacher_aliases?.length) return option.required_teacher_aliases
    const sim = simulations.find((item) => item.simulation_id === option.simulation_id)
    return (sim?.required_teacher_confirmations ?? []).map((item) => item.teacher_alias)
  }

  function sacrificeAliases(option: DecisionOption): string[] {
    if (option.sacrifice_aliases?.length) return option.sacrifice_aliases
    const sim = simulations.find((item) => item.simulation_id === option.simulation_id)
    return (sim?.sacrifices ?? []).map((item) => item.subject_alias)
  }

  function isConfirmed(key: string, aliases: string[], authorized: string[], sacrificeAliases: string[]): boolean {
    return aliases.every((alias) => confirmedFor(key).includes(alias))
      && sacrificeAliases.every((alias) => authorized.includes(alias))
  }

  const applyMutation = useMutation({
    mutationFn: () => {
      if (!workspaceVersion || !investigation?.investigation_id) throw new Error('Investigation unavailable')
      if (!chosenOption) throw new Error('No option is available')
      const sim = simulations.find((item) => item.simulation_id === chosenOption.simulation_id)
      const key = optionTargetKey(chosenOption)
      const confirmed = confirmedFor(key)
      const confirmationIds = (sim?.required_teacher_confirmations ?? [])
        .filter((item) => confirmed.includes(item.teacher_alias))
        .map((item) => item.confirmation_id)
      return applyReconciliation(
        investigation.investigation_id,
        chosenOption.simulation_id,
        workspaceVersion,
        confirmed,
        sacrificesFor(key),
        note,
        confirmationIds,
        'option',
      )
    },
    onSuccess: (response) => {
      queryClient.setQueryData([...schedulerResolutionKey, response.workspace_version], response)
      void queryClient.invalidateQueries({ queryKey: schedulerSessionKey })
      setGoal('')
    },
  })

  const applyCommonMutation = useMutation({
    mutationFn: () => {
      if (!workspaceVersion || !investigation?.investigation_id) throw new Error('Investigation unavailable')
      if (!common) throw new Error('No common part is available')
      return applyReconciliation(
        investigation.investigation_id,
        '',
        workspaceVersion,
        confirmedFor(commonTargetKey),
        sacrificesFor(commonTargetKey),
        note,
        [],
        'common',
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

  const active = disabled
    || startMutation.isPending
    || rejectMutation.isPending
    || applyMutation.isPending
    || applyCommonMutation.isPending
    || operation?.status === 'queued'
    || operation?.status === 'running'
  const error = (startMutation.error ?? rejectMutation.error ?? applyMutation.error ?? applyCommonMutation.error ?? (operationNotFound ? null : operationQuery.error)) as ApiClientError | null
  const status = investigation?.status
  const isRuntimeTimeout = status === 'timeout' || (brief?.termination as string) === 'runtime_timeout'
  const interrupted = (brief?.termination as string) === 'budget_exhausted' || status === 'timeout' || status === 'interrupted' || isRuntimeTimeout
  const applied = status === 'applied'
  const applyResult = investigation?.apply_result ?? null
  const stale = Boolean(investigation?.stale) && !applied
  const lastInstruction = String(investigation?.task?.goal || '').trim()
  const remaining = brief?.remaining_issues ?? []
  const pendingMutationError = error

  function toggle(list: string[], setList: (next: string[]) => void, value: string, checked: boolean) {
    setList(checked ? [...list, value] : list.filter((item) => item !== value))
  }

  /** Per-lesson change table — Inspect layer, never the default view. */
  function lessonDetails(changes: ChangeRow[] | undefined, caption: string) {
    if (!changes?.length) return null
    return <details className={styles.piHistory}>
      <summary>{c.inspect}</summary>
      <table className={styles.changeTable}>
        <caption>{caption}</caption>
        <thead><tr><th>{c.colTeacher}</th><th>{c.colLesson}</th><th>{c.colFrom}</th><th>{c.colTo}</th><th>{c.colNote}</th></tr></thead>
        <tbody>
          {changes.map((row) => <tr key={`${row.group_alias}-${row.subject_alias}`}>
            <td>{row.teacher || '—'}</td>
            <td>{row.label || row.subject_alias}{row.group_size > 1 ? <small>{fmt(c.teacherDayBlock, { n: row.group_size })}</small> : null}</td>
            <td>{placement(row.from, c)}</td>
            <td>{row.action === 'withdraw' ? c.withdrawnSacrifice : placement(row.to, c)}</td>
            <td>{[
              row.action === 'place' ? c.place : row.action === 'withdraw' ? c.withdraw : c.move,
              row.room_changed && row.action !== 'withdraw' ? c.roomChange : '',
              row.time_changed ? c.timeChange : '',
            ].filter(Boolean).join(' · ')}</td>
          </tr>)}
        </tbody>
      </table>
    </details>
  }

  function remainingList(ariaLabel: string) {
    if (!remaining.length) return null
    return <div className={styles.remainingGroup}>
      <small className={styles.decisionSubHeading}>{c.stillUnplaced}</small>
      <ul aria-label={ariaLabel} className={styles.remainingSummaries}>
        {remainingTeacherLines(remaining, teacherNames, c).map((item) => (
          <li key={`remaining-${item.key}`}>{item.text}</li>
        ))}
      </ul>
    </div>
  }

  function confirmationCheckboxes(targetKey: string, teacherAliases: string[], sacrificeAliasList: string[], sacrificeSource: Simulation | undefined) {
    return <>
      {teacherAliases.length ? (
        <div className={styles.decisionSubGroup}>
          <small className={styles.decisionSubHeading}>{c.confirmTeachers}</small>
          <div className={styles.checkboxGroup}>
            {teacherAliases.map((alias) => (
              <label key={alias} className={styles.decisionLabel}>
                <input
                  checked={confirmedFor(targetKey).includes(alias)}
                  onChange={(event) => toggle(confirmedFor(targetKey), (next) => setConfirmedFor(targetKey, next), alias, event.target.checked)}
                  type="checkbox"
                />
                <span>{fmt(c.confirmed, { name: teacherName(alias) })}</span>
              </label>
            ))}
          </div>
        </div>
      ) : null}
      {sacrificeAliasList.length ? (
        <div className={styles.decisionSubGroup}>
          <small className={styles.decisionSubHeading}>{c.sacrificeAuth}</small>
          <div className={styles.checkboxGroup}>
            {sacrificeAliasList.map((alias) => {
              const item = sacrificeSource?.sacrifices?.find((row) => row.subject_alias === alias)
              const who = teacherName(item?.teacher_alias ?? alias)
              const when = item?.start && item?.end ? ` ${clock(item.start)}–${clock(item.end)}` : ''
              return (
                <label key={alias} className={styles.decisionLabel}>
                  <input
                    checked={sacrificesFor(targetKey).includes(alias)}
                    onChange={(event) => toggle(sacrificesFor(targetKey), (next) => setSacrificesFor(targetKey, next), alias, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{fmt(c.authorizeSacrifice, { who, when })}</span>
                </label>
              )
            })}
          </div>
        </div>
      ) : null}
    </>
  }

  /** Slot 2 — only teachers and rooms actually involved. */
  function contextSlot() {
    if (!decisionBrief) return null
    const teacherDays = decisionBrief.teacher_days ?? []
    const roomViews = decisionBrief.room_views ?? []
    const unknowns = decisionBrief.unknowns ?? []
    const prior = investigation?.task?.prior_thread
    if (!teacherDays.length && !roomViews.length && !unknowns.length && !prior) return null
    return <aside className={styles.contextColumn}>
      <h3 className={styles.slotHeading}>{c.contextHeading}</h3>
      {teacherDays.map((day) => (
        <div className={styles.teacherDay} key={day.teacher}>
          <strong className={styles.teacherDayName}>{teacherName(day.teacher)}</strong>
          <ul className={styles.teacherDayRows}>
            {(day.rows ?? []).map((row, index) => {
              const variantNotes = Object.entries(row.variants ?? {})
                .filter(([, value]) => (value || '') !== (row.room || ''))
                .map(([key, value]) => ({ key, label: optionLabelFor(c, key), value: value ? String(value) : c.unplaced }))
              return (
                <li key={`${day.teacher}-${index}`} data-state={row.state} className={styles.teacherDayRow}>
                  <span className={styles.teacherDayTime}>{clock(row.start)}–{clock(row.end)}</span>
                  <span className={styles.teacherDayRoom}>{row.room ?? c.unplacedLesson}</span>
                  {row.label ? <span className={styles.teacherDayLabel}>{row.label}</span> : null}
                  {variantNotes.map((note) => <span key={note.key} className={styles.variantNote}>{note.label} → {note.value}</span>)}
                </li>
              )
            })}
          </ul>
        </div>
      ))}
      {roomViews.length ? (
        <div className={styles.roomChips}>
          {roomViews.map((view) => (
            <div className={styles.roomChip} key={view.room}>
              <strong>{view.room}</strong>
              <span>{c.accepts} {view.accepts?.length ? view.accepts.join(locale === 'zh' ? '、' : ', ') : '—'}</span>
              {view.busy?.length
                ? <small>{c.busy}{view.busy.map((item) => `${clock(item.start)}–${clock(item.end)} ${item.label}`).join(locale === 'zh' ? '；' : '; ')}</small>
                : <small>{c.noBusy}</small>}
            </div>
          ))}
        </div>
      ) : null}
      {unknowns.length ? (
        <ul className={styles.unknownList}>
          {unknowns.map((item, index) => (
            <li key={`unknown-${index}`}>{c.unverified}{item.subject}{item.note ? ` — ${item.note}` : ''}</li>
          ))}
        </ul>
      ) : null}
      {prior ? <small className={styles.priorNote}>{fmt(c.priorNote, { goal: prior.goal, termination: terminationLabel(c, prior.termination) })}</small> : null}
    </aside>
  }

  function optionLabel(option: DecisionOption): string {
    return optionLabelFor(c, option.option_id)
  }

  /** Slot 3 — comparison plus per-option blocks; Slot 4 — shared common part. */
  function optionsSlot() {
    if (!decisionBrief || !options.length) return null
    const agentNote = decisionBrief.agent_note?.trim()
    return <div className={styles.optionsColumn}>
      {options.length >= 2 && (decisionBrief.comparison ?? []).length ? (
        <table className={styles.compareTable} aria-label={c.compare}>
          <thead>
            <tr><th>{c.compare}</th>{options.map((option) => <th key={option.option_id}>{optionLabel(option)}</th>)}</tr>
          </thead>
          <tbody>
            {(decisionBrief.comparison ?? []).map((row) => (
              <tr key={row.label}><td>{localizeServerLabel(locale, row.label)}</td>{(row.values ?? []).map((value, index) => <td key={options[index]?.option_id ?? index}>{localizeServerValue(locale, value)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {options.map((option) => (
        <section
          className={styles.optionBlock}
          data-selected={chosenOption?.option_id === option.option_id}
          data-testid={`reconciliation-option-${option.option_id}`}
          key={option.option_id}
        >
          <label className={styles.optionHead}>
            <input
              aria-label={fmt(c.selectOption, { option: optionLabel(option) })}
              checked={chosenOption?.option_id === option.option_id}
              disabled={active}
              name="reconciliation-option"
              onChange={() => setChosenOptionId(option.option_id)}
              type="radio"
            />
            <strong>{optionLabel(option)}</strong>
          </label>
          {changeList(option.diffs ?? option.changes, fmt(c.optionChanges, { option: optionLabel(option) }), c)
            || (decisionBrief.common ? <p className={styles.quietNote}>{c.sameAsCommon}</p> : null)}
          {lessonDetails(option.changes, fmt(c.lessonDetails, { option: optionLabel(option), n: option.changes?.length ?? 0 }))}
        </section>
      ))}
      {agentNote ? <p className={styles.quietNote}>{c.piLeans}{agentNote}</p> : null}
      {common ? (() => {
        const key = commonTargetKey
        const teachers = common.required_teacher_aliases ?? []
        const sacrificeAliasList = common.sacrifice_aliases ?? []
        const ready = !active && isConfirmed(key, teachers, sacrificesFor(key), sacrificeAliasList)
        return <section className={styles.commonBlock} data-testid="reconciliation-common">
          <h3 className={styles.slotHeading}>{c.commonHeading}</h3>
          <p className={styles.quietNote}>{c.commonNote}</p>
          {changeList(common.changes, c.commonChanges, c)}
          {confirmationCheckboxes(key, teachers, sacrificeAliasList, undefined)}
          <div className={styles.commonActionRow}>
            <button disabled={!ready} onClick={() => applyCommonMutation.mutate()} type="button">{c.applyCommon}</button>
          </div>
        </section>
      })() : null}
    </div>
  }

  /** Slot 5 — confirmations gating the apply action for the chosen option. */
  function confirmSlot() {
    if (!chosenOption) return null
    const sim = simulations.find((item) => item.simulation_id === chosenOption.simulation_id)
    const teachers = requiredTeachers(chosenOption)
    const sacrificeAliasList = sacrificeAliases(chosenOption)
    return <section className={styles.confirmSection} data-testid="reconciliation-confirm">
      <h3 className={styles.slotHeading}>{c.confirmHeading}</h3>
      {sim?.same_day_time_change ? (
        <p className={styles.exceptionNotice}>{fmt(c.timeChangeNotice, { option: optionLabel(chosenOption) })}</p>
      ) : null}
      {confirmationCheckboxes(optionTargetKey(chosenOption), teachers, sacrificeAliasList, sim)}
      {!teachers.length && !sacrificeAliasList.length ? (
        <small className={styles.quietNote}>{c.noConfirm}</small>
      ) : null}
    </section>
  }

  /** Slot 6 — steer the next investigation. */
  function continueSlot(guidance: string) {
    return <section className={styles.piTalkProposal}>
      <h3 className={styles.slotHeading}>{c.continueHeading}</h3>
      <p className={styles.piTalkGuidance}>{guidance}</p>
      {lastInstruction ? <small className={styles.lastInstruction}>{fmt(c.lastInstruction, { goal: lastInstruction })}</small> : null}
      <div className={styles.talkInputRow}>
        <input
          aria-label={c.goalAria}
          disabled={active}
          maxLength={600}
          onChange={(event) => setGoal(event.target.value)}
          placeholder={c.goalPlaceholder}
          type="text"
          value={goal}
        />
        <button
          disabled={active || !workspaceVersion || !parseChoice(choice).model}
          onClick={() => startMutation.mutate()}
          type="button"
        >
          {active ? c.investigating : c.reinvestigate}
        </button>
      </div>
    </section>
  }

  /** Evidence layer — technical detail, collapsed by default. */
  function evidenceDetails() {
    const hasEvents = Boolean(operation?.events.length)
    const hasBriefDetail = Boolean(
      brief?.rationale
      || brief?.trade_offs?.length
      || brief?.limitations?.length
      || brief?.pending_decisions?.length
      || brief?.primary_simulation_id,
    )
    if (!hasEvents && !hasBriefDetail) return null
    const coverage = investigation?.coverage ?? {}
    return <details className={styles.evidenceBlock} data-testid="reconciliation-evidence">
      <summary>{c.evidence}</summary>
      <div className={styles.evidenceBody}>
        {typeof coverage.subjects_inspected === 'number' && typeof coverage.subjects_total === 'number'
          ? <small>{fmt(c.coverage, { inspected: coverage.subjects_inspected, total: coverage.subjects_total })}{typeof coverage.simulation_count === 'number' ? ` · ${fmt(c.metricsValid, { n: coverage.simulation_count })}` : ''}</small>
          : null}
        {options.length ? <small>{c.optionIds}{options.map((option) => `${optionLabel(option)}=${option.simulation_id}`).join(' · ')}</small> : null}
        {brief?.primary_simulation_id ? <small>{fmt(c.primarySim, { id: brief.primary_simulation_id })}{brief.fallback_simulation_id ? fmt(c.fallbackSim, { id: brief.fallback_simulation_id }) : ''}</small> : null}
        {operation?.status === 'completed' && operationMetrics(operation, c) ? <small>{operationMetrics(operation, c)}</small> : null}
        {brief?.rationale ? <p><strong>{c.rationale}</strong>{brief.rationale}</p> : null}
        {brief?.trade_offs?.length ? (
          <div><strong>{c.tradeoffs}</strong><ul>{brief.trade_offs.map((item, index) => <li key={`trade-${index}`}>{item}</li>)}</ul></div>
        ) : null}
        {brief?.limitations?.length ? <p><strong>{c.limitations}</strong>{brief.limitations.join(locale === 'zh' ? '；' : '; ')}</p> : null}
        {brief?.pending_decisions?.length ? (
          <div><strong>{c.pendingOriginal}</strong><ul>
            {brief.pending_decisions.map((item, index) => (
              <li key={`pending-${index}`}>
                {pendingKindLabel(c, item.kind)}{item.teacher_alias ? ` · ${teacherName(item.teacher_alias)}` : ''}
                {item.detail ? ` — ${item.detail}` : ''}
              </li>
            ))}
          </ul></div>
        ) : null}
        {operation?.events.length ? (
          <ol className={styles.evidenceEvents}>
            {operation.events.map((event) => <li key={event.seq}>{event.label || event.type}</li>)}
          </ol>
        ) : null}
      </div>
    </details>
  }

  /** Slot 1 — the current decision, strongest headline on the page. */
  function focusBlock(question: string, statusKey: string) {
    return <div className={styles.focusBlock}>
      <span className={styles.statusChip} data-status={statusKey}>{statusLabel(c, statusKey)}</span>
      <h3 className={styles.focusQuestion}>{question}</h3>
      {interrupted ? (
        <div className={styles.interruptedCallout} role="status">
          <strong>{c.interruptedTitle}</strong>
          <p>{isRuntimeTimeout ? c.interruptedTimeout : c.interruptedBudget}</p>
        </div>
      ) : null}
    </div>
  }

  function revisionSlot() {
    const revision = decisionBrief?.revision
    if (!revision) return null
    const effects = revision.effects ?? []
    if (!effects.length && !revision.instruction) return null
    return <section className={styles.revisionBlock} data-testid="reconciliation-revision">
      <h3 className={styles.slotHeading}>{c.revisionHeading}</h3>
      {revision.instruction ? <p>{c.thisRound}{revision.instruction}</p> : null}
      {effects.length ? <ul>{effects.map((item, index) => <li key={`${item.code}-${index}`}>{localizeRevisionEffect(locale, item.code, item.text, revision)}</li>)}</ul> : null}
    </section>
  }

  function decisionView() {
    if (!decisionBrief) return null
    const question = localizeFocusQuestion(locale, decisionBrief.focus.question, decisionBrief.focus.status)
    const key = chosenOption ? optionTargetKey(chosenOption) : ''
    const teachers = chosenOption ? requiredTeachers(chosenOption) : []
    const sacrificeAliasList = chosenOption ? sacrificeAliases(chosenOption) : []
    const applyReady = !active && chosenOption
      && isConfirmed(key, teachers, sacrificesFor(key), sacrificeAliasList)
    return <article data-testid="reconciliation-decision">
      {focusBlock(question, decisionBrief.focus.status)}
      {revisionSlot()}
      <div className={styles.decisionBand}>
        {contextSlot()}
        {optionsSlot()}
      </div>
      {options.length ? confirmSlot() : null}
      {continueSlot(c.continueDecision)}
      {options.length ? (
        <footer className={styles.decisionActions}>
          <input
            aria-label={c.noteAria}
            disabled={active}
            maxLength={500}
            onChange={(event) => setNote(event.target.value)}
            placeholder={c.notePlaceholder}
            type="text"
            value={note}
          />
          <div className={styles.decisionActionButtons}>
            <button disabled={!applyReady} onClick={() => applyMutation.mutate()} type="button">{c.apply}</button>
            <button disabled={active || applied} onClick={() => rejectMutation.mutate()} type="button">{c.defer}</button>
          </div>
        </footer>
      ) : null}
      {evidenceDetails()}
    </article>
  }

  function stopView() {
    if (!brief) return null
    const question = localizeFocusQuestion(locale, decisionBrief?.focus.question || brief.focus_question || '', decisionBrief?.focus.status ?? 'no_package')
    const pending = brief.pending_decisions ?? []
    return <article data-testid="reconciliation-stop-result">
      {focusBlock(question, decisionBrief?.focus.status ?? 'no_package')}
      {revisionSlot()}
      <div className={styles.decisionBand}>
        {contextSlot()}
        <div className={styles.optionsColumn}>
          {remaining.length ? (
            <section>
              <h3 className={styles.slotHeading}>{c.remainingHeading}</h3>
              <ul className={styles.remainingSummaries}>
                {remainingTeacherLines(remaining, teacherNames, c).map((item) => (
                  <li key={`stop-${item.key}`}>{item.text}</li>
                ))}
              </ul>
            </section>
          ) : null}
          {pending.length ? (
            <section>
              <h3 className={styles.slotHeading}>{c.pendingHeading}</h3>
              <ul className={styles.pendingItems}>
                {pending.map((item, index) => (
                  <li key={`pending-${index}`}>
                    <strong>{pendingKindLabel(c, item.kind)}{item.teacher_alias ? ` · ${teacherName(item.teacher_alias)}` : ''}</strong>
                    {item.detail ? <span className={styles.pendingDetail}>{item.detail}</span> : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </div>
      {continueSlot(c.continueStop)}
      {brief.status === 'proposed' ? (
        <footer className={styles.decisionActions}>
          <input
            aria-label={c.noteAria}
            disabled={active}
            maxLength={500}
            onChange={(event) => setNote(event.target.value)}
            placeholder={c.notePlaceholder}
            type="text"
            value={note}
          />
          <div className={styles.decisionActionButtons}>
            <button disabled={active} onClick={() => rejectMutation.mutate()} type="button">{c.recordClose}</button>
          </div>
        </footer>
      ) : null}
      {evidenceDetails()}
    </article>
  }

  function appliedView() {
    if (!applyResult) return null
    return <article data-testid="reconciliation-applied">
      {focusBlock(c.appliedFocus, 'ready')}
      <div className={styles.decisionBand}>
        <div className={styles.contextColumn}>
          <h3 className={styles.slotHeading}>{c.appliedChanges}</h3>
          {changeList(applyResult.changes, c.appliedChanges, c)}
          <small className={styles.quietNote}>{c.appliedNote}</small>
        </div>
        <div className={styles.optionsColumn}>
          {remainingList(c.remainingAria)}
        </div>
      </div>
      {lessonDetails(applyResult.changes, fmt(c.appliedDetails, { n: applyResult.changes?.length ?? 0 }))}
      {continueSlot(c.continueApplied)}
      {evidenceDetails()}
    </article>
  }

  function rejectedView() {
    if (!brief) return null
    return <article data-testid="reconciliation-rejected">
      {focusBlock(localizeFocusQuestion(locale, brief.focus_question || '', 'no_package') || c.rejectedFallback, 'no_package')}
      <p className={styles.rationaleBody}>
        {brief.decision_note ? fmt(c.rejectedBodyNote, { note: brief.decision_note }) : c.rejectedBody}
      </p>
      {continueSlot(c.continueRejected)}
    </article>
  }

  return (
    <section className={styles.piIntervention} aria-label={c.panelAria} lang={locale === 'zh' ? 'zh-CN' : 'en'}>
      <div className={styles.piWorkbenchHeading}>
        <div className={styles.piHeadingTitle}>
          <div className={styles.piHeadingMainRow}>
            <h2>{c.panelTitle}</h2>
            <div className={styles.piHeadingActions}>
              <button
                aria-label={locale === 'zh' ? c.switchToEn : c.switchToZh}
                className={styles.expandReadingButton}
                data-testid="pi-locale-toggle"
                onClick={() => {
                  const next = locale === 'zh' ? 'en' : 'zh'
                  writePiLocale(next)
                  setLocale(next)
                }}
                type="button"
              >
                {c.switchLabel}
              </button>
              {onToggleReadingExpanded ? (
                <button
                  aria-pressed={isReadingExpanded}
                  className={styles.expandReadingButton}
                  onClick={onToggleReadingExpanded}
                  type="button"
                >
                  {isReadingExpanded ? c.backToGrid : c.expandReading}
                  <span aria-hidden="true" className={styles.expandReadingIcon}>
                    {isReadingExpanded ? '◧' : '◨'}
                  </span>
                </button>
              ) : null}
            </div>
          </div>
          <small>{c.tagline}</small>
        </div>
        <div className={styles.piRuntimePickers}>
          <label>{c.model}
            <select
              aria-label={c.model}
              disabled={active || !choices.length}
              onChange={(event) => setChoice(event.target.value)}
              value={choices.some((item) => choiceValue(item) === choice) ? choice : defaultChoice}
            >
              {choices.map((item) => (
                <option key={choiceValue(item)} value={choiceValue(item)}>{`${item.provider} / ${item.model}`}</option>
              ))}
            </select>
          </label>
          <label>{c.thinking}
            <select
              aria-label={c.thinking}
              disabled={active || !thinkingLevels.length}
              onChange={(event) => setThinking(event.target.value)}
              value={thinkingLevels.includes(thinking) ? thinking : (piRuntime?.thinking_level || 'off')}
            >
              {thinkingLevels.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
      </div>
      <p className={styles.piPrivacy}>{c.privacy}</p>
      {stale ? <p className={styles.resolutionError}>{c.stale}</p> : null}
      {operation?.status === 'failed' ? <p className={styles.resolutionError} role="alert">{operation.error ?? c.noResult}</p> : null}
      {operation ? (
        <div className={styles.piProgress} data-testid="pi-progress">
          <small>
            {operationStatusLabel(operation, c)}
            {elapsedSeconds(operation, now) ? ` · ${fmt(c.elapsed, { n: elapsedSeconds(operation, now) ?? '' })}` : ''}
          </small>
          {operation.status === 'completed' && operationMetrics(operation, c) ? (
            <small className="meta">{operationMetrics(operation, c)}</small>
          ) : null}
        </div>
      ) : null}
      {operation?.events.length && (!decisionBrief || isOperationActive) ? (
        <details className={styles.evidenceBlock} data-testid="reconciliation-evidence-running">
          <summary>{c.evidence}</summary>
          <div className={styles.evidenceBody}>
            <ol className={styles.evidenceEvents}>
              {operation.events.map((event) => <li key={event.seq}>{event.label || event.type}</li>)}
            </ol>
          </div>
        </details>
      ) : null}

      {applied && applyResult ? appliedView() : null}
      {!applied && brief?.status === 'rejected' ? rejectedView() : null}
      {!applied && brief?.status !== 'rejected' && options.length ? decisionView() : null}
      {!applied && brief?.status !== 'rejected' && !options.length && brief ? stopView() : null}
      {!applied && !brief && !options.length ? (
        <div className={styles.piTalkInitial}>
          <p className={styles.piTalkGuidance}>
            {c.initialGuidance}
          </p>
          <div className={styles.talkInputRow}>
            <input
              aria-label={c.goalAria}
              disabled={active}
              maxLength={600}
              onChange={(event) => setGoal(event.target.value)}
              placeholder={c.initialPlaceholder}
              type="text"
              value={goal}
            />
            <button
              disabled={active || !workspaceVersion || !parseChoice(choice).model}
              onClick={() => startMutation.mutate()}
              type="button"
            >
              {active ? c.investigating : fmt(c.investigateDay, { day: c.days[activeDay] ?? '' })}
            </button>
          </div>
        </div>
      ) : null}

      {pendingMutationError ? <p className={styles.resolutionError} role="alert">{pendingMutationError.message}</p> : null}
    </section>
  )
}
