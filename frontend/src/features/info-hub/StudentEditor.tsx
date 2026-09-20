import * as Dialog from '@radix-ui/react-dialog'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import type { components } from '../../api/schema'
import { ApiClientError, apiRequest, type ApiEnvelope } from '../../api/client'
import { Button } from '../../components/common/Button'
import { Field } from '../../components/common/Field'
import styles from './infoHub.module.css'

type StudentRecord = components['schemas']['StudentRecord']
type StudentUpdate = components['schemas']['StudentUpdateRequest']
type StudentDeleteResult = components['schemas']['StudentDeleteResult']
type EditableKey = Exclude<keyof StudentUpdate, 'expected_version'>
type Draft = Pick<StudentUpdate, EditableKey>

const fields: readonly { key: EditableKey; label: string; type?: 'number'; helper?: string }[] = [
  { key: 'name_en', label: 'English name' },
  { key: 'name_ch', label: 'Chinese name' },
  { key: 'display_name', label: 'Display name' },
  { key: 'year', label: 'Study year', type: 'number', helper: 'Use 0 if the study year is not assigned.' },
  { key: 'instructor', label: 'Instructor' },
  { key: 'instrument', label: 'Instrument' },
  { key: 'type', label: 'Student type' },
  { key: 'course_code', label: 'Course code' },
  { key: 'status', label: 'Status' },
]

function draftFrom(student: StudentRecord): Draft {
  return Object.fromEntries(fields.map(({ key }) => [key, student[key]])) as Draft
}

interface StudentEditorProps {
  detailQuery: UseQueryResult<ApiEnvelope<StudentRecord>, Error>
  onDeleted: (studentId: string) => void
  onReloadList: () => Promise<unknown>
  studentId: string
}

interface SaveVariables {
  body: StudentUpdate
  studentId: string
}

export function StudentEditor({ detailQuery, onDeleted, onReloadList, studentId }: StudentEditorProps) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>({})
  const [touched, setTouched] = useState<Set<EditableKey>>(() => new Set())
  const [conflict, setConflict] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [isReloading, setIsReloading] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const activeStudent = useRef<string | null>(null)
  const currentStudentId = useRef<string | null>(studentId)
  const student = detailQuery.data?.data ?? null

  const mutation = useMutation({
    mutationFn: ({ body, studentId: mutationStudentId }: SaveVariables) => apiRequest<StudentRecord>(
      `/api/students/${encodeURIComponent(mutationStudentId)}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    ),
    onSuccess: (envelope, variables) => {
      queryClient.setQueryData(['student', variables.studentId], envelope)
      void queryClient.invalidateQueries({ queryKey: ['students'] })
      if (currentStudentId.current !== variables.studentId) return
      setDraft(envelope.data ? draftFrom(envelope.data) : {})
      setTouched(new Set())
      setConflict(null)
      setSaved(true)
    },
    onError: (error, variables) => {
      if (currentStudentId.current !== variables.studentId) return
      setSaved(false)
      if (error instanceof ApiClientError && error.status === 409) setConflict(error.message)
    },
  })
  const deleteMutation = useMutation({
    mutationFn: () => {
      if (!detailQuery.data?.workspace_version) throw new Error('A trusted workspace version is required')
      return apiRequest<StudentDeleteResult>(`/api/students/${encodeURIComponent(studentId)}`, {
        method: 'DELETE',
        body: JSON.stringify({ expected_version: detailQuery.data.workspace_version }),
      })
    },
    onSuccess: (envelope) => {
      const deletedId = envelope.data?.deleted_student_id ?? studentId
      queryClient.removeQueries({ queryKey: ['student', deletedId] })
      void queryClient.invalidateQueries({ queryKey: ['students'] })
      setDeleteOpen(false)
      onDeleted(deletedId)
    },
    onError: (error) => {
      if (error instanceof ApiClientError && error.status === 409) setConflict(error.message)
    },
  })

  const resetMutation = mutation.reset
  useEffect(() => () => {
    currentStudentId.current = null
    resetMutation()
  }, [resetMutation])

  useEffect(() => {
    if (!student) return
    if (activeStudent.current !== studentId) {
      activeStudent.current = studentId
      setDraft(draftFrom(student))
      return
    }
    setDraft((current) => {
      const next = { ...current } as Record<EditableKey, string | number | undefined>
      for (const { key } of fields) if (!touched.has(key)) next[key] = student[key]
      return next as Draft
    })
  }, [student, studentId, touched])

  const changes: Partial<StudentUpdate> = {}
  if (student) {
    for (const { key } of fields) {
      if (touched.has(key) && draft[key] !== student[key]) {
        Object.assign(changes, { [key]: draft[key] })
      }
    }
  }
  const isSaving = mutation.isPending && mutation.variables?.studentId === studentId
  const isDeleting = deleteMutation.isPending

  if (detailQuery.isPending) return <aside aria-label="Student record inspector" className={styles.editor}><p role="status">Loading student record...</p></aside>
  if (detailQuery.isError && !student) {
    const notFound = detailQuery.error instanceof ApiClientError && detailQuery.error.status === 404
    return (
      <aside aria-label="Student record inspector" className={styles.editor}>
        <h2>{notFound ? 'Student Not Found' : 'Student Record Unavailable'}</h2>
        <div className={styles.inlineError} role="alert"><p>{detailQuery.error.message}</p><Button onClick={() => void detailQuery.refetch()} variant="secondary">Retry student record</Button></div>
      </aside>
    )
  }
  if (!student) return <aside aria-label="Student record inspector" className={styles.editor}><h2>No Student Record</h2><p>The workspace returned no details for this student.</p></aside>

  async function reloadWorkspace() {
    if (isReloading) return
    const reloadingStudentId = studentId
    setIsReloading(true)
    try {
      await Promise.all([
        detailQuery.refetch({ throwOnError: true }),
        onReloadList(),
      ])
      mutation.reset()
      setConflict(null)
      setSaved(false)
    } catch {
      // The conflict remains actionable until both workspace reads succeed.
    } finally {
      if (currentStudentId.current === reloadingStudentId) setIsReloading(false)
    }
  }

  return (
    <aside aria-label="Student record inspector" className={styles.editor} tabIndex={0}>
      <div className={styles.editorHeading}><div><p className="meta">Student editor</p><h2 id="editor-heading">{student.name_en || student.display_name || student.student_id}</h2></div><span className="numeric">{student.student_id}</span></div>
      {conflict ? (
        <div className={styles.conflict} role="alert"><p>{conflict}. Your draft is preserved.</p><Button aria-busy={isReloading} disabled={isReloading} onClick={() => void reloadWorkspace()} variant="secondary">Reload workspace</Button></div>
      ) : null}
      {mutation.isError && mutation.variables?.studentId === studentId && !conflict ? <p className={styles.inlineError} role="alert">{mutation.error.message}</p> : null}
      {deleteMutation.isError && !conflict ? <p className={styles.inlineError} role="alert">{deleteMutation.error.message}</p> : null}
      {saved ? <p className={styles.saved} role="status">Student record saved.</p> : null}
      <form aria-busy={isSaving} onSubmit={(event) => {
        event.preventDefault()
        if (!detailQuery.data?.workspace_version || !Object.keys(changes).length) return
        setSaved(false)
        mutation.mutate({
          body: { ...changes, expected_version: detailQuery.data.workspace_version },
          studentId,
        })
      }}>
        <fieldset className={styles.editorFieldset} disabled={isSaving || isDeleting}>
          <div className={styles.formFields}>
            {fields.map(({ key, label, type, helper }) => (
              <Field helper={helper} key={key} label={label}>
                <input
                  min={type === 'number' ? 0 : undefined}
                  onChange={(event) => {
                    const value = type === 'number' ? Number(event.target.value) : event.target.value
                    setDraft((current) => ({ ...current, [key]: value }))
                    setTouched((current) => new Set(current).add(key))
                    setSaved(false)
                  }}
                  type={type ?? 'text'}
                  value={draft[key] ?? ''}
                />
              </Field>
            ))}
          </div>
        </fieldset>
        <div className={styles.editorActions}>
          <Dialog.Root onOpenChange={setDeleteOpen} open={deleteOpen}>
            <Dialog.Trigger asChild><Button disabled={isSaving || isDeleting || !detailQuery.data.workspace_version} variant="destructive">Delete Student</Button></Dialog.Trigger>
            <Dialog.Portal><Dialog.Overlay className={styles.dialogOverlay} /><Dialog.Content className={styles.dialog}><Dialog.Title>Delete {student.name_en || student.student_id}?</Dialog.Title><Dialog.Description>This removes the canonical student record. Existing exported files and schedule history are not rewritten.</Dialog.Description><div className={styles.dialogActions}><Dialog.Close asChild><Button disabled={isDeleting} variant="secondary">Cancel</Button></Dialog.Close><Button loading={isDeleting} loadingLabel="Deleting Student" onClick={() => deleteMutation.mutate()} variant="destructive">Confirm Delete</Button></div></Dialog.Content></Dialog.Portal>
          </Dialog.Root>
          <div><Button disabled={isSaving || isDeleting || !detailQuery.data.workspace_version || !Object.keys(changes).length} type="submit">{isSaving ? 'Saving…' : 'Save student'}</Button><span>{Object.keys(changes).length ? `${Object.keys(changes).length} changed` : 'No changes'}</span></div>
        </div>
      </form>
    </aside>
  )
}
