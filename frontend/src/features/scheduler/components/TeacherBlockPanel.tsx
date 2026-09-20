import * as Dialog from '@radix-ui/react-dialog'
import { useState } from 'react'
import type { ApiEnvelope } from '../../../api/client'
import type { SchedulerSession } from '../api'
import type { AssignmentCommand } from '../hooks/useAssignmentCommands'
import { adaptAssignment } from './AssignmentBlock'
import type { TeacherSegment } from './teacherPresentation'
import styles from '../assignmentEditor.module.css'

interface TeacherBlockPanelProps {
  assignments: SchedulerSession['assignments']
  commandPending: boolean
  execute: (command: AssignmentCommand) => Promise<ApiEnvelope<SchedulerSession> | null>
  onClose: () => void
  onUnassigned: () => void
  segment: TeacherSegment
  versionConflict: boolean
  workspaceVersion: string | null
}

export function TeacherBlockPanel({
  assignments,
  commandPending,
  execute,
  onClose,
  onUnassigned,
  segment,
  versionConflict,
  workspaceVersion,
}: TeacherBlockPanelProps) {
  const [open, setOpen] = useState(false)
  const lessons = segment.assignmentIds
    .map((id) => assignments.find((item) => item.id === id))
    .filter((item): item is SchedulerSession['assignments'][number] => Boolean(item))
    .map((item) => adaptAssignment(item))
  const commandVersion = workspaceVersion ?? ''
  const disabled = commandPending || versionConflict || !commandVersion || lessons.length === 0

  async function confirm() {
    setOpen(false)
    try {
      const result = await execute({
        assignmentIds: segment.assignmentIds,
        expectedVersion: commandVersion,
        kind: 'unassign_block',
      })
      if (result) onUnassigned()
    } catch {
      // The shared command surface renders the persistent server error.
    }
  }

  return (
    <section className={styles.assignmentEditor} data-teacher-block-panel>
      <header className={styles.panelHeading}>
        <div>
          <h2>Selected teacher block</h2>
          <p>Unassign every lesson in this contiguous same-room block. Canonical identities stay one-to-one.</p>
        </div>
        <button className="button button--secondary" onClick={onClose} type="button">Close</button>
      </header>
      <div className={styles.editorIdentity}>
        <span>Teachers</span>
        <strong>{segment.instructor}</strong>
        <span>{segment.room} · {segment.start}–{segment.end}</span>
      </div>
      <ul className={styles.blockLessonList}>
        {lessons.map((lesson) => (
          <li key={lesson.id}>
            <strong>{lesson.person || lesson.title}</strong>
            <span>{lesson.start}–{lesson.end}</span>
          </li>
        ))}
      </ul>
      <div className={styles.editorActions}>
        <Dialog.Root onOpenChange={setOpen} open={open}>
          <Dialog.Trigger asChild>
            <button className="button button--destructive" disabled={disabled} type="button">
              Unassign this block
            </button>
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className={styles.dialogOverlay} />
            <Dialog.Content className={styles.dialogContent}>
              <Dialog.Title>Unassign this teacher block?</Dialog.Title>
              <Dialog.Description>
                {lessons.length} lesson{lessons.length === 1 ? '' : 's'} return to the issue queue. The rest of {segment.instructor}&apos;s day is unchanged.
              </Dialog.Description>
              <div className={styles.dialogActions}>
                <Dialog.Close asChild><button className="button button--secondary" type="button">Cancel</button></Dialog.Close>
                <button className="button button--destructive" disabled={commandPending} onClick={() => { void confirm() }} type="button">Confirm unassign</button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </div>
    </section>
  )
}
