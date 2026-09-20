import { useEffect, useRef, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { SECTION_TITLES, workspaceRevisionLabel } from '../../../app/productLanguage'
import { Button } from '../../../components/common/Button'
import { DockedPane, EmptyState, WorkspaceHeader, WorkspaceSurface, WorkspaceToolbar } from '../../../components/workspace/WorkspacePrimitives'
import { getOperation, getSchedulerOptimizerPreflight, runSchedulerOptimizer, useOptimizerLearningRecords, useSchedulerSession, type SchedulerRerunMode, type SchedulerSession } from '../api'
import { OperationProgress } from '../OperationProgress'
import pageStyles from './OptimizerPage.module.css'
import workspaceStyles from '../schedulerWorkspace.module.css'

const styles = new Proxy(workspaceStyles, { get: (target, key: string) => target[key] ?? pageStyles[key] })

function InlineError({ error }: { error: Error | null }) {
  return error ? <div className={`${styles.inlineError} ${styles.optimizerInlineError}`} role="alert"><strong>{error.message}</strong></div> : null
}

export function OptimizerPage() {
  const sessionQuery = useSchedulerSession()
  const learningQuery = useOptimizerLearningRecords()
  const latestLearningRecord = learningQuery.data?.data?.latest
  const preflightQuery = useQuery({
    queryKey: ['scheduler-optimizer-preflight', sessionQuery.data?.workspace_version],
    queryFn: ({ signal }) => getSchedulerOptimizerPreflight(signal),
    enabled: Boolean(sessionQuery.data?.workspace_version),
  })
  const [operationId, setOperationId] = useState('')
  const [runContext, setRunContext] = useState<{ mode?: SchedulerRerunMode; startedAt: string; version: string } | null>(null)
  const [rerunDialogOpen, setRerunDialogOpen] = useState(false)
  const [resultState, setResultState] = useState<'idle' | 'refreshing' | 'ready' | 'failed'>('idle')
  const [resultSnapshot, setResultSnapshot] = useState<{
    issues: SchedulerSession['issues']
    unresolved: number
    version: string
  } | null>(null)
  const synchronizedOperation = useRef('')
  const submissionLocked = useRef(false)
  const runMutation = useMutation({
    mutationFn: (rerunMode?: SchedulerRerunMode) => runSchedulerOptimizer(sessionQuery.data!.workspace_version!, rerunMode),
    onSuccess: (response) => {
      if (response.data) setOperationId(response.data.operation_id)
    },
    onError: () => { submissionLocked.current = false },
  })
  const operationQuery = useQuery({
    queryKey: ['scheduler-operation', operationId],
    queryFn: ({ signal }) => getOperation(operationId, signal),
    enabled: Boolean(operationId),
    refetchInterval: (query) => {
      const status = query.state.data?.data?.status
      return status === 'queued' || status === 'running' ? 500 : false
    },
  })
  const operation = operationQuery.data?.data ?? null
  const active = operation?.status === 'queued' || operation?.status === 'running'

  useEffect(() => {
    if (operation?.status === 'completed' || operation?.status === 'failed') submissionLocked.current = false
    if (operation?.status !== 'completed' || synchronizedOperation.current === operation.id) return
    synchronizedOperation.current = operation.id
    setResultState('refreshing')
    setResultSnapshot(null)
    void sessionQuery.refetch().then((response) => {
      if (synchronizedOperation.current !== operation.id) return
      const canonical = response.data
      if (response.isSuccess && canonical?.data && canonical.workspace_version) {
        setResultSnapshot({
          issues: canonical.data.issues,
          unresolved: canonical.data.metrics.unresolved,
          version: canonical.workspace_version,
        })
        setResultState('ready')
        void learningQuery.refetch()
        return
      }
      setResultState('failed')
    }).catch(() => {
      if (synchronizedOperation.current === operation.id) setResultState('failed')
    })
  }, [learningQuery, operation?.id, operation?.status, sessionQuery])

  const waitingForOperation = Boolean(operationId) && !operation
  const preflight = preflightQuery.data?.data
  const runDisabled = sessionQuery.isError || preflightQuery.isPending || preflightQuery.isError || Boolean(preflight?.is_blocked) || !sessionQuery.data?.workspace_version || runMutation.isPending || active || waitingForOperation

  function submitOptimizer(rerunMode?: SchedulerRerunMode) {
    if (submissionLocked.current || runDisabled) return
    const version = sessionQuery.data?.workspace_version
    if (!version) return
    submissionLocked.current = true
    synchronizedOperation.current = ''
    setResultSnapshot(null)
    setResultState('idle')
    setRunContext({ mode: rerunMode, startedAt: new Date().toISOString(), version })
    setRerunDialogOpen(false)
    runMutation.mutate(rerunMode)
  }

  function runOptimizer() {
    if (sessionQuery.data?.data?.draft.dirty) {
      setRerunDialogOpen(true)
      return
    }
    submitOptimizer()
  }

  return (
    <div className={`${styles.page} ${styles.workspacePage}`}>
      <WorkspaceHeader
        actions={<Button disabled={runDisabled} loading={runMutation.isPending || active} loadingLabel={active ? 'Optimizer running' : 'Submitting…'} onClick={runOptimizer}>{operation?.status === 'failed' ? 'Retry optimizer' : 'Run optimizer'}</Button>}
        context="Local Scheduling Engine"
        title="Optimizer"
      />
      <div className={styles.optimizerWorkbench}>
      <WorkspaceSurface className={styles.optimizerMain}>
      <WorkspaceToolbar className={styles.actionRail}>
        <div><strong>Local Optimizer</strong><span>Runs against the current imported sources, lecture locks, and canonical rules.</span></div>
      </WorkspaceToolbar>

      {sessionQuery.isPending ? <div aria-label="Loading scheduler session" className={styles.skeleton} /> : null}
      <InlineError error={sessionQuery.error ?? preflightQuery.error ?? runMutation.error} />
      {operationQuery.isError && operationId ? <div className={`${styles.inlineError} ${styles.optimizerInlineError}`} role="alert">
        <strong>Operation status unavailable</strong>
        <p>The optimizer was already submitted. Retry only the operation status check.</p>
        <Button onClick={() => void operationQuery.refetch()} variant="secondary">Retry operation status</Button>
      </div> : null}

      <section aria-labelledby="readiness-heading" className={styles.readiness}>
        <div className={styles.sectionHeading}><div><h2 id="readiness-heading">{SECTION_TITLES.workspaceReadiness}</h2><p>Authoritative checks run against the current rooms and canonical rule file before submission.</p></div><span className={styles.stateLabel}>{preflight?.is_blocked ? 'blocked' : preflight ? 'ready' : 'checking'}</span></div>
        <dl className={styles.readinessLedger}>
          <div><dt>Rooms</dt><dd className="numeric">{sessionQuery.data?.data?.rooms.length ?? 0}</dd></div>
          <div><dt>Existing assignments</dt><dd className="numeric">{sessionQuery.data?.data?.metrics.assigned ?? 0}</dd></div>
          <div><dt>Unresolved</dt><dd className="numeric">{sessionQuery.data?.data?.metrics.unresolved ?? 0}</dd></div>
          <div><dt>Workspace Revision</dt><dd className="meta">{workspaceRevisionLabel(sessionQuery.data?.workspace_version)}</dd></div>
        </dl>
        {preflight?.issues.length ? <div className={styles.preflightIssues} role="alert"><strong>Resolve Before Running</strong><ul>{preflight.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>{preflight.instructor_conflicts?.length ? <Link to="/schedule/import">Review Source Data</Link> : <Link to="/schedule/rules">Open Rules</Link>}</div> : null}
        {preflightQuery.isError ? <Button onClick={() => void preflightQuery.refetch()} variant="secondary">Retry Readiness Check</Button> : null}
      </section>

      {operation ? <OperationProgress operation={operation} /> : (
        <EmptyState title="Ready for an Optimizer Run"><p>Run the optimizer when source workbooks and canonical configuration are ready.</p></EmptyState>
      )}

      {operation?.status === 'completed' && resultState === 'failed' ? <div className={`${styles.inlineError} ${styles.optimizerInlineError}`} role="alert">
        <strong>Optimizer result refresh failed</strong>
        <p>The operation completed, but its canonical scheduler result could not be refreshed. Existing workspace content is preserved.</p>
      </div> : null}

      {operation?.status === 'completed' && resultState === 'ready' && resultSnapshot ? <section aria-labelledby="optimizer-causes-heading" className={styles.rootCausePanel}>
        <div className={styles.sectionHeading}>
          <div><h2 id="optimizer-causes-heading">{SECTION_TITLES.unresolvedCauses}</h2><p>Canonical unresolved groups returned in the refreshed scheduler session.</p></div>
          <span className="numeric">{resultSnapshot.unresolved}</span>
        </div>
        {resultSnapshot.issues.length ? <ul className={styles.rootCauseList}>{resultSnapshot.issues.map((issue) => (
          <li key={issue.reason_code}><span>{issue.label}</span><strong>{issue.count}</strong></li>
        ))}</ul> : <p className={styles.empty}>No unresolved causes remain in the current schedule.</p>}
      </section> : null}

      {operation?.status === 'failed' ? <div className={styles.failureActions}><span className="meta">Operation ID: {operation.id}</span><span>Use Retry optimizer to run again with the current workspace version.</span></div> : null}
      {operation?.status === 'completed' ? <div className={styles.continueRow}><Link className="button button--primary" to="/schedule/resolve">Continue to resolve</Link><span>Review generated assignments and unresolved lessons.</span></div> : null}
      </WorkspaceSurface>
      <DockedPane aria-label="Optimizer run information" className={styles.runInspector}>
        <div className={`${styles.sectionHeading} ${styles.runInspectorHeading}`}><div><h2>{SECTION_TITLES.runInformation}</h2><p>The exact canonical snapshot used for this optimizer run.</p></div></div>
        {runContext ? <dl aria-label="Optimizer run versions" className={styles.runLedger}>
          <div><dt>Source + Rules Snapshot</dt><dd className="meta">{workspaceRevisionLabel(runContext.version)}</dd></div>
          <div><dt>Run started</dt><dd className="meta">{new Date(runContext.startedAt).toLocaleString()}</dd></div>
          <div><dt>Run state</dt><dd>{operation?.status ?? (runMutation.isPending ? 'Submitting' : 'Accepted')}</dd></div>
          <div><dt>Rerun mode</dt><dd>{runContext.mode === 'preserve_pinned' ? 'Preserve pinned edits' : 'Start fresh'}</dd></div>
          <div><dt>Result version</dt><dd className="meta">{operation?.status === 'completed'
            ? resultState === 'ready' ? resultSnapshot?.version : resultState === 'failed' ? 'Result unavailable' : 'Refreshing'
            : 'Pending'}</dd></div>
        </dl> : <p className={styles.empty}>No run has been submitted in this session.</p>}
        <div className={`${styles.sectionHeading} ${styles.runInspectorHeading}`}>
          <div><h2>Learning record</h2><p>Persistent local evidence for comparing optimizer output with finalized human intervention.</p></div>
        </div>
        {latestLearningRecord ? <dl aria-label="Latest optimizer learning record" className={styles.runLedger}>
          <div><dt>Run</dt><dd className="meta">{latestLearningRecord.run_id.slice(0, 8)}</dd></div>
          <div><dt>Status</dt><dd>{latestLearningRecord.status}</dd></div>
          <div><dt>Baseline allocation</dt><dd className="numeric">{(latestLearningRecord.baseline.allocation_rate * 100).toFixed(1)}%</dd></div>
          <div><dt>Baseline unresolved</dt><dd className="numeric">{latestLearningRecord.baseline.unresolved}</dd></div>
          {latestLearningRecord.outcome ? <>
            <div><dt>Final allocation</dt><dd className="numeric">{(latestLearningRecord.outcome.allocation_rate * 100).toFixed(1)}%</dd></div>
            <div><dt>Allocation change</dt><dd className="numeric">{latestLearningRecord.outcome.allocation_rate_change >= 0 ? '+' : ''}{(latestLearningRecord.outcome.allocation_rate_change * 100).toFixed(1)} pp</dd></div>
            <div><dt>Recorded interventions</dt><dd className="numeric">{latestLearningRecord.outcome.intervention_count}</dd></div>
            <div><dt>Decision notes</dt><dd className="numeric">{latestLearningRecord.outcome.decision_note_count}</dd></div>
          </> : null}
          <div><dt>Stored runs</dt><dd className="numeric">{learningQuery.data?.data?.total_runs ?? 0}</dd></div>
        </dl> : learningQuery.isPending ? <p className={styles.empty}>Loading learning record…</p>
          : learningQuery.isError ? <p className={styles.empty}>Learning record unavailable.</p>
            : <p className={styles.empty}>No persistent optimizer run record yet.</p>}
        {latestLearningRecord ? <p className="meta">Pi investigation is available inside Step 4 reconciliation, where each proposal is sandbox-tested before the operator can adopt or modify it.</p> : null}
      </DockedPane>
      </div>
      <Dialog.Root onOpenChange={setRerunDialogOpen} open={rerunDialogOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className={styles.dialogOverlay} />
          <Dialog.Content aria-describedby="optimizer-rerun-description" className={styles.dialogContent}>
            <Dialog.Title>Choose how to rerun the Optimizer</Dialog.Title>
            <Dialog.Description id="optimizer-rerun-description">Step 4 contains unsaved draft edits. Choose explicitly whether valid pinned edits should be carried into the next run.</Dialog.Description>
            <div className={styles.dialogActions}>
              <Dialog.Close asChild><Button variant="secondary">Cancel</Button></Dialog.Close>
              <Button onClick={() => submitOptimizer('fresh')}>Start fresh</Button>
              <Button onClick={() => submitOptimizer('preserve_pinned')}>Preserve pinned edits</Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  )
}
