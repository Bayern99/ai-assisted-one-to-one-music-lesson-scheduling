/* eslint-disable react-refresh/only-export-components */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent as ReactDragEvent } from 'react'
import { DndContext, DragOverlay, PointerSensor, useSensor, useSensors, type DragEndEvent, type DragMoveEvent, type DragStartEvent } from '@dnd-kit/core'
import type { SchedulerSession } from '../api'
import type { MoveTarget } from '../hooks/useAssignmentCommands'
import { useScheduleKeyboard, type ScheduleFocusCandidate } from '../hooks/useScheduleKeyboard'
import styles from '../scheduleGrid.module.css'
import { adaptAssignment, AssignmentBlock, type Assignment, type AssignmentView } from './AssignmentBlock'
import { GhostAssignmentBlock } from './GhostAssignmentBlock'
import { ReservationDateChips } from './ReservationDateChips'
import { buildTeacherSegments, teacherSegmentKey, type SchedulePresentationMode, type TeacherSegment } from './teacherPresentation'
import type { Assignment as AuthorityAssignment, ReservationMarker } from '../scheduleAuthority'
import type { ReconciliationHighlight } from './PiReconciliationPanel'

const DAYS = [
  { id: 1, label: 'Monday' },
  { id: 2, label: 'Tuesday' },
  { id: 3, label: 'Wednesday' },
  { id: 4, label: 'Thursday' },
  { id: 5, label: 'Friday' },
  { id: 6, label: 'Saturday' },
  { id: 0, label: 'Sunday' },
] as const

export const VISIBLE_START_MINUTES = 9 * 60
export const VISIBLE_END_MINUTES = 22 * 60
const ROOM_COLUMN_WIDTH = 74
const TIME_HEADER_HEIGHT = 30

function isScheduleDay(day: number | null): day is 0 | 1 | 2 | 3 | 4 | 5 | 6 {
  return day !== null && day >= 0 && day <= 6
}

export function clockToMinutes(value: string | null | undefined): number | null {
  if (!value) return null
  const match = value.match(/(?:T|^)(\d{1,2}):(\d{2})(?::\d{2})?$/)
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (!Number.isInteger(hours) || !Number.isInteger(minutes) || hours > 23 || minutes > 59) return null
  return hours * 60 + minutes
}

export interface PresentationBounds {
  end: number
  start: number
}

const PRESENTATION_BOUNDS: PresentationBounds = {
  end: VISIBLE_END_MINUTES,
  start: VISIBLE_START_MINUTES,
}

function timeSpanPlacement(room: string | null, startValue: string | null, endValue: string | null, roomIds: string[], timeBounds: PresentationBounds): CSSProperties | null {
  const roomIndex = room ? roomIds.indexOf(room) : -1
  const start = clockToMinutes(startValue)
  const end = clockToMinutes(endValue)
  if (
    roomIndex < 0
    || start === null
    || end === null
    || start < timeBounds.start
    || end > timeBounds.end
    || end <= start
  ) return null
  const span = timeBounds.end - timeBounds.start
  return {
    gridColumn: '2',
    gridRow: String(roomIndex + 2),
    marginInlineStart: `${((start - timeBounds.start) / span) * 100}%`,
    width: `${Math.max(((end - start) / span) * 100, 1.75)}%`,
  }
}

function placement(view: AssignmentView, activeDay: number, roomIds: string[], timeBounds: PresentationBounds): CSSProperties | null {
  if (view.day !== activeDay) return null
  return timeSpanPlacement(view.room, view.start, view.end, roomIds, timeBounds)
}

function segmentPlacement(segment: TeacherSegment, roomIds: string[], timeBounds: PresentationBounds): CSSProperties | null {
  return timeSpanPlacement(segment.room, segment.start, segment.end, roomIds, timeBounds)
}

function targetPlacement(target: MoveTarget, durationMinutes: number, roomIds: string[], timeBounds: PresentationBounds): CSSProperties | null {
  const roomIndex = roomIds.indexOf(target.room)
  const start = clockToMinutes(target.start)
  if (roomIndex < 0 || start === null) return null
  const span = timeBounds.end - timeBounds.start
  return {
    gridColumn: '2',
    gridRow: String(roomIndex + 2),
    marginInlineStart: `${((start - timeBounds.start) / span) * 100}%`,
    width: `${Math.max((durationMinutes / span) * 100, 1.75)}%`,
  }
}

interface DropMappingInput {
  activeDay: number
  assignment: Assignment
  bounds: Pick<DOMRect, 'height' | 'left' | 'top' | 'width'>
  pointer: { x: number; y: number }
  rooms: SchedulerSession['rooms']
  timeBounds: PresentationBounds
}

interface PointMappingInput {
  activeDay: number
  bounds: Pick<DOMRect, 'height' | 'left' | 'top' | 'width'>
  durationMinutes: number
  pointer: { x: number; y: number }
  rooms: SchedulerSession['rooms']
  timeBounds: PresentationBounds
}

function formatMinutes(value: number) {
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}

function mapPointToTarget({ activeDay, bounds, durationMinutes, pointer, rooms, timeBounds }: PointMappingInput): MoveTarget | null {
  if (
    !Number.isFinite(durationMinutes)
    || durationMinutes <= 0
    || !Number.isFinite(pointer.x)
    || !Number.isFinite(pointer.y)
    || rooms.length === 0
  ) return null
  const right = bounds.left + bounds.width
  const bottom = bounds.top + bounds.height
  if (
    pointer.x < bounds.left + ROOM_COLUMN_WIDTH
    || pointer.x > right
    || pointer.y < bounds.top + TIME_HEADER_HEIGHT
    || pointer.y > bottom
  ) return null
  const timeWidth = bounds.width - ROOM_COLUMN_WIDTH
  const roomHeight = (bounds.height - TIME_HEADER_HEIGHT) / rooms.length
  if (timeWidth <= 0 || roomHeight <= 0) return null
  const roomIndex = Math.max(0, Math.min(rooms.length - 1, Math.floor((pointer.y - bounds.top - TIME_HEADER_HEIGHT) / roomHeight)))
  const timeOffset = pointer.x - bounds.left - ROOM_COLUMN_WIDTH
  const rawStart = timeBounds.start + (Math.max(0, Math.min(timeWidth, timeOffset)) / timeWidth) * (timeBounds.end - timeBounds.start)
  const latestStart = Math.max(timeBounds.start, timeBounds.end - durationMinutes)
  const start = Math.max(timeBounds.start, Math.min(latestStart, Math.round(rawStart / 60) * 60))
  return { room: rooms[roomIndex].id, day: activeDay, start: formatMinutes(start), end: formatMinutes(start + durationMinutes) }
}

export function mapDropToMoveTarget({ activeDay, assignment, bounds, pointer, rooms, timeBounds }: DropMappingInput): MoveTarget | null {
  const view = adaptAssignment(assignment)
  const originalStart = clockToMinutes(view.start)
  const originalEnd = clockToMinutes(view.end)
  if (originalStart === null || originalEnd === null || originalEnd <= originalStart || rooms.length === 0) return null
  return mapPointToTarget({
    activeDay,
    bounds,
    durationMinutes: originalEnd - originalStart,
    pointer,
    rooms,
    timeBounds,
  })
}

export type IssueDropMappingInput = PointMappingInput

export function mapIssueDropToTarget(input: IssueDropMappingInput): MoveTarget | null {
  return mapPointToTarget(input)
}

interface ScheduleGridProps {
  activeDay: number
  assignments: SchedulerSession['assignments']
  commandPending?: boolean
  ghostAssignments?: AuthorityAssignment[]
  ghostPlacementKeys?: ReadonlySet<string>
  issueMatchIds: ReadonlySet<string>
  issueDragDuration?: number | null
  issueProposal?: MoveTarget | null
  issueProposalLabel?: string | null
  now?: Date
  onDayChange: (day: number) => void
  onMove?: (assignmentId: string, target: MoveTarget, expectedVersion: string) => void
  onIssueProposal?: (target: MoveTarget) => void
  onSelect: (id: string) => void
  onSelectSegment?: (segment: TeacherSegment) => void
  presentationMode?: SchedulePresentationMode
  reconciliationHighlight?: ReconciliationHighlight
  reservationMarkers?: ReservationMarker[]
  rooms: SchedulerSession['rooms']
  selectedId: string | null
  selectedSegmentKey?: string | null
  timeBounds?: PresentationBounds
  workspaceVersion?: string | null
}

function assignmentSearchText(view: AssignmentView) {
  return [view.title, view.instructor, view.person, view.room, view.kind].filter(Boolean).join(' ').toLowerCase()
}

function getReconciliationRole(
  highlight: ReconciliationHighlight,
  room: string | null | undefined,
  instructor: string | null | undefined,
  start: string | null | undefined,
  end: string | null | undefined,
): 'source' | 'destination' | null {
  if (!highlight) return null
  const roomMatchFrom = Boolean(highlight.fromRoom && room === highlight.fromRoom)
  const roomMatchTo = Boolean(highlight.toRoom && room === highlight.toRoom)
  if (!roomMatchFrom && !roomMatchTo) return null

  if (highlight.teacher && instructor) {
    const tA = highlight.teacher.trim().toLowerCase()
    const tB = instructor.trim().toLowerCase()
    if (!tA.includes(tB) && !tB.includes(tA)) return null
  }

  if (highlight.start && highlight.end && start && end) {
    const hStart = clockToMinutes(highlight.start)
    const hEnd = clockToMinutes(highlight.end)
    const sStart = clockToMinutes(start)
    const sEnd = clockToMinutes(end)
    if (hStart !== null && hEnd !== null && sStart !== null && sEnd !== null) {
      if (sStart >= hEnd || sEnd <= hStart) return null
    }
  }

  return roomMatchFrom ? 'source' : 'destination'
}

export function ScheduleGrid({
  activeDay,
  assignments,
  commandPending = false,
  ghostAssignments = [],
  ghostPlacementKeys = new Set<string>(),
  issueDragDuration = null,
  issueMatchIds,
  issueProposal = null,
  issueProposalLabel = null,
  now,
  onDayChange,
  onIssueProposal,
  onMove,
  onSelect,
  onSelectSegment,
  presentationMode = 'lessons',
  reconciliationHighlight = null,
  reservationMarkers = [],
  rooms,
  selectedId,
  selectedSegmentKey = null,
  timeBounds = PRESENTATION_BOUNDS,
  workspaceVersion = null,
}: ScheduleGridProps) {
  const teacherView = presentationMode === 'teachers'
  const [instructorFilter, setInstructorFilter] = useState('')
  const [roomFilter, setRoomFilter] = useState('')
  const [search, setSearch] = useState('')
  const [clockNow, setClockNow] = useState(() => new Date())
  const adaptedAssignments = useMemo(() => assignments.map((assignment) => ({ assignment, view: adaptAssignment(assignment) })), [assignments])
  const instructors = useMemo(() => [...new Set(adaptedAssignments.map(({ view }) => view.instructor))].sort(), [adaptedAssignments])
  const displayedRooms = roomFilter ? rooms.filter((room) => room.id === roomFilter) : rooms
  const roomIds = displayedRooms.map((room) => room.id)
  const hours = useMemo(() => {
    const count = Math.max(1, Math.ceil((timeBounds.end - timeBounds.start) / 60))
    return Array.from({ length: count }, (_, index) => Math.floor(timeBounds.start / 60) + index)
  }, [timeBounds.end, timeBounds.start])
  const normalizedSearch = search.trim().toLowerCase()
  useEffect(() => {
    if (now) return
    const timer = window.setInterval(() => setClockNow(new Date()), 60_000)
    return () => window.clearInterval(timer)
  }, [now])

  const filteredAssignments = adaptedAssignments.filter(({ view }) => {
    if (instructorFilter && view.instructor !== instructorFilter) return false
    if (roomFilter && view.room !== roomFilter) return false
    return !normalizedSearch || assignmentSearchText(view).includes(normalizedSearch)
  })
  const canvasRef = useRef<HTMLDivElement>(null)
  const lastDragSelection = useRef<{ id: string; at: number } | null>(null)
  const [activeDrag, setActiveDrag] = useState<{
    assignment: Assignment
    durationMinutes: number
    expectedVersion: string
    height: number
    width: number
  } | null>(null)
  const [dragTarget, setDragTarget] = useState<MoveTarget | null>(null)
  const [issueHoverTarget, setIssueHoverTarget] = useState<MoveTarget | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))
  const placements = filteredAssignments.map(({ assignment, view }) => ({ assignment, view, style: placement(view, activeDay, roomIds, timeBounds) }))
  const placed = placements.flatMap(({ assignment, view, style }) => style ? [{ assignment, view, style }] : [])
  const teacherSegments = teacherView ? buildTeacherSegments(filteredAssignments, activeDay) : []
  const placedSegments = teacherSegments.flatMap((segment) => {
    const style = segmentPlacement(segment, roomIds, timeBounds)
    return style ? [{ segment, style }] : []
  })
  const placedGhosts = teacherView
    ? []
    : ghostAssignments.flatMap((assignment) => {
      const view = adaptAssignment(assignment)
      const style = placement(view, activeDay, roomIds, timeBounds)
      return style ? [{ assignment, style }] : []
    })
  const visibleReservationMarkers = reservationMarkers.flatMap((marker) => {
    if (marker.weekday !== activeDay) return []
    const chipKey = `${marker.magnet_room}:${marker.weekday}:${marker.start_time}:${marker.end_time}`
    if (ghostPlacementKeys.has(chipKey)) return []
    const hasMagnetHolder = assignments.some((assignment) => {
      const view = adaptAssignment(assignment)
      const start = clockToMinutes(view.start)
      const markerStart = clockToMinutes(marker.start_time)
      return view.room === marker.magnet_room
        && view.day === marker.weekday
        && start !== null
        && markerStart !== null
        && start === markerStart
    })
    if (!hasMagnetHolder) return []
    const style = timeSpanPlacement(marker.magnet_room, marker.start_time, marker.end_time, roomIds, timeBounds)
    return style ? [{ marker, style }] : []
  })
  const outOfView = filteredAssignments.filter(({ view }) => {
    if (isScheduleDay(view.day) && view.day !== activeDay) return false
    return !placement(view, activeDay, roomIds, timeBounds)
  })
  const focusCandidates: ScheduleFocusCandidate[] = teacherView
    ? [
      ...placedSegments.map(({ segment }) => ({
        id: segment.assignmentIds[0],
        day: activeDay,
        roomIndex: roomIds.indexOf(segment.room),
        start: clockToMinutes(segment.start),
      })),
      ...outOfView.map(({ assignment }) => ({ id: assignment.id, day: null, roomIndex: -1, start: null })),
    ]
    : [
      ...placed.map(({ assignment, view }) => {
        return { id: assignment.id, day: view.day, roomIndex: view.room ? roomIds.indexOf(view.room) : -1, start: clockToMinutes(view.start) }
      }),
      ...outOfView.map(({ assignment }) => ({ id: assignment.id, day: null, roomIndex: -1, start: null })),
    ]
  const dayCounts = new Map(DAYS.map((day) => [day.id, adaptedAssignments.filter(({ view }) => view.day === day.id).length]))
  const handleKeyboard = useScheduleKeyboard(focusCandidates, onSelect)
  const currentNow = now ?? clockNow
  const nowMinutes = currentNow.getHours() * 60 + currentNow.getMinutes()
  const nowVisible = currentNow.getDay() === activeDay && nowMinutes >= timeBounds.start && nowMinutes <= timeBounds.end
  const nowPosition = `${((nowMinutes - timeBounds.start) / (timeBounds.end - timeBounds.start)) * 100}%`

  function startDrag(event: DragStartEvent) {
    if (teacherView) return
    const adapted = adaptedAssignments.find(({ assignment }) => assignment.id === event.active.id)
    const assignment = adapted?.assignment
    const initial = event.active.rect.current.initial ?? { height: 42, width: 160 }
    if (!adapted || !assignment || !workspaceVersion) return
    const view = adapted.view
    const start = clockToMinutes(view.start)
    const end = clockToMinutes(view.end)
    if (start === null || end === null || end <= start) return
    setActiveDrag({
      assignment,
      durationMinutes: end - start,
      expectedVersion: workspaceVersion,
      height: initial.height,
      width: initial.width,
    })
    setDragTarget(null)
  }

  function targetFromDrag(event: DragMoveEvent | DragEndEvent) {
    const canvasBounds = canvasRef.current?.getBoundingClientRect()
    const translated = event.active.rect.current.translated
    if (!activeDrag || !canvasBounds || !translated) return null
    return mapDropToMoveTarget({
      activeDay,
      assignment: activeDrag.assignment,
      bounds: canvasBounds,
      // The translated leading edge preserves the exact grab offset. Using the
      // card centre would shift every drop by half of its duration.
      pointer: { x: translated.left, y: translated.top + translated.height / 2 },
      rooms: displayedRooms,
      timeBounds,
    })
  }

  function moveDrag(event: DragMoveEvent) {
    setDragTarget(targetFromDrag(event))
  }

  function endDrag(event: DragEndEvent) {
    const drag = activeDrag
    const target = targetFromDrag(event)
    setActiveDrag(null)
    setDragTarget(null)
    if (!drag) return
    if (target) {
      lastDragSelection.current = { id: drag.assignment.id, at: performance.now() }
      onMove?.(drag.assignment.id, target, drag.expectedVersion)
    }
  }

  function selectAssignment(id: string) {
    if (teacherView) return
    const lastDrag = lastDragSelection.current
    if (lastDrag?.id === id && performance.now() - lastDrag.at < 500) {
      return
    }
    lastDragSelection.current = null
    onSelect(id)
  }

  function dropIssue(event: ReactDragEvent<HTMLDivElement>) {
    if (!issueDragDuration) return
    event.preventDefault()
    const canvasBounds = canvasRef.current?.getBoundingClientRect()
    if (!canvasBounds) return
    const target = issueHoverTarget ?? mapIssueDropToTarget({
      activeDay,
      bounds: canvasBounds,
      durationMinutes: issueDragDuration,
      pointer: { x: event.clientX, y: event.clientY },
      rooms: displayedRooms,
      timeBounds,
    })
    setIssueHoverTarget(null)
    if (target) onIssueProposal?.(target)
  }

  const visibleDropTarget = dragTarget ?? issueHoverTarget ?? issueProposal
  const visibleDropDuration = activeDrag?.durationMinutes ?? issueDragDuration ?? 0
  const visibleDropPlacement = visibleDropTarget && visibleDropDuration
    ? targetPlacement(visibleDropTarget, visibleDropDuration, roomIds, timeBounds)
    : null

  const destinationPlacement = useMemo(() => {
    if (!reconciliationHighlight?.toRoom || !reconciliationHighlight.start || !reconciliationHighlight.end) return null
    return timeSpanPlacement(reconciliationHighlight.toRoom, reconciliationHighlight.start, reconciliationHighlight.end, roomIds, timeBounds)
  }, [reconciliationHighlight, roomIds, timeBounds])

  return (
    <DndContext
      accessibility={{ screenReaderInstructions: { draggable: 'Drag with a pointer, or select this assignment and use the editor for keyboard movement.' } }}
      onDragCancel={() => { setActiveDrag(null); setDragTarget(null) }}
      onDragEnd={endDrag}
      onDragMove={moveDrag}
      onDragStart={startDrag}
      sensors={sensors}
    >
      <section aria-label="Schedule grid" className={styles.scheduleGrid}>
        <div className={styles.scheduleToolbar}>
          <div aria-label="Schedule weekday" className={styles.daySelector} role="group">
            {DAYS.map((day) => {
              const count = dayCounts.get(day.id) ?? 0
              return (
                <button
                  aria-label={`${day.label}, ${count} ${count === 1 ? 'assignment' : 'assignments'}`}
                  aria-pressed={activeDay === day.id}
                  key={day.id}
                  onClick={() => onDayChange(day.id)}
                  type="button"
                >
                  <span>{day.label.slice(0, 3)}</span>
                </button>
              )
            })}
          </div>
          <div aria-label="Schedule display filters" className={styles.scheduleFilters} role="group">
            <label><span>Instructor</span><select aria-label="Filter by instructor" onChange={(event) => setInstructorFilter(event.target.value)} value={instructorFilter}>
              <option value="">All instructors</option>
              {instructors.map((instructor) => <option key={instructor}>{instructor}</option>)}
            </select></label>
            <label><span>Room</span><select aria-label="Filter by room" onChange={(event) => setRoomFilter(event.target.value)} value={roomFilter}>
              <option value="">All rooms</option>
              {rooms.map((room) => <option key={room.id}>{room.id}</option>)}
            </select></label>
            <label className={styles.searchFilter}><span>Search</span><input aria-label="Search assignments" onChange={(event) => setSearch(event.target.value)} placeholder="Search" type="search" value={search} /></label>
          </div>
        </div>
        <div className={styles.gridRegion}>
          <div className={styles.gridScroller}>
            <div
              className={styles.gridCanvas}
              data-time-end={`${String(Math.floor(timeBounds.end / 60)).padStart(2, '0')}:00`}
              data-time-start={`${String(Math.floor(timeBounds.start / 60)).padStart(2, '0')}:00`}
              data-testid="schedule-grid-canvas"
              style={{ '--hour-count': hours.length, '--room-count': roomIds.length } as CSSProperties}
              data-drop-state={activeDrag ? (dragTarget ? 'valid' : 'invalid') : issueDragDuration ? (issueHoverTarget ? 'valid' : 'idle') : undefined}
              data-pick-state={issueDragDuration && onIssueProposal ? 'active' : undefined}
              onClick={(event) => {
                if (!issueDragDuration || !onIssueProposal || (event.target as HTMLElement).closest('button')) return
                const canvasBounds = canvasRef.current?.getBoundingClientRect()
                if (!canvasBounds) return
                const target = mapIssueDropToTarget({
                  activeDay,
                  bounds: canvasBounds,
                  durationMinutes: issueDragDuration,
                  pointer: { x: event.clientX, y: event.clientY },
                  rooms: displayedRooms,
                  timeBounds,
                })
                if (target) onIssueProposal(target)
              }}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setIssueHoverTarget(null)
              }}
              onDragOver={(event) => {
                if (!issueDragDuration) return
                event.preventDefault()
                const canvasBounds = canvasRef.current?.getBoundingClientRect()
                if (!canvasBounds) return
                setIssueHoverTarget(mapIssueDropToTarget({
                  activeDay,
                  bounds: canvasBounds,
                  durationMinutes: issueDragDuration,
                  pointer: { x: event.clientX, y: event.clientY },
                  rooms: displayedRooms,
                  timeBounds,
                }))
              }}
              onDrop={dropIssue}
              ref={canvasRef}
            >
              <div className={styles.gridCorner}>ROOM</div>
              <div aria-label="Visible hours" className={styles.timeHeading}>
                {hours.map((hour) => <span data-testid="schedule-hour" key={hour}>{String(hour).padStart(2, '0')}</span>)}
              </div>
              {roomIds.map((roomId) => <div className={styles.roomHeading} key={roomId}>{roomId}</div>)}
              {roomIds.map((roomId) => <div aria-hidden="true" className={styles.gridCell} key={roomId}>{hours.map((hour) => <span className={styles.hourCell} key={hour} />)}</div>)}
              {nowVisible && roomIds.length ? <div
                aria-hidden="true"
                className={styles.currentTime}
                data-minute={nowMinutes}
                data-testid="current-time-marker"
                style={{ gridRow: `2 / span ${roomIds.length}`, marginInlineStart: nowPosition }}
              /> : null}
              {visibleDropPlacement ? <div aria-hidden="true" className={styles.dropTarget} data-state={issueProposal && visibleDropTarget === issueProposal ? 'proposal' : 'preview'} data-testid="schedule-drop-target" style={visibleDropPlacement}>{issueProposal && visibleDropTarget === issueProposal ? `PROPOSED · ${issueProposalLabel ?? 'lesson'}` : null}</div> : null}
              {destinationPlacement ? (
                <div
                  aria-hidden="true"
                  className={styles.reconciliationTargetPreview}
                  data-testid="reconciliation-target-preview"
                  style={destinationPlacement}
                >
                  <span className={styles.assignmentTopline}>
                    <span className={styles.assignmentTime}>{reconciliationHighlight?.start}–{reconciliationHighlight?.end}</span>
                    <span className={styles.assignmentKind}>Target</span>
                  </span>
                  <strong className={styles.teacherSegmentName}>{reconciliationHighlight?.teacher || reconciliationHighlight?.toRoom}</strong>
                  <span className={styles.assignmentInstructor}>→ {reconciliationHighlight?.toRoom}</span>
                </div>
              ) : null}
              {teacherView
                ? [
                  ...placedSegments.map(({ segment, style }) => {
                    const issueMatch = segment.assignmentIds.some((id) => issueMatchIds.has(id))
                    const visibleTime = `${segment.start}–${segment.end}`
                    const label = segment.isLecture ? segment.title || 'Lecture' : segment.instructor
                    const selected = selectedSegmentKey === teacherSegmentKey(segment)
                    const Tag = segment.isLecture ? 'div' : 'button'
                    const reconciliationRole = getReconciliationRole(
                      reconciliationHighlight,
                      segment.room,
                      segment.instructor,
                      segment.start,
                      segment.end,
                    )
                    return (
                      <Tag
                        aria-label={segment.isLecture
                          ? `Lecture block, ${label}, room ${segment.room}, ${visibleTime}, locked`
                          : `Teacher block, ${segment.instructor}, room ${segment.room}, ${visibleTime}`}
                        aria-pressed={segment.isLecture ? undefined : selected}
                        className={styles.assignment}
                        data-density={segment.assignmentIds.length > 1 ? 'wide' : 'standard'}
                        data-issue-match={issueMatch ? 'true' : undefined}
                        data-kind={segment.kind}
                        data-lecture={segment.isLecture ? 'true' : undefined}
                        data-presentation="teacher"
                        data-reconciliation-highlight={reconciliationRole ?? undefined}
                        data-room={segment.room}
                        data-teacher-tone={segment.isLecture ? undefined : segment.tone}
                        data-testid="teacher-segment"
                        key={`${segment.room}:${segment.start}:${segment.instructor}:${segment.isLecture ? 'lecture' : 'teacher'}`}
                        onClick={segment.isLecture ? undefined : () => onSelectSegment?.(segment)}
                        style={style}
                        title={segment.isLecture ? `${visibleTime} · Lecture · ${label}` : `${visibleTime} · ${segment.instructor}`}
                        type={segment.isLecture ? undefined : 'button'}
                      >
                        <span className={styles.assignmentTopline}>
                          <span className={styles.assignmentTime}>{visibleTime}</span>
                          {segment.isLecture ? <span aria-hidden="true" className={styles.assignmentKind}>Lecture</span> : null}
                        </span>
                        <strong className={styles.teacherSegmentName}>{label}</strong>
                        {segment.isLecture ? <span className={styles.assignmentInstructor}>Locked lecture</span> : null}
                      </Tag>
                    )
                  }),
                ]
                : [
                  ...placed.map(({ assignment, style, view }) => {
                    const reconciliationRole = getReconciliationRole(
                      reconciliationHighlight,
                      view.room,
                      view.instructor,
                      view.start,
                      view.end,
                    )
                    return (
                      <AssignmentBlock
                        assignment={assignment}
                        dragDisabled={commandPending || !workspaceVersion}
                        issueMatch={issueMatchIds.has(assignment.id)}
                        key={assignment.id}
                        onKeyDown={(event) => handleKeyboard(assignment.id, event)}
                        onSelect={selectAssignment}
                        placement={style}
                        reconciliationHighlight={reconciliationRole}
                        selected={selectedId === assignment.id}
                      />
                    )
                  }),
                  ...placedGhosts.map(({ assignment, style }) => (
                    <GhostAssignmentBlock assignment={assignment} key={`ghost:${assignment.id}`} placement={style} />
                  )),
                  ...visibleReservationMarkers.map(({ marker, style }) => (
                    <ReservationDateChips key={`${marker.instructor}:${marker.start_time}:${marker.magnet_room}`} marker={marker} placement={style} />
                  )),
                ]}
            </div>
          </div>
          {assignments.length === 0
            ? <p className={styles.empty}>No assignments in the current scheduler session.</p>
            : filteredAssignments.length === 0
              ? <p className={styles.empty}>No assignments match these display filters.</p>
              : (teacherView ? placedSegments.length : placed.length) === 0 && outOfView.length === 0
                ? <p className={styles.gridNotice}>No placed assignments for {DAYS.find((day) => day.id === activeDay)?.label}.</p>
                : null}
          {outOfView.length > 0 ? (
            <section aria-label="Assignments outside the visible schedule" className={styles.unplacedAssignments}>
              <div className={styles.unplacedHeading}>
                <h2>Outside {String(Math.floor(timeBounds.start / 60)).padStart(2, '0')}:00-{String(Math.floor(timeBounds.end / 60)).padStart(2, '0')}:00</h2>
                <span className="numeric">{outOfView.length}</span>
              </div>
              <div className={styles.unplacedList}>
              {outOfView.map(({ assignment }) => (
                  <AssignmentBlock
                    assignment={assignment}
                    dragDisabled={commandPending || !workspaceVersion}
                    issueMatch={issueMatchIds.has(assignment.id)}
                    key={assignment.id}
                    onKeyDown={(event) => handleKeyboard(assignment.id, event)}
                    onSelect={selectAssignment}
                    selected={selectedId === assignment.id}
                  />
                ))}
              </div>
            </section>
          ) : null}
        </div>
      </section>
      <DragOverlay dropAnimation={null}>
        {activeDrag ? (
          <div
            className={styles.dragPreview}
            data-kind={adaptAssignment(activeDrag.assignment).kind}
            data-testid="assignment-drag-preview"
            style={{ height: activeDrag.height, width: activeDrag.width }}
          >
            <span>{adaptAssignment(activeDrag.assignment).kind}</span>
            <strong>{adaptAssignment(activeDrag.assignment).title}</strong>
            <small>{adaptAssignment(activeDrag.assignment).instructor}</small>
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}
