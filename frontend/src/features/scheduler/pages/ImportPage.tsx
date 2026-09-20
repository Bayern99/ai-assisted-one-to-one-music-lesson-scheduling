import * as Dialog from '@radix-ui/react-dialog'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { PAGE_TITLES, SECTION_TITLES } from '../../../app/productLanguage'
import { ApiClientError } from '../../../api/client'
import { Button } from '../../../components/common/Button'
import { NativeFilePicker, type NativeFileSelection } from '../../../components/common/NativeFilePicker'
import {
  EmphasisSurface,
  WorkspaceHeader,
  WorkspaceSurface,
  WorkspaceToolbar,
} from '../../../components/workspace/WorkspacePrimitives'
import {
  applySchedulerWorkbook,
  applySchedulerImport,
  previewSchedulerImport,
  previewSchedulerWorkbook,
  resetScheduler,
  schedulerSessionKey,
  type SchedulerImportPreview,
  type SchedulerWorkbookImportPreview,
  useSchedulerSession,
} from '../api'
import pageStyles from './ImportPage.module.css'
import workspaceStyles from '../schedulerWorkspace.module.css'

const styles = new Proxy(workspaceStyles, { get: (target, key: string) => target[key] ?? pageStyles[key] })

function detailText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value !== 'object') return String(value)
  if (Array.isArray(value)) return value.map(detailText).filter(Boolean).join(', ')
  const record = value as Record<string, unknown>
  return Object.entries(record).map(([key, item]) => {
    const label = key === 'row' ? 'Row' : key.replaceAll('_', ' ')
    return `${label} ${detailText(item)}`
  }).join(' - ')
}

function ApiErrorDetails({ error }: { error: Error | null }) {
  if (!error) return null
  const details = error instanceof ApiClientError ? error.details : null
  const items = details ? Object.values(details).flatMap((value) => Array.isArray(value) ? value : [value]) : []
  return (
    <div className={`${styles.inlineError} ${styles.importInlineError}`} role="alert">
      <strong>{error.message}</strong>
      {items.length ? <ul>{items.map((item, index) => <li key={index}>{detailText(item)}</li>)}</ul> : null}
    </div>
  )
}

function sampleText(value: unknown) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

interface BoundWorkbookPreview {
  data: SchedulerWorkbookImportPreview
  file: File
  workspaceVersion: string
}

interface BoundSourcePreview {
  data: SchedulerImportPreview
  workspaceVersion: string
}

function IndividualSourceImport({ slot }: { slot: 'weekly' | 'studio' }) {
  const queryClient = useQueryClient()
  const [selection, setSelection] = useState<NativeFileSelection | null>(null)
  const [boundPreview, setBoundPreview] = useState<BoundSourcePreview | null>(null)
  const [result, setResult] = useState('')
  const [stale, setStale] = useState(false)
  const label = slot === 'weekly' ? 'Weekly Lesson Source' : 'Studio Class Source'
  const hasBlockers = Boolean(boundPreview?.data.blocking_errors.length)

  const previewMutation = useMutation({
    mutationFn: (file: File) => previewSchedulerImport(slot, file),
    onSuccess: (response) => {
      setBoundPreview(response.data && response.workspace_version
        ? { data: response.data, workspaceVersion: response.workspace_version }
        : null)
      setResult('')
      setStale(false)
      applyMutation.reset()
    },
  })
  const applyMutation = useMutation({
    mutationFn: () => applySchedulerImport(boundPreview!.data.preview_id, boundPreview!.workspaceVersion),
    onSuccess: async (response) => {
      const applied = response.data
      if (!applied || !('state_key' in applied) || applied.state_key !== (slot === 'weekly' ? 'wk_df' : 'stu_df')) {
        throw new Error('The local API returned an incomplete source apply result.')
      }
      setResult(`${label} applied — ${applied.row_count} ${applied.row_count === 1 ? 'row' : 'rows'} from ${applied.sheet_name}.`)
      setSelection(null)
      setBoundPreview(null)
      setStale(false)
      await queryClient.invalidateQueries({ queryKey: schedulerSessionKey })
    },
    onError: (error) => {
      if (error instanceof ApiClientError && error.status === 409) setStale(true)
    },
  })

  return <section aria-label={`${label} import`} className={styles.importColumn}>
    <div className={`${styles.sectionHeading} ${styles.importSectionHeading}`}>
      <div><h2>{label}</h2><p>Replace only the {slot === 'weekly' ? 'weekly lesson requests' : 'dated Studio class requests'} while keeping the other source intact.</p></div>
      <span className="meta">{boundPreview ? 'Preview ready' : 'No preview'}</span>
    </div>
    <NativeFilePicker
      accept=".csv,.xlsx,.xlsm,text/csv"
      inputLabel={`${label} file`}
      kind="schedulerSource"
      label={label}
      onSelect={(next) => {
        setSelection(next)
        setBoundPreview(null)
        setResult('')
        setStale(false)
        previewMutation.reset()
        applyMutation.reset()
      }}
      selection={selection}
    />
    <WorkspaceToolbar className={styles.actionRow}>
      <Button disabled={!selection} loading={previewMutation.isPending} loadingLabel="Previewing…" onClick={() => previewMutation.mutate(selection!.file)} variant="secondary">Preview {slot === 'weekly' ? 'Weekly' : 'Studio'}</Button>
      <Button disabled={!boundPreview || hasBlockers || stale} loading={applyMutation.isPending} loadingLabel="Applying…" onClick={() => applyMutation.mutate()}>Apply {slot === 'weekly' ? 'Weekly' : 'Studio'}</Button>
    </WorkspaceToolbar>
    <ApiErrorDetails error={previewMutation.error ?? applyMutation.error} />
    {stale ? <p className={styles.conflictAction}>This preview is stale. Preview the source again.</p> : null}
    {boundPreview?.data.blocking_errors.length ? (
      <div className={`${styles.inlineError} ${styles.importInlineError}`} role="alert">
        <strong>Source cannot be applied</strong>
        <p>One teacher cannot teach two lessons at the same time. Correct these rows and preview again.</p>
        <ul>{boundPreview.data.blocking_errors.map((message) => <li key={message}>{message}</li>)}</ul>
      </div>
    ) : null}
    {boundPreview ? <div className={styles.sourcePreview}>
      <dl>
        <div><dt>File</dt><dd>{boundPreview.data.file_name}</dd></div>
        <div><dt>Detected Sheet</dt><dd>{boundPreview.data.sheet_name}</dd></div>
        <div><dt>Rows</dt><dd className="numeric">{boundPreview.data.row_count}</dd></div>
      </dl>
      <div className={`${styles.tableFrame} ${styles.sourceColumns}`}><table><caption>Detected source columns</caption><thead><tr>{boundPreview.data.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead></table></div>
    </div> : null}
    {result ? <p className={`${styles.persistentStatus} ${styles.importPersistentStatus}`} role="status">{result}</p> : null}
  </section>
}

function WorkbookImport() {
  const queryClient = useQueryClient()
  const [selection, setSelection] = useState<NativeFileSelection | null>(null)
  const [boundPreview, setBoundPreview] = useState<BoundWorkbookPreview | null>(null)
  const [selectedSheetIndex, setSelectedSheetIndex] = useState(0)
  const [result, setResult] = useState('')
  const [stale, setStale] = useState(false)
  const fileRevision = useRef(0)

  const applyMutation = useMutation({
    mutationFn: async ({ selectedFile, previewId, fingerprint, expectedVersion }: { selectedFile: File; previewId: string; fingerprint: string; expectedVersion: string }) => {
      const response = await applySchedulerWorkbook(selectedFile, previewId, fingerprint, expectedVersion)
      const applied = response.data
      if (
        !applied
        || !Array.isArray(applied.state_keys)
        || !applied.state_keys.includes('wk_df')
        || !applied.state_keys.includes('stu_df')
        || !applied.sheet_names
        || typeof applied.sheet_names.weekly !== 'string'
        || typeof applied.sheet_names.studio !== 'string'
        || !applied.row_counts
        || !Number.isFinite(applied.row_counts.weekly)
        || !Number.isFinite(applied.row_counts.studio)
        || applied.row_counts.weekly < 0
        || applied.row_counts.studio < 0
        || applied.fingerprint !== fingerprint
        || !applied.sync_results
        || typeof applied.sync_results !== 'object'
        || Array.isArray(applied.sync_results)
        || !applied.session
        || typeof applied.session !== 'object'
        || Array.isArray(applied.session)
      ) {
        throw new Error('The local API returned an incomplete workbook apply result.')
      }
      return response
    },
    onSuccess: async (response) => {
      const weeklyRows = response.data?.row_counts.weekly ?? 0
      const studioRows = response.data?.row_counts.studio ?? 0
      setResult(
        `Workbook applied atomically - ${weeklyRows} Weekly ${weeklyRows === 1 ? 'row' : 'rows'}, `
        + `${studioRows} Studio ${studioRows === 1 ? 'row' : 'rows'}, and available Student Info, `
        + 'Instructor, Room and Course Code sheets synchronized.',
      )
      fileRevision.current += 1
      setSelection(null)
      setBoundPreview(null)
      setSelectedSheetIndex(0)
      setStale(false)
      await queryClient.invalidateQueries({ queryKey: schedulerSessionKey })
    },
    onError: (error) => {
      if (error instanceof ApiClientError && error.status === 409) setStale(true)
    },
  })

  const previewMutation = useMutation({
    mutationFn: ({ selectedFile }: { selectedFile: File; revision: number }) => previewSchedulerWorkbook(selectedFile),
    onSuccess: (response, { revision, selectedFile }) => {
      if (revision !== fileRevision.current) return
      setBoundPreview(
        response.data && response.workspace_version
          ? { data: response.data, file: selectedFile, workspaceVersion: response.workspace_version }
          : null,
      )
      setSelectedSheetIndex(0)
      setResult('')
      setStale(false)
      applyMutation.reset()
    },
  })

  const preview = boundPreview?.data ?? null
  const hasBlockers = Boolean(preview?.blocking_errors.length)
  const selectedSheet = preview?.sheets[selectedSheetIndex] ?? null

  return (
    <section aria-label="Scheduler workbook import" className={styles.importColumn}>
      <div className={`${styles.sectionHeading} ${styles.importSectionHeading}`}>
        <div><h2>{SECTION_TITLES.schedulerWorkbook}</h2><p>Preview all source sheets before one atomic workspace update.</p></div>
        <span className="meta">{preview ? 'Preview ready' : 'No preview'}</span>
      </div>
      <NativeFilePicker
        accept=".xlsx,.xlsm"
        inputLabel="Scheduler workbook"
        kind="workbook"
        label="Scheduling workbook"
        onSelect={(nextSelection) => {
          fileRevision.current += 1
          setSelection(nextSelection)
          setBoundPreview(null)
          setSelectedSheetIndex(0)
          setResult('')
          setStale(false)
          previewMutation.reset()
          applyMutation.reset()
        }}
        selection={selection}
      />
      <WorkspaceToolbar className={styles.actionRow}>
        <Button
          disabled={!selection}
          loading={previewMutation.isPending}
          loadingLabel="Previewing…"
          onClick={() => previewMutation.mutate({ selectedFile: selection!.file, revision: fileRevision.current })}
          variant="secondary"
        >
          Preview workbook
        </Button>
        <Button
          disabled={!boundPreview || hasBlockers || stale}
          loading={applyMutation.isPending}
          loadingLabel="Applying…"
          onClick={() => {
            if (boundPreview) {
              applyMutation.mutate({
                selectedFile: boundPreview.file,
                previewId: boundPreview.data.preview_id,
                fingerprint: boundPreview.data.fingerprint,
                expectedVersion: boundPreview.workspaceVersion,
              })
            }
          }}
        >
          Apply workbook
        </Button>
      </WorkspaceToolbar>
      <ApiErrorDetails error={previewMutation.error ?? applyMutation.error} />
      {stale ? <p className={styles.conflictAction}>This preview is stale. Preview the workbook again.</p> : null}
      {preview?.blocking_errors.length ? (
        <div className={`${styles.inlineError} ${styles.importInlineError}`} role="alert">
          <strong>Workbook cannot be applied</strong>
          {preview.instructor_conflicts.length ? <p>One teacher cannot teach two lessons at the same time. Correct these rows and preview again.</p> : null}
          <ul>{preview.blocking_errors.map((message) => <li key={message}>{message}</li>)}</ul>
        </div>
      ) : null}
      {preview?.warnings.length ? (
        <EmphasisSurface className={styles.warningPanel} tone="warning">
          <strong>Workbook warnings</strong>
          <ul>{preview.warnings.map((message) => <li key={message}>{message}</li>)}</ul>
        </EmphasisSurface>
      ) : null}
      {preview?.possible_instructor_duplicates?.length ? (
        <EmphasisSurface aria-label="Possible duplicate instructor names" className={styles.warningPanel} role="status" tone="warning">
          <strong>Check possible duplicate instructor names</strong>
          <p>These spellings use the same name parts in a different order. Review the workbook before applying; nothing will be merged automatically.</p>
          <ul>{preview.possible_instructor_duplicates.map((names) => <li key={names.join('\u0000')}>{names.join(' ↔ ')}</li>)}</ul>
        </EmphasisSurface>
      ) : null}
      {preview ? (
        <div className={styles.preview}>
          <div className={styles.previewHeading}><h3>{preview.sheets.length} Sheets Detected</h3><span className="meta">{preview.file_name} · {preview.fingerprint.slice(0, 12)}</span></div>
          <div className={styles.workbookWorkbench}>
            <aside aria-label="Workbook sheets" className={styles.sheetTabs}>
              {preview.sheets.map((sheet, index) => (
                <button
                  aria-pressed={index === selectedSheetIndex}
                  className={styles.sheetTab}
                  key={`${sheet.sheet_name}-${index}`}
                  onClick={() => setSelectedSheetIndex(index)}
                  type="button"
                >
                  <strong>{sheet.role}</strong>
                  <span>
                      <span>{sheet.row_count} {sheet.row_count === 1 ? 'row' : 'rows'}</span>
                    <small> · header {sheet.header_row}</small>
                  </span>
                </button>
              ))}
            </aside>
            {selectedSheet ? <div className={styles.sheetPreview}>
              <div className={styles.sectionHeading}>
                <div><h3>{selectedSheet.role}</h3><p>Header row {selectedSheet.header_row}</p></div>
                <span className="meta">{selectedSheet.normalized_name}</span>
              </div>
              {selectedSheet.blocking_errors.length ? (
                <div className={styles.inlineError} role="alert">
                  <ul>{selectedSheet.blocking_errors.map((message) => <li key={message}>{message}</li>)}</ul>
                </div>
              ) : null}
              {selectedSheet.warnings.length ? (
                <div className={styles.warningPanel}>
                  <ul>{selectedSheet.warnings.map((message) => <li key={message}>{message}</li>)}</ul>
                </div>
              ) : null}
              <div className={`${styles.tableFrame} ${styles.canonicalPreviewFrame}`}>
                <table>
                  <caption>Sample rows from {selectedSheet.sheet_name}</caption>
                  <thead><tr>{selectedSheet.columns.map((column, index) => <th key={`${column}-${index}`}>{column}</th>)}</tr></thead>
                  <tbody>
                    {selectedSheet.sample_rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>{selectedSheet.columns.map((column, columnIndex) => <td key={`${column}-${columnIndex}`}>{sampleText(row[column])}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div> : null}
          </div>
        </div>
      ) : null}
      {result ? <p className={`${styles.persistentStatus} ${styles.importPersistentStatus}`} role="status">{result}</p> : null}
    </section>
  )
}

export function ImportPage() {
  const location = useLocation()
  const queryClient = useQueryClient()
  const sessionQuery = useSchedulerSession()
  const [resetOpen, setResetOpen] = useState(false)
  const [resetGeneration, setResetGeneration] = useState(0)
  const [resetResult, setResetResult] = useState('')
  const [importMode, setImportMode] = useState<'workbook' | 'weekly' | 'studio'>('workbook')
  const roundMessage = location.state && typeof location.state === 'object'
    && typeof (location.state as Record<string, unknown>).roundMessage === 'string'
    ? (location.state as Record<string, string>).roundMessage
    : ''
  const resetMutation = useMutation({
    mutationFn: () => resetScheduler(sessionQuery.data!.workspace_version!),
    onSuccess: async () => {
      setResetOpen(false)
      setResetGeneration((current) => current + 1)
      setResetResult('Scheduling workspace reset.')
      await queryClient.invalidateQueries({ queryKey: schedulerSessionKey })
    },
  })

  return (
    <div className={`${styles.page} ${styles.workspacePage}`}>
      <WorkspaceHeader
        actions={<Button onClick={() => setResetOpen(true)} variant="secondary">Reset scheduling workspace</Button>}
        context={sessionQuery.data?.workspace_version ? 'Local Scheduling Sources' : 'Source Workspace Needs Review'}
        title={PAGE_TITLES.sourceImport}
      />
      {sessionQuery.isPending ? <div aria-label="Loading scheduler session" className={styles.skeleton} /> : null}
      {sessionQuery.isError ? <ApiErrorDetails error={sessionQuery.error} /> : null}
      {roundMessage ? <p className={styles.persistentStatus} role="status">{roundMessage}</p> : null}
      {resetResult ? <p className={styles.persistentStatus} role="status">{resetResult}</p> : null}
      <WorkspaceSurface className={styles.importGrid}>
        <div aria-label="Source import mode" className={styles.importModeBar} role="group">
          <button aria-pressed={importMode === 'workbook'} onClick={() => setImportMode('workbook')} type="button">Complete Workbook</button>
          <button aria-pressed={importMode === 'weekly'} onClick={() => setImportMode('weekly')} type="button">Weekly Only</button>
          <button aria-pressed={importMode === 'studio'} onClick={() => setImportMode('studio')} type="button">Studio Only</button>
        </div>
        {importMode === 'workbook' ? <WorkbookImport key={`workbook-${resetGeneration}`} /> : null}
        {importMode === 'weekly' ? <IndividualSourceImport key={`weekly-${resetGeneration}`} slot="weekly" /> : null}
        {importMode === 'studio' ? <IndividualSourceImport key={`studio-${resetGeneration}`} slot="studio" /> : null}
      </WorkspaceSurface>

      <Dialog.Root onOpenChange={setResetOpen} open={resetOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className={styles.dialogOverlay} />
          <Dialog.Content className={styles.dialogContent}>
            <Dialog.Title>Reset scheduling workspace?</Dialog.Title>
            <Dialog.Description>This permanently clears imported scheduling sources, drafts, and generated Weekly/Studio bookings. Lecture locks, rooms, students, and rules remain.</Dialog.Description>
            <ApiErrorDetails error={resetMutation.error} />
            <div className={styles.dialogActions}>
              <Dialog.Close asChild><Button variant="secondary">Cancel</Button></Dialog.Close>
              <Button disabled={sessionQuery.isError || !sessionQuery.data?.workspace_version || resetMutation.isPending} onClick={() => resetMutation.mutate()}>Reset workspace</Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  )
}
