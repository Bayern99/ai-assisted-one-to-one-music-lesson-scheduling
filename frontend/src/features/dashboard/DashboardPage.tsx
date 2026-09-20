import * as Dialog from '@radix-ui/react-dialog'
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import type { components } from '../../api/schema'
import { apiRequest } from '../../api/client'
import { SECTION_TITLES, titleCaseLabel, workflowStageLabel } from '../../app/productLanguage'
import { Button } from '../../components/common/Button'
import {
  DockedPane,
  EmphasisSurface,
  Section,
  WorkspaceHeader,
  WorkspaceSurface,
} from '../../components/workspace/WorkspacePrimitives'
import styles from './dashboard.module.css'

type DashboardData = components['schemas']['DashboardData']
type SemesterConfig = components['schemas']['SemesterConfigView']

function SemesterOverview({
  config,
  version,
  onSaved,
}: {
  config: SemesterConfig
  version: string | null
  onSaved: () => Promise<unknown>
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(config)
  const saveMutation = useMutation({
    mutationFn: () => apiRequest<SemesterConfig>('/api/dashboard/semester-config', {
      method: 'PATCH',
      body: JSON.stringify({ expected_version: version, ...draft }),
    }),
    onSuccess: async () => { setOpen(false); await onSaved() },
  })
  const valid = Boolean(
    version
    && draft.start_date <= draft.last_day,
  )
  const update = (key: keyof SemesterConfig, value: string) => setDraft((current) => ({ ...current, [key]: value }))

  return <section aria-labelledby="semester-heading" className={styles.railSection}>
    <div className={styles.semesterHeading}><div><h2 id="semester-heading">Semester Overview</h2><p>{draft.start_date.slice(0, 4)} Academic Calendar</p></div><Button onClick={() => setOpen(true)} variant="quiet">Edit Dates</Button></div>
    <ol className={styles.milestones}>
      <li><span>Classes Begin</span><time dateTime={config.start_date}>{config.start_date}</time></li>
      <li><span>Last Class Day</span><time dateTime={config.last_day}>{config.last_day}</time></li>
    </ol>
    <Dialog.Root onOpenChange={setOpen} open={open}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.dialogOverlay} />
        <Dialog.Content className={styles.dialogContent}>
          <Dialog.Title>Edit Semester Dates</Dialog.Title>
          <Dialog.Description>These dates drive the shared local semester calendar and scheduling context.</Dialog.Description>
          <div className={styles.semesterFields}>
            <label><span>Classes Begin</span><input aria-label="Classes Begin" onChange={(event) => update('start_date', event.target.value)} type="date" value={draft.start_date} /></label>
            <label><span>Last Class Day</span><input aria-label="Last Class Day" onChange={(event) => update('last_day', event.target.value)} type="date" value={draft.last_day} /></label>
          </div>
          {!valid ? <p className={styles.dateError} role="alert">End dates must not precede their corresponding start dates.</p> : null}
          {saveMutation.error ? <p className={styles.dateError} role="alert">{saveMutation.error.message}</p> : null}
          <div className={styles.dialogActions}><Dialog.Close asChild><Button variant="secondary">Cancel</Button></Dialog.Close><Button disabled={!valid} loading={saveMutation.isPending} loadingLabel="Saving Semester Dates" onClick={() => saveMutation.mutate()}>Save Dates</Button></div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  </section>
}

function textEntries(record: Record<string, unknown>) {
  return Object.entries(record).filter(
    (entry): entry is [string, string | number | boolean] =>
      ['string', 'number', 'boolean'].includes(typeof entry[1]),
  )
}

const technicalHealthTerms = /pandas|openpyxl|xlsxwriter|fastapi|sqlite|python|react|local api/i

const healthNames: Record<string, string> = {
  'data directory': 'Workspace Storage',
  'data files location': 'Workspace Files',
  'import: data processing': 'Workbook Processing',
  'import: excel reading': 'Workbook Reading',
  'import: excel writing': 'Workbook Export',
  'temp file leaks': 'Temporary Files',
}

function productStatus(value: unknown) {
  if (typeof value !== 'string') return 'Not Reported'
  const normalized = value.trim().toLowerCase()
  if (['available', 'healthy', 'ok', 'ready'].includes(normalized)) return 'Ready'
  if (['warning', 'warn'].includes(normalized)) return 'Attention'
  if (['error', 'failed', 'unavailable'].includes(normalized)) return 'Unavailable'
  return titleCaseLabel(value)
}

function productHealthCheck(check: Record<string, unknown>) {
  const rawName = typeof check.name === 'string' ? check.name : 'Workspace Check'
  const rawDetail = typeof check.detail === 'string' ? check.detail : null
  const status = productStatus(check.status)
  const mappedName = healthNames[rawName.trim().toLowerCase()]
  const name = mappedName ?? (technicalHealthTerms.test(rawName) ? 'Workspace Capability' : titleCaseLabel(rawName))
  const detail = rawDetail && !(mappedName && status === 'Ready') && !technicalHealthTerms.test(rawDetail)
    ? rawDetail
    : status === 'Ready' ? null : 'Review this workspace check.'

  return { detail, name, status }
}

function workflowLabel(key: string) {
  if (key === 'current_phase') return 'Current Stage'
  return titleCaseLabel(key)
}

function workflowValue(key: string, value: string | number | boolean) {
  if (key === 'current_phase' && typeof value === 'string') return workflowStageLabel(value)
  return typeof value === 'string' ? titleCaseLabel(value) : String(value)
}

function productRecommendation(value: string) {
  if (!technicalHealthTerms.test(value)) return value
  return 'A workspace capability needs attention. Review Workspace Health before continuing.'
}

function DashboardSkeleton() {
  return (
    <div aria-label="Loading dashboard" className={styles.skeleton} role="status">
      <div className={styles.skeletonBand} />
      <div className={styles.skeletonColumns}>
        <div />
        <div />
      </div>
    </div>
  )
}

export function DashboardPage() {
  const query = useQuery({
    queryKey: ['dashboard'],
    queryFn: ({ signal }) => apiRequest<DashboardData>('/api/dashboard', { signal }),
  })

  if (query.isPending) return <DashboardSkeleton />
  if (query.isError) {
    return (
      <section aria-labelledby="dashboard-error" className={styles.error} role="alert">
        <h2 id="dashboard-error">Dashboard Unavailable</h2>
        <p>{query.error.message}</p>
        <Button onClick={() => void query.refetch()} variant="secondary">Retry</Button>
      </section>
    )
  }

  const dashboard = query.data.data
  if (!dashboard) {
    return (
      <section className={styles.empty}>
        <h2>No Dashboard Data</h2>
        <p>The workspace did not return a dashboard summary.</p>
      </section>
    )
  }

  const workflow = textEntries(dashboard.workflow_state ?? {})
  const health = dashboard.health ?? {}
  const healthStatus = typeof health.status === 'string' ? health.status : 'not reported'
  const checks = Array.isArray(health.checks)
    ? health.checks.filter((check): check is Record<string, unknown> => Boolean(check)
      && typeof check === 'object'
    )
      .map(productHealthCheck)
    : []
  const recommendations = Array.isArray(health.recommendations)
    ? health.recommendations
      .filter((item): item is string => typeof item === 'string')
      .map(productRecommendation)
      .filter((item, index, items) => items.indexOf(item) === index)
    : []

  return (
    <div aria-label="Operations workbench" className={styles.page}>
      <WorkspaceHeader
        actions={<p className={styles.healthStatus} data-state={healthStatus}>Status: {productStatus(healthStatus)}</p>}
        context="Local scheduling workspace"
        title="Overview"
      />
      <div className={styles.workbench}>
      <WorkspaceSurface aria-labelledby="operation-summary-heading" className={styles.operationPanel}>
        <div className={styles.panelHeading}>
          <div><h2 id="operation-summary-heading">{SECTION_TITLES.activeWorkspace}</h2><p>Canonical scheduling data, rules and draft state.</p></div>
        </div>
        <div aria-label="Workspace counts" className={styles.countStrip} role="group">
          <dl className={styles.counts}>
            {Object.entries(dashboard.counts).map(([label, value]) => (
              <div key={label}><dt>{titleCaseLabel(label)}</dt><dd className="numeric">{value}</dd></div>
            ))}
          </dl>
        </div>
        <Section title={SECTION_TITLES.workspaceHealth} aria-labelledby="health-heading" className={styles.ledgerSection}>
          <span className={styles.srHeading} id="health-heading">{SECTION_TITLES.workspaceHealth}</span>
            {checks.length ? (() => {
              const allReady = checks.every((check) => check.status === 'Ready')
              const list = <dl className={styles.healthList}>
                {checks.map((check, index) => (
                  <div key={`${check.name}-${index}`}>
                    <dt>{check.name}</dt>
                    <dd><strong>{check.status}</strong>{check.detail ? `: ${check.detail}` : ''}</dd>
                  </div>
                ))}
              </dl>
              return allReady && !recommendations.length
                ? <details className={styles.healthCompact}><summary>Workspace health: {checks.length} checks ready</summary>{list}</details>
                : list
            })() : <p className={styles.muted}>No workspace checks were reported.</p>}
        </Section>
        <EmphasisSurface
          aria-labelledby="attention-heading"
          className={`${styles.attention} ${recommendations.length ? styles.attentionActive : styles.attentionClear}`}
          data-state={recommendations.length ? 'attention' : 'clear'}
          tone={recommendations.length ? 'warning' : 'status'}
        >
          <h3 id="attention-heading">{recommendations.length ? 'Attention Required' : 'No Attention Required'}</h3>
          {recommendations.length
            ? <ul>{recommendations.map((item) => <li key={item}>{item}</li>)}</ul>
            : <p>Workspace checks did not return an attention item.</p>}
        </EmphasisSurface>
      </WorkspaceSurface>

      <DockedPane aria-labelledby="recent-activity-heading" className={styles.activityRail}>
        <div className={styles.activityPanel}>
          <section className={styles.railSection}>
            <h2 id="recent-activity-heading">{SECTION_TITLES.recentActivity}</h2>
            <p className={styles.activityTitle}>{dashboard.continue_action?.page_title ?? 'No recent workspace activity'}</p>
            <p className={`${styles.meta} meta`}>{dashboard.continue_action?.timestamp ? `Last activity ${dashboard.continue_action.timestamp}` : 'No timestamp recorded'}</p>
          </section>

          <SemesterOverview
            config={dashboard.semester_config}
            key={`${dashboard.semester_config.start_date}-${dashboard.semester_config.last_day}-${dashboard.semester_config.jury_start}-${dashboard.semester_config.jury_end}`}
            onSaved={() => query.refetch()}
            version={query.data.workspace_version}
          />

          <section aria-labelledby="continue-heading" className={styles.railSection}>
            <h2 id="continue-heading">{SECTION_TITLES.workflowContinuation}</h2>
            {dashboard.continue_action?.continue_label && dashboard.continue_action.continue_path ? (
              <Link className={styles.continueLink} to={dashboard.continue_action.continue_path}>
                {dashboard.continue_action.continue_label}
              </Link>
            ) : <p className={styles.muted}>No continuation action is available.</p>}
          </section>

          <section aria-labelledby="workflow-heading" className={styles.railSection}>
            <h2 id="workflow-heading">{SECTION_TITLES.workflowState}</h2>
            {workflow.length ? (
              <dl className={styles.workflowList}>
                {workflow.map(([key, value]) => (
                  <div key={key}><dt>{workflowLabel(key)}</dt><dd>{workflowValue(key, value)}</dd></div>
                ))}
              </dl>
            ) : <p className={styles.muted}>No workflow state has been recorded.</p>}
          </section>

          <section aria-labelledby="session-heading" className={styles.railSection}>
            <h2 id="session-heading">{SECTION_TITLES.schedulingSession}</h2>
            <dl className={styles.session}>
              <div><dt>Active View</dt><dd>{workflowStageLabel(dashboard.session.active_step)}</dd></div>
              <div><dt>Round Committed</dt><dd>{dashboard.session.round_committed ? 'Yes' : 'No'}</dd></div>
              <div><dt>Draft Changes</dt><dd>{dashboard.session.draft_dirty ? 'Unpublished draft' : 'None'}</dd></div>
            </dl>
          </section>
        </div>
      </DockedPane>
      </div>
    </div>
  )
}
