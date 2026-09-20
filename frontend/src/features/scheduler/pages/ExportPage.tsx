import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { PAGE_TITLES, SECTION_TITLES, workspaceRevisionLabel } from '../../../app/productLanguage'
import { ApiClientError, type ApiEnvelope } from '../../../api/client'
import { Button } from '../../../components/common/Button'
import { useArtifactSave } from '../../../components/common/useArtifactSave'
import { DockedPane, WorkspaceHeader, WorkspaceSurface, WorkspaceToolbar } from '../../../components/workspace/WorkspacePrimitives'
import {
  buildSchedulerExports,
  getDashboard,
  schedulerSessionKey,
  startSchedulerRound,
  useSchedulerSession,
  type DashboardData,
  type SchedulerExportBuildResult,
  type SchedulerSession,
} from '../api'
import { adaptAssignment } from '../components/AssignmentBlock'
import pageStyles from './ExportPage.module.css'
import workspaceStyles from '../schedulerWorkspace.module.css'

const styles = new Proxy(workspaceStyles, { get: (target, key: string) => target[key] ?? pageStyles[key] })

type Artifact = SchedulerExportBuildResult['artifacts'][number]
type FailedAssignment = NonNullable<SchedulerExportBuildResult['failed_assignments']>[number]

function artifactLabel(filename: string) {
  return filename.replace(/\.[^.]+$/, '').replaceAll('_', ' ').replaceAll('-', ' ')
}

function clock(value: string | null) {
  return value?.match(/(?:T|^)(\d{2}:\d{2})/)?.[1] ?? value ?? 'Unavailable'
}

function routeWarnings(state: unknown) {
  if (!state || typeof state !== 'object') return []
  const warnings = (state as Record<string, unknown>).finalizeWarnings
  return Array.isArray(warnings) ? warnings.filter((item): item is string => typeof item === 'string') : []
}

function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function firstText(record: Record<string, unknown>, keys: string[], fallback = 'Unavailable') {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value
    if (typeof value === 'number') return String(value)
  }
  return fallback
}

function ErrorDetails({ error, title }: { error: Error | null; title: string }) {
  if (!error) return null
  const apiError = error instanceof ApiClientError ? error : null
  return (
    <div className={`${styles.inlineError} ${styles.exportInlineError}`} role="alert">
      <strong>{title}</strong>
      <p>{error.message}</p>
      {apiError?.operationId ? <p className="meta">Operation {apiError.operationId}</p> : null}
    </div>
  )
}

export function ExportPage() {
  const queryClient = useQueryClient()
  const location = useLocation()
  const navigate = useNavigate()
  const sessionQuery = useSchedulerSession()
  const dashboardQuery = useQuery({
    queryKey: ['dashboard'],
    queryFn: ({ signal }) => getDashboard(signal),
  })
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [failedAssignments, setFailedAssignments] = useState<FailedAssignment[]>([])
  const [artifactVersion, setArtifactVersion] = useState<string | null>(null)
  const [buildVersionError, setBuildVersionError] = useState('')
  const [hasBuilt, setHasBuilt] = useState(false)
  const { clearError, error: saveError, saveArtifact, savedArtifacts } = useArtifactSave()
  const [revealError, setRevealError] = useState('')
  const buildPending = useRef(false)
  const roundPending = useRef(false)
  const buildMutation = useMutation<ApiEnvelope<SchedulerExportBuildResult>, ApiClientError, string>({
    mutationFn: buildSchedulerExports,
    onSuccess: (response, expectedVersion) => {
      if (response.workspace_version !== expectedVersion || currentTrustedVersion() !== expectedVersion) {
        setArtifacts([])
        setFailedAssignments([])
        setArtifactVersion(null)
        setHasBuilt(false)
        setBuildVersionError('The export response does not match the trusted scheduler workspace. Refresh the workspace and build again.')
        void retryReads()
        return
      }
      setArtifacts(response.data?.artifacts ?? [])
      setFailedAssignments(response.data?.failed_assignments ?? [])
      setArtifactVersion(expectedVersion)
      setHasBuilt(true)
      setBuildVersionError('')
      clearError()
      setRevealError('')
    },
    onSettled: () => { buildPending.current = false },
  })
  const roundMutation = useMutation({
    mutationFn: startSchedulerRound,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: schedulerSessionKey, refetchType: 'none' })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'], refetchType: 'none' })
      navigate('/schedule/import', { state: { roundMessage: 'Committed assignments remain locked' } })
    },
    onSettled: () => { roundPending.current = false },
  })

  const session = sessionQuery.data?.data
  const dashboard = dashboardQuery.data?.data
  const initialLoading = (sessionQuery.isPending && !session) || (dashboardQuery.isPending && !dashboard)
  const fatalReadError = (sessionQuery.isError && !session) || (dashboardQuery.isError && !dashboard)

  async function retryReads() {
    await Promise.all([sessionQuery.refetch(), dashboardQuery.refetch()])
  }

  function currentTrustedVersion() {
    const sessionState = queryClient.getQueryState(schedulerSessionKey)
    const dashboardState = queryClient.getQueryState(['dashboard'])
    const sessionEnvelope = queryClient.getQueryData<ApiEnvelope<SchedulerSession>>(schedulerSessionKey)
    const dashboardEnvelope = queryClient.getQueryData<ApiEnvelope<DashboardData>>(['dashboard'])
    const sessionVersion = sessionEnvelope?.workspace_version
    const dashboardVersion = dashboardEnvelope?.workspace_version
    return sessionState?.status === 'success'
      && dashboardState?.status === 'success'
      && sessionVersion
      && sessionVersion === dashboardVersion
      ? sessionVersion
      : null
  }

  async function reloadRoundState() {
    const [sessionResult, dashboardResult] = await Promise.all([sessionQuery.refetch(), dashboardQuery.refetch()])
    if (sessionResult.isSuccess && dashboardResult.isSuccess) roundMutation.reset()
  }

  async function revealArtifact(artifact: Artifact) {
    const reveal = window.piDesktop?.revealArtifact
    if (!reveal) return
    clearError()
    setRevealError('')
    try {
      await reveal(artifact.artifact_id)
    } catch (error) {
      setRevealError(error instanceof Error ? error.message : 'The artifact could not be revealed in Finder')
    }
  }

  if (initialLoading) {
    return <div aria-live="polite" className={styles.exportLoading} role="status">Loading export workspace</div>
  }
  if (fatalReadError) {
    const messages = [sessionQuery.error, dashboardQuery.error].filter((error): error is Error => error instanceof Error)
    return (
      <section className={`${styles.inlineError} ${styles.exportInlineError}`} role="alert">
        <strong>Export workspace unavailable</strong>
        {messages.map((error) => <p key={error.message}>{error.message}</p>)}
        <Button onClick={() => void retryReads()} variant="secondary">Retry export workspace</Button>
      </section>
    )
  }
  if (!session || !dashboard) {
    return <section className={styles.emptyOperation}><h2>No Export Workspace</h2><p>The local API returned no scheduler or dashboard state.</p></section>
  }

  const views = session.assignments.map(adaptAssignment)
  const warnings = [...new Set([...routeWarnings(location.state), ...(sessionQuery.data?.warnings ?? []), ...(session.warnings ?? [])])]
  const sessionVersion = sessionQuery.data?.workspace_version
  const dashboardVersion = dashboardQuery.data?.workspace_version
  const versionsMatch = Boolean(sessionVersion && dashboardVersion && sessionVersion === dashboardVersion)
  const coherentVersion = versionsMatch ? sessionVersion : null
  const trustedVersion = coherentVersion && !sessionQuery.isError && !dashboardQuery.isError ? coherentVersion : null
  const exportReady = session.active_stage === 'export'
    && dashboard.session.round_committed
    && !session.draft.dirty
    && trustedVersion
  const exportBlocks = [
    session.active_stage !== 'export' ? 'Resolve the schedule before building exports.' : null,
    !dashboard.session.round_committed ? 'Finalize the current round before building exports.' : null,
    session.draft.dirty ? 'Clear draft changes before building exports.' : null,
    sessionQuery.isError || dashboardQuery.isError ? 'Refresh the export workspace before building exports.' : null,
    !sessionQuery.isError && !dashboardQuery.isError && sessionVersion && dashboardVersion && !versionsMatch
      ? 'Scheduler and dashboard versions do not match. Refresh the export workspace.' : null,
    !sessionVersion || !dashboardVersion ? 'A workspace version is required before building exports.' : null,
  ].filter((reason): reason is string => Boolean(reason))
  const artifactStale = Boolean(artifactVersion && (
    (sessionVersion && sessionVersion !== artifactVersion)
    || (dashboardVersion && dashboardVersion !== artifactVersion)
  ))
  const visibleArtifacts = artifactStale ? [] : artifacts
  const canRevealArtifacts = Boolean(window.piDesktop?.revealArtifact)
  const visibleFailures = artifactStale ? [] : failedAssignments
  const roundReady = Boolean(exportReady)
  const roundError = roundMutation.error as ApiClientError | null

  return (
    <div className={`${styles.page} ${styles.exportPage} ${styles.workspacePage}`}>
      <WorkspaceHeader
        actions={<Button
          disabled={!exportReady}
          loading={buildMutation.isPending}
          loadingLabel="Building export files"
          onClick={() => {
            if (!trustedVersion || !exportReady || buildPending.current) return
            buildPending.current = true
            setBuildVersionError('')
            buildMutation.mutate(trustedVersion)
          }}
        >Build export files</Button>}
        context="Validated output artifacts"
        title={PAGE_TITLES.scheduleExport}
      />
      <div className={styles.exportWorkbench}>
      <WorkspaceSurface className={styles.exportMain}>
      <WorkspaceToolbar className={`${styles.actionRail} ${styles.exportActionRail}`}>
        <div><strong>Export Ledger</strong><span>Build files from the current validated schedule.</span></div>
      </WorkspaceToolbar>

      {warnings.length ? <div className={styles.warningLedger} role="status"><strong>Finalize warnings</strong><ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div> : null}
      {sessionQuery.isError || dashboardQuery.isError ? (
        <div className={`${styles.inlineError} ${styles.exportInlineError}`} role="alert">
          <strong>Some export metadata could not be refreshed</strong>
          {sessionQuery.isError ? <p>{sessionQuery.error.message}</p> : null}
          {dashboardQuery.isError ? <p>{dashboardQuery.error.message}</p> : null}
          <Button onClick={() => void retryReads()} variant="secondary">Retry export workspace</Button>
        </div>
      ) : null}
      <section aria-labelledby="canonical-preview-heading" className={styles.exportSection}>
        <div className={`${styles.sectionHeading} ${styles.exportSectionHeading}`}>
          <div><h2 id="canonical-preview-heading">{SECTION_TITLES.canonicalSchedulePreview}</h2><p>This table previews the current session, not the generated workbook files.</p></div>
          <span className="meta">{views.length} assignment{views.length === 1 ? '' : 's'}</span>
        </div>
        {views.length ? (
          <div className={`${styles.tableFrame} ${styles.exportTableFrame} ${styles.canonicalPreviewFrame} ${styles.exportCanonicalPreview}`}>
            <table aria-label="Canonical schedule preview">
              <thead><tr><th>Assignment</th><th>Kind</th><th>Instructor</th><th>Room</th><th>Day</th><th>Time</th><th>State</th></tr></thead>
              <tbody>{views.map((assignment) => (
                <tr key={assignment.id}>
                  <td><strong>{assignment.title}</strong></td>
                  <td>{assignment.kind}</td>
                  <td>{assignment.instructor}</td>
                  <td className="room">{assignment.room ?? 'Unavailable'}</td>
                  <td>{assignment.dayLabel}</td>
                  <td className="time">{clock(assignment.start)} - {clock(assignment.end)}</td>
                  <td>{assignment.locked ? 'Locked' : 'Editable'}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className={styles.empty}>No assignments are available in the canonical session.</p>}
      </section>

      <section aria-labelledby="artifact-heading" className={styles.exportSection}>
        <div className={`${styles.sectionHeading} ${styles.exportSectionHeading}`}>
          <div><h2 id="artifact-heading">{SECTION_TITLES.generatedArtifacts}</h2><p>Authenticated downloads use opaque artifact identifiers only.</p></div>
          <span className="meta">{visibleArtifacts.length} files</span>
        </div>
        <ErrorDetails error={buildMutation.error} title="Export Build Failed" />
        {buildVersionError || artifactStale ? (
          <div className={`${styles.inlineError} ${styles.exportInlineError}`} role="alert">
            <strong>{buildVersionError ? 'Export build version changed' : 'Generated artifacts are stale'}</strong>
            <p>{buildVersionError || 'The canonical workspace advanced after these files were generated. Build export files again.'}</p>
            <Button onClick={() => void retryReads()} variant="secondary">Retry export workspace</Button>
          </div>
        ) : null}
        {(saveError || revealError) ? <div className={`${styles.inlineError} ${styles.exportInlineError}`} role="alert"><strong>Desktop save failed</strong><p>{saveError || revealError}</p></div> : null}
        {visibleArtifacts.length ? (
          <div className={`${styles.tableFrame} ${styles.exportTableFrame}`}>
            <table aria-label="Generated export artifacts">
              <thead><tr><th>Artifact</th><th>Filename</th><th>Media type</th>{canRevealArtifacts ? <th>Finder</th> : null}</tr></thead>
              <tbody>{visibleArtifacts.map((artifact) => (
                <tr key={artifact.artifact_id}>
                  <td><a aria-label={artifactLabel(artifact.filename)} className={styles.artifactLink} download={artifact.filename} href={`/api/scheduler/exports/${encodeURIComponent(artifact.artifact_id)}`} onClick={(event) => void saveArtifact(event, artifact.artifact_id)}>{artifactLabel(artifact.filename)}</a></td>
                  <td className="meta">{artifact.filename}</td>
                  <td className="meta">{artifact.mime_type}</td>
                  {canRevealArtifacts ? <td><Button disabled={!savedArtifacts.has(artifact.artifact_id)} onClick={() => void revealArtifact(artifact)} variant="quiet">Reveal</Button></td> : null}
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : hasBuilt && !artifactStale ? <p className={styles.empty}>No export artifacts were generated.</p> : <p className={styles.empty}>Build export files to create authenticated downloads.</p>}
      </section>
      <section aria-labelledby="failed-assignments-heading" className={styles.exportSection}>
        <div className={`${styles.sectionHeading} ${styles.exportSectionHeading}`}>
          <div><h2 id="failed-assignments-heading">Failed Assignments</h2><p>Unscheduled lessons are included here so export never hides an incomplete result.</p></div>
          <span className="meta">{visibleFailures.length} failed</span>
        </div>
        {hasBuilt && visibleFailures.length ? <div className={`${styles.tableFrame} ${styles.exportTableFrame} ${styles.failedAssignmentsFrame}`}><table aria-label="Failed schedule assignments"><thead><tr><th>Assignment</th><th>Instructor</th><th>Course</th><th>Reason</th></tr></thead><tbody>{visibleFailures.map((failure, index) => {
          const source = recordOf(failure)
          const raw = recordOf(source.raw_row)
          const reason = firstText(source, ['reservation_note', 'reason', 'message', 'reason_code'])
          return <tr key={firstText(source, ['stable_issue_id', 'id'], `failed-${index}`)}><td><strong>{firstText(raw, ['Student Name', 'Student', 'Name'], firstText(source, ['title', 'student_name'], `Assignment ${index + 1}`))}</strong></td><td>{firstText(raw, ['Instructor', 'Teacher'], firstText(source, ['instructor']))}</td><td>{firstText(raw, ['Course Code', 'Course'], firstText(source, ['course_code']))}</td><td>{reason}</td></tr>
        })}</tbody></table></div> : hasBuilt ? <p className={styles.persistentStatus}>No failed assignments reported.</p> : <p className={styles.empty}>Build export files to verify failed assignments.</p>}
      </section>
      </WorkspaceSurface>

      <DockedPane aria-label="Export settings and readiness" className={styles.exportInspector}>
      <div className={`${styles.sectionHeading} ${styles.exportInspectorHeading}`}><div><h2>{SECTION_TITLES.exportReadiness}</h2><p>Canonical state required to build trusted artifacts.</p></div></div>
      <dl aria-label="Export readiness" className={styles.exportLedger}>
        <div><dt>Stage</dt><dd className="meta">{session.active_stage}</dd></div>
        <div><dt>Workspace Revision</dt><dd className="meta">{workspaceRevisionLabel(trustedVersion ?? sessionVersion)}</dd></div>
        <div><dt>Round status</dt><dd>{dashboard.session.round_committed ? 'Committed' : 'Not committed'}</dd></div>
        <div><dt>Draft state</dt><dd>{session.draft.dirty ? 'Draft changes present' : 'No draft changes'}</dd></div>
      </dl>
      {!exportReady ? (
        <section aria-labelledby="export-not-ready-heading" className={`${styles.persistentStatus} ${styles.exportPersistentStatus}`} role="status">
          <strong id="export-not-ready-heading">Export is not ready</strong>
          <ul>{exportBlocks.map((reason) => <li key={reason}>{reason}</li>)}</ul>
          <Link className="button button--secondary" to="/schedule/resolve">Return to Resolve</Link>
        </section>
      ) : null}
      <section aria-labelledby="round-heading" className={styles.roundRail}>
        <div><h2 id="round-heading">{SECTION_TITLES.nextSchedulingRound}</h2><p>Round 2 can begin only after the current round is committed and the draft is clean.</p></div>
        <Button disabled={!roundReady || roundMutation.isPending} onClick={() => {
          if (!trustedVersion || roundPending.current) return
          roundPending.current = true
          roundMutation.mutate(trustedVersion)
        }} variant="secondary">
          {roundMutation.isPending ? 'Starting Round 2' : 'Start Round 2'}
        </Button>
      </section>
      {roundError ? (
        <div className={`${styles.inlineError} ${styles.exportInlineError}`} role="alert">
          <strong>Round 2 could not start</strong><p>{roundError.message}</p>
          {roundError.operationId ? <p className="meta">Operation {roundError.operationId}</p> : null}
          {roundError.status === 409 ? <Button onClick={() => void reloadRoundState()} variant="secondary">Reload scheduler state</Button> : null}
        </div>
      ) : null}
      </DockedPane>
      </div>
    </div>
  )
}
