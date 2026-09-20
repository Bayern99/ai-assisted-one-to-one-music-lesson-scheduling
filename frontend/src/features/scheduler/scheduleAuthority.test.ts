import { describe, expect, it } from 'vitest'
import { draftState } from '../../test/draftState'
import {
  buildReservationMarkers,
  computeGhostAssignments,
  draftSaveHint,
  isReservationInternal,
  resolveScheduleAuthority,
  type ExtendedSchedulerSession,
} from './scheduleAuthority'

const baseSession = {
  active_stage: 'resolve' as const,
  assignments: [
    {
      id: 'weekly-1',
      title: 'Weekly lesson',
      type: 'weekly_lesson',
      resourceId: 'R101',
      daysOfWeek: [1],
      startTime: '09:00:00',
      endTime: '10:00:00',
      source_request_id: 'weekly-1',
    },
    {
      id: 'studio-1',
      title: 'Studio lesson',
      type: 'studio_class',
      resourceId: 'R102',
      daysOfWeek: [2],
      start: '2026-03-03T14:00:00',
      end: '2026-03-03T15:00:00',
      source_request_id: 'studio-1',
    },
  ],
  issues: [],
  rooms: [{ id: 'R101' }, { id: 'R102' }],
  instructors: [],
  draft: draftState(draftState({ dirty: false, can_undo: false, can_redo: false })),
  metrics: { assigned: 2, unresolved: 0, source_gaps: 0 },
}

describe('scheduleAuthority', () => {
  it('infers editing when validation authority diverges from the live draft', () => {
    const session: ExtendedSchedulerSession = {
      ...baseSession,
      validation_authority: [
        {
          ...baseSession.assignments[0],
          resourceId: 'R102',
        },
        baseSession.assignments[1],
      ],
    }
    expect(resolveScheduleAuthority(session)).toBe('editing')
    const ghosts = computeGhostAssignments(session)
    expect(ghosts).toHaveLength(1)
    expect(ghosts[0].id).toBe('weekly-1')
  })

  it('never treats lectures as held ghosts', () => {
    const session: ExtendedSchedulerSession = {
      ...baseSession,
      validation_authority: [
        {
          id: 'lecture-1',
          title: 'Lecture',
          type: 'lecture',
          resourceId: 'Hall-A',
          daysOfWeek: [3],
          startTime: '11:00',
          endTime: '12:00',
          locked: true,
        },
      ],
    }
    expect(computeGhostAssignments(session)).toEqual([])
  })

  it('builds reservation markers from reservation-internal issues', () => {
    const session: ExtendedSchedulerSession = {
      ...baseSession,
      issues: [{
        reason_code: 'reservation_internal',
        label: 'Reservation internal',
        count: 1,
        items: [{
          id: 'issue-res',
          reason_code: 'reservation_internal',
          message: 'Held in instructor reservation',
          reason: 'Held in instructor reservation',
          duration_minutes: 60,
          source_request_id: 'studio-series',
          instructor: 'Piano D',
          original_day: 1,
          original_start: '19:00',
          original_end: '20:00',
          magnet_room: 'R101',
          reservation_note: 'Optimizer left this studio date in the instructor reservation.',
          type: 'studio_class',
          payload: {
            placed_dates: ['2026-11-17'],
            unplaced_dates: ['2026-11-24'],
          },
        }],
      }],
    }
    expect(isReservationInternal(session.issues[0].items[0])).toBe(true)
    const markers = buildReservationMarkers(session, session.issues.flatMap((group) => group.items))
    expect(markers).toEqual([{
      instructor: 'Piano D',
      weekday: 1,
      start_time: '19:00',
      end_time: '20:00',
      magnet_room: 'R101',
      placed_dates: ['2026-11-17'],
      unplaced_dates: ['2026-11-24'],
    }])
  })

  it('prefers explicit schedule authority from the backend', () => {
    const session: ExtendedSchedulerSession = {
      ...baseSession,
      schedule_authority: 'finalized',
      active_stage: 'export',
    }
    expect(resolveScheduleAuthority(session)).toBe('finalized')
  })

  it('treats a persisted unpublished draft as autosaved', () => {
    expect(draftSaveHint(draftState({ dirty: true, can_undo: true, can_redo: false, save_status: 'saved' }))).toBe('Autosave active')
    expect(draftSaveHint(draftState({ dirty: true, can_undo: false, can_redo: false, save_status: 'failed' }))).toBe('Save failed')
    expect(draftSaveHint(draftState(draftState({ dirty: true, can_undo: false, can_redo: false })), true)).toBe('Autosave pending')
  })
})
