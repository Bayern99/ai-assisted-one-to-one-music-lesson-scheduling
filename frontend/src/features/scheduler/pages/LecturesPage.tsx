import * as Dialog from '@radix-ui/react-dialog'
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PAGE_TITLES } from '../../../app/productLanguage'
import { ApiClientError } from '../../../api/client'
import { Button } from '../../../components/common/Button'
import { Field } from '../../../components/common/Field'
import { NativeFilePicker, type NativeFileSelection } from '../../../components/common/NativeFilePicker'
import { TimeInput } from '../../../components/common/TimeInput'
import { isCanonicalTime } from '../../../components/common/timeInputUtils'
import { DockedPane, WorkspaceHeader, WorkspaceSurface, WorkspaceToolbar } from '../../../components/workspace/WorkspacePrimitives'
import {
  getSchedulerLectures,
  previewSchedulerLectures,
  saveSchedulerLectures,
  schedulerLecturesKey,
  schedulerSessionKey,
  type LectureEvent,
  type SchedulerLectureCsvPreview,
  useSchedulerSession,
  validateSchedulerLectures,
} from '../api'
import pageStyles from './LecturesPage.module.css'
import workspaceStyles from '../schedulerWorkspace.module.css'

const styles = new Proxy(workspaceStyles, { get: (target, key: string) => target[key] ?? pageStyles[key] })

const DAYS = [
  { value: 1, label: 'Monday' }, { value: 2, label: 'Tuesday' },
  { value: 3, label: 'Wednesday' }, { value: 4, label: 'Thursday' },
  { value: 5, label: 'Friday' }, { value: 6, label: 'Saturday' },
  { value: 0, label: 'Sunday' },
] as const

function InlineError({ error }: { error: Error | null }) {
  if (!error) return null
  const details = error instanceof ApiClientError ? error.details : null
  const messages = details ? Object.values(details).flatMap((value) => Array.isArray(value) ? value : [value]) : []
  return <div className={styles.inlineError} role="alert"><strong>{error.message}</strong>{messages.map((message, index) => <p key={index}>{typeof message === 'object' ? JSON.stringify(message) : String(message)}</p>)}</div>
}

function daySummary(days: number[]) {
  return DAYS.filter((day) => days.includes(day.value)).map((day) => day.label.slice(0, 3)).join(', ') || 'No day'
}

function newLecture(room: string): LectureEvent {
  return {
    id: crypto.randomUUID(), title: 'New Lecture', resourceId: room,
    daysOfWeek: [1], startTime: '09:00', endTime: '10:00', type: 'lecture', locked: true,
  }
}

export function LecturesPage() {
  const queryClient = useQueryClient()
  const sessionQuery = useSchedulerSession()
  const lecturesQuery = useQuery({ queryKey: schedulerLecturesKey, queryFn: ({ signal }) => getSchedulerLectures(signal) })
  const [draft, setDraft] = useState<LectureEvent[] | null>(null)
  const [baseline, setBaseline] = useState<LectureEvent[] | null>(null)
  const [baselineVersion, setBaselineVersion] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [revision, setRevision] = useState(0)
  const [validatedRevision, setValidatedRevision] = useState<number | null>(null)
  const [validation, setValidation] = useState<Awaited<ReturnType<typeof validateSchedulerLectures>>['data']>(null)
  const [message, setMessage] = useState('')
  const [preview, setPreview] = useState<SchedulerLectureCsvPreview | null>(null)
  const [selection, setSelection] = useState<NativeFileSelection | null>(null)
  const [removeOpen, setRemoveOpen] = useState(false)

  /* eslint-disable react-hooks/set-state-in-effect -- The editable draft is hydrated once from an asynchronously versioned workspace snapshot. */
  useEffect(() => {
    const loaded = lecturesQuery.data?.data
    if (!loaded || draft !== null) return
    const lectures = structuredClone(loaded.lectures)
    setDraft(lectures)
    setBaseline(structuredClone(lectures))
    setBaselineVersion(lecturesQuery.data?.workspace_version ?? null)
    setSelectedId(lectures[0]?.id ?? '')
  }, [draft, lecturesQuery.data])
  /* eslint-enable react-hooks/set-state-in-effect */

  const rooms = (sessionQuery.data?.data?.rooms ?? []).map((room) => room.id)
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(baseline)
  const selectedIndex = draft?.findIndex((lecture) => lecture.id === selectedId) ?? -1
  const selected = selectedIndex >= 0 ? draft?.[selectedIndex] ?? null : null
  const validTimes = Boolean(draft?.every((lecture) => isCanonicalTime(lecture.startTime.slice(0, 5)) && isCanonicalTime(lecture.endTime.slice(0, 5))))
  const readOnly = sessionQuery.isError || lecturesQuery.isError
  const conflictByLecture = useMemo(() => new Map(
    (validation?.conflicts ?? []).map((conflict) => [conflict.lecture_id, conflict]),
  ), [validation])

  function replaceDraft(lectures: LectureEvent[], selectId = lectures[0]?.id ?? '') {
    setDraft(lectures)
    setSelectedId(selectId)
    setRevision((value) => value + 1)
    setValidatedRevision(null)
    setValidation(null)
    setMessage('')
  }

  function updateSelected(changes: Partial<LectureEvent>) {
    if (!draft || selectedIndex < 0) return
    replaceDraft(draft.map((lecture, index) => index === selectedIndex ? { ...lecture, ...changes } : lecture), selectedId)
  }

  const previewMutation = useMutation({
    mutationFn: previewSchedulerLectures,
    onSuccess: (response) => {
      if (!response.data) return
      setPreview(response.data)
      setBaselineVersion(response.workspace_version ?? baselineVersion)
      replaceDraft(structuredClone(response.data.lectures))
    },
  })
  const validateMutation = useMutation({
    mutationFn: ({ lectures }: { lectures: LectureEvent[]; revision: number }) => validateSchedulerLectures(lectures),
    onSuccess: (response, variables) => {
      setValidation(response.data)
      setValidatedRevision(response.data?.conflicts.length ? null : variables.revision)
      setMessage(response.data?.conflicts.length ? 'Conflicts found. Select each marked lecture to review it.' : 'No lecture conflicts found.')
    },
    onError: () => setValidatedRevision(null),
  })
  const saveMutation = useMutation({
    mutationFn: () => saveSchedulerLectures(draft!, baselineVersion!),
    onSuccess: async (response) => {
      const saved = structuredClone(response.data?.lectures ?? draft ?? [])
      setDraft(saved)
      setBaseline(structuredClone(saved))
      setBaselineVersion(response.workspace_version ?? baselineVersion)
      setValidatedRevision(null)
      setValidation(null)
      setMessage(response.warnings.join(' ') || 'Lecture Locks Saved and Revalidated.')
      if (!saved.some((lecture) => lecture.id === selectedId)) setSelectedId(saved[0]?.id ?? '')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: schedulerSessionKey }),
        queryClient.invalidateQueries({ queryKey: schedulerLecturesKey }),
      ])
    },
  })

  return (
    <div className={`${styles.page} ${styles.workspacePage}`}>
      <WorkspaceHeader
        actions={<span className={styles.dirtyState}>{dirty ? 'Unsaved Changes' : 'Workspace Aligned'}</span>}
        context={baselineVersion ? 'Academic Registry Lecture Constraints' : 'Lecture Workspace Needs Review'}
        title={PAGE_TITLES.lectureLocks}
      />
      <div className={styles.lectureWorkbench}>
        <WorkspaceSurface className={styles.lectureMain}>
          <WorkspaceToolbar className={`${styles.actionRail} ${styles.lectureActionRail}`}>
            <div><strong>Lecture Lock Register</strong><span>Import, inspect, validate, and save fixed room events before source requirements.</span></div>
            <Button disabled={readOnly || !draft} onClick={() => {
              const lecture = newLecture(rooms[0] ?? '')
              replaceDraft([...(draft ?? []), lecture], lecture.id)
            }} variant="secondary">Add Lecture</Button>
          </WorkspaceToolbar>
          <NativeFilePicker
            accept=".csv,text/csv"
            disabled={readOnly || previewMutation.isPending}
            inputLabel="Lecture CSV file"
            kind="lectureCSV"
            label="Lecture Lock CSV"
            onSelect={(next) => { setSelection(next); previewMutation.mutate(next.file) }}
            selection={selection}
          />
          <InlineError error={sessionQuery.error ?? lecturesQuery.error ?? previewMutation.error} />
          {sessionQuery.isError || lecturesQuery.isError ? <Button onClick={() => void Promise.all([sessionQuery.refetch(), lecturesQuery.refetch()])} variant="secondary">Retry Lecture Workspace</Button> : null}
          {preview ? <div className={styles.lecturePreviewSummary} role="status"><div><strong>{preview.file_name}</strong><span>{preview.source_row_count} source rows · {preview.lectures.length} candidates</span></div>{preview.warnings.length ? <ul>{preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}</div> : null}
          {lecturesQuery.isPending || !draft ? <div aria-label="Loading lecture locks" className={styles.skeleton} /> : (
            <div className={`${styles.tableFrame} ${styles.lectureListFrame}`}>
              <table aria-label="Lecture locks">
                <thead><tr><th>Lecture</th><th>Room</th><th>Day</th><th>Time</th><th>State</th></tr></thead>
                <tbody>{draft.map((lecture) => {
                  const conflict = conflictByLecture.get(lecture.id)
                  return <tr aria-selected={lecture.id === selectedId} className={conflict ? styles.conflictRow : undefined} key={lecture.id} onClick={() => setSelectedId(lecture.id)}>
                    <td><button className={styles.rowSelectButton} onClick={() => setSelectedId(lecture.id)} type="button"><strong>{lecture.title || 'Untitled Lecture'}</strong><span className="meta">{lecture.id}</span></button></td>
                    <td className="room">{lecture.resourceId || 'Unassigned'}</td>
                    <td>{daySummary(lecture.daysOfWeek)}</td>
                    <td className="time">{lecture.startTime.slice(0, 5)} – {lecture.endTime.slice(0, 5)}</td>
                    <td>{conflict ? 'Conflict' : 'Locked'}</td>
                  </tr>
                })}</tbody>
              </table>
              {!draft.length ? <p className={styles.empty}>No lecture locks are configured.</p> : null}
            </div>
          )}
        </WorkspaceSurface>
        <DockedPane aria-label="Selected lecture inspector" className={styles.lectureInspector}>
          {selected ? <fieldset className={styles.editorScope} disabled={readOnly || saveMutation.isPending}>
            <legend className={styles.scopeLegend}>Selected Lecture</legend>
            <div className={`${styles.sectionHeading} ${styles.lectureInspectorHeading}`}><div><h2>{selected.title || 'Untitled Lecture'}</h2><p className="meta">{selected.id}</p></div></div>
            <div className={styles.lectureInspectorFields}>
              <Field label="Title"><input aria-label={`Lecture title ${selected.id}`} onChange={(event) => updateSelected({ title: event.target.value })} value={selected.title} /></Field>
              <Field label="Room"><select aria-label={`Room for ${selected.id}`} onChange={(event) => updateSelected({ resourceId: event.target.value })} value={selected.resourceId}>{[...new Set([selected.resourceId, ...rooms])].filter(Boolean).map((room) => <option key={room}>{room}</option>)}</select></Field>
              <fieldset className={styles.daysFieldset}><legend>Days</legend>{DAYS.map((day) => <label key={day.value}><input aria-label={`${day.label} for ${selected.id}`} checked={selected.daysOfWeek.includes(day.value)} onChange={(event) => updateSelected({ daysOfWeek: event.target.checked ? [...selected.daysOfWeek, day.value].sort((a, b) => a - b) : selected.daysOfWeek.filter((value) => value !== day.value) })} type="checkbox" /><span>{day.label.slice(0, 2)}</span></label>)}</fieldset>
              <div className={styles.timePair}><Field label="Start"><TimeInput aria-label={`Start time for ${selected.id}`} onChange={(event) => updateSelected({ startTime: event.target.value })} value={selected.startTime.slice(0, 5)} /></Field><Field label="End"><TimeInput aria-label={`End time for ${selected.id}`} onChange={(event) => updateSelected({ endTime: event.target.value })} value={selected.endTime.slice(0, 5)} /></Field></div>
            </div>
            {conflictByLecture.get(selected.id) ? <div className={styles.inlineError} role="alert"><strong>Lecture Conflict</strong><p>{conflictByLecture.get(selected.id)?.message}</p></div> : null}
            <Dialog.Root onOpenChange={setRemoveOpen} open={removeOpen}>
              <Dialog.Trigger asChild><Button variant="quiet">Remove Lecture</Button></Dialog.Trigger>
              <Dialog.Portal>
                <Dialog.Overlay className={styles.dialogOverlay} />
                <Dialog.Content className={styles.dialogContent}>
                  <Dialog.Title>Remove this lecture?</Dialog.Title>
                  <Dialog.Description>This removes the lecture from the current draft. It is not saved until you save lecture locks.</Dialog.Description>
                  <div className={styles.dialogActions}>
                    <Dialog.Close asChild><Button variant="secondary">Cancel</Button></Dialog.Close>
                    <Button onClick={() => {
                      const next = (draft ?? []).filter((lecture) => lecture.id !== selected.id)
                      replaceDraft(next, next[0]?.id ?? '')
                      setRemoveOpen(false)
                    }} variant="destructive">Confirm remove</Button>
                  </div>
                </Dialog.Content>
              </Dialog.Portal>
            </Dialog.Root>
          </fieldset> : <div className={styles.inspectorEmpty}><h2>Select a Lecture</h2><p>Choose a row to inspect and edit its locked room and time.</p></div>}
          <InlineError error={validateMutation.error ?? saveMutation.error} />
          {message ? <p className={styles.persistentStatus} role="status">{message}</p> : null}
          <div className={styles.lectureCommands}>
            <Button disabled={readOnly || !draft || !validTimes || validateMutation.isPending} onClick={() => validateMutation.mutate({ lectures: draft ?? [], revision })} variant="secondary">Check Conflicts</Button>
            <Button disabled={!dirty || !validTimes || validatedRevision !== revision || !baselineVersion || saveMutation.isPending} onClick={() => saveMutation.mutate()}>Save Lecture Locks</Button>
            {draft && !validTimes ? <span className={styles.fieldHint}>Enter lecture times as 24-hour HH:MM before checking conflicts.</span> : null}
          </div>
        </DockedPane>
      </div>
    </div>
  )
}
