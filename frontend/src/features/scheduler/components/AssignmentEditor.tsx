import * as Dialog from '@radix-ui/react-dialog'
import { useCallback, useEffect, useState } from 'react'
import type { ApiEnvelope } from '../../../api/client'
import { Field } from '../../../components/common/Field'
import { TimeInput } from '../../../components/common/TimeInput'
import { isCanonicalTime } from '../../../components/common/timeInputUtils'
import { validateAssignmentMove, validateIssueAssignment, type SchedulerSession } from '../api'
import type { AssignmentCommand, MoveTarget } from '../hooks/useAssignmentCommands'
import styles from '../assignmentEditor.module.css'
import { adaptAssignment, type AssignmentView } from './AssignmentBlock'
import type { ResolutionSelectionContext } from './ResolutionCaseCard'
import { issueReservationNote } from '../scheduleAuthority'
import { TeacherConfirmationFields } from './TeacherConfirmationFields'

const DAYS = [
  { id: 0, label: 'Sunday' }, { id: 1, label: 'Monday' }, { id: 2, label: 'Tuesday' },
  { id: 3, label: 'Wednesday' }, { id: 4, label: 'Thursday' }, { id: 5, label: 'Friday' },
  { id: 6, label: 'Saturday' },
]

interface AssignmentEditorProps {
  assignment: SchedulerSession['assignments'][number] | null
  assignmentProposal: MoveTarget | null
  commandPending: boolean
  editorEpoch: number
  execute: (command: AssignmentCommand) => Promise<ApiEnvelope<SchedulerSession> | null>
  issue: SchedulerSession['issues'][number]['items'][number] | null
  issueProposal: MoveTarget | null
  onCanonicalResponse: (result: ApiEnvelope<SchedulerSession>) => void
  onClose?: () => void
  onIssueAssigned: (result: ApiEnvelope<SchedulerSession>) => void
  onSetWaiting: (caseId: string, waiting: boolean, note: string) => void
  reconciliation?: boolean
  resolutionContext: ResolutionSelectionContext | null
  rooms: SchedulerSession['rooms']
  versionConflict: boolean
  waitingPending: boolean
  workspaceVersion: string | null
}

interface MoveDraft {
  day: string
  end: string
  room: string
  start: string
}

function clockInput(value: string | null) {
  return value?.match(/(?:T|^)(\d{2}:\d{2})/)?.[1] ?? ''
}

function draftFrom(view: AssignmentView): MoveDraft {
  return { day: view.day === null ? '' : String(view.day), end: view.proposalEnd ?? clockInput(view.end), room: view.room ?? '', start: view.proposalStart ?? clockInput(view.start) }
}

interface EditorFormProps extends Omit<AssignmentEditorProps, 'assignment' | 'editorEpoch' | 'issue' | 'issueProposal' | 'onIssueAssigned' | 'onSetWaiting' | 'reconciliation' | 'resolutionContext' | 'waitingPending'> {
  assignment: SchedulerSession['assignments'][number]
}

function AssignmentEditorForm({ assignment, assignmentProposal, commandPending, execute, onCanonicalResponse, rooms, versionConflict, workspaceVersion }: EditorFormProps) {
  const initialView = adaptAssignment(assignment)
  const [draft, setDraft] = useState(() => assignmentProposal
    ? { day: String(assignmentProposal.day), end: assignmentProposal.end, room: assignmentProposal.room, start: assignmentProposal.start }
    : draftFrom(initialView))
  const [baselineVersion, setBaselineVersion] = useState(workspaceVersion)
  const [validation, setValidation] = useState<Awaited<ReturnType<typeof validateAssignmentMove>>['data']>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [validationPending, setValidationPending] = useState(false)
  const [teacherConfirmed, setTeacherConfirmed] = useState(false)
  const [confirmationNote, setConfirmationNote] = useState('')
  const [decisionNote, setDecisionNote] = useState('')
  const [unassignOpen, setUnassignOpen] = useState(false)

  function update<K extends keyof MoveDraft>(key: K, value: MoveDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }))
    setValidation(null)
    setValidationError(null)
    setTeacherConfirmed(false)
    setConfirmationNote('')
    setDecisionNote('')
  }

  function adoptCanonical(result: ApiEnvelope<SchedulerSession>) {
    const canonical = result.data?.assignments.find((item) => item.id === assignment.id)
    if (canonical) setDraft(draftFrom(adaptAssignment(canonical)))
    setBaselineVersion(result.workspace_version)
    setValidation(null)
    setValidationError(null)
    setTeacherConfirmed(false)
    setConfirmationNote('')
    setDecisionNote('')
  }

  async function run(command: AssignmentCommand) {
    try {
      const result = await execute(command)
      if (result) {
        adoptCanonical(result)
        onCanonicalResponse(result)
      }
    } catch {
      // The shared command surface renders the persistent server error.
    }
  }

  function target(): MoveTarget {
    return { day: Number(draft.day), end: draft.end, room: draft.room, start: draft.start }
  }

  async function validateMove() {
    setValidationPending(true)
    setValidationError(null)
    try {
      const result = await validateAssignmentMove(assignment.id, target())
      setValidation(result.data)
      setBaselineVersion(result.workspace_version)
    } catch (error) {
      setValidation(null)
      setValidationError(error instanceof Error ? error.message : 'Move validation failed')
    } finally {
      setValidationPending(false)
    }
  }

  function commitMove() {
    if (!baselineVersion || !validation?.success) return
    void run({
      assignmentId: assignment.id,
      expectedVersion: baselineVersion,
      kind: 'move',
      target: target(),
      confirmation: { confirmed: teacherConfirmed, note: confirmationNote },
      decisionNote,
    })
  }

  const commandVersion = workspaceVersion ?? ''
  const complete = Boolean(draft.room && draft.day !== '' && isCanonicalTime(draft.start) && isCanonicalTime(draft.end))
  const controlsDisabled = commandPending || versionConflict || validationPending
  return (
    <form className={styles.editorForm} onSubmit={(event) => event.preventDefault()}>
      <div className={styles.editorIdentity}>
        <span>{initialView.kind === 'locked' ? 'Locked' : initialView.kind === 'studio' ? 'Studio' : 'Weekly'}</span>
        <strong>{initialView.title}</strong>
        <span>{initialView.instructor}</span>
      </div>
      <Field label="Room"><select disabled={controlsDisabled} onChange={(event) => update('room', event.target.value)} required value={draft.room}>
        <option disabled value="">Select room</option>
        {rooms.map((room) => <option key={room.id} value={room.id}>{room.id}</option>)}
      </select></Field>
      <Field label="Day"><select disabled={controlsDisabled} onChange={(event) => update('day', event.target.value)} required value={draft.day}>
        <option disabled value="">Select day</option>
        {DAYS.map((day) => <option key={day.id} value={day.id}>{day.label}</option>)}
      </select></Field>
      <Field label="Start time"><TimeInput disabled={controlsDisabled} onChange={(event) => update('start', event.target.value)} required value={draft.start} /></Field>
      <Field label="End time"><TimeInput disabled={controlsDisabled} onChange={(event) => update('end', event.target.value)} required value={draft.end} /></Field>
      {validationError || (validation && !validation.success && validation.message) ? <p className={styles.proposalError} role="alert">{validationError ?? validation?.message}</p> : null}
      {validation?.success ? (
        <div aria-live="polite" className={styles.proposalValidation} role="status">
          <strong>Move validated.</strong>
          {validation.start_norm && validation.end_norm ? <span>Final occupancy: {validation.start_norm}–{validation.end_norm}</span> : null}
          {validation.warnings?.length ? <ul aria-label="Move warnings">{validation.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
        </div>
      ) : null}
      {validation?.success && validation.requires_teacher_confirmation ? (
        <TeacherConfirmationFields
          checked={teacherConfirmed}
          message={validation.teacher_confirmation_message}
          note={confirmationNote}
          onCheckedChange={setTeacherConfirmed}
          onNoteChange={setConfirmationNote}
        />
      ) : null}
      <Field
        helper="Record why this intervention was chosen. Avoid personal names or IDs."
        label="Decision note"
      >
        <textarea
          disabled={controlsDisabled}
          maxLength={500}
          onChange={(event) => setDecisionNote(event.target.value)}
          placeholder="e.g. Preserves teacher workload while accepting a second-choice time"
          rows={3}
          value={decisionNote}
        />
      </Field>
      <div className={styles.editorActions}>
        <button className="button button--secondary" disabled={controlsDisabled || !complete} onClick={() => void validateMove()} type="button">Validate move</button>
        <button className="button button--primary" disabled={controlsDisabled || !validation?.success || !baselineVersion || Boolean(validation.requires_teacher_confirmation && !teacherConfirmed)} onClick={commitMove} type="button">Move assignment</button>
        <Dialog.Root onOpenChange={setUnassignOpen} open={unassignOpen}>
          <Dialog.Trigger asChild>
            <button className="button button--secondary" disabled={controlsDisabled || !commandVersion} type="button">Unassign assignment</button>
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className={styles.dialogOverlay} />
            <Dialog.Content className={styles.dialogContent}>
              <Dialog.Title>Unassign this assignment?</Dialog.Title>
              <Dialog.Description>This removes the current placement and returns the request to the issue queue. The schedule is not changed until you confirm.</Dialog.Description>
              <div className={styles.dialogActions}>
                <Dialog.Close asChild><button className="button button--secondary" type="button">Cancel</button></Dialog.Close>
                <button className="button button--destructive" disabled={commandPending} onClick={() => { setUnassignOpen(false); void run({ assignmentId: assignment.id, decisionNote, expectedVersion: commandVersion, kind: 'unassign' }) }} type="button">Confirm unassign</button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
        {initialView.locked ? <button className="button button--secondary" disabled={commandPending || versionConflict || !commandVersion} onClick={() => void run({ assignmentId: assignment.id, expectedVersion: commandVersion, kind: 'unlock' })} type="button">Unlock assignment</button> : null}
      </div>
      {!complete ? <small className="meta">Enter a room, day, and valid 24-hour HH:MM times before checking conflicts.</small> : !validation ? <small className="meta">Check conflicts after every change before moving the assignment.</small> : null}
    </form>
  )
}

type Issue = SchedulerSession['issues'][number]['items'][number]

interface IssueEditorFormProps {
  commandPending: boolean
  execute: AssignmentEditorProps['execute']
  issue: Issue
  issueProposal: MoveTarget | null
  onIssueAssigned: AssignmentEditorProps['onIssueAssigned']
  onSetWaiting: AssignmentEditorProps['onSetWaiting']
  reconciliation: boolean
  resolutionContext: ResolutionSelectionContext | null
  rooms: SchedulerSession['rooms']
  versionConflict: boolean
  waitingPending: boolean
  workspaceVersion: string | null
}

function issueDraft(issue: Issue, rooms: SchedulerSession['rooms'], proposal: MoveTarget | null): MoveDraft {
  if (proposal) {
    return {
      day: String(proposal.day),
      end: proposal.end,
      room: proposal.room,
      start: proposal.start,
    }
  }
  const canonicalRoomIds = new Set(rooms.map((room) => room.id))
  const preferredRoom = issue.preferred_venues?.find((room) => canonicalRoomIds.has(room)) ?? ''
  return {
    day: issue.original_day === null || issue.original_day === undefined ? '' : String(issue.original_day),
    end: issue.proposal_end ?? issue.original_end ?? '',
    room: preferredRoom,
    start: issue.proposal_start ?? issue.original_start ?? '',
  }
}

function issueProposalKey(proposal: MoveTarget | null) {
  return proposal ? `${proposal.room}:${proposal.day}:${proposal.start}:${proposal.end}` : 'source'
}

function contextValue(value: string | number | null | undefined, fallback = 'Not provided') {
  return value === null || value === undefined || value === '' ? fallback : String(value)
}

function decisionReason(issue: Issue, adviceReason?: string) {
  if (adviceReason) return adviceReason
  const reason = issue.reason || issue.message
  if (/^Duplicate Student Entry/i.test(reason)) return 'This student appears more than once in the source schedule.'
  if (/^No feasible room/i.test(reason)) return 'No compatible room is available under the current scheduling rules.'
  return reason
}

function IssueAssignmentEditorForm({ commandPending, execute, issue, issueProposal, onIssueAssigned, onSetWaiting, reconciliation, resolutionContext, rooms, versionConflict, waitingPending, workspaceVersion }: IssueEditorFormProps) {
  const [draft, setDraft] = useState(() => issueDraft(issue, rooms, issueProposal))
  const [baselineVersion, setBaselineVersion] = useState(workspaceVersion)
  const [validation, setValidation] = useState<Awaited<ReturnType<typeof validateIssueAssignment>>['data']>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [validationPending, setValidationPending] = useState(false)
  const [teacherConfirmed, setTeacherConfirmed] = useState(false)
  const [confirmationNote, setConfirmationNote] = useState('')
  const [decisionNote, setDecisionNote] = useState('')
  const [manualOpen, setManualOpen] = useState(false)
  const [waitingNote, setWaitingNote] = useState(resolutionContext?.waitingNote ?? '')

  function update<K extends keyof MoveDraft>(key: K, value: MoveDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }))
    setValidation(null)
    setValidationError(null)
    setTeacherConfirmed(false)
    setConfirmationNote('')
  }

  function target(): MoveTarget {
    return {
      day: Number(draft.day),
      end: draft.end,
      room: draft.room,
      start: draft.start,
    }
  }

  const validateProposal = useCallback(async () => {
    setValidationPending(true)
    setValidationError(null)
    try {
      const result = await validateIssueAssignment(issue.id, {
        day: Number(draft.day),
        end: draft.end,
        room: draft.room,
        start: draft.start,
      })
      setValidation(result.data)
      setBaselineVersion(result.workspace_version)
    } catch (error) {
      setValidation(null)
      setValidationError(error instanceof Error ? error.message : 'Proposal validation failed')
    } finally {
      setValidationPending(false)
    }
  }, [draft.day, draft.end, draft.room, draft.start, issue.id])

  async function assignIssue() {
    if (!validation?.success || !baselineVersion) return
    try {
      const result = await execute({
        expectedVersion: baselineVersion,
        issueId: issue.id,
        kind: 'assign',
        target: target(),
        confirmation: { confirmed: teacherConfirmed, note: confirmationNote },
        decisionNote,
      })
      if (result) onIssueAssigned(result)
    } catch {
      // The shared command surface owns persistent commit failures and 409 recovery.
    }
  }

  const complete = Boolean(draft.room && draft.day !== '' && isCanonicalTime(draft.start) && isCanonicalTime(draft.end))
  const controlsDisabled = commandPending || versionConflict || validationPending
  const blocked = resolutionContext?.status === 'blocked'
  const originalSchedule = [
    issue.original_date,
    issue.original_day === null || issue.original_day === undefined ? null : DAYS.find((day) => day.id === issue.original_day)?.label,
    issue.original_time,
  ].filter(Boolean).join(' · ')
  const proposedSchedule = `${draft.room || 'Room not selected'} · ${DAYS.find((day) => day.id === Number(draft.day))?.label ?? 'Day not selected'} · ${draft.start || '—'}–${draft.end || '—'}`
  useEffect(() => {
    if (!reconciliation || !issueProposal || manualOpen) return
    const timer = window.setTimeout(() => void validateProposal(), 0)
    return () => window.clearTimeout(timer)
  }, [issueProposal, manualOpen, reconciliation, validateProposal])

  if (reconciliation) {
    return (
      <form className={styles.reconciliationDecision} data-testid="reconciliation-decision" onSubmit={(event) => event.preventDefault()}>
        <div className={styles.decisionIdentity}>
          <span>{issue.type === 'studio_class' ? 'Studio' : 'Weekly'} · {contextValue(issue.instrument, 'Instrument not specified')}</span>
          <strong>{issue.student_name ?? issue.instructor ?? issue.message}</strong>
          <small>{issue.instructor ?? 'Instructor not provided'}</small>
        </div>
        <div className={styles.decisionComparison}>
          <span><small>Original request</small><strong>{originalSchedule || 'Not provided'}</strong></span>
          <span><small>Proposed placement</small><strong>{issueProposal || manualOpen ? proposedSchedule : 'Select a recommendation or click the timetable'}</strong></span>
        </div>
        <dl className={styles.issueContext}>
          <div><dt>Decision needed</dt><dd>{decisionReason(issue, resolutionContext?.adviceReason)}</dd></div>
          {issueReservationNote(issue) ? <div><dt>Reservation note</dt><dd>{issueReservationNote(issue)}</dd></div> : null}
          <div><dt>Course</dt><dd>{contextValue(issue.course_code)} · {issue.duration_minutes} minutes</dd></div>
          <div><dt>Room requirement</dt><dd>{issue.room_types?.join(', ') || 'Not provided'}</dd></div>
          <div><dt>Preferred venue</dt><dd>{issue.preferred_venues?.join(', ') || 'Not provided'}</dd></div>
        </dl>
        <div aria-live="polite" className={styles.decisionStatus} role={validationError || validation?.message ? 'alert' : 'status'}>
          {validationError || validation?.message ? <span className={styles.decisionError}>{validationError ?? validation?.message}</span>
            : validationPending ? <span>Checking room, time and schedule conflicts…</span>
              : validation?.success ? <><strong>Placement clear</strong>{validation.start_norm && validation.end_norm ? <span>Final occupancy: {validation.start_norm}–{validation.end_norm}</span> : null}<span>{validation.requires_teacher_confirmation ? 'Teacher confirmation is required for this placement.' : 'The server accepted this placement.'}</span>{validation.warnings?.length ? <span>{validation.warnings.join(' · ')}</span> : null}</>
                : resolutionContext?.waiting ? <span>This teacher-day case is waiting. Resume it when the requested response arrives.</span>
                  : blocked && resolutionContext?.timeChangeAllowed === false ? <span>No compatible original-time placement is available. Try another room at the same time, or move this case to Waiting.</span>
                    : <span>{manualOpen ? 'Enter an exact placement, then check conflicts.' : 'Choose a recommendation or click an empty timetable position.'}</span>}
        </div>
        {manualOpen && !resolutionContext?.waiting ? <div className={styles.manualPlacement}>
          <Field label="Room"><select disabled={controlsDisabled} onChange={(event) => update('room', event.target.value)} required value={draft.room}>
            <option disabled value="">Select room</option>
            {rooms.map((room) => <option key={room.id} value={room.id}>{room.id}</option>)}
          </select></Field>
          <><Field label="Day"><select disabled={controlsDisabled} onChange={(event) => update('day', event.target.value)} required value={draft.day}>
            <option disabled value="">Select day</option>
            {DAYS.map((day) => <option key={day.id} value={day.id}>{day.label}</option>)}
          </select></Field>
          <Field label="Start time"><TimeInput disabled={controlsDisabled} onChange={(event) => update('start', event.target.value)} required value={draft.start} /></Field>
          <Field label="End time"><TimeInput disabled={controlsDisabled} onChange={(event) => update('end', event.target.value)} required value={draft.end} /></Field>
          </>
        </div> : null}
        {resolutionContext && (blocked || resolutionContext.waiting) ? <div className={styles.manualPlacement}>
          <Field label="Waiting note"><input disabled={waitingPending} maxLength={500} onChange={(event) => setWaitingNote(event.target.value)} placeholder="What response or decision is needed?" value={waitingNote} /></Field>
        </div> : null}
        {validation?.success && validation.requires_teacher_confirmation ? (
          <TeacherConfirmationFields
            checked={teacherConfirmed}
            message={validation.teacher_confirmation_message}
            note={confirmationNote}
            onCheckedChange={setTeacherConfirmed}
            onNoteChange={setConfirmationNote}
          />
        ) : null}
        <Field
          helper="Record why this intervention was chosen. Avoid personal names or IDs."
          label="Decision note"
        >
          <textarea
            disabled={controlsDisabled}
            maxLength={500}
            onChange={(event) => setDecisionNote(event.target.value)}
            placeholder="e.g. Uses an available compatible room without changing teacher load"
            rows={3}
            value={decisionNote}
          />
        </Field>
        <div className={styles.decisionActions}>
          {resolutionContext?.waiting ? <button className="button button--primary" disabled={waitingPending} onClick={() => onSetWaiting(resolutionContext.caseId, false, '')} type="button">Resume case</button> : <>
            <button className="button button--secondary" disabled={controlsDisabled} onClick={() => setManualOpen((open) => !open)} type="button">{manualOpen ? 'Close manual fields' : 'Adjust manually'}</button>
            {manualOpen || validationError ? <button className="button button--secondary" disabled={controlsDisabled || !complete} onClick={() => void validateProposal()} type="button">Check conflicts</button> : null}
            {blocked && resolutionContext ? <button className="button button--primary" disabled={waitingPending || !waitingNote.trim()} onClick={() => onSetWaiting(resolutionContext.caseId, true, waitingNote)} type="button">Move to Waiting</button>
              : <button className="button button--primary" disabled={controlsDisabled || !validation?.success || !baselineVersion || Boolean(validation.requires_teacher_confirmation && !teacherConfirmed)} onClick={() => void assignIssue()} type="button">Place lesson</button>}
          </>}
        </div>
      </form>
    )
  }

  return (
    <form className={`${styles.editorForm} ${styles.issueEditorForm}`} onSubmit={(event) => event.preventDefault()}>
      <div className={styles.editorIdentity}>
        <span>{issue.type === 'studio_class' ? 'Studio issue' : 'Weekly issue'} · Original {originalSchedule || 'not provided'}</span>
        <strong>{issue.student_name ?? issue.instructor ?? issue.message}</strong>
        <span>{issue.instructor ?? 'Instructor not provided'}</span>
      </div>
      <Field label="Room"><select disabled={controlsDisabled} onChange={(event) => update('room', event.target.value)} required value={draft.room}>
        <option disabled value="">Select room</option>
        {rooms.map((room) => <option key={room.id} value={room.id}>{room.id}</option>)}
      </select></Field>
      <Field label="Day"><select disabled={controlsDisabled} onChange={(event) => update('day', event.target.value)} required value={draft.day}>
        <option disabled value="">Select day</option>
        {DAYS.map((day) => <option key={day.id} value={day.id}>{day.label}</option>)}
      </select></Field>
      <Field label="Start time"><TimeInput disabled={controlsDisabled} onChange={(event) => update('start', event.target.value)} required value={draft.start} /></Field>
      <Field label="End time"><TimeInput disabled={controlsDisabled} onChange={(event) => update('end', event.target.value)} required value={draft.end} /></Field>
      {validationError || validation?.message ? <p className={styles.proposalError} role="alert">{validationError ?? validation?.message}</p> : null}
      {validation?.success ? (
        <div aria-live="polite" className={styles.proposalValidation} role="status">
            <strong>Proposal validated.</strong>
          {validation.start_norm && validation.end_norm ? <span>Final occupancy: {validation.start_norm}–{validation.end_norm}</span> : null}
          {validation.warnings?.length ? <ul aria-label="Proposal warnings">{validation.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
        </div>
      ) : null}
      {validation?.success && validation.requires_teacher_confirmation ? (
        <TeacherConfirmationFields
          checked={teacherConfirmed}
          message={validation.teacher_confirmation_message}
          note={confirmationNote}
          onCheckedChange={setTeacherConfirmed}
          onNoteChange={setConfirmationNote}
        />
      ) : null}
      <Field
        helper="Record why this intervention was chosen. Avoid personal names or IDs."
        label="Decision note"
      >
        <textarea
          disabled={controlsDisabled}
          maxLength={500}
          onChange={(event) => setDecisionNote(event.target.value)}
          placeholder="e.g. Uses an available compatible room without changing teacher load"
          rows={3}
          value={decisionNote}
        />
      </Field>
      <div className={styles.editorActions}>
        <button className="button button--secondary" disabled={controlsDisabled || validationPending || !complete} onClick={() => void validateProposal()} type="button">Validate proposal</button>
        <button className="button button--primary" disabled={controlsDisabled || validationPending || !validation?.success || !baselineVersion || Boolean(validation.requires_teacher_confirmation && !teacherConfirmed)} onClick={() => void assignIssue()} type="button">Assign issue</button>
      </div>
      {!complete ? <small className="meta">Enter a room, day, and valid 24-hour HH:MM times before checking the proposal.</small> : !validation ? <small className="meta">Check conflicts after every change before assigning the issue.</small> : null}
      <dl className={styles.issueContext}>
        <div><dt>Student</dt><dd>{contextValue(issue.student_name)} · {contextValue(issue.student_id)}</dd></div>
        <div><dt>Course / instrument</dt><dd>{contextValue(issue.course_code)} · {contextValue(issue.instrument)}</dd></div>
        <div><dt>Duration</dt><dd>{issue.duration_minutes} minutes</dd></div>
        <div><dt>Original schedule</dt><dd>{originalSchedule || 'Not provided'}</dd></div>
        <div><dt>Preferred venue</dt><dd>{issue.preferred_venues?.join(', ') || 'Not provided'}</dd></div>
        <div><dt>Room type</dt><dd>{issue.room_types?.join(', ') || 'Not provided'}</dd></div>
        <div><dt>Reason</dt><dd>{issue.reason || issue.message}</dd></div>
        {issueReservationNote(issue) ? <div><dt>Reservation note</dt><dd>{issueReservationNote(issue)}</dd></div> : null}
        <div><dt>Source request</dt><dd>{issue.source_request_id}</dd></div>
      </dl>
      <details className={styles.sourcePayload}><summary>Source payload</summary><pre>{JSON.stringify(issue.payload, null, 2)}</pre></details>
    </form>
  )
}

export function AssignmentEditor({ assignment, assignmentProposal, commandPending, editorEpoch, execute, issue, issueProposal, onCanonicalResponse, onClose, onIssueAssigned, onSetWaiting, reconciliation = false, resolutionContext, rooms, versionConflict, waitingPending, workspaceVersion }: AssignmentEditorProps) {
  return (
    <section aria-label="Selected assignment" className={styles.assignmentEditor} role="region" tabIndex={0}>
      <div className={styles.panelHeading}>
        <div><h2>{issue && !assignment ? 'Resolve Issue' : 'Selected Assignment'}</h2><p>{issue && !assignment ? 'Compare the request with the timetable, then make one explicit decision.' : 'Review and validate the selected timetable assignment.'}</p></div>
        <div className={styles.editorHeadingActions}>
          {onClose ? <button aria-label="Back to issues" className="button button--quiet" onClick={onClose} type="button">Back to issues</button> : null}
          <span className={styles.editorMode}>{commandPending ? 'Command pending' : versionConflict ? 'Reload required' : 'Schedule draft'}</span>
        </div>
      </div>
      {assignment ? (
        <AssignmentEditorForm
          assignment={assignment}
          assignmentProposal={assignmentProposal}
          commandPending={commandPending}
          execute={execute}
          key={`${assignment.id}:${editorEpoch}:${workspaceVersion ?? 'pending'}:${assignmentProposal ? issueProposalKey(assignmentProposal) : 'canonical'}`}
          onCanonicalResponse={onCanonicalResponse}
          rooms={rooms}
          versionConflict={versionConflict}
          workspaceVersion={workspaceVersion}
        />
      ) : issue ? (
        <IssueAssignmentEditorForm
          commandPending={commandPending}
          execute={execute}
          issue={issue}
          issueProposal={issueProposal}
          key={`${issue.id}:${editorEpoch}:${workspaceVersion ?? 'pending'}:${issueProposalKey(issueProposal)}`}
          onIssueAssigned={onIssueAssigned}
          onSetWaiting={onSetWaiting}
          reconciliation={reconciliation}
          resolutionContext={resolutionContext}
          rooms={rooms}
          versionConflict={versionConflict}
          waitingPending={waitingPending}
          workspaceVersion={workspaceVersion}
        />
      ) : <p className={styles.empty}>No assignment selected. Choose an assignment or a linked issue.</p>}
    </section>
  )
}
