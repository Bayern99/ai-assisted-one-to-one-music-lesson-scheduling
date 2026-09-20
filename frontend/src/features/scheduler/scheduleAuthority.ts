import type { SchedulerSession } from './api'
import { adaptAssignment } from './components/AssignmentBlock'
import type { Issue } from './components/IssueQueue'

export type ScheduleAuthority = 'editing' | 'staged' | 'finalized'

export const SCHEDULE_AUTHORITY_LABELS: Record<ScheduleAuthority, string> = {
  editing: 'Editing',
  staged: 'Staged',
  finalized: 'Finalized',
}

export type Assignment = SchedulerSession['assignments'][number]

export interface SchedulerSessionExtensions {
  schedule_authority?: ScheduleAuthority
  validation_authority?: Assignment[]
  reservations?: ReservationMarker[]
}

export type ExtendedSchedulerSession = SchedulerSession & SchedulerSessionExtensions

export type ExtendedDraftState = SchedulerSession['draft'] & {
  unsealed?: boolean
  save_status?: 'saved' | 'degraded' | 'failed'
}

export function draftSaveHint(
  draft: ExtendedDraftState,
  pending = false,
): string {
  if (pending) return 'Autosave pending'
  if (draft.save_status === 'failed') return 'Save failed'
  if (draft.save_status === 'degraded') return 'Autosave warning'
  return 'Autosave active'
}

export interface ReservationMarker {
  instructor: string
  weekday: number
  start_time: string
  end_time: string
  magnet_room: string
  placed_dates: string[]
  unplaced_dates: string[]
}

export interface ExtendedIssue extends Issue {
  reservation_classification?: 'reservation_internal' | 'contention'
  reservation_note?: string | null
  magnet_room?: string | null
  placed_dates?: string[]
  unplaced_dates?: string[]
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function clockKey(value: string | null | undefined): string | null {
  if (!value) return null
  const match = value.match(/(?:T|^)(\d{1,2}):(\d{2})/)
  return match ? `${match[1].padStart(2, '0')}:${match[2]}` : null
}

export function canonicalAssignmentId(assignment: Assignment): string {
  const source = assignment as Record<string, unknown>
  return text(source.source_request_id) ?? assignment.id
}

export function placementKey(view: ReturnType<typeof adaptAssignment>): string | null {
  const start = clockKey(view.start)
  const end = clockKey(view.end)
  if (view.day === null || !view.room || !start || !end) return null
  return `${view.room}:${view.day}:${start}:${end}`
}

export function authorityPlacementDelta(l0: Assignment[], l1: Assignment[]): boolean {
  const l0ById = new Map(l0.map((item) => [canonicalAssignmentId(item), item]))
  const l1ById = new Map(l1.map((item) => [canonicalAssignmentId(item), item]))
  if (l0ById.size !== l1ById.size) return true
  for (const [id, l1Item] of l1ById) {
    const l0Item = l0ById.get(id)
    if (!l0Item) return true
    const l0Key = placementKey(adaptAssignment(l0Item))
    const l1Key = placementKey(adaptAssignment(l1Item))
    if (l0Key !== l1Key) return true
  }
  return false
}

export function resolveScheduleAuthority(session: ExtendedSchedulerSession): ScheduleAuthority {
  if (session.schedule_authority) return session.schedule_authority
  const draft = session.draft as ExtendedDraftState & { validation_state?: ScheduleAuthority }
  if (draft.validation_state) return draft.validation_state
  if (session.active_stage === 'export') return 'finalized'
  const l1 = session.validation_authority ?? session.assignments
  if (draft.unsealed || authorityPlacementDelta(session.assignments, l1)) return 'editing'
  return 'staged'
}

export function computeGhostAssignments(session: ExtendedSchedulerSession): Assignment[] {
  const l1 = session.validation_authority ?? session.assignments
  const l0ById = new Map(session.assignments.map((item) => [canonicalAssignmentId(item), item]))
  const ghosts: Assignment[] = []
  for (const l1Item of l1) {
    const view = adaptAssignment(l1Item)
    if (view.isLecture) continue
    const key = placementKey(view)
    if (!key) continue
    const l0Item = l0ById.get(canonicalAssignmentId(l1Item))
    if (!l0Item) {
      ghosts.push(l1Item)
      continue
    }
    if (placementKey(adaptAssignment(l0Item)) !== key) ghosts.push(l1Item)
  }
  return ghosts
}

export function ghostPlacementKeys(ghosts: Assignment[]): Set<string> {
  return new Set(
    ghosts
      .map((item) => placementKey(adaptAssignment(item)))
      .filter((key): key is string => Boolean(key)),
  )
}

export function isReservationInternal(issue: Issue | ExtendedIssue): boolean {
  if (issue.reason_code === 'reservation_internal') return true
  const extended = issue as ExtendedIssue & { reservation_label?: string | null }
  if (extended.reservation_label === 'reservation_internal') return true
  return extended.reservation_classification === 'reservation_internal'
}

export function issueReservationNote(issue: Issue | ExtendedIssue): string | null {
  const extended = issue as ExtendedIssue
  const direct = text(extended.reservation_note)
  if (direct) return direct
  const payload = record(issue.payload)
  return text(payload.reservation_note)
}

function dateList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0).map((item) => item.trim())
}

function formatChipDate(value: string): string {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/)
  return match ? `${match[2]}/${match[3]}` : value
}

export function reservationChipLabel(value: string): string {
  return formatChipDate(value)
}

export function buildReservationMarkers(
  session: ExtendedSchedulerSession,
  issues: Issue[],
): ReservationMarker[] {
  if (session.reservations?.length) return session.reservations
  const markers = new Map<string, ReservationMarker>()
  for (const issue of issues) {
    if (!isReservationInternal(issue)) continue
    const extended = issue as ExtendedIssue
    const payload = record(issue.payload)
    const magnet = text(extended.magnet_room) ?? text(payload.magnet_room)
    const weekday = issue.original_day
    const start = clockKey(issue.original_start ?? text(payload.start) ?? text(payload.startTime))
    const end = clockKey(issue.original_end ?? text(payload.end) ?? text(payload.endTime)) ?? start
    if (!magnet || weekday === null || weekday === undefined || !start) continue
    const key = `${issue.instructor ?? 'unknown'}:${weekday}:${start}:${magnet}`
    const placed = dateList(extended.placed_dates ?? payload.placed_dates)
    const unplaced = dateList(extended.unplaced_dates ?? payload.unplaced_dates)
    const existing = markers.get(key)
    if (existing) {
      existing.placed_dates = [...new Set([...existing.placed_dates, ...placed])]
      existing.unplaced_dates = [...new Set([...existing.unplaced_dates, ...unplaced])]
      continue
    }
    markers.set(key, {
      instructor: issue.instructor ?? 'Instructor unavailable',
      weekday,
      start_time: start,
      end_time: end ?? start,
      magnet_room: magnet,
      placed_dates: placed,
      unplaced_dates: unplaced,
    })
  }
  return [...markers.values()]
}

export function reservationMarkersForDay(markers: ReservationMarker[], activeDay: number) {
  return markers.filter((marker) => marker.weekday === activeDay)
}
