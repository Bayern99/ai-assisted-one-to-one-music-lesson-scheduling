import { forwardRef, useState } from 'react'
import { SECTION_TITLES } from '../../../app/productLanguage'
import type { SchedulerSession } from '../api'
import {
  isReservationInternal,
  issueReservationNote,
} from '../scheduleAuthority'
import resolutionStyles from '../resolutionPanel.module.css'
import styles from '../issueQueue.module.css'

export type Issue = SchedulerSession['issues'][number]['items'][number]

function contextLabel(issue: Issue) {
  const schedule = [issue.original_date, issue.original_time].filter(Boolean).join(' · ')
  const identity = issue.student_name ?? issue.instructor
  if (identity || schedule) return [identity, schedule].filter(Boolean).join(' · ')
  const payload = issue.payload ?? {}
  const nested = payload.raw_row !== null && typeof payload.raw_row === 'object' && !Array.isArray(payload.raw_row)
    ? payload.raw_row as Record<string, unknown>
    : {}
  return Object.entries({ ...nested, ...payload }).flatMap(([key, value]) => {
    if (!['instructor', 'Instructor', 'room', 'Room', 'resourceId', 'start', 'startTime', 'Class Time', 'day', 'Day of Week'].includes(key)) return []
    return typeof value === 'string' || typeof value === 'number' ? [`${key}: ${value}`] : []
  }).join(', ')
}

interface IssueQueueProps {
  expanded?: boolean
  issues: SchedulerSession['issues']
  onDragEnd?: () => void
  onDragStart?: (issue: Issue) => void
  onSelect: (issue: Issue) => void
  selectedIssueId: string | null
  onShowRecommended?: () => void
}

export const IssueQueue = forwardRef<HTMLElement, IssueQueueProps>(function IssueQueue({ expanded = false, issues, onDragEnd, onDragStart, onSelect, selectedIssueId, onShowRecommended }, ref) {
  const [reasonFilter, setReasonFilter] = useState<string | null>(null)
  const total = issues.reduce((sum, group) => sum + group.count, 0)
  const operationalGroups = issues.map((group) => ({
    ...group,
    items: group.items.filter((issue) => !isReservationInternal(issue)),
  }))
  const reservationIssues = issues.flatMap((group) => group.items.filter((issue) => isReservationInternal(issue)))
  const visibleIssues = operationalGroups
    .filter((group) => !reasonFilter || group.reason_code === reasonFilter)
    .flatMap((group) => group.items)
  return (
    <aside aria-label="Needs resolution" className={`${styles.issueQueue} ${onShowRecommended ? styles.issueQueueWithTabs : ''} ${expanded ? styles.issueQueueExpanded : ''}`} data-width={expanded ? 'fluid' : '286'} ref={ref} role="region" tabIndex={-1}>
      <div className={styles.issueQueueHeading}>
        <div><h2>{SECTION_TITLES.needsResolution}</h2><p>Grouped by root cause</p></div>
        <span className="numeric">{total}</span>
      </div>
      {onShowRecommended ? (
        <div aria-label="Resolution view" className={resolutionStyles.resolutionTabs} role="group">
          <button aria-pressed="false" onClick={onShowRecommended} type="button">Recommended</button>
          <button aria-pressed="true" type="button">All</button>
        </div>
      ) : null}
      {issues.length ? (
        <>
          <div aria-label="Resolution causes" className={styles.issueCauses} role="group">
            {issues.map((group) => (
              <button
                aria-pressed={reasonFilter === group.reason_code}
                key={group.reason_code}
                onClick={() => setReasonFilter((current) => current === group.reason_code ? null : group.reason_code)}
                type="button"
              >
                <span>{group.label}</span><strong className="numeric">{group.count}</strong>
              </button>
            ))}
          </div>
          <p className={styles.resultsLabel}>FILTERED RESULTS</p>
          <div className={styles.issueResults}>
            {visibleIssues.map((issue) => {
              const context = contextLabel(issue)
              return (
                <button
                  aria-label={`${issue.message}. ${context || (issue.assignment_id ? `Assignment ${issue.assignment_id}` : 'No linked assignment')}`}
                  aria-pressed={selectedIssueId === issue.id}
                  className={styles.issueButton}
                  draggable={!expanded && !issue.assignment_id}
                  key={issue.id}
                  onDragEnd={onDragEnd}
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = 'move'
                    event.dataTransfer.setData('application/x-scheduler-issue', issue.id)
                    onDragStart?.(issue)
                  }}
                  onClick={() => onSelect(issue)}
                  type="button"
                >
                  <span><strong>{issue.student_name ?? issue.instructor ?? issue.message}</strong><small>{context || issue.message}</small></span>
                  <em>{issue.assignment_id ? 'EDIT' : 'OPEN'}</em>
                </button>
              )
            })}
          </div>
          {reservationIssues.length ? (
            <section aria-label="Instructor reservations ledger" className={styles.reservationLedger}>
              <p className={styles.resultsLabel}>INSTRUCTOR RESERVATIONS</p>
              <div className={styles.reservationLedgerList}>
                {reservationIssues.map((issue) => {
                  const context = contextLabel(issue)
                  const note = issueReservationNote(issue)
                  return (
                    <div className={styles.reservationLedgerItem} data-testid="reservation-ledger-item" key={issue.id}>
                      <strong>{issue.student_name ?? issue.instructor ?? issue.message}</strong>
                      <small>{context || issue.message}</small>
                      {note ? <p className={styles.reservationNote}>{note}</p> : null}
                    </div>
                  )
                })}
              </div>
            </section>
          ) : null}
        </>
      ) : <p className={styles.empty}>No unresolved items in the canonical session.</p>}
    </aside>
  )
})
