import type { SchedulerSession } from '../../features/scheduler/api'
import { WORKFLOW_LABELS } from '../../app/productLanguage'

export type SchedulerStage = SchedulerSession['active_stage']
export type WorkflowVisualState = 'current' | 'done' | 'pending'

export interface ShellWorkspaceState {
  activeStage: SchedulerStage
  connection: 'connected' | 'connecting' | 'disconnected'
  draft: {
    canRedo: boolean
    canUndo: boolean
    dirty: boolean
    saveStatus?: 'saved' | 'degraded' | 'failed'
  }
  source: 'needs-review' | 'pending' | 'verified'
  version: string | null
}

export interface ShellSessionSnapshot {
  data: SchedulerSession | null
  error?: unknown
  warnings?: readonly string[]
  workspace_version: string | null
}

export const WORKFLOW_STEPS = [
  { label: WORKFLOW_LABELS.lectures, path: '/schedule/lectures', stage: 'lectures' },
  { label: WORKFLOW_LABELS.import, path: '/schedule/import', stage: 'import' },
  { label: WORKFLOW_LABELS.rules, path: '/schedule/rules', stage: 'rules' },
  { label: WORKFLOW_LABELS.optimize, path: '/schedule/optimize', stage: 'optimize' },
  { label: WORKFLOW_LABELS.resolve, path: '/schedule/resolve', stage: 'resolve' },
  { label: WORKFLOW_LABELS.export, path: '/schedule/export', stage: 'export' },
] as const

export function normalizePathname(pathname: string) {
  return pathname.replace(/\/+$/, '') || '/'
}

export function workflowIndexForStage(stage: SchedulerStage) {
  return Math.max(0, WORKFLOW_STEPS.findIndex((step) => step.stage === stage))
}

export function workflowIndexForRoute(pathname: string) {
  const normalized = normalizePathname(pathname)
  const index = WORKFLOW_STEPS.findIndex((step) => normalized === step.path || normalized.startsWith(`${step.path}/`))
  return index >= 0 ? index : null
}

export function workflowState(
  index: number,
  pathname: string,
  activeStage: SchedulerStage,
): WorkflowVisualState {
  const progressIndex = workflowIndexForStage(activeStage)
  const routeIndex = workflowIndexForRoute(pathname)
  const currentIndex = routeIndex ?? progressIndex
  if (index === currentIndex) return 'current'
  if (index < progressIndex) return 'done'
  return 'pending'
}

export function sourceStatusLabel(source: ShellWorkspaceState['source']) {
  if (source === 'verified') return 'Source verified'
  if (source === 'needs-review') return 'Source needs review'
  return 'Source status pending'
}

export function draftStatusLabel(workspace: ShellWorkspaceState) {
  if (workspace.connection === 'disconnected') return 'Draft status unavailable'
  if (workspace.connection === 'connecting') return 'Draft status pending'
  if (workspace.draft.saveStatus === 'failed') return 'Save failed'
  if (workspace.draft.saveStatus === 'degraded') return 'Autosave warning'
  return 'Autosave active'
}

export function connectionStatusLabel(connection: ShellWorkspaceState['connection']) {
  if (connection === 'connected') return 'Workspace ready'
  if (connection === 'disconnected') return 'Workspace unavailable'
  return 'Preparing workspace'
}

export function deriveShellWorkspaceState({
  envelope,
  isError,
}: {
  envelope?: ShellSessionSnapshot | null
  isError: boolean
}): ShellWorkspaceState {
  const session = envelope?.data ?? null
  const activeStage = session?.active_stage ?? 'import'
  return {
    activeStage,
    connection: isError ? 'disconnected' : session ? 'connected' : 'connecting',
    draft: session
      ? {
          canRedo: session.draft.can_redo,
          canUndo: session.draft.can_undo,
          dirty: session.draft.dirty,
          saveStatus: session.draft.save_status ?? 'saved',
        }
      : { canRedo: false, canUndo: false, dirty: false, saveStatus: 'saved' },
    source: session
      ? activeStage !== 'import'
        && activeStage !== 'lectures'
        && session.metrics.source_gaps === 0
        && (envelope?.warnings?.length ?? 0) === 0
        ? 'verified'
        : 'needs-review'
      : 'pending',
    version: envelope?.workspace_version ?? null,
  }
}
