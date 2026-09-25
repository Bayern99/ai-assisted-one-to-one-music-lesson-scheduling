import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { PAGE_TITLES, workspaceRevisionLabel } from '../../../app/productLanguage'
import type { ApiClientError, ApiEnvelope } from '../../../api/client'
import { WorkspaceHeader } from '../../../components/workspace/WorkspacePrimitives'
import { AssignmentEditor } from '../components/AssignmentEditor'
import { adaptAssignment } from '../components/AssignmentBlock'
import { FinalizeDialog } from '../components/FinalizeDialog'
import type { Issue } from '../components/IssueQueue'
import type { ResolutionSelectionContext } from '../components/ResolutionCaseCard'
import { ResolutionPanel } from '../components/ResolutionPanel'
import { type ReconciliationHighlight } from '../components/PiReconciliationPanel'
import { clockToMinutes, ScheduleGrid, type PresentationBounds } from '../components/ScheduleGrid'
import { buildTeacherSegments, teacherSegmentKey, type SchedulePresentationMode, type TeacherSegment } from '../components/teacherPresentation'
import { TeacherBlockPanel } from '../components/TeacherBlockPanel'
import {
  finalizeScheduler,
  getSchedulerLectures,
  schedulerLecturesKey,
  schedulerResolutionKey,
  schedulerSessionKey,
  setResolutionWaiting,
  stageScheduler,
  useSchedulerSession,
  type LectureEvent,
  type SchedulerSession,
} from '../api'
import {
  draftSaveHint,
  buildReservationMarkers,
  computeGhostAssignments,
  ghostPlacementKeys,
  resolveScheduleAuthority,
  reservationMarkersForDay,
  SCHEDULE_AUTHORITY_LABELS,
  type ExtendedSchedulerSession,
} from '../scheduleAuthority'
import { useAssignmentCommands, type MoveTarget } from '../hooks/useAssignmentCommands'
import styles from '../resolve.module.css'

function lectureAsAssignment(lecture: LectureEvent): SchedulerSession['assignments'][number] {
  return {
    id: lecture.id,
    title: lecture.title || 'Lecture',
    type: 'lecture',
    resourceId: lecture.resourceId,
    daysOfWeek: lecture.daysOfWeek,
    startTime: lecture.startTime,
    endTime: lecture.endTime,
    locked: true,
  }
}

const DAY_LABELS: Record<number, string> = {
  0: 'Sunday',
  1: 'Monday',
  2: 'Tuesday',
  3: 'Wednesday',
  4: 'Thursday',
  5: 'Friday',
  6: 'Saturday',
}

const QUEUE_MIN = 240
const QUEUE_MAX = 720
const QUEUE_WIDTH_KEY = 'pi.resolve.queueWidth'

function storedQueueWidth(mode: 'schedule' | 'reconciliation') {
  const fallback = mode === 'reconciliation' ? 420 : 300
  const raw = window.localStorage.getItem(`${QUEUE_WIDTH_KEY}.${mode}`)
  const value = Number(raw)
  return raw && Number.isFinite(value) ? Math.min(QUEUE_MAX, Math.max(QUEUE_MIN, value)) : fallback
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function issueMatches(issue: Issue, assignment: SchedulerSession['assignments'][number]) {
  return Boolean(
    (issue.assignment_id && issue.assignment_id === assignment.id)
      || (issue.source_request_id && issue.source_request_id === assignment.source_request_id)
      || (assignment.unresolved_issue_id && issue.id === assignment.unresolved_issue_id),
  )
}

function weekday(value: number | null): value is 0 | 1 | 2 | 3 | 4 | 5 | 6 {
  return value !== null && value >= 0 && value <= 6
}

function conflictDetail(value: unknown, index: number) {
  const item = record(value)
  const sources = [record(item.conflict), record(item.event), item]
  for (const source of sources) {
    for (const key of ['message', 'reason', 'type', 'code', 'title', 'name', 'id']) {
      const detail = source[key]
      if (typeof detail === 'string' && detail.trim()) return detail.trim()
    }
  }
  return `Conflict ${index + 1}`
}

export function ResolvePage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const sessionQuery = useSchedulerSession()
  const lecturesQuery = useQuery({
    queryKey: schedulerLecturesKey,
    queryFn: ({ signal }) => getSchedulerLectures(signal),
  })
  const commands = useAssignmentCommands()
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null)
  const [draggingIssue, setDraggingIssue] = useState<Issue | null>(null)
  const [issueProposal, setIssueProposal] = useState<{ issueId: string; target: MoveTarget } | null>(null)
  const [assignmentProposal, setAssignmentProposal] = useState<{ assignmentId: string; target: MoveTarget } | null>(null)
  const [selectedResolution, setSelectedResolution] = useState<(ResolutionSelectionContext & { issueId: string }) | null>(null)
  const [editorEpoch, setEditorEpoch] = useState(0)
  const [finalizeOpen, setFinalizeOpen] = useState(false)
  const [finalizeVersion, setFinalizeVersion] = useState<string | null>(null)
  const [presentationMode, setPresentationMode] = useState<SchedulePresentationMode>(
    searchParams.get('workspace') === 'schedule' ? 'lessons' : 'teachers',
  )
  const [selectedTeacherKey, setSelectedTeacherKey] = useState<string | null>(null)
  const [reconciliationHighlight, setReconciliationHighlight] = useState<ReconciliationHighlight>(null)
  const workspaceMode = searchParams.get('workspace') === 'schedule' ? 'schedule' : 'reconciliation'
  const [queueWidths, setQueueWidths] = useState(() => ({
    schedule: storedQueueWidth('schedule'),
    reconciliation: storedQueueWidth('reconciliation'),
  }))
  const queueWidth = queueWidths[workspaceMode]
  const setQueueWidth = (next: number | ((current: number) => number)) => {
    setQueueWidths((widths) => {
      const previous = widths[workspaceMode]
      const value = typeof next === 'function' ? next(previous) : next
      return { ...widths, [workspaceMode]: value }
    })
  }
  const [isReadingExpanded, setIsReadingExpanded] = useState(() => {
    return workspaceMode === 'reconciliation' && queueWidth >= 600
  })
  const previousQueueWidth = useRef(queueWidth < 600 ? queueWidth : 420)

  function toggleReadingExpanded() {
    if (isReadingExpanded) {
      const restored = previousQueueWidth.current < 600 ? previousQueueWidth.current : 420
      setQueueWidth(restored)
      window.localStorage.setItem(`${QUEUE_WIDTH_KEY}.${workspaceMode}`, String(restored))
      setIsReadingExpanded(false)
    } else {
      if (queueWidth < 600) {
        previousQueueWidth.current = queueWidth
      }
      const target = Math.min(QUEUE_MAX, Math.max(620, Math.min(680, window.innerWidth - 480)))
      setQueueWidth(target)
      window.localStorage.setItem(`${QUEUE_WIDTH_KEY}.${workspaceMode}`, String(target))
      setIsReadingExpanded(true)
      if (selected || selectedTeacherKey || selectedIssueId) {
        closeInspector()
      }
    }
  }
  const errorRef = useRef<HTMLElement>(null)
  const issueQueueRef = useRef<HTMLElement>(null)
  const focusIssueOnClose = useRef(false)
  const finalizePending = useRef(false)
  const finalizeErrorBaseline = useRef<string | null>(null)
  const requestedId = searchParams.get('assignment')
  const session = sessionQuery.data?.data as ExtendedSchedulerSession | undefined
  const operatingWindow = record(session?.operating_window)
  const scheduleTimeBounds: PresentationBounds | undefined = (() => {
    const start = clockToMinutes(typeof operatingWindow.start === 'string' ? operatingWindow.start : null)
    const end = clockToMinutes(typeof operatingWindow.end === 'string' ? operatingWindow.end : null)
    return start !== null && end !== null && end > start ? { start, end } : undefined
  })()
  const selected = presentationMode === 'teachers'
    ? null
    : session?.assignments.find((assignment) => assignment.id === requestedId) ?? null
  const selectedDay = selected ? adaptAssignment(selected).day : null
  const requestedDayValue = searchParams.get('day')
  const requestedDay = requestedDayValue === null ? null : Number(requestedDayValue)
  const availableDays = session?.assignments.map((assignment) => adaptAssignment(assignment).day).filter(weekday) ?? []
  const displayAssignments = useMemo(() => {
    if (!session) return []
    const assignmentIds = new Set(session.assignments.map((assignment) => assignment.id))
    const lectures = (lecturesQuery.data?.data?.lectures ?? [])
      .filter((lecture) => lecture.id && !assignmentIds.has(lecture.id))
      .map(lectureAsAssignment)
    return [...session.assignments, ...lectures]
  }, [lecturesQuery.data?.data?.lectures, session])
  const displayRooms = useMemo(() => {
    if (!session) return []
    const rooms = [...session.rooms]
    const roomIds = new Set(rooms.map((room) => room.id))
    for (const assignment of displayAssignments) {
      const room = adaptAssignment(assignment).room
      if (room && !roomIds.has(room)) {
        rooms.push({ id: room })
        roomIds.add(room)
      }
    }
    return rooms
  }, [displayAssignments, session])
  const firstIssueDay = session?.issues
    .flatMap((group) => group.items)
    .map((issue) => issue.original_day)
    .filter(weekday)
    .sort((a, b) => a - b)[0]
  const defaultDay = workspaceMode === 'reconciliation' && weekday(firstIssueDay ?? null)
    ? firstIssueDay
    : (availableDays.includes(1) ? 1 : availableDays[0] ?? 1)
  const proposedDay = assignmentProposal && assignmentProposal.assignmentId === selected?.id ? assignmentProposal.target.day : null
  const activeDay = weekday(proposedDay) ? proposedDay : weekday(selectedDay) ? selectedDay : weekday(requestedDay) ? requestedDay : defaultDay
  const requestedIdIsStale = Boolean(requestedId && session && !selected)
  const selectedIssue = session?.issues.flatMap((group) => group.items).find((issue) => issue.id === selectedIssueId) ?? null
  const selectedIssueAssignment = selectedIssue && session
    ? session.assignments.find((assignment) => issueMatches(selectedIssue, assignment)) ?? null
    : null
  const activeIssueProposal = issueProposal && issueProposal.issueId === selectedIssue?.id ? issueProposal.target : null
  const issueMatchIds = useMemo(() => new Set(
    selectedIssue && session
      ? session.assignments.filter((assignment) => issueMatches(selectedIssue, assignment)).map((assignment) => assignment.id)
      : [],
  ), [selectedIssue, session])
  const versionConflict = commands.error?.status === 409
  const reloadError = sessionQuery.isError && session ? sessionQuery.error as ApiClientError : null
  const workspaceVersion = sessionQuery.data?.workspace_version ?? null
  const scheduleAuthority = session ? resolveScheduleAuthority(session) : 'staged'
  const ghostAssignments = useMemo(
    () => session ? computeGhostAssignments(session) : [],
    [session],
  )
  const ghostKeys = useMemo(() => ghostPlacementKeys(ghostAssignments), [ghostAssignments])
  const allSessionIssues = useMemo(
    () => session?.issues.flatMap((group) => group.items) ?? [],
    [session],
  )
  const reservationMarkers = useMemo(
    () => session ? reservationMarkersForDay(buildReservationMarkers(session, allSessionIssues), activeDay) : [],
    [activeDay, allSessionIssues, session],
  )
  const teacherSegments = useMemo(() => {
    if (presentationMode !== 'teachers') return []
    return buildTeacherSegments(
      displayAssignments.map((assignment) => ({ assignment, view: adaptAssignment(assignment) })),
      activeDay,
    )
  }, [activeDay, displayAssignments, presentationMode])
  const selectedTeacherSegment = selectedTeacherKey
    ? teacherSegments.find((segment) => teacherSegmentKey(segment) === selectedTeacherKey) ?? null
    : null
  const finalizeMutation = useMutation({
    mutationFn: finalizeScheduler,
    onSuccess: (canonical) => {
      queryClient.setQueryData(schedulerSessionKey, canonical)
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      navigate('/schedule/export', { state: { finalizeWarnings: canonical.warnings } })
    },
    onError: (error: ApiClientError) => {
      focusIssueOnClose.current = error.status === 400 && error.code === 'SCHEDULER_FINALIZE_CONFLICT'
      setFinalizeOpen(false)
    },
    onSettled: () => { finalizePending.current = false },
  })
  const stageMutation = useMutation({
    mutationFn: stageScheduler,
    onSuccess: (canonical) => {
      queryClient.setQueryData(schedulerSessionKey, canonical)
    },
  })
  const waitingMutation = useMutation({
    mutationFn: ({ caseId, waiting, note }: { caseId: string; waiting: boolean; note: string }) => {
      if (!workspaceVersion) throw new Error('Workspace version unavailable')
      return setResolutionWaiting(caseId, waiting, note, workspaceVersion)
    },
    onSuccess: (result, variables) => {
      queryClient.setQueryData(schedulerSessionKey, (current: ApiEnvelope<SchedulerSession> | undefined) => (
        current ? { ...current, workspace_version: result.workspace_version } : current
      ))
      queryClient.setQueryData([...schedulerResolutionKey, result.workspace_version], result)
      setSelectedResolution((current) => current && current.caseId === variables.caseId
        ? { ...current, waiting: variables.waiting, waitingNote: variables.note }
        : current)
    },
  })

  useEffect(() => {
    if (commands.error) errorRef.current?.focus()
  }, [commands.error])

  useEffect(() => {
    if (!finalizeMutation.error || !finalizeErrorBaseline.current || !workspaceVersion) return
    if (workspaceVersion !== finalizeErrorBaseline.current) {
      finalizeMutation.reset()
      finalizeErrorBaseline.current = null
    }
  }, [finalizeMutation, workspaceVersion])

  useLayoutEffect(() => {
    if (!session || searchParams.get('day') === String(activeDay)) return
    const next = new URLSearchParams(searchParams)
    next.set('day', String(activeDay))
    setSearchParams(next, { replace: true })
  }, [activeDay, searchParams, session, setSearchParams])

  function selectAssignment(id: string | null) {
    const next = new URLSearchParams(searchParams)
    const assignment = id ? session?.assignments.find((item) => item.id === id) : null
    const day = assignment ? adaptAssignment(assignment).day : null
    if (weekday(day)) next.set('day', String(day))
    if (id) next.set('assignment', id)
    else next.delete('assignment')
    setSearchParams(next)
  }

  function changeDay(day: number) {
    setSelectedIssueId(null)
    setSelectedResolution(null)
    setIssueProposal(null)
    setDraggingIssue(null)
    setAssignmentProposal(null)
    setSelectedTeacherKey(null)
    const next = new URLSearchParams(searchParams)
    next.set('day', String(day))
    if (!weekday(selectedDay) || selectedDay !== day) next.delete('assignment')
    setSearchParams(next)
  }

  function selectIssue(issue: Issue, context?: ResolutionSelectionContext) {
    setSelectedIssueId(issue.id)
    setSelectedResolution(context ? { ...context, issueId: issue.id } : null)
    setIssueProposal(null)
    setAssignmentProposal(null)
    setSelectedTeacherKey(null)
    const related = session?.assignments.find((assignment) => issueMatches(issue, assignment))
    const next = new URLSearchParams(searchParams)
    const day = related ? adaptAssignment(related).day : null
    if (weekday(day)) next.set('day', String(day))
    if (related) next.set('assignment', related.id)
    else next.delete('assignment')
    setSearchParams(next)
  }

  function selectGridAssignment(id: string) {
    setSelectedIssueId(null)
    setSelectedResolution(null)
    setIssueProposal(null)
    setAssignmentProposal(null)
    setSelectedTeacherKey(null)
    selectAssignment(id)
  }

  function selectTeacherSegment(segment: TeacherSegment) {
    if (segment.isLecture) return
    setSelectedIssueId(null)
    setSelectedResolution(null)
    setIssueProposal(null)
    setAssignmentProposal(null)
    setSelectedTeacherKey(teacherSegmentKey(segment))
    const next = new URLSearchParams(searchParams)
    next.delete('assignment')
    setSearchParams(next)
  }

  function closeInspector() {
    setSelectedIssueId(null)
    setSelectedResolution(null)
    setIssueProposal(null)
    setAssignmentProposal(null)
    setDraggingIssue(null)
    setSelectedTeacherKey(null)
    const next = new URLSearchParams(searchParams)
    next.delete('assignment')
    setSearchParams(next)
  }

  function beginIssueDrag(issue: Issue) {
    setDraggingIssue(issue)
    setSelectedIssueId(issue.id)
    setSelectedResolution(null)
    setIssueProposal(null)
    setAssignmentProposal(null)
    setSelectedTeacherKey(null)
    selectAssignment(null)
  }

  function proposeDraggedIssue(target: MoveTarget) {
    const issue = draggingIssue ?? selectedIssue
    if (!issue) return
    setSelectedIssueId(issue.id)
    setIssueProposal({ issueId: issue.id, target })
    const next = new URLSearchParams(searchParams)
    next.set('day', String(target.day))
    next.delete('assignment')
    setSearchParams(next)
  }

  function useResolutionOption(issue: Issue, target: MoveTarget, context?: ResolutionSelectionContext) {
    setSelectedIssueId(issue.id)
    setSelectedResolution(context ? { ...context, issueId: issue.id } : null)
    setAssignmentProposal(null)
    setIssueProposal({ issueId: issue.id, target })
    const next = new URLSearchParams(searchParams)
    next.set('day', String(target.day))
    next.delete('assignment')
    setSearchParams(next)
  }

  function changeWorkspaceMode(mode: 'schedule' | 'reconciliation') {
    window.localStorage.setItem(`${QUEUE_WIDTH_KEY}.${workspaceMode}`, String(queueWidth))
    const next = new URLSearchParams(searchParams)
    if (mode === 'reconciliation') {
      setPresentationMode('teachers')
      next.set('workspace', 'reconciliation')
      if (!selectedIssue) next.delete('assignment')
      if (!selectedIssue && firstIssueDay) next.set('day', String(firstIssueDay))
      setIsReadingExpanded(queueWidths.reconciliation >= 600)
    } else {
      setPresentationMode('lessons')
      next.set('workspace', 'schedule')
      setIsReadingExpanded(false)
    }
    setSearchParams(next)
  }

  function changePresentationMode(mode: SchedulePresentationMode) {
    setPresentationMode(mode)
    setSelectedTeacherKey(null)
    if (mode !== 'teachers') return
    setSelectedIssueId(null)
    setSelectedResolution(null)
    setIssueProposal(null)
    setAssignmentProposal(null)
    setDraggingIssue(null)
    if (!searchParams.get('assignment')) return
    const next = new URLSearchParams(searchParams)
    next.delete('assignment')
    setSearchParams(next)
  }

  function startQueueResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return
    event.preventDefault()
    const origin = event.clientX
    const initial = queueWidth
    const persistKey = `${QUEUE_WIDTH_KEY}.${workspaceMode}`
    const onMove = (move: PointerEvent) => {
      setQueueWidth(Math.min(QUEUE_MAX, Math.max(QUEUE_MIN, initial + (move.clientX - origin))))
    }
    const onUp = (up: PointerEvent) => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      const next = Math.min(QUEUE_MAX, Math.max(QUEUE_MIN, initial + (up.clientX - origin)))
      setQueueWidth(next)
      window.localStorage.setItem(persistKey, String(next))
      if (workspaceMode === 'reconciliation') {
        setIsReadingExpanded(next >= 600)
      }
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  function proposeAssignmentMove(assignmentId: string, target: MoveTarget) {
    setSelectedIssueId(null)
    setSelectedResolution(null)
    setIssueProposal(null)
    setAssignmentProposal({ assignmentId, target })
    const next = new URLSearchParams(searchParams)
    next.set('day', String(target.day))
    next.set('assignment', assignmentId)
    setSearchParams(next)
  }

  function selectedSourceId() {
    if (selectedIssue?.source_request_id) return selectedIssue.source_request_id
    if (!selected) return requestedId
    const sourceId = record(selected).source_request_id
    return typeof sourceId === 'string' && sourceId ? sourceId : selected.id
  }

  function reconcileCanonicalSelection(
    result: Awaited<ReturnType<typeof commands.execute>>,
    preferredSourceId = selectedSourceId(),
  ) {
    if (!result?.data) return
    setEditorEpoch((value) => value + 1)
    if (!preferredSourceId) return
    const canonical = result.data?.assignments.find((assignment) => (
      assignment.id === preferredSourceId
      || record(assignment).source_request_id === preferredSourceId
      || Boolean(selectedIssue && record(assignment).unresolved_issue_id === selectedIssue.id)
    ))
    setIssueProposal(null)
    setAssignmentProposal(null)
    setDraggingIssue(null)
    setSelectedResolution(null)
    const next = new URLSearchParams(searchParams)
    if (canonical) {
      setSelectedIssueId(null)
      const day = adaptAssignment(canonical).day
      if (weekday(day)) next.set('day', String(day))
      next.set('assignment', canonical.id)
      setSearchParams(next)
      return
    }
    const canonicalIssue = result.data.issues
      .flatMap((group) => group.items)
      .find((issue) => issue.source_request_id === preferredSourceId || issue.id === preferredSourceId)
    if (!canonicalIssue) return
    setSelectedIssueId(canonicalIssue.id)
    next.delete('assignment')
    setSearchParams(next)
  }

  function completeIssueAssignment(result: Awaited<ReturnType<typeof commands.execute>>) {
    reconcileCanonicalSelection(result, selectedIssue?.source_request_id)
  }

  async function runHistoryCommand(kind: 'undo' | 'redo') {
    if (!workspaceVersion) return
    const sourceId = selectedSourceId()
    try {
      const result = await commands.execute({ expectedVersion: workspaceVersion, kind })
      reconcileCanonicalSelection(result, sourceId)
    } catch {
      // The shared command error remains visible and owns recovery.
    }
  }

  async function reloadWorkspace() {
    const result = await sessionQuery.refetch()
    if (result.isSuccess) {
      commands.clearError()
      setAssignmentProposal(null)
      setIssueProposal(null)
      setSelectedResolution(null)
      setEditorEpoch((value) => value + 1)
    }
  }

  function changeFinalizeOpen(open: boolean) {
    setFinalizeOpen(open)
    if (open) {
      setFinalizeVersion(workspaceVersion)
    }
  }

  const finalizeError = finalizeMutation.error as ApiClientError | null
  const finalizeConflicts = Array.isArray(finalizeError?.details?.conflicts)
    ? finalizeError.details.conflicts.length
    : 0
  const finalizeDetails = Array.isArray(finalizeError?.details?.conflicts)
    ? finalizeError.details.conflicts.map(conflictDetail)
    : []
  const finalizeWarnings = Array.isArray(finalizeError?.details?.warnings)
    ? finalizeError.details.warnings.filter((warning): warning is string => typeof warning === 'string')
    : []
  const scheduleMutationPending = commands.isPending || finalizeMutation.isPending || stageMutation.isPending || sessionQuery.isError
  const finalizeBlocked = scheduleAuthority === 'editing' || scheduleAuthority === 'finalized'
  const finalizeHint = scheduleAuthority === 'editing' ? 'Stage before finalizing' : null
  const stageDisabled = scheduleMutationPending
    || versionConflict
    || !workspaceVersion
    || scheduleAuthority !== 'editing'

  function renderDetails(details: Record<string, unknown> | null) {
    if (!details) return null
    return <dl className={styles.errorDetails}>{Object.entries(details).map(([key, value]) => (
      <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'string' ? value : JSON.stringify(value)}</dd></div>
    ))}</dl>
  }

  if (sessionQuery.isPending) return <div aria-live="polite" className={styles.loading} role="status"><span>Loading schedule workspace</span></div>
  if (sessionQuery.isError && !session) {
    const error = sessionQuery.error as ApiClientError
    return <div className={styles.error} role="alert"><strong>Schedule workspace unavailable</strong><p>{error.message}</p></div>
  }
  if (!session) return <div className={styles.error} role="alert">The scheduler returned no canonical session.</div>
  const workspaceWarnings = [...new Set([
    ...(session.warnings ?? []),
    ...(sessionQuery.data?.warnings ?? []),
  ])]

  const assignmentEditor = <AssignmentEditor
    assignment={selectedIssueAssignment ?? (selectedIssue ? null : selected)}
    assignmentProposal={assignmentProposal && assignmentProposal.assignmentId === selected?.id ? assignmentProposal.target : null}
    commandPending={scheduleMutationPending}
    editorEpoch={editorEpoch}
    execute={commands.execute}
    issue={selectedIssueAssignment ? null : selectedIssue}
    issueProposal={activeIssueProposal}
    onCanonicalResponse={reconcileCanonicalSelection}
    onClose={closeInspector}
    onIssueAssigned={completeIssueAssignment}
    onSetWaiting={(caseId, waiting, note) => waitingMutation.mutate({ caseId, waiting, note })}
    reconciliation={Boolean(selectedIssue && !selectedIssueAssignment)}
    resolutionContext={selectedResolution?.issueId === selectedIssue?.id ? selectedResolution : null}
    rooms={session.rooms}
    versionConflict={versionConflict}
    waitingPending={waitingMutation.isPending}
    workspaceVersion={sessionQuery.data?.workspace_version ?? null}
  />
  const showInspector = Boolean(selectedTeacherSegment) || (presentationMode !== 'teachers' && Boolean(selectedIssue || selected))

  return (
    <div className={styles.page}>
      <WorkspaceHeader
        actions={<>
          <div aria-label="Resolution workspace view" className={styles.workspaceModeSwitch} role="group">
            <button aria-pressed={workspaceMode === 'schedule'} onClick={() => changeWorkspaceMode('schedule')} type="button">Timetable</button>
            <button aria-pressed={workspaceMode === 'reconciliation'} onClick={() => changeWorkspaceMode('reconciliation')} type="button">Reconciliation <span className="numeric">{session.metrics.unresolved}</span></button>
          </div>
          <div aria-label="Schedule presentation" className={styles.workspaceModeSwitch} role="group">
            <button aria-pressed={presentationMode === 'lessons'} onClick={() => changePresentationMode('lessons')} type="button">Lessons</button>
            <button aria-pressed={presentationMode === 'teachers'} onClick={() => changePresentationMode('teachers')} type="button">Teachers</button>
          </div>
        </>}
        context={`${DAY_LABELS[activeDay]} · ${presentationMode === 'teachers' ? 'Teacher blocks' : 'Canonical schedule'}`}
        title={PAGE_TITLES.scheduleResolution}
      />
      {workspaceWarnings.length ? (
        <section className={styles.commandError} role="alert">
          <strong>Workspace record needs attention</strong>
          <ul>{workspaceWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </section>
      ) : null}
      {finalizeError ? (
        <section className={styles.commandError} role="alert">
          <strong>{finalizeError.status === 400 && finalizeConflicts
            ? `${finalizeConflicts} conflicts block finalization`
            : finalizeError.status === 409 ? 'Workspace conflict' : 'Finalize failed'}</strong>
          <p>{finalizeError.message}</p>
          {reloadError ? <p>Reload failed: {reloadError.message}</p> : null}
          {finalizeDetails.length ? <ul>{finalizeDetails.map((detail, index) => <li key={`${index}-${detail}`}>{detail}</li>)}</ul> : null}
          {finalizeWarnings.length ? <ul>{finalizeWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
          {finalizeError.operationId ? <p className="meta">Operation {finalizeError.operationId}</p> : null}
          {finalizeError.status === 409 ? <button className="button button--secondary" onClick={() => void reloadWorkspace()} type="button">Reload workspace</button> : null}
        </section>
      ) : null}
      {commands.error ? (
        <section className={styles.commandError} ref={errorRef} role="alert" tabIndex={-1}>
          <strong>{commands.error.status === 409 ? 'Workspace conflict' : 'Schedule command rejected'}</strong>
          <p>{commands.error.message}</p>
          {reloadError ? <p>Reload failed: {reloadError.message}</p> : null}
          {renderDetails(commands.error.details)}
          {commands.error.operationId ? <p className="meta">Operation {commands.error.operationId}</p> : null}
          {commands.error.status === 409 ? <button className="button button--secondary" onClick={() => void reloadWorkspace()} type="button">Reload workspace</button> : null}
        </section>
      ) : null}
      {reloadError && !commands.error && !finalizeError ? (
        <section className={styles.commandError} role="alert">
          <strong>Schedule refresh failed</strong>
          <p>{reloadError.message}</p>
          <span>The cached schedule remains visible in read-only mode.</span>
          <button className="button button--secondary" onClick={() => void reloadWorkspace()} type="button">Retry schedule refresh</button>
        </section>
      ) : null}
      {waitingMutation.error ? <section className={styles.commandError} role="alert"><strong>Waiting status not saved</strong><p>{waitingMutation.error.message}</p></section> : null}
      {requestedIdIsStale ? <p className={styles.staleSelection} role="status">Assignment {requestedId} is no longer available. Select a current assignment.</p> : null}
      <div
        className={`${styles.resolveWorkspace} ${workspaceMode === 'reconciliation' ? styles.reconciliationMode : ''} ${isReadingExpanded ? styles.expandedReadingMode : ''} ${showInspector ? styles.reconciliationWithInspector : ''}`}
        data-testid="resolve-workspace"
        style={{ '--resolve-queue-width': `${queueWidth}px` } as CSSProperties}
      >
        <ResolutionPanel
          activeDay={activeDay}
          disabled={scheduleMutationPending || versionConflict}
          expanded={workspaceMode === 'reconciliation'}
          isReadingExpanded={isReadingExpanded}
          issues={session.issues}
          key={workspaceMode}
          onDayChange={changeDay}
          onDragEnd={() => setDraggingIssue(null)}
          onDragStart={beginIssueDrag}
          onHighlightChange={setReconciliationHighlight}
          onSelect={selectIssue}
          onToggleReadingExpanded={workspaceMode === 'reconciliation' ? toggleReadingExpanded : undefined}
          onUseOption={useResolutionOption}
          ref={issueQueueRef}
          selectedProposal={activeIssueProposal}
          selectedIssueId={selectedIssueId}
          workspaceVersion={workspaceVersion}
        />
        <div
          aria-label="Resize issue queue"
          aria-orientation="vertical"
          aria-valuemax={QUEUE_MAX}
          aria-valuemin={QUEUE_MIN}
          aria-valuenow={queueWidth}
          className={styles.queueSplitter}
          data-testid="queue-splitter"
          onPointerDown={startQueueResize}
          role="separator"
        />
        <section className={styles.schedulePane} data-layout="timetable-footer" data-mode="schedule" data-testid="schedule-pane" data-workspace={workspaceMode}>
          <ScheduleGrid
            activeDay={activeDay}
            assignments={displayAssignments}
            commandPending={scheduleMutationPending || versionConflict}
            ghostAssignments={workspaceMode === 'schedule' && presentationMode !== 'teachers' ? ghostAssignments : []}
            ghostPlacementKeys={workspaceMode === 'schedule' && presentationMode !== 'teachers' ? ghostKeys : new Set()}
            issueDragDuration={selectedIssue?.duration_minutes ?? draggingIssue?.duration_minutes ?? null}
            issueMatchIds={issueMatchIds}
            issueProposal={activeIssueProposal}
            issueProposalLabel={selectedIssue?.student_name ?? selectedIssue?.instructor ?? null}
            onDayChange={changeDay}
            onIssueProposal={proposeDraggedIssue}
            onMove={proposeAssignmentMove}
            onSelect={workspaceMode === 'reconciliation' || presentationMode === 'teachers' ? () => {} : selectGridAssignment}
            onSelectSegment={presentationMode === 'teachers' ? selectTeacherSegment : undefined}
            presentationMode={presentationMode}
            reconciliationHighlight={reconciliationHighlight}
            reservationMarkers={reservationMarkers}
            rooms={displayRooms}
            selectedId={selected?.id ?? null}
            selectedSegmentKey={selectedTeacherKey}
            timeBounds={scheduleTimeBounds}
            workspaceVersion={sessionQuery.data?.workspace_version ?? null}
          />
          <footer aria-label="Schedule legend and commands" className={styles.scheduleLegend}>
            <span className={styles.legendKeys}>
              <span>Pattern: Locked / Lecture</span>
              {workspaceMode === 'schedule' && presentationMode !== 'teachers' ? <span className={styles.legendHeld}>Last staged</span> : null}
              <span className={styles.legendReservation}>Reservation (unplaced dates)</span>
            </span>
            <dl aria-label="Schedule metrics" className={styles.legendMetrics}>
              <div><dt>Assigned</dt><dd className="numeric">{session.metrics.assigned}</dd></div>
              <div><dt>Unresolved</dt><dd className="numeric">{session.metrics.unresolved}</dd></div>
              <div><dt>Source gaps</dt><dd className="numeric">{session.metrics.source_gaps}</dd></div>
            </dl>
            <span className={styles.canonicalMeta}><span>{session.active_stage}</span><span>{workspaceRevisionLabel(sessionQuery.data?.workspace_version)}</span></span>
            <div aria-label="Schedule authority" className={styles.scheduleAuthorityBar} role="group">
              {(['editing', 'staged', 'finalized'] as const).map((state) => (
                <span
                  aria-current={scheduleAuthority === state ? 'step' : undefined}
                  className={styles.scheduleAuthorityState}
                  data-active={scheduleAuthority === state ? 'true' : undefined}
                  key={state}
                >
                  {SCHEDULE_AUTHORITY_LABELS[state]}
                </span>
              ))}
            </div>
            <span className={styles.autosaveHint}>{draftSaveHint(session.draft, commands.isPending || finalizeMutation.isPending || stageMutation.isPending)}</span>
            <span className={styles.draftMeta}>
              <span>{session.draft.can_undo ? 'Undo available' : 'Undo unavailable'}</span>
              <span>{session.draft.can_redo ? 'Redo available' : 'Redo unavailable'}</span>
            </span>
            <div aria-label="Schedule history controls" className={styles.legendCommands} role="group">
              <button disabled={scheduleMutationPending || versionConflict || !session.draft.can_undo || !workspaceVersion} onClick={() => void runHistoryCommand('undo')} type="button">Undo last schedule change</button>
              <button disabled={scheduleMutationPending || versionConflict || !session.draft.can_redo || !workspaceVersion} onClick={() => void runHistoryCommand('redo')} type="button">Redo schedule change</button>
              <button
                disabled={stageDisabled}
                onClick={() => workspaceVersion && stageMutation.mutate(workspaceVersion)}
                type="button"
              >
                Stage schedule
              </button>
              {session.metrics.unresolved > 0 ? <button className="button button--secondary" disabled={scheduleMutationPending || versionConflict} onClick={() => changeWorkspaceMode('reconciliation')} type="button">Review {session.metrics.unresolved} unresolved</button> : null}
              <FinalizeDialog
                baselineVersion={finalizeVersion}
                disabled={commands.isPending || versionConflict || sessionQuery.isError || !workspaceVersion || finalizeBlocked}
                finalizeHint={finalizeHint}
                onCloseAutoFocus={(event) => {
                  if (!focusIssueOnClose.current) return
                  event.preventDefault()
                  focusIssueOnClose.current = false
                  issueQueueRef.current?.focus()
                }}
                onConfirm={(expectedVersion) => {
                  if (finalizePending.current) return
                  finalizePending.current = true
                  finalizeErrorBaseline.current = expectedVersion
                  finalizeMutation.mutate(expectedVersion)
                }}
                onOpenChange={changeFinalizeOpen}
                open={finalizeOpen}
                pending={finalizeMutation.isPending}
                unresolvedCount={session.metrics.unresolved}
                workspaceVersion={workspaceVersion}
            />
          </div>
          </footer>
        </section>
        {showInspector ? (
          <aside
            aria-label={selectedTeacherSegment ? 'Teacher block inspector' : selectedIssue ? 'Reconciliation inspector' : 'Schedule inspector'}
            className={styles.reconciliationInspector}
            data-reconciliation-inspector
            data-testid="reconciliation-inspector"
            role="region"
          >
            {selectedTeacherSegment ? (
              <TeacherBlockPanel
                assignments={session.assignments}
                commandPending={scheduleMutationPending}
                execute={commands.execute}
                onClose={closeInspector}
                onUnassigned={() => setSelectedTeacherKey(null)}
                segment={selectedTeacherSegment}
                versionConflict={versionConflict}
                workspaceVersion={workspaceVersion}
              />
            ) : assignmentEditor}
          </aside>
        ) : null}
      </div>
    </div>
  )
}
