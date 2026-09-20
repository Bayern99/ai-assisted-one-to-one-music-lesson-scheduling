import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { apiRequest, type ApiEnvelope } from '../../api/client'
import {
  schedulerSessionKey,
  useSchedulerSession,
  type SchedulerSession,
} from '../../features/scheduler/api'
import {
  StatusBanner,
  type StatusBannerProps,
} from '../common/StatusBanner'
import styles from './AppShell.module.css'
import {
  deriveShellWorkspaceState,
  normalizePathname,
  type ShellWorkspaceState,
} from './shellModel'
import {
  AppRoot,
  StatusFooter,
  WorkspaceCanvas,
  WorkspaceRail,
} from './V7Shell'

export type { ShellWorkspaceState } from './shellModel'

export interface AppShellProps {
  children?: ReactNode
  onRedo?: () => void
  onUndo?: () => void
  status?: StatusBannerProps
  workspace?: ShellWorkspaceState
}

function AppShellView({
  children,
  historyBusy = false,
  onRedo,
  onUndo,
  status,
  workspace,
}: Omit<AppShellProps, 'workspace'> & {
  historyBusy?: boolean
  workspace: ShellWorkspaceState
}) {
  const { pathname } = useLocation()
  const normalizedPathname = normalizePathname(pathname)
  const supportsHistory = normalizedPathname === '/schedule/resolve'
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>('[data-workspace-heading]')?.focus()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [normalizedPathname])
  return (
    <AppRoot>
      <WorkspaceRail pathname={normalizedPathname} workspace={workspace} />
      <section className={styles.mainFrame}>
        <div className={styles.workspaceFrame}>
          <div className={styles.statusSlot}>
            <StatusBanner {...status} />
          </div>
          <WorkspaceCanvas>{children ?? <Outlet />}</WorkspaceCanvas>
        </div>
        <StatusFooter
          busy={historyBusy}
          onRedo={onRedo}
          onUndo={onUndo}
          supportsHistory={supportsHistory}
          workspace={workspace}
        />
      </section>
    </AppRoot>
  )
}

function LiveAppShell(props: Omit<AppShellProps, 'workspace'>) {
  const queryClient = useQueryClient()
  const sessionQuery = useSchedulerSession()
  const historyMutation = useMutation<
    ApiEnvelope<SchedulerSession>,
    Error,
    'undo' | 'redo'
  >({
    mutationFn: (kind) => {
      const version = sessionQuery.data?.workspace_version
      if (!version) throw new Error('The scheduler workspace version is unavailable.')
      return apiRequest<SchedulerSession>(`/api/scheduler/draft/${kind}`, {
        method: 'POST',
        body: JSON.stringify({ expected_version: version }),
      })
    },
    onSuccess: (canonical) => {
      queryClient.setQueryData(schedulerSessionKey, canonical)
    },
  })

  const workspace = deriveShellWorkspaceState({
    envelope: sessionQuery.data,
    isError: sessionQuery.isError,
  })
  const historyStatus: StatusBannerProps | undefined = historyMutation.isError
    ? {
        kind: 'save',
        message: historyMutation.error.message,
        tone: 'error',
      }
    : undefined

  return (
    <AppShellView
      {...props}
      historyBusy={historyMutation.isPending}
      onRedo={() => historyMutation.mutate('redo')}
      onUndo={() => historyMutation.mutate('undo')}
      status={props.status ?? historyStatus}
      workspace={workspace}
    />
  )
}

export function AppShell({ workspace, ...props }: AppShellProps) {
  if (workspace) return <AppShellView {...props} workspace={workspace} />
  return <LiveAppShell {...props} />
}
