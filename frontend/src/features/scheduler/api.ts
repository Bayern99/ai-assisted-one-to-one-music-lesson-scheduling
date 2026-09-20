import { useQuery } from '@tanstack/react-query'
import type { components } from '../../api/schema'
import { apiRequest, type ApiEnvelope } from '../../api/client'

export type SchedulerSession = components['schemas']['SchedulerSessionView']
export type SchedulerImportPreview = components['schemas']['SchedulerImportPreview']
export type SchedulerWorkbookImportPreview = components['schemas']['SchedulerWorkbookImportPreview']
export type SchedulerImportResult = components['schemas']['SchedulerImportResult']
export type SchedulerWorkbookImportResult = components['schemas']['SchedulerWorkbookImportResult']
export type SchedulerLecturesView = components['schemas']['SchedulerLecturesView']
export type SchedulerLectureCsvPreview = components['schemas']['SchedulerLectureCsvPreview']
export type SchedulerLectureValidationResult = components['schemas']['SchedulerLectureValidationResult']
export type SchedulerRulesView = components['schemas']['SchedulerRulesView']
export type LectureEvent = components['schemas']['LectureEvent']
export type Operation = components['schemas']['Operation']
export type SchedulerOptimizeAccepted = components['schemas']['SchedulerOptimizeAccepted']
export type SchedulerOptimizerPreflight = components['schemas']['SchedulerOptimizerPreflight']
export type OptimizerLearningView = components['schemas']['OptimizerLearningView']
export type SchedulerExportBuildResult = components['schemas']['SchedulerExportBuildResult']
export type SchedulerRoundStartResult = components['schemas']['SchedulerRoundStartResult']
export type SchedulerMoveValidationResult = components['schemas']['SchedulerMoveValidationResult']
export type ResolutionAdvice = components['schemas']['ResolutionAdvice']
export type DashboardData = components['schemas']['DashboardData']
export type SchedulerRerunMode = 'fresh' | 'preserve_pinned'

export const schedulerSessionKey = ['scheduler-session'] as const
export const schedulerLecturesKey = ['scheduler-lectures'] as const
export const schedulerRulesKey = ['scheduler-rules'] as const
export const schedulerResolutionKey = ['scheduler-resolution-advice'] as const
export const optimizerLearningKey = ['scheduler-optimizer-learning-records'] as const

export function useSchedulerSession() {
  return useQuery({
    queryKey: schedulerSessionKey,
    queryFn: ({ signal }) => apiRequest<SchedulerSession>('/api/scheduler/session', { signal }),
  })
}

export function useResolutionAdvice(workspaceVersion: string | null) {
  return useQuery({
    enabled: Boolean(workspaceVersion),
    queryKey: [...schedulerResolutionKey, workspaceVersion],
    queryFn: ({ signal }) => apiRequest<ResolutionAdvice>(
      '/api/scheduler/resolution/advice',
      { signal },
    ),
  })
}

export function useOptimizerLearningRecords() {
  return useQuery({
    queryKey: optimizerLearningKey,
    queryFn: ({ signal }) => apiRequest<OptimizerLearningView>(
      '/api/scheduler/optimize/records',
      { signal },
    ),
  })
}

export function reviewDraft(expectedVersion: string, signal?: AbortSignal) {
  return apiRequest<components['schemas']['PiReviewDraftView']>(
    '/api/scheduler/resolution/review-draft',
    {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion }),
      signal,
    },
  )
}

export function setResolutionWaiting(
  caseId: string,
  waiting: boolean,
  note: string,
  expectedVersion: string,
) {
  return apiRequest<ResolutionAdvice>(
    `/api/scheduler/resolution/cases/${encodeURIComponent(caseId)}/waiting`,
    {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion, waiting, note }),
    },
  )
}

export function applyPianoLeverage(
  proposalId: string,
  expectedVersion: string,
  confirmationNote: string,
) {
  return apiRequest<SchedulerSession>(
    `/api/scheduler/resolution/piano-leverage/${encodeURIComponent(proposalId)}/apply`,
    {
      method: 'POST',
      body: JSON.stringify({
        expected_version: expectedVersion,
        teacher_confirmed: true,
        confirmation_note: confirmationNote,
      }),
    },
  )
}

export function previewSchedulerImport(slot: 'weekly' | 'studio', file: File) {
  const form = new FormData()
  form.set('file', file, file.name)
  return apiRequest<SchedulerImportPreview>(
    `/api/scheduler/import/preview?${new URLSearchParams({ slot })}`,
    { method: 'POST', body: form },
  )
}

export function previewSchedulerWorkbook(file: File) {
  const form = new FormData()
  form.set('file', file, file.name)
  return apiRequest<SchedulerWorkbookImportPreview>(
    '/api/scheduler/import/preview',
    { method: 'POST', body: form },
  )
}

export function applySchedulerImport(previewId: string, expectedVersion: string) {
  return apiRequest<SchedulerImportResult | SchedulerWorkbookImportResult>('/api/scheduler/import/apply', {
    method: 'POST',
    body: JSON.stringify({ preview_id: previewId, expected_version: expectedVersion }),
  })
}

export function applySchedulerWorkbook(file: File, previewId: string, fingerprint: string, expectedVersion: string) {
  const form = new FormData()
  form.set('file', file, file.name)
  form.set('preview_id', previewId)
  form.set('fingerprint', fingerprint)
  form.set('expected_version', expectedVersion)
  return apiRequest<SchedulerWorkbookImportResult>('/api/scheduler/import/apply', {
    method: 'POST',
    body: form,
  })
}

export function resetScheduler(expectedVersion: string) {
  return apiRequest<SchedulerSession>('/api/scheduler/reset', {
    method: 'POST', body: JSON.stringify({ expected_version: expectedVersion }),
  })
}

export function getSchedulerLectures(signal?: AbortSignal) {
  return apiRequest<SchedulerLecturesView>('/api/scheduler/lectures', { signal })
}

export function previewSchedulerLectures(file: File) {
  const form = new FormData()
  form.set('file', file, file.name)
  return apiRequest<SchedulerLectureCsvPreview>('/api/scheduler/lectures/preview', {
    method: 'POST', body: form,
  })
}

export function validateSchedulerLectures(lectures: LectureEvent[]) {
  return apiRequest<SchedulerLectureValidationResult>('/api/scheduler/lectures/validate', {
    method: 'POST', body: JSON.stringify({ lectures }),
  })
}

export function saveSchedulerLectures(lectures: LectureEvent[], expectedVersion: string) {
  return apiRequest<SchedulerLecturesView>('/api/scheduler/lectures', {
    method: 'PUT', body: JSON.stringify({ lectures, expected_version: expectedVersion }),
  })
}

export function getSchedulerRules(signal?: AbortSignal) {
  return apiRequest<SchedulerRulesView>('/api/scheduler/rules', { signal })
}

export function saveSchedulerRules(rules: Record<string, unknown>, expectedVersion: string) {
  return apiRequest<SchedulerRulesView>('/api/scheduler/rules', {
    method: 'PUT', body: JSON.stringify({ rules, expected_version: expectedVersion }),
  })
}

export function runSchedulerOptimizer(expectedVersion: string, rerunMode?: SchedulerRerunMode) {
  const payload: { expected_version: string; rerun_mode?: SchedulerRerunMode } = { expected_version: expectedVersion }
  if (rerunMode) payload.rerun_mode = rerunMode
  return apiRequest<SchedulerOptimizeAccepted>('/api/scheduler/optimize', {
    method: 'POST', body: JSON.stringify(payload),
  })
}

export type PiInterventionModel = string
export type PiRuntimeChoice = { provider: string; model: string }
export type PiRuntime = {
  provider: string
  model: string
  thinking_level?: string
  thinking_levels?: string[]
  choices?: PiRuntimeChoice[]
  allowed_models?: string[]
}

export interface ReconciliationTaskInputs {
  goal?: string
  provider?: string
  thinkingLevel?: string
  protectInstructors?: string[]
  allowTimeChangeInstructors?: string[]
  lockedRoomDays?: { room: string; day: number }[]
  maxToolCalls?: number
}

/** One whole-day delegation: the day is the task, not a single issue. */
export function investigateReconciliation(
  model: PiInterventionModel,
  expectedVersion: string,
  day: number,
  task: ReconciliationTaskInputs = {},
) {
  return apiRequest<SchedulerOptimizeAccepted>('/api/scheduler/resolution/reconciliation/investigate', {
    method: 'POST',
    body: JSON.stringify({
      expected_version: expectedVersion,
      model,
      provider: task.provider ?? '',
      thinking_level: task.thinkingLevel ?? '',
      day,
      goal: task.goal ?? '',
      protect_instructors: task.protectInstructors ?? [],
      allow_time_change_instructors: task.allowTimeChangeInstructors ?? [],
      locked_room_days: task.lockedRoomDays ?? [],
      max_tool_calls: task.maxToolCalls,
    }),
  })
}

export function decideReconciliation(
  investigationId: string,
  decision: 'pursuing' | 'rejected',
  expectedVersion: string,
  note = '',
) {
  return apiRequest<ResolutionAdvice>(
    `/api/scheduler/resolution/reconciliation/${encodeURIComponent(investigationId)}/decision`,
    {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion, decision, note }),
    },
  )
}

export function applyReconciliation(
  investigationId: string,
  simulationId: string,
  expectedVersion: string,
  confirmedTeacherAliases: string[] = [],
  authorizedSacrificeAliases: string[] = [],
  note = '',
  confirmedConfirmationIds: string[] = [],
) {
  return apiRequest<ResolutionAdvice>(
    `/api/scheduler/resolution/reconciliation/${encodeURIComponent(investigationId)}/apply`,
    {
      method: 'POST',
      body: JSON.stringify({
        expected_version: expectedVersion,
        simulation_id: simulationId,
        confirmed_teacher_aliases: confirmedTeacherAliases,
        confirmed_confirmation_ids: confirmedConfirmationIds,
        authorized_sacrifice_aliases: authorizedSacrificeAliases,
        note,
      }),
    },
  )
}

export function getSchedulerOptimizerPreflight(signal?: AbortSignal) {
  return apiRequest<SchedulerOptimizerPreflight>('/api/scheduler/optimize/preflight', { signal })
}

export function getOperation(operationId: string, signal?: AbortSignal): Promise<ApiEnvelope<Operation>> {
  return apiRequest<Operation>(`/api/operations/${encodeURIComponent(operationId)}`, { signal })
}

export function stageScheduler(expectedVersion: string) {
  return apiRequest<SchedulerSession>('/api/scheduler/stage', {
    method: 'POST',
    body: JSON.stringify({ expected_version: expectedVersion }),
  })
}

export function finalizeScheduler(expectedVersion: string) {
  return apiRequest<SchedulerSession>('/api/scheduler/finalize', {
    method: 'POST', body: JSON.stringify({ expected_version: expectedVersion }),
  })
}

export function buildSchedulerExports() {
  return apiRequest<SchedulerExportBuildResult>('/api/scheduler/exports/build', { method: 'POST' })
}

export function startSchedulerRound(expectedVersion: string) {
  return apiRequest<SchedulerRoundStartResult>('/api/scheduler/rounds/start', {
    method: 'POST', body: JSON.stringify({ expected_version: expectedVersion }),
  })
}

export interface SchedulerAssignmentProposal {
  day: number
  end: string
  room: string
  start: string
}

export function validateIssueAssignment(issueId: string, proposal: SchedulerAssignmentProposal) {
  return apiRequest<SchedulerMoveValidationResult>(
    `/api/scheduler/issues/${encodeURIComponent(issueId)}/validate-assignment`,
    { method: 'POST', body: JSON.stringify(proposal) },
  )
}

export function validateAssignmentMove(assignmentId: string, proposal: SchedulerAssignmentProposal) {
  return apiRequest<SchedulerMoveValidationResult>(
    `/api/scheduler/assignments/${encodeURIComponent(assignmentId)}/validate-move`,
    { method: 'POST', body: JSON.stringify(proposal) },
  )
}

export function getDashboard(signal?: AbortSignal) {
  return apiRequest<DashboardData>('/api/dashboard', { signal })
}
