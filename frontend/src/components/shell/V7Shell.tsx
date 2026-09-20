import {
  CalendarDots,
  FileText,
  SquaresFour,
} from '@phosphor-icons/react'
import {
  type ComponentPropsWithoutRef,
  type ReactNode,
  useEffect,
  useState,
} from 'react'
import { Link } from 'react-router-dom'
import styles from './AppShell.module.css'
import {
  connectionStatusLabel,
  draftStatusLabel,
  normalizePathname,
  sourceStatusLabel,
  WORKFLOW_STEPS,
  workflowState,
  type ShellWorkspaceState,
} from './shellModel'

const WORKSPACE_ITEMS = [
  { icon: SquaresFour, label: 'Overview', path: '/' },
  { icon: CalendarDots, label: 'Schedule', path: '/schedule/resolve' },
  { icon: FileText, label: 'Source Data', path: '/students' },
] as const

const TEXT_SIZES = ['small', 'standard', 'large'] as const
const TEXT_SIZE_LABELS = ['90%', '100%', '115%'] as const
type TextSize = typeof TEXT_SIZES[number]

function storedTextSize(): TextSize {
  try {
    const value = localStorage.getItem('music-lesson-scheduler-text-size')
    return TEXT_SIZES.includes(value as TextSize) ? value as TextSize : 'standard'
  } catch {
    return 'standard'
  }
}

function TextSizeControls() {
  const [size, setSize] = useState<TextSize>(storedTextSize)
  const index = TEXT_SIZES.indexOf(size)

  useEffect(() => {
    document.documentElement.dataset.textSize = size
    try { localStorage.setItem('music-lesson-scheduler-text-size', size) } catch { /* private storage is optional */ }
  }, [size])

  useEffect(() => {
    const changeSize = (direction: 'decrease' | 'increase' | 'reset') => {
      if (direction === 'reset') setSize('standard')
      else if (direction === 'decrease') setSize(TEXT_SIZES[Math.max(0, index - 1)])
      else setSize(TEXT_SIZES[Math.min(TEXT_SIZES.length - 1, index + 1)])
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!event.metaKey) return
      if (event.key === '0') changeSize('reset')
      else if (event.key === '-' || event.key === '_') changeSize('decrease')
      else if (event.key === '=' || event.key === '+') changeSize('increase')
      else return
      event.preventDefault()
    }
    const handleNativeCommand = (event: Event) => {
      const direction = (event as CustomEvent).detail
      if (direction === 'decrease' || direction === 'increase' || direction === 'reset') changeSize(direction)
    }
    window.addEventListener('keydown', handleKeyDown, true)
    window.addEventListener('pi:text-size', handleNativeCommand)
    return () => {
      window.removeEventListener('keydown', handleKeyDown, true)
      window.removeEventListener('pi:text-size', handleNativeCommand)
    }
  }, [index])

  return (
    <span aria-label="Interface text size" className={styles.textSizeControls} role="group">
      <button aria-label="Decrease interface text size" disabled={index === 0} onClick={() => setSize(TEXT_SIZES[Math.max(0, index - 1)])} title="Smaller text (⌘−)" type="button">A−</button>
      <button aria-label="Reset interface text size" className={styles.textSizeValue} disabled={index === 1} onClick={() => setSize('standard')} title="Standard text size (⌘0)" type="button">{TEXT_SIZE_LABELS[index]}</button>
      <button aria-label="Increase interface text size" disabled={index === TEXT_SIZES.length - 1} onClick={() => setSize(TEXT_SIZES[Math.min(TEXT_SIZES.length - 1, index + 1)])} title="Larger text (⌘+)" type="button">A+</button>
    </span>
  )
}

function activeWorkspacePath(pathname: string) {
  const normalized = normalizePathname(pathname)
  if (normalized === '/schedule' || normalized.startsWith('/schedule/')) return '/schedule/resolve'
  if (normalized === '/students' || normalized.startsWith('/students/')) return '/students'
  return WORKSPACE_ITEMS.find((item) => item.path === normalized)?.path
}

export function AppRoot({ children }: { children: ReactNode }) {
  return <div className={styles.app}>{children}</div>
}

export function BrandBlock() {
  return (
    <div className={styles.brand} title="AI-Assisted One-to-One Music Lesson Scheduling">
      <span aria-hidden="true" className={styles.mark}>1:1</span>
      <span className={styles.brandText}>
        <strong>AI-Assisted</strong>
        <small>ONE-TO-ONE MUSIC LESSON SCHEDULING</small>
      </span>
    </div>
  )
}

export function WorkspaceNavigation({ pathname }: { pathname: string }) {
  const activePath = activeWorkspacePath(pathname)
  return (
    <div className={styles.railSection}>
      <p className={styles.railLabel}>WORKSPACE</p>
      <nav aria-label="Workspace">
        <ul className={styles.navList}>
          {WORKSPACE_ITEMS.map(({ icon: Icon, label, path }) => (
            <li key={path}>
              <Link
                aria-current={path === activePath ? 'page' : undefined}
                className={styles.navLink}
                to={path}
              >
                <Icon aria-hidden="true" data-testid="workspace-icon" size={15} weight="regular" />
                <span>{label}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  )
}

export function WorkflowStepper({
  activeStage,
  pathname,
}: {
  activeStage: ShellWorkspaceState['activeStage']
  pathname: string
}) {
  return (
    <div className={styles.workflowSection}>
      <p className={styles.railLabel}>WORKFLOW</p>
      <nav aria-label="Workflow">
        <ol className={styles.workflowList}>
          {WORKFLOW_STEPS.map((step, index) => {
            const state = workflowState(index, pathname, activeStage)
            return (
              <li className={styles.workflowItem} key={step.path}>
                <Link
                  aria-current={state === 'current' ? 'step' : undefined}
                  className={styles.workflowLink}
                  data-state={state}
                  to={step.path}
                >
                  <span className={styles.workflowNumber}>{String(index + 1).padStart(2, '0')}</span>
                  <span>{step.label}</span>
                </Link>
              </li>
            )
          })}
        </ol>
      </nav>
    </div>
  )
}

export function LocalStatus({ workspace }: { workspace: ShellWorkspaceState }) {
  const active = workspace.connection === 'connected'
  const title = active ? 'Local workspace active' : workspace.connection === 'connecting'
    ? 'Local workspace connecting'
    : 'Local workspace unavailable'
  const draft = workspace.connection === 'connecting'
    ? 'Draft pending'
    : workspace.connection === 'disconnected'
      ? 'Draft status unavailable'
      : workspace.draft.saveStatus === 'failed'
        ? 'Draft save failed'
        : workspace.draft.saveStatus === 'degraded'
          ? 'Draft saved with warning'
          : 'Draft saved'
  return (
    <div className={styles.localStatus}>
      <strong>{title}</strong>
      <span>Stored locally · {draft}</span>
    </div>
  )
}

export function WorkspaceRail({ pathname, workspace }: { pathname: string; workspace: ShellWorkspaceState }) {
  return (
    <aside className={styles.rail}>
      <BrandBlock />
      <WorkspaceNavigation pathname={pathname} />
      <WorkflowStepper activeStage={workspace.activeStage} pathname={pathname} />
      <LocalStatus workspace={workspace} />
    </aside>
  )
}

export function WorkspaceCanvas({ children }: { children: ReactNode }) {
  return <main className={styles.workspace}>{children}</main>
}

export function V7Panel({ className, ...props }: ComponentPropsWithoutRef<'section'>) {
  return <section className={[styles.panel, className].filter(Boolean).join(' ')} {...props} />
}

export function StatusFooter({
  busy = false,
  onRedo,
  onUndo,
  supportsHistory,
  workspace,
}: {
  busy?: boolean
  onRedo?: () => void
  onUndo?: () => void
  supportsHistory: boolean
  workspace: ShellWorkspaceState
}) {
  return (
    <footer className={styles.footer}>
      <span className={styles.footerStatus}>
        <span>{sourceStatusLabel(workspace.source)}</span>
        <span>{draftStatusLabel(workspace)}</span>
        <span>{connectionStatusLabel(workspace.connection)}</span>
      </span>
      <span className={styles.footerActions}>
        <TextSizeControls />
        {supportsHistory ? (
          <span className={styles.historyActions}>
          <button disabled={busy || workspace.connection !== 'connected' || !workspace.draft.canUndo || !onUndo} onClick={onUndo} type="button">Undo</button>
          <button disabled={busy || workspace.connection !== 'connected' || !workspace.draft.canRedo || !onRedo} onClick={onRedo} type="button">Redo</button>
          </span>
        ) : null}
      </span>
    </footer>
  )
}
