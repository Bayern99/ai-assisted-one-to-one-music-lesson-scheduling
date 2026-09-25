import { useMutation, useQueryClient } from '@tanstack/react-query'
import { forwardRef, useState } from 'react'
import type { ApiClientError, ApiEnvelope } from '../../../api/client'
import {
  applyPianoLeverage,
  schedulerResolutionKey,
  schedulerSessionKey,
  setResolutionWaiting,
  useResolutionAdvice,
  type SchedulerSession,
} from '../api'
import type { MoveTarget } from '../hooks/useAssignmentCommands'
import { isReservationInternal } from '../scheduleAuthority'
import { IssueQueue, type Issue } from './IssueQueue'
import { PianoLeverageCard } from './PianoLeverageCard'
import { PiReconciliationPanel, type ReconciliationHighlight } from './PiReconciliationPanel'
import { DraftReviewCard } from './DraftReviewCard'
import { ResolutionCaseCard, type ResolutionSelectionContext } from './ResolutionCaseCard'
import layoutStyles from '../issueQueue.module.css'
import styles from '../resolutionPanel.module.css'

interface ResolutionPanelProps {
  activeDay: number
  disabled: boolean
  expanded?: boolean
  isReadingExpanded?: boolean
  issues: SchedulerSession['issues']
  onDayChange: (day: number) => void
  onDragEnd: () => void
  onDragStart: (issue: Issue) => void
  onHighlightChange?: (highlight: ReconciliationHighlight) => void
  onSelect: (issue: Issue, context?: ResolutionSelectionContext) => void
  onToggleReadingExpanded?: () => void
  onUseOption: (issue: Issue, target: MoveTarget, context?: ResolutionSelectionContext) => void
  selectedIssueId: string | null
  selectedProposal: MoveTarget | null
  workspaceVersion: string | null
}

const DAYS = [
  { day: 1, label: 'Monday', short: 'Mon' },
  { day: 2, label: 'Tuesday', short: 'Tue' },
  { day: 3, label: 'Wednesday', short: 'Wed' },
  { day: 4, label: 'Thursday', short: 'Thu' },
  { day: 5, label: 'Friday', short: 'Fri' },
  { day: 6, label: 'Saturday', short: 'Sat' },
  { day: 0, label: 'Sunday', short: 'Sun' },
]
const WORK_TYPES = [
  { key: 'weekly', label: 'Weekly lessons' },
  { key: 'studio', label: 'Studio' },
  { key: 'other', label: 'Other' },
] as const

function workType(type: string) {
  const value = type.toLowerCase()
  if (value.includes('studio')) return 'studio'
  if (value.includes('weekly')) return 'weekly'
  return 'other'
}

function updateSessionVersion(current: ApiEnvelope<SchedulerSession> | undefined, workspaceVersion: string | null) {
  return current ? { ...current, workspace_version: workspaceVersion } : current
}

export const ResolutionPanel = forwardRef<HTMLElement, ResolutionPanelProps>(function ResolutionPanel(props, ref) {
  const queryClient = useQueryClient()
  const [view, setView] = useState<'recommended' | 'waiting' | 'all'>(props.expanded ? 'recommended' : 'all')
  const adviceQuery = useResolutionAdvice(props.workspaceVersion)
  const advice = adviceQuery.data?.data
  const waitingMutation = useMutation({
    mutationFn: ({ caseId, waiting, note }: { caseId: string; waiting: boolean; note: string }) => {
      if (!props.workspaceVersion) throw new Error('Workspace version unavailable')
      return setResolutionWaiting(caseId, waiting, note, props.workspaceVersion)
    },
    onSuccess: (result) => {
      queryClient.setQueryData(schedulerSessionKey, (current: ApiEnvelope<SchedulerSession> | undefined) => updateSessionVersion(current, result.workspace_version))
      queryClient.setQueryData([...schedulerResolutionKey, result.workspace_version], result)
    },
  })
  const leverageMutation = useMutation({
    mutationFn: ({ proposalId, note }: { proposalId: string; note: string }) => {
      if (!props.workspaceVersion) throw new Error('Workspace version unavailable')
      return applyPianoLeverage(proposalId, props.workspaceVersion, note)
    },
    onSuccess: (result) => {
      queryClient.setQueryData(schedulerSessionKey, result)
      void queryClient.invalidateQueries({ queryKey: schedulerResolutionKey })
    },
  })
  const error = (waitingMutation.error ?? leverageMutation.error ?? adviceQuery.error) as ApiClientError | null
  const allIssues = props.issues.flatMap((group) => group.items)
  const operationalIssues = allIssues.filter((issue) => !isReservationInternal(issue))
  const hasRecommendations = Boolean(advice?.cases.length || advice?.piano_leverage.length)
  const adviceMissedVisibleIssues = Boolean(advice && !hasRecommendations && operationalIssues.length)

  if (!props.expanded && (view === 'all' || (view === 'recommended' && adviceMissedVisibleIssues))) {
    return <IssueQueue expanded={props.expanded} issues={props.issues} onDragEnd={props.onDragEnd} onDragStart={props.onDragStart} onSelect={props.onSelect} onShowRecommended={hasRecommendations ? () => setView('recommended') : undefined} ref={ref} selectedIssueId={props.selectedIssueId} />
  }

  const visibleCases = advice?.cases.filter((item) => view === 'waiting' ? item.waiting : view === 'all' || !item.waiting) ?? []
  const dayCases = visibleCases.filter((item) => item.day === props.activeDay)
  const dayProposals = view === 'recommended'
    ? advice?.piano_leverage.filter((item) => item.target_day === props.activeDay) ?? []
    : []
  const dayCounts = DAYS.map(({ day }) => (advice?.cases
    .filter((item) => item.day === day)
    .reduce((sum, item) => sum + item.issues.length, 0) ?? 0)
    + (advice?.piano_leverage.filter((item) => item.target_day === day).length ?? 0))
  const viewTabs = (
    <div aria-label="Resolution view" className={styles.resolutionTabs} role="group">
      <button aria-pressed={view === 'recommended'} onClick={() => setView('recommended')} type="button">{props.expanded ? 'Open' : 'Recommended'}</button>
      <button aria-pressed={view === 'waiting'} onClick={() => setView('waiting')} type="button">Waiting ({advice?.summary.waiting ?? 0})</button>
      <button aria-pressed={view === 'all'} onClick={() => setView('all')} type="button">All</button>
    </div>
  )
  const weekSummary = advice ? (
    <dl aria-label="Resolution advice summary" className={styles.resolutionSummary}>
      <div><dt>Week · Place now</dt><dd>{advice.summary.place_now}</dd></div>
      <div><dt>Week · Alternatives</dt><dd>{advice.summary.same_day_alternative}</dd></div>
      <div><dt>Week · Blocked</dt><dd>{advice.summary.blocked}</dd></div>
    </dl>
  ) : null
  const caseResults = (
    <div className={styles.resolutionResults}>
      {dayProposals.length ? <section className={styles.typeGroup}><h3>Block moves</h3>{dayProposals.map((proposal) => <PianoLeverageCard disabled={props.disabled || leverageMutation.isPending} key={proposal.id} onApply={(proposalId, note) => leverageMutation.mutate({ proposalId, note })} proposal={proposal} />)}</section> : null}
      {WORK_TYPES.map(({ key, label }) => {
        const cases = dayCases.filter((item) => item.issues.some((issue) => workType(issue.type) === key))
        return cases.length ? <section className={styles.typeGroup} key={key}><h3>{label}</h3>{cases.map((resolutionCase) => (
          <ResolutionCaseCard allIssues={allIssues} disabled={props.disabled || waitingMutation.isPending} key={`${resolutionCase.id}:${key}:${resolutionCase.waiting}:${resolutionCase.waiting_note}`} onSelect={props.onSelect} onSetWaiting={(caseId, waiting, note) => waitingMutation.mutate({ caseId, waiting, note })} onUseOption={props.onUseOption} resolutionCase={resolutionCase} selectedIssueId={props.selectedIssueId} selectedProposal={props.selectedProposal} typeFilter={key} />
        ))}</section> : null
      })}
      {!dayCases.length && !dayProposals.length ? <p className={styles.empty}>{view === 'waiting' ? 'No waiting cases on this day.' : 'No unresolved cases on this day.'}</p> : null}
    </div>
  )
  return (
    <aside aria-label="Needs resolution" className={`${layoutStyles.issueQueue} ${styles.resolutionQueue} ${props.expanded ? styles.resolutionWorkspace : ''}`} data-width={props.expanded ? '420' : '286'} ref={ref} role="region" tabIndex={-1}>
      {props.expanded ? null : <div className={layoutStyles.issueQueueHeading}>
        <div><h2>Resolution desk</h2><p>Teacher-day decisions</p></div>
        <span className="numeric">{advice?.summary.total ?? operationalIssues.length}</span>
      </div>}
      {props.expanded ? <div aria-label="Reconciliation day" className={styles.dayStrip} role="group">
        {DAYS.map(({ day, label, short }, index) => <button aria-label={`${label} ${dayCounts[index]} unresolved`} aria-pressed={props.activeDay === day} key={day} onClick={() => props.onDayChange(day)} type="button"><span>{short}</span><strong>{dayCounts[index]}</strong></button>)}
      </div> : null}
      {advice ? <>
        {props.expanded ? null : viewTabs}
        {props.expanded ? null : weekSummary}
        <div className={styles.resolutionBody}>
          {props.expanded ? null : caseResults}
          {props.expanded ? <PiReconciliationPanel
            activeDay={props.activeDay}
            disabled={props.disabled || waitingMutation.isPending || leverageMutation.isPending || !advice.pi_available}
            investigation={advice.pi_reconciliation?.day === props.activeDay ? advice.pi_reconciliation : null}
            isReadingExpanded={props.isReadingExpanded}
            onHighlightChange={props.onHighlightChange}
            onToggleReadingExpanded={props.onToggleReadingExpanded}
            piRuntime={advice.pi_runtime}
            workspaceVersion={props.workspaceVersion}
          /> : null}
          {props.expanded ? <DraftReviewCard workspaceVersion={props.workspaceVersion} /> : null}
        </div>
      </> : adviceQuery.isPending ? <p className={styles.empty}>Analyzing resolution options…</p> : <p className={styles.empty}>Resolution advice unavailable.</p>}
      {error ? <p className={styles.resolutionError} role="alert">{error.message}</p> : null}
    </aside>
  )
})
