import type { Operation } from './api'
import operationStyles from './OperationProgress.module.css'
import workspaceStyles from './schedulerWorkspace.module.css'

const styles = new Proxy(workspaceStyles, { get: (target, key: string) => target[key] ?? operationStyles[key] })

const PHASE_LABELS: Record<string, string> = {
  queued: 'Queued for local execution',
  preflight: 'Checking scheduler inputs',
  optimizing: 'Optimizing room assignments',
  persisting: 'Saving the scheduling draft',
  completed: 'Optimizer run completed',
  failed: 'Optimizer run failed',
}

function numericResult(result: Record<string, unknown> | null | undefined, key: string) {
  const value = result?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function recordList(result: Record<string, unknown> | null | undefined, key: string) {
  const value = result?.[key]
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object') : []
}

function stringList(result: Record<string, unknown> | null | undefined, key: string) {
  const value = result?.[key]
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function text(value: unknown) {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

export function OperationProgress({ operation }: { operation: Operation }) {
  const assignments = numericResult(operation.result, 'assignment_count')
  const unresolved = numericResult(operation.result, 'unassigned_count')
  const duplicates = numericResult(operation.result, 'duplicate_count')
  const duplicateRecords = recordList(operation.result, 'duplicates')
  const logs = stringList(operation.result, 'logs')
  const learningRecordWarning = text(operation.result?.learning_record_warning)

  return (
    <section aria-labelledby="operation-heading" className={styles.operation}>
      <div className={styles.sectionHeading}>
        <div>
          <h2 id="operation-heading">Operation</h2>
          <p className="meta">{operation.id}</p>
        </div>
        <span className={styles.stateLabel}>{operation.status}</span>
      </div>
      <div aria-atomic="true" aria-live="polite" className={styles.phase} role="status">
        <span className={styles.phaseMarker} aria-hidden="true" />
        <div><strong>{PHASE_LABELS[operation.phase] ?? operation.phase}</strong><p>Phase: {operation.phase}</p></div>
      </div>
      {learningRecordWarning ? (
        <div className={styles.inlineError} role="alert">
          <strong>Learning record needs attention</strong>
          <p>{learningRecordWarning}</p>
        </div>
      ) : null}
      {operation.status === 'completed' ? (
        <><dl className={styles.resultLedger}>
          {assignments === null ? null : <div><dt>Assignments</dt><dd>{assignments} assignments generated</dd></div>}
          {unresolved === null ? null : <div><dt>Unresolved</dt><dd>{unresolved} unresolved lessons</dd></div>}
          {duplicates === null ? null : <div><dt>Duplicates</dt><dd>{duplicates} duplicate records</dd></div>}
        </dl>
        {duplicateRecords.length ? <details className={styles.operationEvidence}>
          <summary>Duplicate Records <span className="numeric">{duplicateRecords.length}</span></summary>
          <ul>{duplicateRecords.map((record, index) => <li key={`${text(record.id)}-${index}`}><strong>{text(record.name) || text(record.id) || `Record ${index + 1}`}</strong><span>{[text(record.course), text(record.day), text(record.time)].filter(Boolean).join(' · ') || 'Skipped because this identity was already processed.'}</span></li>)}</ul>
        </details> : null}
        {logs.length ? <details className={styles.operationEvidence}>
          <summary>Optimization Log <span className="numeric">{logs.length}</span></summary>
          <ol className={styles.operationLog}>{logs.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}</ol>
        </details> : null}</>
      ) : null}
      {operation.status === 'failed' ? (
        <div className={styles.inlineError} role="alert">
          <strong>Optimizer could not complete</strong>
          <p>{operation.error || 'The local optimizer stopped without an error message.'}</p>
        </div>
      ) : null}
    </section>
  )
}
