import { describe, expect, it } from 'vitest'
import { adaptAssignment } from './AssignmentBlock'
import { buildTeacherSegments, teacherTone } from './teacherPresentation'

function item(id: string, instructor: string, room: string, start: string, end: string, day = 3) {
  const assignment = {
    id,
    title: `Student ${id}`,
    type: 'weekly_lesson',
    resourceId: room,
    daysOfWeek: [day],
    startTime: start,
    endTime: end,
    extendedProps: { Instructor: instructor },
  }
  return { assignment, view: adaptAssignment(assignment) }
}

describe('teacherPresentation', () => {
  it('merges contiguous same-teacher same-room lessons into one segment', () => {
    const segments = buildTeacherSegments([
      item('a', 'Dr. A', 'CC101', '13:00', '14:00'),
      item('b', 'Dr. A', 'CC101', '14:00', '15:00'),
      item('c', 'Dr. A', 'CC101', '15:00', '16:00'),
      item('d', 'Dr. A', 'CC101', '16:00', '17:00'),
    ], 3)
    expect(segments).toHaveLength(1)
    expect(segments[0]).toMatchObject({
      instructor: 'Dr. A',
      room: 'CC101',
      start: '13:00',
      end: '17:00',
      assignmentIds: ['a', 'b', 'c', 'd'],
    })
  })

  it('keeps a gap as separate segments but assigns the same tone', () => {
    const segments = buildTeacherSegments([
      item('a', 'Dr. A', 'CC101', '13:00', '14:00'),
      item('b', 'Dr. A', 'CC101', '16:00', '17:00'),
      item('c', 'Dr. B', 'CC102', '13:00', '14:00'),
    ], 3)
    expect(segments).toHaveLength(3)
    expect(segments[0].tone).toBe(segments[1].tone)
    expect(segments[0].tone).toBe(teacherTone('Dr. A'))
    expect(segments[2].tone).toBe(teacherTone('Dr. B'))
    expect(segments[0].tone).not.toBe(segments[2].tone)
  })

  it('does not merge across rooms or teachers', () => {
    const segments = buildTeacherSegments([
      item('a', 'Dr. A', 'CC101', '13:00', '14:00'),
      item('b', 'Dr. A', 'CC102', '14:00', '15:00'),
      item('c', 'Dr. B', 'CC101', '14:00', '15:00'),
    ], 3)
    expect(segments.map((segment) => segment.assignmentIds.join('+'))).toEqual(['a', 'c', 'b'])
  })
})
