import type { CSSProperties } from 'react'
import { adaptAssignment, assignmentAccessibleName } from './AssignmentBlock'
import type { Assignment } from '../scheduleAuthority'
import styles from '../scheduleGrid.module.css'

interface GhostAssignmentBlockProps {
  assignment: Assignment
  placement: CSSProperties
}

export function GhostAssignmentBlock({ assignment, placement }: GhostAssignmentBlockProps) {
  const view = adaptAssignment(assignment)
  const visibleTime = `${view.start?.match(/(?:T|^)(\d{2}:\d{2})/)?.[1] ?? '—'}–${view.end?.match(/(?:T|^)(\d{2}:\d{2})/)?.[1] ?? '—'}`
  return (
    <div
      aria-label={`${assignmentAccessibleName(view)}, last staged placement`}
      className={styles.assignment}
      data-held="true"
      data-kind="held"
      data-presentation="ghost"
      data-room={view.room ?? undefined}
      data-testid="ghost-assignment"
      style={placement}
      title={`${visibleTime} · Last staged · ${view.title}`}
    >
      <span className={styles.assignmentTopline}>
        <span className={styles.assignmentTime}>{visibleTime}</span>
        <span aria-hidden="true" className={styles.assignmentKind}>Last staged</span>
      </span>
      <strong>{view.title}</strong>
      <span className={styles.assignmentInstructor}>Last staged placement</span>
    </div>
  )
}
