import { useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiRequest, type ApiClientError, type ApiEnvelope } from '../../../api/client'
import { schedulerSessionKey, type SchedulerSession } from '../api'

export interface MoveTarget {
  day: number
  end: string
  room: string
  start: string
}

export interface TeacherConfirmation {
  confirmed: boolean
  note: string
}

export type AssignmentCommand =
  | { issueId: string; expectedVersion: string; kind: 'assign'; target: MoveTarget; confirmation?: TeacherConfirmation; decisionNote?: string }
  | { assignmentId: string; expectedVersion: string; kind: 'move'; target: MoveTarget; confirmation?: TeacherConfirmation; decisionNote?: string }
  | { assignmentId: string; expectedVersion: string; kind: 'unassign'; decisionNote?: string }
  | { assignmentIds: string[]; expectedVersion: string; kind: 'unassign_block'; decisionNote?: string }
  | { assignmentId: string; expectedVersion: string; kind: 'unlock' }
  | { expectedVersion: string; kind: 'undo' | 'redo' }

function requestCommand(command: AssignmentCommand) {
  const expected_version = command.expectedVersion
  if (command.kind === 'assign') {
    return apiRequest<SchedulerSession>(`/api/scheduler/issues/${encodeURIComponent(command.issueId)}/assign`, {
      method: 'POST', body: JSON.stringify({
        ...command.target,
        expected_version,
        teacher_confirmed: command.confirmation?.confirmed ?? false,
        teacher_confirmation_note: command.confirmation?.note ?? '',
        ...(command.decisionNote?.trim() ? { decision_note: command.decisionNote.trim() } : {}),
      }),
    })
  }
  if (command.kind === 'move') {
    return apiRequest<SchedulerSession>(`/api/scheduler/assignments/${encodeURIComponent(command.assignmentId)}/move`, {
      method: 'POST', body: JSON.stringify({
        ...command.target,
        expected_version,
        teacher_confirmed: command.confirmation?.confirmed ?? false,
        teacher_confirmation_note: command.confirmation?.note ?? '',
        ...(command.decisionNote?.trim() ? { decision_note: command.decisionNote.trim() } : {}),
      }),
    })
  }
  if (command.kind === 'unassign') {
    return apiRequest<SchedulerSession>(`/api/scheduler/assignments/${encodeURIComponent(command.assignmentId)}/unassign`, {
      method: 'POST', body: JSON.stringify({
        expected_version,
        ...(command.decisionNote?.trim() ? { decision_note: command.decisionNote.trim() } : {}),
      }),
    })
  }
  if (command.kind === 'unassign_block') {
    return apiRequest<SchedulerSession>('/api/scheduler/assignments/unassign-block', {
      method: 'POST', body: JSON.stringify({
        assignment_ids: command.assignmentIds,
        expected_version,
        ...(command.decisionNote?.trim() ? { decision_note: command.decisionNote.trim() } : {}),
      }),
    })
  }
  if (command.kind === 'unlock') {
    return apiRequest<SchedulerSession>(`/api/scheduler/assignments/${encodeURIComponent(command.assignmentId)}/${command.kind}`, {
      method: 'POST', body: JSON.stringify({ expected_version }),
    })
  }
  return apiRequest<SchedulerSession>(`/api/scheduler/draft/${command.kind}`, {
    method: 'POST', body: JSON.stringify({ expected_version }),
  })
}

export function useAssignmentCommands() {
  const queryClient = useQueryClient()
  const pending = useRef(false)
  const mutation = useMutation<ApiEnvelope<SchedulerSession>, ApiClientError, AssignmentCommand>({
    mutationFn: requestCommand,
    onSuccess: (canonical) => queryClient.setQueryData(schedulerSessionKey, canonical),
  })

  async function execute(command: AssignmentCommand): Promise<ApiEnvelope<SchedulerSession> | null> {
    if (pending.current) return null
    pending.current = true
    try {
      return await mutation.mutateAsync(command)
    } finally {
      pending.current = false
    }
  }

  return {
    clearError: mutation.reset,
    error: mutation.error,
    execute,
    isPending: mutation.isPending,
  }
}
