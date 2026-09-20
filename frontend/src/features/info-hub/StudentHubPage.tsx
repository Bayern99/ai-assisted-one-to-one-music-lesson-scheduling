import * as Dialog from '@radix-ui/react-dialog'
import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { PAGE_TITLES, SECTION_TITLES } from '../../app/productLanguage'
import type { components } from '../../api/schema'
import { apiRequest, type ApiEnvelope } from '../../api/client'
import { Button } from '../../components/common/Button'
import { Field } from '../../components/common/Field'
import { NativeFilePicker, type NativeFileSelection } from '../../components/common/NativeFilePicker'
import { useArtifactSave } from '../../components/common/useArtifactSave'
import { WorkspaceHeader, WorkspaceSurface } from '../../components/workspace/WorkspacePrimitives'
import { StudentEditor } from './StudentEditor'
import styles from './infoHub.module.css'

type StudentRecord = components['schemas']['StudentRecord']
type SourceDataView = components['schemas']['SourceDataView']
type SourceImportPreview = components['schemas']['SourceDataImportPreview']
type SourceImportResult = components['schemas']['SourceDataImportResult']
type SourceExportResult = components['schemas']['SourceDataExportBuildResult']
type SourceArtifact = components['schemas']['SourceDataExportArtifact']
type StudentBulkDeleteResult = components['schemas']['StudentBulkDeleteResult']
type Dataset = 'students' | 'instructors' | 'rooms' | 'courses' | 'conveners'
type Section = Dataset | 'import-backup'
type ImportDataset = 'students' | 'rooms' | 'conveners'

const sections: Array<{ id: Section; label: string; detail: string }> = [
  { id: 'students', label: 'Students', detail: 'Canonical roster' },
  { id: 'instructors', label: 'Instructors', detail: 'Teaching staff' },
  { id: 'rooms', label: 'Rooms', detail: 'Scheduling spaces' },
  { id: 'courses', label: 'Courses', detail: 'Course catalogue' },
  { id: 'conveners', label: 'Conveners', detail: 'Course ownership' },
  { id: 'import-backup', label: 'Import & Backup', detail: 'Replace and archive' },
]

const datasetColumns: Record<Exclude<Dataset, 'students'>, Array<{ key: string; label: string }>> = {
  instructors: [{ key: 'name', label: 'Instructor' }, { key: 'status', label: 'Status' }, { key: 'email', label: 'Email' }],
  rooms: [{ key: 'id', label: 'Room' }, { key: 'name', label: 'Name' }, { key: 'type', label: 'Type' }, { key: 'types', label: 'Capabilities' }],
  courses: [{ key: 'course_code', label: 'Course Code' }, { key: 'course_title', label: 'Course Title' }, { key: 'instrument_family', label: 'Instrument' }, { key: 'year_level', label: 'Year' }],
  conveners: [{ key: 'course_code', label: 'Course Code' }, { key: 'course_title', label: 'Course Title' }, { key: 'convener_name', label: 'Convener' }, { key: 'teachers', label: 'Teachers' }],
}

function studentListPath(query: string, instrument: string) {
  const params = new URLSearchParams()
  if (query) params.set('query', query)
  if (instrument) params.set('instrument', instrument)
  const search = params.toString()
  return `/api/students${search ? `?${search}` : ''}`
}

function displayValue(value: unknown) {
  if (Array.isArray(value)) return value.join(', ')
  if (value && typeof value === 'object') return JSON.stringify(value)
  return value == null ? '' : String(value)
}

export function StudentHubPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { studentId } = useParams()
  const [section, setSection] = useState<Section>('students')
  const [search, setSearch] = useState('')
  const [instrument, setInstrument] = useState('')
  const [filters, setFilters] = useState({ query: '', instrument: '' })
  const [selectedStudentIds, setSelectedStudentIds] = useState<Set<string>>(() => new Set())
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)
  useEffect(() => {
    const timeout = window.setTimeout(() => setFilters({ query: search, instrument }), 150)
    return () => window.clearTimeout(timeout)
  }, [search, instrument])
  const activeSection: Section = studentId ? 'students' : section

  const listQuery = useQuery({
    queryKey: ['students', filters.query, filters.instrument],
    queryFn: ({ signal }) => apiRequest<StudentRecord[]>(studentListPath(filters.query, filters.instrument), { signal }),
    enabled: activeSection === 'students',
    placeholderData: keepPreviousData,
  })
  const detailQuery = useQuery({
    queryKey: ['student', studentId ?? ''],
    queryFn: ({ signal }) => apiRequest<StudentRecord>(`/api/students/${encodeURIComponent(studentId ?? '')}`, { signal }),
    enabled: Boolean(studentId),
  })
  const datasetQuery = useQuery({
    queryKey: ['source-data', activeSection],
    queryFn: ({ signal }) => apiRequest<SourceDataView>(`/api/source-data/${activeSection}`, { signal }),
    enabled: !['students', 'import-backup'].includes(activeSection),
  })
  const students = listQuery.data?.data ?? []
  const selectedSection = sections.find((item) => item.id === activeSection) ?? sections[0]
  const visibleIds = students.map((student) => student.student_id)
  const allVisibleSelected = Boolean(visibleIds.length) && visibleIds.every((id) => selectedStudentIds.has(id))
  const bulkDeleteMutation = useMutation<ApiEnvelope<StudentBulkDeleteResult>, Error>({
    mutationFn: () => {
      const version = listQuery.data?.workspace_version
      if (!version || !selectedStudentIds.size) throw new Error('Select students from a trusted workspace first')
      return apiRequest<StudentBulkDeleteResult>('/api/students/bulk-delete', {
        method: 'POST',
        body: JSON.stringify({ expected_version: version, student_ids: [...selectedStudentIds] }),
      })
    },
    onSuccess: (response) => {
      const deleted = new Set(response.data?.deleted_student_ids ?? [])
      setSelectedStudentIds(new Set())
      setBulkDeleteOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['students'] })
      for (const id of deleted) queryClient.removeQueries({ queryKey: ['student', id] })
      if (studentId && deleted.has(studentId)) void navigate('/students')
    },
  })

  function chooseSection(next: Section) {
    setSection(next)
    if (next !== 'students' && studentId) void navigate('/students')
  }

  return (
    <div aria-label="Source data workbench" className={styles.page}>
      <WorkspaceHeader context="Canonical records, imports, and recovery" title={PAGE_TITLES.sourceData} />
      <div className={styles.sourceWorkbench}>
        <nav aria-label="Source Data Sections" className={styles.sourceSectionRail}>
          {sections.map((item) => <button aria-current={activeSection === item.id ? 'page' : undefined} key={item.id} onClick={() => chooseSection(item.id)}><strong>{item.label}</strong><span>{item.detail}</span></button>)}
        </nav>
        <main className={styles.sourceWorkspace}>
          {activeSection === 'students' ? (
            <div className={styles.detailLayout}>
              <WorkspaceSurface aria-labelledby="student-records-heading" className={styles.records}>
                <div className={styles.sectionTitle}><div><h2 id="student-records-heading">{SECTION_TITLES.studentRecords}</h2><p>Search and maintain the local student roster.</p></div><span className="meta">{listQuery.isSuccess ? `${students.length} records` : 'Local workspace'}</span></div>
                <div className={styles.controls}><Field label="Search"><input aria-label="Search" onChange={(event) => setSearch(event.target.value)} value={search} /></Field><Field label="Instrument"><input aria-label="Instrument" onChange={(event) => setInstrument(event.target.value)} value={instrument} /></Field>{selectedStudentIds.size ? <Button onClick={() => setBulkDeleteOpen(true)} variant="destructive">Delete {selectedStudentIds.size} Selected</Button> : null}</div>
                {listQuery.isError ? <div className={styles.inlineError} role="alert"><p>{listQuery.error.message}</p><Button onClick={() => void listQuery.refetch()} variant="secondary">Retry student list</Button></div> : null}
                <div className={styles.tableFrame}><table className={styles.studentTable}><colgroup><col className={styles.selectColumn} /><col className={styles.studentIdColumn} /><col className={styles.studentNameColumn} /><col className={styles.studentChineseNameColumn} /><col className={styles.studentInstrumentColumn} /><col className={styles.studentInstructorColumn} /></colgroup><thead><tr><th className={styles.selectColumn}><input aria-label="Select all visible students" checked={allVisibleSelected} onChange={(event) => setSelectedStudentIds((current) => { const next = new Set(current); for (const id of visibleIds) { if (event.target.checked) next.add(id); else next.delete(id) } return next })} type="checkbox" /></th><th>ID</th><th>English Name</th><th>Chinese Name</th><th>Instrument</th><th>Instructor</th></tr></thead><tbody>
                  {listQuery.isPending ? Array.from({ length: 6 }, (_, index) => <tr aria-label="Loading student" className={styles.skeletonRow} key={index}><td colSpan={6}><span /></td></tr>) : students.map((student) => {
                    const selected = student.student_id === studentId
                    const name = student.name_en || student.display_name
                    return <tr aria-selected={selected} key={student.student_id} onClick={() => void navigate(`/students/${encodeURIComponent(student.student_id)}`)}><td className={styles.selectColumn}><input aria-label={`Select ${name || student.student_id}`} checked={selectedStudentIds.has(student.student_id)} onClick={(event) => event.stopPropagation()} onChange={(event) => setSelectedStudentIds((current) => { const next = new Set(current); if (event.target.checked) next.add(student.student_id); else next.delete(student.student_id); return next })} type="checkbox" /></td><td className="numeric">{student.student_id}</td><td><Link aria-current={selected ? 'page' : undefined} aria-label={`Open student ${name} (${student.student_id})`} className={styles.studentLink} onClick={(event) => event.stopPropagation()} to={`/students/${encodeURIComponent(student.student_id)}`}>{name}</Link></td><td>{student.name_ch}</td><td>{student.instrument}</td><td>{student.instructor}</td></tr>
                  })}
                </tbody></table>{!listQuery.isPending && !listQuery.isError && !students.length ? <div className={styles.empty}><p>No student records match these filters.</p>{(search || instrument) ? <Button onClick={() => { setSearch(''); setInstrument('') }} variant="secondary">Clear filters</Button> : null}</div> : null}</div>
              </WorkspaceSurface>
              {studentId ? <StudentEditor detailQuery={detailQuery} key={studentId} onDeleted={() => void navigate('/students')} onReloadList={() => listQuery.refetch({ throwOnError: true })} studentId={studentId} /> : <aside aria-label="Student record inspector" className={`${styles.editor} ${styles.inspectorEmpty}`}><p className="meta">Record Inspector</p><h2>{SECTION_TITLES.selectStudentRecord}</h2><p>Choose a row to inspect and edit canonical source fields.</p></aside>}
              <Dialog.Root onOpenChange={setBulkDeleteOpen} open={bulkDeleteOpen}><Dialog.Portal><Dialog.Overlay className={styles.dialogOverlay} /><Dialog.Content className={styles.dialog}><Dialog.Title>Delete Selected Students?</Dialog.Title><Dialog.Description>This permanently removes {selectedStudentIds.size} canonical student records.</Dialog.Description>{bulkDeleteMutation.error ? <div className={styles.inlineError} role="alert">{bulkDeleteMutation.error.message}</div> : null}<div className={styles.dialogActions}><Dialog.Close asChild><Button variant="secondary">Cancel</Button></Dialog.Close><Button loading={bulkDeleteMutation.isPending} loadingLabel="Deleting Students" onClick={() => bulkDeleteMutation.mutate()} variant="destructive">Delete Students</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
            </div>
          ) : activeSection === 'import-backup' ? (
            <SourceImportAndBackup onApplied={(dataset) => {
              void queryClient.invalidateQueries({ queryKey: ['source-data', dataset] })
              void queryClient.invalidateQueries({ queryKey: ['students'] })
            }} />
          ) : (
            <DatasetLedger dataset={activeSection} detail={selectedSection.detail} query={datasetQuery} />
          )}
        </main>
      </div>
    </div>
  )
}

function DatasetLedger({ dataset, detail, query }: { dataset: Exclude<Dataset, 'students'>; detail: string; query: ReturnType<typeof useQuery<ApiEnvelope<SourceDataView>, Error>> }) {
  const records = (query.data?.data?.records ?? []) as Array<Record<string, unknown>>
  const columns = datasetColumns[dataset]
  return <WorkspaceSurface className={`${styles.records} ${styles.datasetLedger}`}>
    <div className={styles.sectionTitle}><div><h2>{dataset[0].toUpperCase() + dataset.slice(1)}</h2><p>{detail} from the active local workspace.</p></div><span className="meta">{records.length} records</span></div>
    {query.isError ? <div className={styles.inlineError} role="alert"><strong>Dataset Unavailable</strong><p>{query.error.message}</p><Button onClick={() => void query.refetch()} variant="secondary">Retry Dataset</Button></div> : null}
    <div className={styles.tableFrame}><table><thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{query.isPending ? <tr><td colSpan={columns.length}>Loading canonical records…</td></tr> : records.map((record, index) => <tr key={`${displayValue(record[columns[0].key])}-${index}`}>{columns.map((column) => <td key={column.key}>{displayValue(record[column.key])}</td>)}</tr>)}</tbody></table>{!query.isPending && !query.isError && !records.length ? <div className={styles.empty}><strong>No {dataset} loaded</strong><p>Use Import & Backup when this dataset supports a canonical import.</p></div> : null}</div>
  </WorkspaceSurface>
}

function SourceImportAndBackup({ onApplied }: { onApplied: (dataset: ImportDataset) => void }) {
  const [dataset, setDataset] = useState<ImportDataset>('students')
  const [selection, setSelection] = useState<NativeFileSelection | null>(null)
  const [preview, setPreview] = useState<{ data: SourceImportPreview; version: string } | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [artifacts, setArtifacts] = useState<SourceArtifact[]>([])
  const { saveArtifact } = useArtifactSave()
  const previewMutation = useMutation<ApiEnvelope<SourceImportPreview>, Error, File>({
    mutationFn: (file) => { const body = new FormData(); body.set('file', file); return apiRequest<SourceImportPreview>(`/api/source-data/${dataset}/preview`, { method: 'POST', body }) },
    onSuccess: (response) => { if (response.data && response.workspace_version) setPreview({ data: response.data, version: response.workspace_version }) },
  })
  const applyMutation = useMutation<ApiEnvelope<SourceImportResult>, Error>({
    mutationFn: () => { if (!preview) throw new Error('Preview required'); return apiRequest<SourceImportResult>('/api/source-data/import/apply', { method: 'POST', body: JSON.stringify({ preview_id: preview.data.preview_id, expected_version: preview.version }) }) },
    onSuccess: (response) => { if (response.data) onApplied(response.data.dataset); setPreview(null); setSelection(null); setConfirmed(false) },
  })
  const backupMutation = useMutation<ApiEnvelope<SourceExportResult>, Error>({
    mutationFn: () => apiRequest<SourceExportResult>('/api/source-data/exports/build', { method: 'POST' }),
    onSuccess: (response) => setArtifacts(response.data?.artifacts ?? []),
  })
  const sample = useMemo(() => (preview?.data.sample ?? []) as Array<Record<string, unknown>>, [preview])
  const sampleColumns = useMemo(() => [...new Set(sample.flatMap((record) => Object.keys(record)))].slice(0, 6), [sample])
  return <div className={styles.importBackupWorkspace}>
    <section className={styles.sourceImportPane} aria-labelledby="source-import-heading">
      <div className={styles.sectionTitle}><div><h2 id="source-import-heading">Import Canonical Data</h2><p>Inspect a replacement file before committing it to the local workspace.</p></div><span className="meta">CSV / XLSX · 10 MB max</span></div>
      <div className={styles.sourceImportControls}><Field label="Dataset"><select aria-label="Import Dataset" onChange={(event) => { setDataset(event.target.value as ImportDataset); setSelection(null); setPreview(null); setConfirmed(false) }} value={dataset}><option value="students">Students</option><option value="rooms">Rooms</option><option value="conveners">Course Conveners</option></select></Field><NativeFilePicker accept={dataset === 'conveners' ? '.csv' : '.csv,.xlsx'} kind="sourceData" label={`Choose ${dataset} source`} onSelect={(next) => { setSelection(next); setPreview(null); setConfirmed(false); previewMutation.mutate(next.file) }} selection={selection} /></div>
      {previewMutation.error ? <div className={styles.inlineError} role="alert"><strong>Source Preview Failed</strong><p>{previewMutation.error.message}</p></div> : null}
      {preview ? <div className={styles.sourcePreview}><div><strong>{preview.data.row_count} Valid Records</strong><span className="meta">{preview.data.file_name} · {preview.data.columns.length} columns</span></div><div className={styles.tableFrame}><table><thead><tr>{sampleColumns.map((column) => <th key={column}>{column.replaceAll('_', ' ')}</th>)}</tr></thead><tbody>{sample.map((record, index) => <tr key={index}>{sampleColumns.map((column) => <td key={column}>{displayValue(record[column])}</td>)}</tr>)}</tbody></table></div><label className={styles.importConfirm}><input checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} type="checkbox" />Replace the current canonical {dataset} dataset with this inspected preview.</label><Button disabled={!confirmed || applyMutation.isPending} loading={applyMutation.isPending} loadingLabel="Applying Source Data" onClick={() => applyMutation.mutate()}>Apply {dataset} Import</Button></div> : null}
      {applyMutation.error ? <div className={styles.inlineError} role="alert"><strong>Source Apply Failed</strong><p>{applyMutation.error.message}</p></div> : null}
    </section>
    <aside className={styles.backupPane} aria-labelledby="backup-heading"><p className="meta">Recovery</p><h2 id="backup-heading">Source Exports</h2><p>Build a focused student register plus a complete backup containing students, instructors, rooms, courses, and conveners.</p><Button loading={backupMutation.isPending} loadingLabel="Building Recovery Files" onClick={() => backupMutation.mutate()} variant="secondary">Build Recovery Files</Button>{backupMutation.error ? <div className={styles.inlineError} role="alert"><p>{backupMutation.error.message}</p></div> : null}{artifacts.map((artifact) => <a className="button button--secondary" href={`/api/source-data/exports/${encodeURIComponent(artifact.artifact_id)}`} key={artifact.artifact_id} onClick={(event) => void saveArtifact(event, artifact.artifact_id)}>Save {artifact.filename}</a>)}</aside>
  </div>
}
