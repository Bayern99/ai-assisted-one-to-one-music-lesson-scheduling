import type { Assignment, AssignmentView } from './AssignmentBlock'

export type SchedulePresentationMode = 'lessons' | 'teachers'

export interface TeacherSegment {
  assignmentIds: string[]
  end: string
  instructor: string
  isLecture: boolean
  kind: AssignmentView['kind']
  locked: boolean
  room: string
  start: string
  title: string
  tone: number
}

export function teacherSegmentKey(segment: Pick<TeacherSegment, 'end' | 'instructor' | 'isLecture' | 'room' | 'start'>) {
  return `${segment.room}|${segment.start}|${segment.end}|${segment.instructor}|${segment.isLecture ? 'lecture' : 'teacher'}`
}

const TONE_COUNT = 8

export function teacherTone(instructor: string): number {
  let hash = 0
  for (let index = 0; index < instructor.length; index += 1) {
    hash = (hash * 31 + instructor.charCodeAt(index)) >>> 0
  }
  return hash % TONE_COUNT
}

function clockToMinutes(value: string | null | undefined): number | null {
  if (!value) return null
  const match = value.match(/(?:T|^)(\d{1,2}):(\d{2})(?::\d{2})?$/)
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (!Number.isInteger(hours) || !Number.isInteger(minutes) || hours > 23 || minutes > 59) return null
  return hours * 60 + minutes
}

function formatMinutes(value: number) {
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}

/** Pure presentation merge: same teacher + same room + contiguous time → one visual segment. */
export function buildTeacherSegments(
  items: Array<{ assignment: Assignment; view: AssignmentView }>,
  activeDay: number,
): TeacherSegment[] {
  const dayItems = items
    .map(({ assignment, view }) => {
      const start = clockToMinutes(view.start)
      const end = clockToMinutes(view.end)
      if (view.day !== activeDay || !view.room || start === null || end === null || end <= start) return null
      return { assignment, view, start, end }
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item))
    .sort((left, right) => {
      if (left.view.room !== right.view.room) return left.view.room!.localeCompare(right.view.room!)
      if (left.start !== right.start) return left.start - right.start
      return left.assignment.id.localeCompare(right.assignment.id)
    })

  const segments: TeacherSegment[] = []
  for (const item of dayItems) {
    const previous = segments.at(-1)
    const sameTeacherRoom = previous
      && previous.room === item.view.room
      && previous.instructor === item.view.instructor
      && previous.isLecture === item.view.isLecture
    const contiguous = previous && clockToMinutes(previous.end) === item.start
    if (sameTeacherRoom && contiguous) {
      previous.assignmentIds.push(item.assignment.id)
      previous.end = formatMinutes(item.end)
      if (item.view.locked) previous.locked = true
      if (item.view.kind === 'locked') previous.kind = 'locked'
      else if (previous.kind !== 'locked' && item.view.kind === 'studio') previous.kind = 'studio'
      continue
    }
    segments.push({
      assignmentIds: [item.assignment.id],
      end: formatMinutes(item.end),
      instructor: item.view.instructor,
      isLecture: item.view.isLecture,
      kind: item.view.kind,
      locked: item.view.locked,
      room: item.view.room!,
      start: formatMinutes(item.start),
      title: item.view.title,
      tone: teacherTone(item.view.instructor),
    })
  }
  return segments
}
