import { useQuery } from '@tanstack/react-query'
import type { ApiClientError } from '../../../api/client'
import { reviewDraft } from '../api'
import styles from '../resolutionPanel.module.css'

interface DraftReviewCardProps {
  workspaceVersion: string | null
}

function summaryCount(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function statusLabel(status: string | undefined, unassigned: number | undefined) {
  switch (status) {
    case 'ready':
      return unassigned
        ? `Assigned lessons OK · ${unassigned} still need placement`
        : 'Assigned lessons OK — ready to Finalize'
    case 'blocked': return 'Conflicts block Finalize'
    case 'integrity_blocked': return 'Source integrity check failed'
    default: return 'Draft review'
  }
}

function statusClass(status: string | undefined) {
  switch (status) {
    case 'ready': return styles.reviewReady
    case 'blocked':
    case 'integrity_blocked': return styles.reviewBlocked
    default: return undefined
  }
}

export function DraftReviewCard({ workspaceVersion }: DraftReviewCardProps) {
  const query = useQuery({
    queryKey: ['draft-review', workspaceVersion],
    queryFn: ({ signal }) => {
      if (!workspaceVersion) throw new Error('Workspace version unavailable')
      return reviewDraft(workspaceVersion, signal)
    },
    enabled: Boolean(workspaceVersion),
  })
  const review = query.data?.data
  const error = query.error as ApiClientError | null
  return (
    <details className={styles.piIntervention} aria-label="Draft review">
      <summary className={styles.piHeading}>
        <div><strong>Before you Finalize</strong><small>Checks already-assigned lessons for conflicts</small></div>
        <span className={statusClass(review?.status)}>{statusLabel(review?.status, summaryCount(review?.summary.unassigned))}</span>
      </summary>
      {error ? <p className={styles.resolutionError} role="alert">{error.message}</p> : null}
      {review ? <div className={styles.draftReview}>
        <dl className={styles.resolutionSummary}>
          <div><dt>Assignments</dt><dd>{String(review.summary.assignments)}</dd></div>
          <div><dt>Still unplaced</dt><dd>{String(review.summary.unassigned)}</dd></div>
          <div><dt>Unpublished draft</dt><dd>{review.summary.draft_dirty ? 'Yes' : 'No'}</dd></div>
        </dl>
        {Array.isArray(review.conflicts) && review.conflicts.length ? <ul className={styles.draftConflicts}>
          {review.conflicts.map((conflict, index) => <li key={`${conflict.left}:${index}`}>{conflict.message} <small>{conflict.left} ↔ {conflict.right}</small></li>)}
        </ul> : null}
        {Array.isArray(review.integrity.blocking_reason_codes) && review.integrity.blocking_reason_codes.length ? <ul className={styles.draftConflicts}>
          {review.integrity.blocking_reason_codes.map((code) => <li key={code}>Integrity blocked: {code}</li>)}
        </ul> : null}
        {Array.isArray(review.warnings) && review.warnings.length ? <ul className={styles.draftConflicts}>
          {review.warnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul> : null}
        {review.status === 'ready' ? <p className={styles.piPrivacy}>No conflicts among assigned lessons. Finalize still reruns the full validator.</p> : null}
      </div> : null}
      {query.isFetching ? <small className={styles.piPrivacy}>Checking draft…</small> : null}
    </details>
  )
}
