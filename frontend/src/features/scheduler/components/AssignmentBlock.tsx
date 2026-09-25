/* eslint-disable react-refresh/only-export-components */
import type { CSSProperties } from 'react'
import { useDraggable } from '@dnd-kit/core'
import type { SchedulerSession } from '../api'
import styles from '../scheduleGrid.module.css'

export type Assignment = SchedulerSession['assignments'][number]
export type AssignmentKind = 'weekly' | 'studio' | 'locked'

const DAY_LABELS: Record<number, string> = {
  0: 'Sunday', 1: 'Monday', 2: 'Tuesday', 3: 'Wednesday',
  4: 'Thursday', 5: 'Friday', 6: 'Saturday',
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function boolean(value: unknown): boolean {
  return value === true
}

function stripLeadingDecoration(value: string) {
  return value.replace(/^(?:[👤📌🔒⚠•◆◇★☆]\uFE0F?\s*)+/u, '').trim()
}

function dayFromIso(value: string | null): number | null {
  const match = value?.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!match) return null
  const day = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))).getUTCDay()
  return Number.isFinite(day) ? day : null
}

export interface AssignmentView {
  day: number | null
  dayLabel: string
  end: string | null
  id: string
  instructor: string
  isLecture: boolean
  kind: AssignmentKind
  locked: boolean
  person: string | null
  proposalEnd: string | null
  proposalStart: string | null
  room: string | null
  start: string | null
  title: string
}

export function adaptAssignment(assignment: Assignment): AssignmentView {
  const source = assignment as Record<string, unknown>
  const extended = record(source.extendedProps)
  const rawDays = Array.isArray(source.daysOfWeek) ? source.daysOfWeek : []
  const listedDay = rawDays.find((value): value is number => typeof value === 'number' && value >= 0 && value <= 6)
  const start = text(source.startTime) ?? text(source.start)
  const end = text(source.endTime) ?? text(source.end)
  const proposalStart = text(source.proposal_start)
  const proposalEnd = text(source.proposal_end)
  const type = (text(source.type) ?? '').toLowerCase()
  const isLecture = type.includes('lecture')
  const locked = boolean(source.locked) || boolean(source.committed) || boolean(source.pinned) || isLecture
  const kind: AssignmentKind = locked ? 'locked' : type.includes('studio') ? 'studio' : 'weekly'
  const day = listedDay ?? dayFromIso(start)
  const instructor = text(extended.Instructor) ?? text(extended.instructor) ?? text(source.instructor) ?? (isLecture ? 'Lecture' : 'Instructor unavailable')
  const person = text(extended.Student) ?? text(extended['Student Name']) ?? text(extended.student) ?? text(source.student)
  const sourceTitle = text(source.title) ?? text(source.name)

  return {
    id: assignment.id,
    title: (sourceTitle ? stripLeadingDecoration(sourceTitle) : null) || person || (isLecture ? 'Lecture' : `Assignment ${assignment.id}`),
    kind,
    locked,
    isLecture,
    room: text(source.resourceId) ?? text(source.room_id) ?? text(source.room),
    day,
    dayLabel: day === null ? 'Day unavailable' : DAY_LABELS[day] ?? `Day ${day}`,
    start,
    end,
    instructor,
    person,
    proposalEnd,
    proposalStart,
  }
}

function clockLabel(value: string | null) {
  if (!value) return 'time unavailable'
  const match = value.match(/(?:T|^)(\d{2}:\d{2})/)
  return match?.[1] ?? value
}

function clockMinutes(value: string | null) {
  const label = clockLabel(value)
  const match = label.match(/^(\d{2}):(\d{2})$/)
  return match ? Number(match[1]) * 60 + Number(match[2]) : null
}

function assignmentDensity(view: AssignmentView) {
  const start = clockMinutes(view.start)
  const end = clockMinutes(view.end)
  if (start === null || end === null || end <= start) return 'compact'
  const duration = end - start
  return duration >= 90 ? 'wide' : duration >= 60 ? 'standard' : 'compact'
}

export function assignmentAccessibleName(view: AssignmentView) {
  const kind = view.isLecture ? 'Lecture' : view.kind === 'locked' ? 'Locked' : view.kind === 'studio' ? 'Studio' : 'Weekly'
  const person = view.person ? `, ${view.person}` : ''
  const lock = view.locked ? ', locked' : ''
  return `${kind}, ${view.title}, ${view.instructor}${person}, room ${view.room ?? 'unavailable'}, ${view.dayLabel}, ${clockLabel(view.start)} to ${clockLabel(view.end)}${lock}`
}

interface AssignmentBlockProps {
  assignment: Assignment
  dragDisabled?: boolean
  issueMatch: boolean
  onKeyDown?: React.KeyboardEventHandler<HTMLButtonElement>
  onSelect: (id: string) => void
  placement?: CSSProperties
  reconciliationHighlight?: 'source' | 'destination' | null
  selected: boolean
}

export function AssignmentBlock({ assignment, dragDisabled, issueMatch, onKeyDown, onSelect, placement, reconciliationHighlight, selected }: AssignmentBlockProps) {
  const view = adaptAssignment(assignment)
  const kindLabel = view.isLecture ? 'Lecture' : view.kind === 'locked' ? 'Locked' : view.kind === 'studio' ? 'Studio' : 'Weekly'
  const visibleTime = `${clockLabel(view.start)}–${clockLabel(view.end)}`
  const { attributes, listeners, setNodeRef } = useDraggable({
    id: view.id,
    disabled: dragDisabled || view.isLecture || view.locked,
    data: { assignmentId: view.id },
  })
  return (
    <button
      {...attributes}
      {...listeners}
      aria-label={assignmentAccessibleName(view)}
      aria-pressed={selected}
      className={placement ? styles.assignment : `${styles.assignment} ${styles.unplacedAssignment}`}
      data-assignment-id={view.id}
      data-density={assignmentDensity(view)}
      data-issue-match={issueMatch ? 'true' : undefined}
      data-kind={view.kind}
      data-lecture={view.isLecture ? 'true' : undefined}
      data-reconciliation-highlight={reconciliationHighlight ?? undefined}
      data-room={view.room ?? undefined}
      onClick={() => { if (!view.isLecture) onSelect(view.id) }}
      onKeyDown={view.isLecture ? undefined : onKeyDown}
      ref={setNodeRef}
      style={placement}
      title={view.isLecture ? `${visibleTime} · Lecture · ${view.title}` : `${visibleTime} · ${view.title} · ${view.instructor}`}
      type="button"
    >
      <span className={styles.assignmentTopline}>
        <span className={styles.assignmentTime}>{visibleTime}</span>
        <span aria-hidden="true" className={styles.assignmentKind}>{view.isLecture ? 'Lecture' : kindLabel.slice(0, 1)}</span>
      </span>
      <strong>{view.title}</strong>
      <span className={styles.assignmentInstructor}>{view.isLecture ? 'Locked lecture' : view.instructor}</span>
    </button>
  )
}
