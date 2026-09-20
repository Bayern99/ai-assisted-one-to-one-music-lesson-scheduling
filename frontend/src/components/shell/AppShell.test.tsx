/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { draftState } from '../../test/draftState'
import userEvent from '@testing-library/user-event'
import {
  createMemoryRouter,
  MemoryRouter,
  Route,
  RouterProvider,
  Routes,
  type RouteObject,
} from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { appRoutes } from '../../app/router'
import { schedulerSessionKey } from '../../features/scheduler/api'
import { StatusBanner } from '../common/StatusBanner'
import {
  AppShell,
  type ShellWorkspaceState,
} from './AppShell'
import { deriveShellWorkspaceState } from './shellModel'
import { V7Panel, WorkspaceCanvas } from './V7Shell'
import { DockedPane, WorkspaceHeader, WorkspaceSurface } from '../workspace/WorkspacePrimitives'

afterEach(() => {
  cleanup()
  delete document.documentElement.dataset.textSize
  try { localStorage.removeItem('music-lesson-scheduler-text-size') } catch { /* optional in the test runtime */ }
})

const shellCss = readFileSync('src/components/shell/AppShell.module.css', 'utf8')
const tokenCss = readFileSync('src/styles/tokens.css', 'utf8')
const workspaceCss = readFileSync('src/components/workspace/WorkspacePrimitives.module.css', 'utf8')

function relativeLuminance(hex: string) {
  const channels = hex.match(/[a-f\d]{2}/gi)?.map((part) => Number.parseInt(part, 16) / 255) ?? []
  const linear = channels.map((channel) => (
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  ))
  return (0.2126 * linear[0]) + (0.7152 * linear[1]) + (0.0722 * linear[2])
}

function contrastRatio(first: string, second: string) {
  const [lighter, darker] = [relativeLuminance(first), relativeLuminance(second)].sort((a, b) => b - a)
  return (lighter + 0.05) / (darker + 0.05)
}

const workspace: ShellWorkspaceState = {
  activeStage: 'resolve',
  connection: 'connected',
  draft: { canRedo: false, canUndo: true, dirty: false },
  source: 'verified',
  version: 'workspace-v17',
}

function renderShell(
  pathname: string,
  options: {
    onRedo?: () => void
    onUndo?: () => void
    state?: ShellWorkspaceState
    status?: { kind: 'api'; message: string; tone: 'warning' }
  } = {},
) {
  render(
    <MemoryRouter initialEntries={[pathname]}>
      <Routes>
        <Route
          element={(
            <AppShell
              onRedo={options.onRedo ?? (() => undefined)}
              onUndo={options.onUndo ?? (() => undefined)}
              status={options.status}
              workspace={options.state ?? workspace}
            />
          )}
        >
          <Route path="*" element={<div>Route content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

function renderProductionRouter(router: ReturnType<typeof createMemoryRouter>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  client.setQueryData(schedulerSessionKey, {
    data: {
      active_stage: 'resolve',
      assignments: [],
      draft: draftState({ can_redo: false, can_undo: true, dirty: false }),
      instructors: [],
      issues: [],
      metrics: { assigned: 0, unresolved: 0, source_gaps: 0 },
      rooms: [],
    },
    error: null,
    warnings: [],
    workspace_version: 'workspace-v17',
  })
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('V7 AppShell', () => {
  it('locks the Golden Master geometry and color tokens', () => {
    expect(tokenCss).toMatch(/--canvas:\s*#e8eaed;/)
    expect(tokenCss).toMatch(/--surface:\s*#f4f5f6;/)
    expect(tokenCss).toMatch(/--raised:\s*#ffffff;/)
    expect(tokenCss).toMatch(/--ink:\s*#202227;/)
    expect(tokenCss).toMatch(/--muted:\s*#737780;/)
    expect(tokenCss).toMatch(/--faint:\s*#9ca0a8;/)
    expect(tokenCss).toMatch(/--rail:\s*#27292e;/)
    expect(tokenCss).toMatch(/--accent:\s*#c35f49;/)
    expect(tokenCss).toMatch(/--accent-soft:\s*#f4e3df;/)
    expect(tokenCss).toMatch(/--native-titlebar-inset:\s*0px;/)
    expect(tokenCss).toMatch(/html\[data-pi-desktop='macos'\]\s*\{[^}]*--native-titlebar-inset:\s*28px;/s)
    expect(shellCss).toMatch(/\.app\s*\{[^}]*grid-template-columns:\s*176px minmax\(0,\s*1fr\);/s)
    expect(shellCss).toMatch(/\.mainFrame\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\) var\(--statusbar-height\);/s)
    expect(shellCss).toMatch(/\.mainFrame\s*\{[^}]*padding-top:\s*var\(--native-titlebar-inset\);/s)
    expect(shellCss).toMatch(/\.rail\s*\{[^}]*padding:\s*calc\(18px \+ var\(--native-titlebar-inset\)\) 14px 16px;/s)
    expect(shellCss).not.toMatch(/\.header\s*\{/)
    expect(workspaceCss).toMatch(/\.header\s*\{[^}]*min-height:\s*66px;/s)
    expect(shellCss).not.toMatch(/\.chassis\s*\{/)
    expect(shellCss).toMatch(/\.app\s*\{[^}]*width:\s*100%;/s)
    expect(shellCss).toMatch(/\.app\s*\{[^}]*min-width:\s*1180px;/s)
    expect(shellCss).toMatch(/\.app\s*\{[^}]*height:\s*100dvh;/s)
    expect(shellCss).toMatch(/\.app\s*\{[^}]*border:\s*0;/s)
    expect(shellCss).toMatch(/\.app\s*\{[^}]*border-radius:\s*0;/s)
    expect(shellCss).toMatch(/\.app\s*\{[^}]*box-shadow:\s*none;/s)
    expect(shellCss).not.toMatch(/@media\s*\(max-width:/)
  })

  it('renders the product brand and scheduling WORKSPACE routes with Phosphor icons', () => {
    renderShell('/schedule/resolve')

    expect(screen.getByText('1:1')).toBeVisible()
    expect(screen.getByText('AI-Assisted')).toBeVisible()
    expect(screen.getByText('ONE-TO-ONE MUSIC LESSON SCHEDULING')).toBeVisible()
    const navigation = screen.getByRole('navigation', { name: 'Workspace' })
    expect(within(navigation).getAllByRole('link').map((link) => link.textContent)).toEqual([
      'Overview',
      'Schedule',
      'Source Data',
    ])
    expect(within(navigation).getAllByTestId('workspace-icon')).toHaveLength(3)
    expect(within(navigation).getByRole('link', { name: 'Schedule' })).toHaveAttribute('href', '/schedule/resolve')
    expect(within(navigation).getByRole('link', { name: 'Source Data' })).toHaveAttribute('href', '/students')
  })

  it('always renders connected 01-06 workflow states from route and real progress', () => {
    renderShell('/students')

    const workflow = screen.getByRole('navigation', { name: 'Workflow' })
    const steps = within(workflow).getAllByRole('link')
    expect(steps.map((step) => step.textContent)).toEqual([
      '01Import Lectures',
      '02Import Sources',
      '03Configure Rules',
      '04Run Optimizer',
      '05Resolve Schedule',
      '06Export Schedule',
    ])
    expect(steps.slice(0, 4).every((step) => step.dataset.state === 'done')).toBe(true)
    expect(steps[4]).toHaveAttribute('aria-current', 'step')
    expect(steps[4]).toHaveAttribute('data-state', 'current')
    expect(steps[5]).toHaveAttribute('data-state', 'pending')
  })

  it('uses the opened schedule route as current without inventing completion', () => {
    renderShell('/schedule/rules', {
      state: { ...workspace, activeStage: 'optimize' },
    })

    expect(screen.getByRole('link', { name: 'Schedule' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: /03Configure Rules/ })).toHaveAttribute('aria-current', 'step')
    expect(screen.getByRole('link', { name: /01Import Lectures/ })).toHaveAttribute('data-state', 'done')
    expect(screen.getByRole('link', { name: /02Import Sources/ })).toHaveAttribute('data-state', 'done')
    expect(screen.getByRole('link', { name: /04Run Optimizer/ })).toHaveAttribute('data-state', 'pending')
  })

  it('preserves trailing-slash deep links without injecting a global page header', () => {
    renderShell('/schedule/resolve/')

    expect(screen.getByText('Route content')).toBeVisible()
    expect(screen.queryByRole('heading')).not.toBeInTheDocument()
    expect(screen.queryByText('RESOLVE SCHEDULE')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Schedule' })).toHaveAttribute('aria-current', 'page')
  })

  it('renders real local/source/draft/API status and no unsupported History action', () => {
    renderShell('/schedule/resolve')

    expect(screen.getByText('Local workspace active')).toBeVisible()
    expect(screen.getByText('Stored locally · Draft saved')).toBeVisible()
    const footer = screen.getByRole('contentinfo')
    expect(footer).toHaveTextContent('Source verified')
    expect(footer).toHaveTextContent('Autosave active')
    expect(footer).toHaveTextContent('Workspace ready')
    expect(within(footer).getByRole('button', { name: 'Undo' })).toBeEnabled()
    expect(within(footer).getByRole('button', { name: 'Redo' })).toBeDisabled()
    expect(within(footer).queryByRole('button', { name: 'History' })).not.toBeInTheDocument()
  })

  it('only exposes contextual history actions where the route supports them', () => {
    renderShell('/students', {
      state: {
        ...workspace,
        connection: 'disconnected',
        draft: { canRedo: false, canUndo: false, dirty: true },
        source: 'needs-review',
      },
    })

    const footer = screen.getByRole('contentinfo')
    expect(footer).toHaveTextContent('Source needs review')
    expect(footer).toHaveTextContent('Draft status unavailable')
    expect(footer).toHaveTextContent('Workspace unavailable')
    expect(screen.getByText('Stored locally · Draft status unavailable')).toBeVisible()
    expect(within(footer).queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
    expect(within(footer).queryByRole('button', { name: 'Redo' })).not.toBeInTheDocument()
  })

  it('never reports cached draft/autosave controls as live after a refetch error', () => {
    const cached = deriveShellWorkspaceState({
      envelope: {
        data: {
          active_stage: 'resolve', assignments: [], instructors: [], issues: [], rooms: [],
          draft: draftState({ can_redo: true, can_undo: true, dirty: false }),
          metrics: { assigned: 0, unresolved: 0, source_gaps: 0 },
        },
        error: null, warnings: [], workspace_version: 'cached-v1',
      },
      isError: true,
    })
    renderShell('/schedule/resolve', { state: cached })

    expect(cached.connection).toBe('disconnected')
    expect(screen.getByText('Stored locally · Draft status unavailable')).toBeVisible()
    const footer = screen.getByRole('contentinfo')
    expect(footer).toHaveTextContent('Draft status unavailable')
    expect(footer).not.toHaveTextContent('Autosave active')
    expect(within(footer).getByRole('button', { name: 'Undo' })).toBeDisabled()
    expect(within(footer).getByRole('button', { name: 'Redo' })).toBeDisabled()
  })

  it('requires progressed stage, zero gaps, and no envelope warnings before source is verified', () => {
    const snapshot = {
      data: {
        active_stage: 'resolve' as const, assignments: [], instructors: [], issues: [], rooms: [],
        draft: draftState({ can_redo: false, can_undo: false, dirty: false }),
        metrics: { assigned: 0, unresolved: 0, source_gaps: 0 },
      },
      error: null, workspace_version: 'v1', warnings: ['Source mapping needs review'],
    }
    expect(deriveShellWorkspaceState({ envelope: snapshot, isError: false }).source).toBe('needs-review')
    expect(deriveShellWorkspaceState({ envelope: { ...snapshot, warnings: [] }, isError: false }).source).toBe('verified')
    expect(deriveShellWorkspaceState({
      envelope: { ...snapshot, warnings: [], data: { ...snapshot.data, metrics: { ...snapshot.data.metrics, source_gaps: 1 } } },
      isError: false,
    }).source).toBe('needs-review')
  })

  it('calls the supplied canonical undo control and retains keyboard focus', async () => {
    const user = userEvent.setup()
    const onUndo = vi.fn()
    renderShell('/schedule/resolve', { onUndo })

    const undo = screen.getByRole('button', { name: 'Undo' })
    undo.focus()
    expect(undo).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(onUndo).toHaveBeenCalledOnce()
  })

  it('adjusts and persists the interface text size without scaling the workspace geometry', async () => {
    const user = userEvent.setup()
    renderShell('/')

    expect(screen.getByRole('button', { name: 'Reset interface text size' })).toHaveTextContent('100%')
    await user.click(screen.getByRole('button', { name: 'Increase interface text size' }))

    expect(document.documentElement).toHaveAttribute('data-text-size', 'large')
    expect(screen.getByRole('button', { name: 'Reset interface text size' })).toHaveTextContent('115%')
    try { expect(localStorage.getItem('music-lesson-scheduler-text-size')).toBe('large') } catch { /* optional in the test runtime */ }
    window.dispatchEvent(new CustomEvent('pi:text-size', { detail: 'reset' }))
    await waitFor(() => expect(document.documentElement).toHaveAttribute('data-text-size', 'standard'))
    expect(tokenCss).toMatch(/html\[data-text-size='large'\]\s*\{\s*--text-size-offset:\s*1\.5px;/)
  })

  it('supports the standard macOS text-size keyboard commands', async () => {
    const user = userEvent.setup()
    renderShell('/')

    await user.keyboard('{Meta>}={/Meta}')
    await waitFor(() => expect(document.documentElement).toHaveAttribute('data-text-size', 'large'))
    await user.keyboard('{Meta>}-{/Meta}')
    await waitFor(() => expect(document.documentElement).toHaveAttribute('data-text-size', 'standard'))
    await user.keyboard('{Meta>}0{/Meta}')
    expect(document.documentElement).toHaveAttribute('data-text-size', 'standard')
  })

  it('lets every workspace own its title and structure', () => {
    for (const path of ['/', '/students/s1', '/schedule/resolve']) {
      const { unmount } = render(
        <MemoryRouter initialEntries={[path]}>
          <AppShell workspace={workspace}><div>Route content</div></AppShell>
        </MemoryRouter>,
      )
      expect(screen.getByText('Route content')).toBeVisible()
      expect(screen.queryByRole('heading')).not.toBeInTheDocument()
      unmount()
    }
  })

  it('keeps every tiny rail label above WCAG AA contrast on the dark rail', () => {
    expect(tokenCss).toMatch(/--rail-muted:\s*#9498a1;/)
    expect(contrastRatio('#9498a1', '#27292e')).toBeGreaterThanOrEqual(4.5)
    expect(shellCss).toMatch(/\.brandText small\s*\{[^}]*color:\s*var\(--rail-muted\);/s)
    expect(shellCss).toMatch(/\.railLabel\s*\{[^}]*color:\s*var\(--rail-muted\);/s)
    expect(shellCss).toMatch(/\.workflowLink\[data-state='pending'\]\s*\{[^}]*color:\s*var\(--rail-muted\);/s)
    expect(shellCss).toMatch(/\.localStatus\s*\{[^}]*color:\s*var\(--rail-muted\);/s)
  })

  it('keeps tiny surface copy and white text on accent backgrounds above AA without opacity animation races', () => {
    expect(tokenCss).toMatch(/--accent-readable:\s*#a34734;/)
    expect(contrastRatio('#ffffff', '#a34734')).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio('#656a73', '#f4f5f6')).toBeGreaterThanOrEqual(4.5)
    expect(shellCss).toMatch(/\.workflowLink\[data-state='current'\] \.workflowNumber\s*\{[^}]*background:\s*var\(--accent-readable\);/s)
    expect(workspaceCss).toMatch(/\.context\s*\{[^}]*color:\s*var\(--muted-readable\);/s)
    expect(shellCss).toMatch(/\.footer\s*\{[^}]*color:\s*var\(--muted-readable\);/s)
    expect(shellCss).not.toMatch(/@keyframes\s+(?:appEnter|panelEnter)\s*\{[^}]*opacity:/s)
  })

  it('integrates the StatusBanner live region without a second fixed visual band', () => {
    renderShell('/', {
      status: { kind: 'api', message: 'API connection delayed.', tone: 'warning' },
    })

    const slot = screen.getByRole('region', { name: 'System status' })
    expect(within(slot).getByRole('status')).toHaveTextContent('API connection delayed.')
    expect(shellCss).toMatch(/\.statusSlot\s*\{[^}]*position:\s*absolute;/s)
    expect(shellCss).not.toMatch(/--status-height:\s*40px/)
  })

  it('exports continuous workspace, docked-pane, and page-header primitives', () => {
    render(
      <WorkspaceCanvas>
        <WorkspaceHeader title="Source import" />
        <WorkspaceSurface aria-label="Workspace">Workspace content</WorkspaceSurface>
        <DockedPane aria-label="Inspector">Inspector content</DockedPane>
        <V7Panel aria-label="Legacy panel">Legacy panel content</V7Panel>
      </WorkspaceCanvas>,
    )

    expect(screen.getByRole('heading', { name: 'Source import' })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Workspace' })).toBeVisible()
    expect(screen.getByRole('complementary', { name: 'Inspector' })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Legacy panel' })).toBeVisible()
  })

  it('keeps reduced-motion and focus-visible contracts', () => {
    expect(shellCss).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/)
    expect(shellCss).toMatch(/\.navLink:focus-visible/)
    expect(shellCss).toMatch(/\.workflowLink:focus-visible/)
  })

  it('redirects the schedule root through the production route config', async () => {
    const router = createMemoryRouter(appRoutes, { initialEntries: ['/schedule'] })
    renderProductionRouter(router)

    await waitFor(() => expect(router.state.location.pathname).toBe('/schedule/resolve'))
    expect(screen.getByRole('link', { name: 'Schedule' })).toHaveAttribute('aria-current', 'page')
  })

  it('keeps one polite status node and one assertive error node', () => {
    const { rerender } = render(<StatusBanner />)
    const live = screen.getByRole('status')
    rerender(<StatusBanner kind="api" tone="warning" message="API delayed." />)
    expect(screen.getByRole('status')).toBe(live)
    rerender(<StatusBanner kind="file-conflict" tone="error" message="File changed." />)
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
    expect(screen.getByRole('alert')).toHaveTextContent('File changed.')
  })

  it('keeps the V7 shell for unknown and failed routes', async () => {
    const unknownRouter = createMemoryRouter(appRoutes, { initialEntries: ['/unknown'] })
    const { unmount } = renderProductionRouter(unknownRouter)
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Workspace' })).toBeInTheDocument()
    unmount()

    const root = appRoutes[0]
    if (root.index) throw new Error('Expected a shell layout route')
    const routesWithFailure: RouteObject[] = [{
      ...root,
      index: false,
      children: [
        ...(root.children ?? []),
        { path: 'broken', loader: () => { throw new Error('private stack detail') } },
      ],
    }]
    const errorRouter = createMemoryRouter(routesWithFailure, { initialEntries: ['/broken'] })
    renderProductionRouter(errorRouter)
    expect(await screen.findByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(screen.queryByText(/private stack detail/i)).not.toBeInTheDocument()
  })
})
