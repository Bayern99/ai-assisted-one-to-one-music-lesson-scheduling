import type { SchedulerSession } from '../features/scheduler/api'

/**
 * Test fixtures intentionally describe only the draft fields under test.
 * This cast keeps the canonical type honest without inventing values that
 * would change how the UI resolves schedule authority.
 */
export function draftState(
  partial: Partial<SchedulerSession['draft']>,
): SchedulerSession['draft'] {
  return partial as SchedulerSession['draft']
}
