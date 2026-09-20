import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { DashboardPage } from './DashboardPage'

const dashboard = {
  continue_action: {
    page_title: 'Smart Scheduler',
    continue_path: '/schedule/resolve',
    continue_label: 'Continue schedule resolution',
  },
  counts: { students: 82, instructors: 19, rooms: 12, bookings: 146 },
  session: { active_step: 'conflicts', round_committed: false, draft_dirty: true },
  workflow_state: { current_phase: 'scheduling', semester: '2026 Spring' },
  health: {
    status: 'warning',
    checks: [{ name: 'Data Files Location', status: 'warning', detail: 'Review source files' }],
    recommendations: ['Check source files.'],
  },
  semester_config: {
    start_date: '2026-02-24',
    last_day: '2026-05-29',
    jury_start: '2026-05-31',
    jury_end: '2026-06-01',
  },
}

const server = setupServer(
  http.get('/api/dashboard', () =>
    HttpResponse.json({ data: dashboard, workspace_version: 'v1', warnings: [], error: null }),
  ),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
})
afterAll(() => server.close())

function renderDashboard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter([{ path: '/', element: <DashboardPage /> }])
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('DashboardPage', () => {
  it('shows a layout-matched loading status until the dashboard resolves', async () => {
    let resolveDashboard: ((response: Response) => void) | undefined
    const pendingDashboard = new Promise<Response>((resolve) => { resolveDashboard = resolve })
    server.use(http.get('/api/dashboard', () => pendingDashboard))
    renderDashboard()

    expect(screen.getByRole('status', { name: 'Loading dashboard' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Continue/ })).not.toBeInTheDocument()

    resolveDashboard?.(HttpResponse.json({ data: dashboard, workspace_version: 'v1', warnings: [], error: null }))
    expect(await screen.findByRole('link', { name: 'Continue schedule resolution' })).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Loading dashboard' })).not.toBeInTheDocument()
  })

  it('places the real continuation action before workspace health', async () => {
    renderDashboard()

    const link = await screen.findByRole('link', { name: 'Continue schedule resolution' })
    expect(link).toHaveAttribute('href', '/schedule/resolve')
    const summary = screen.getByRole('heading', { name: 'Active Workspace' })
    expect(summary.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Recent Activity' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Attention Required' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Workflow Continuation' })).toBeInTheDocument()
    expect(screen.getByText('Status: Attention')).toBeInTheDocument()
    expect(within(screen.getByRole('group', { name: 'Workspace counts' })).getByText('82')).toBeInTheDocument()
    expect(screen.getByText('Current Stage')).toBeInTheDocument()
    expect(screen.getByText('Scheduling')).toBeInTheDocument()
    expect(screen.getByText('Resolve Schedule')).toBeInTheDocument()
  })

  it('translates implementation health checks and legacy workflow steps into product language', async () => {
    server.use(http.get('/api/dashboard', () => HttpResponse.json({
      data: {
        ...dashboard,
        session: { ...dashboard.session, active_step: 'Step 4: Interactive Editor' },
        health: {
          status: 'ok',
          checks: [
            { name: 'Data Directory', status: 'OK', detail: 'data/ exists and writable' },
            { name: 'Import: Data Processing', status: 'OK', detail: 'pandas available' },
            { name: 'Import: Excel Reading', status: 'OK', detail: 'openpyxl available' },
            { name: 'Import: Excel Writing', status: 'OK', detail: 'xlsxwriter available' },
            { name: 'Temp File Leaks', status: 'OK', detail: 'No orphaned temp files' },
          ],
          recommendations: ['Install pandas before continuing.'],
        },
      },
      workspace_version: 'v1', warnings: [], error: null,
    })))
    renderDashboard()

    expect(await screen.findByText('Workspace Storage')).toBeInTheDocument()
    expect(screen.getByText('Workbook Processing')).toBeInTheDocument()
    expect(screen.getByText('Workbook Reading')).toBeInTheDocument()
    expect(screen.getByText('Workbook Export')).toBeInTheDocument()
    expect(screen.getByText('Temporary Files')).toBeInTheDocument()
    expect(screen.getByText('Resolve Schedule')).toBeInTheDocument()
    expect(screen.getByText('Status: Ready')).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/pandas|openpyxl|xlsxwriter|Step 4: Interactive Editor/i)
  })

  it('renders an honest zero summary without inventing a continuation action', async () => {
    server.use(
      http.get('/api/dashboard', () => HttpResponse.json({
        data: {
          continue_action: null,
          counts: { students: 0, instructors: 0, rooms: 0, bookings: 0 },
          session: { active_step: null, round_committed: false, draft_dirty: false },
          workflow_state: {},
          health: {},
          semester_config: dashboard.semester_config,
        },
        workspace_version: 'empty-v1',
        warnings: [],
        error: null,
      })),
    )
    renderDashboard()

    const counts = await screen.findByRole('group', { name: 'Workspace counts' })
    expect(within(counts).getAllByText('0')).toHaveLength(4)
    expect(screen.queryByRole('link', { name: /Continue/ })).not.toBeInTheDocument()
    expect(screen.getByText('No workspace checks were reported.')).toBeInTheDocument()
    const attention = screen.getByRole('heading', { name: 'No Attention Required' }).closest('section')
    expect(attention).toHaveAttribute('data-state', 'clear')
    expect(screen.queryByRole('heading', { name: 'Attention Required' })).not.toBeInTheDocument()
    expect(screen.getByText('No workflow state has been recorded.')).toBeInTheDocument()
    expect(screen.getByText('Not Selected')).toBeInTheDocument()
    expect(screen.getByText('None')).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/\d+%/)
  })

  it('shows a persistent error and recovers through Retry', async () => {
    const user = userEvent.setup()
    let attempts = 0
    server.use(
      http.get('/api/dashboard', () => {
        attempts += 1
        return attempts === 1 ? HttpResponse.json(
          { data: null, workspace_version: null, warnings: [], error: { code: 'FAILED', message: 'Dashboard unavailable' } },
          { status: 500 },
        ) : HttpResponse.json({ data: dashboard, workspace_version: 'v1', warnings: [], error: null })
      }),
    )
    renderDashboard()

    expect(await screen.findByRole('alert')).toHaveTextContent('Dashboard unavailable')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('link', { name: 'Continue schedule resolution' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('restores the versioned semester calendar without expanding the overview into a long form', async () => {
    const user = userEvent.setup()
    let command: Record<string, unknown> | null = null
    server.use(http.patch('/api/dashboard/semester-config', async ({ request }) => {
      command = await request.json() as Record<string, unknown>
      return HttpResponse.json({
        data: {
          start_date: command.start_date,
          last_day: command.last_day,
          jury_start: command.jury_start,
          jury_end: command.jury_end,
        },
        workspace_version: 'v2', warnings: [], error: null,
      })
    }))
    renderDashboard()

    expect(await screen.findByRole('heading', { name: 'Semester Overview' })).toBeInTheDocument()
    expect(screen.getByText('2026-05-29')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit Dates' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit Semester Dates' })
    fireEvent.change(within(dialog).getByLabelText('Classes Begin'), { target: { value: '2026-02-25' } })
    await user.click(within(dialog).getByRole('button', { name: 'Save Dates' }))

    await waitFor(() => expect(command).toMatchObject({ expected_version: 'v1', start_date: '2026-02-25' }))
  })
})
