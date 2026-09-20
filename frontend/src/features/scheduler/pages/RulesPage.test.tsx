import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { RulesPage } from './RulesPage'

const session = {
  active_stage: 'rules', assignments: [], issues: [],
  rooms: [{ id: 'R1' }, { id: 'R2' }], instructors: ['Instructor 0008', 'Instructor 0009'],
  draft: { dirty: false, can_undo: false, can_redo: false },
  metrics: { assigned: 0, unresolved: 0, source_gaps: 0 }, warnings: [],
  source_preferences: [{
    instructor: 'Instructor 0008', request_count: 2,
    room_variants: [['R2'], ['R1', 'UnknownSource']], unknown_rooms: ['UnknownSource'],
  }],
}

const canonicalRules = {
  priorities: { Piano: { Piano: 10, Voice: 5 } },
  constraints: {
    time_range: { start: '08:00', end: '23:00' },
    min_break_between_lessons: 10,
    enforce_instructor_blocks: true,
    room_stability_weight: 8,
  },
  room_types: { R1: ['Piano'] },
  instructor_preferred_rooms: { 'Instructor 0008': ['R1', 'LegacyRoom'] },
  instructor_priority: { 'Instructor 0008': 6 },
  instructor_time_change_eligibility: { 'Instructor 0009': false },
  installation_extension: { keep: true },
}

const rulesView = {
  rules: canonicalRules,
  source_path: 'data/scheduling_rules.json',
  trace: {
    ignored_top_level_keys: ['installation_extension'],
    hidden_ui_fields: ['constraints.room_stability_weight'],
  },
}

const envelope = (data: unknown, version = 'workspace-v1', warnings: string[] = []) => ({
  data, workspace_version: version, warnings, error: null,
})

let rulesBodies: unknown[] = []

const server = setupServer(
  http.get('/api/scheduler/session', () => HttpResponse.json(envelope(session))),
  http.get('/api/scheduler/rules', () => HttpResponse.json(envelope(rulesView))),
  http.get('/api/scheduler/rules/reconciliation', () => HttpResponse.json(envelope({
    source_row_count: 4,
    assignment_count: 4,
    matches: [{ assignment_id: 'a1', details: 'Instructor 0008 w/ 1001 @ 9:00' }],
    missing: [{ Instructor: 'Instructor 0009', Student: 'Student Two', Day: 'Tuesday', Time: '11:00-12:00' }],
    phantom: [{ assignment_id: 'a3', details: 'No source found for Teacher C @ 13:00' }],
  }))),
  http.put('/api/scheduler/rules', async ({ request }) => {
    rulesBodies.push(await request.json())
    return HttpResponse.json(envelope(rulesView, 'workspace-v2', ['Canonical scheduling rules saved.']))
  }),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => { cleanup(); server.resetHandlers(); rulesBodies = [] })
afterAll(() => server.close())

function renderPage(path = '/schedule/rules/constraints') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const router = createMemoryRouter([{ path: '/schedule/rules/:section?', element: <RulesPage /> }], {
    initialEntries: [path],
  })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return { client }
}

describe('RulesPage', () => {
  it('presents canonical rules as four bounded deep-linked workspaces with no lecture editor', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Scheduling Rules', level: 1 })).toBeVisible()
    const navigation = screen.getByRole('navigation', { name: 'Rules sections' })
    expect(within(navigation).getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual([
      '/schedule/rules/constraints',
      '/schedule/rules/priorities',
      '/schedule/rules/resolution',
      '/schedule/rules/rooms',
    ])
    expect(within(navigation).getByRole('link', { name: /^Constraints/ })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByLabelText('Earliest lesson start')).toHaveValue('08:00')
    expect(screen.getByText('…/scheduling_rules.json')).toHaveAttribute('title', 'data/scheduling_rules.json')
    expect(screen.queryByText('Lecture Lock Register')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Lecture CSV/i)).not.toBeInTheDocument()
  })

  it('controls the time-change proposal pool with neutral instructor eligibility labels', async () => {
    const user = userEvent.setup()
    renderPage('/schedule/rules/resolution')

    expect(await screen.findByText('Checked: may move to a different day or time. Unchecked: keep the original day and time.')).toBeVisible()
    const teacherA = screen.getByRole('checkbox', { name: 'Allow time changes for Instructor 0008' })
    const teacherB = screen.getByRole('checkbox', { name: 'Allow time changes for Instructor 0009' })
    expect(teacherA).toBeChecked()
    expect(teacherB).not.toBeChecked()
    expect(screen.getByText('Keep original day and time')).toBeVisible()

    await user.click(teacherA)
    await user.click(teacherB)
    await user.click(screen.getByRole('button', { name: 'Save Rules' }))

    await waitFor(() => expect(rulesBodies).toHaveLength(1))
    expect(rulesBodies[0]).toMatchObject({
      rules: {
        instructor_time_change_eligibility: {
          'Instructor 0008': false,
          'Instructor 0009': true,
        },
      },
    })
  })

  it('retries a rules save when only an unrelated workspace file changed', async () => {
    const user = userEvent.setup()
    let reads = 0
    let writes = 0
    server.use(
      http.get('/api/scheduler/rules', () => {
        reads += 1
        return HttpResponse.json(envelope(rulesView, reads === 1 ? 'workspace-v1' : 'workspace-v2'))
      }),
      http.put('/api/scheduler/rules', async ({ request }) => {
        rulesBodies.push(await request.json())
        writes += 1
        if (writes === 1) {
          return HttpResponse.json({
            data: null, workspace_version: 'workspace-v2', warnings: [],
            error: {
              code: 'WORKSPACE_CHANGED',
              message: 'Workspace changed; reload before saving',
              details: { expected: 'workspace-v1', current: 'workspace-v2' },
            },
          }, { status: 409 })
        }
        return HttpResponse.json(envelope(rulesView, 'workspace-v3'))
      }),
    )
    renderPage('/schedule/rules/resolution')

    await user.click(await screen.findByRole('checkbox', { name: 'Allow time changes for Instructor 0008' }))
    await user.click(screen.getByRole('button', { name: 'Save Rules' }))

    expect(await screen.findByText('Scheduling Rules Saved.')).toBeVisible()
    expect(rulesBodies).toHaveLength(2)
    expect(rulesBodies).toMatchObject([
      { expected_version: 'workspace-v1' },
      { expected_version: 'workspace-v2' },
    ])
    expect(screen.queryByText('workspace-v1')).not.toBeInTheDocument()
    expect(screen.queryByText('workspace-v2')).not.toBeInTheDocument()
  })

  it('enforces bounded priority inputs and uses the canonical instructor default of five', async () => {
    const user = userEvent.setup()
    renderPage('/schedule/rules/priorities')

    const matrix = await screen.findByLabelText('Piano room priority for Voice')
    expect(matrix).toHaveAttribute('min', '0')
    expect(matrix).toHaveAttribute('max', '10')
    const teacherA = await screen.findByLabelText('Priority for Instructor 0008')
    expect(teacherA).toHaveValue(6)
    expect(teacherA).toHaveAttribute('min', '1')
    expect(teacherA).toHaveAttribute('max', '10')

    await user.click(screen.getByRole('button', { name: /Instructor 0009/ }))
    expect(screen.getByLabelText('Priority for Instructor 0009')).toHaveValue(5)
  })

  it('keeps imported request variants read-only and preserves unknown saved rooms', async () => {
    const user = userEvent.setup()
    renderPage('/schedule/rules/rooms')

    expect(await screen.findByText('R1 + UnknownSource')).toBeVisible()
    expect(screen.getByText('Unknown source rooms: UnknownSource')).toBeVisible()
    expect(screen.getByText('Unknown saved rooms preserved: LegacyRoom')).toBeVisible()
    const r1 = screen.getByRole('checkbox', { name: 'Additional room R1 for Instructor 0008' })
    const r2 = screen.getByRole('checkbox', { name: 'Additional room R2 for Instructor 0008' })
    expect(r1).toBeChecked()
    expect(r2).not.toBeChecked()

    await user.click(r1)
    await user.click(r2)
    await user.click(screen.getByRole('button', { name: 'Save Rules' }))

    await waitFor(() => expect(rulesBodies).toHaveLength(1))
    const body = rulesBodies[0] as { rules: { instructor_preferred_rooms: Record<string, string[]> } }
    expect(body.rules.instructor_preferred_rooms['Instructor 0008']).toEqual(['R2', 'LegacyRoom'])
    expect(body.rules.instructor_preferred_rooms['Instructor 0008']).not.toContain('UnknownSource')
  })

  it('keeps one shared draft across sections and preserves compatibility keys in the full save body', async () => {
    const user = userEvent.setup()
    renderPage()

    const start = await screen.findByLabelText('Earliest lesson start')
    await user.clear(start)
    await user.type(start, '07:30')
    await user.click(screen.getByRole('link', { name: /^Priorities/ }))
    const pianoPriority = await screen.findByLabelText('Piano room priority for Voice')
    await user.clear(pianoPriority)
    await user.type(pianoPriority, '7')
    await user.click(screen.getByRole('button', { name: 'Save Rules' }))

    await waitFor(() => expect(rulesBodies).toHaveLength(1))
    expect(rulesBodies[0]).toMatchObject({
      expected_version: 'workspace-v1',
      rules: {
        constraints: { time_range: { start: '07:30', end: '23:00' } },
        priorities: { Piano: { Piano: 10, Voice: 7 } },
        installation_extension: { keep: true },
      },
    })
    expect(screen.queryByRole('textbox', { name: /JSON/i })).not.toBeInTheDocument()
  })

  it('retains the draft after a version conflict and confirms before canonical reload', async () => {
    const user = userEvent.setup()
    server.use(http.put('/api/scheduler/rules', () => HttpResponse.json({
      data: null, workspace_version: 'workspace-v2', warnings: [],
      error: { code: 'WORKSPACE_CHANGED', message: 'Workspace changed on disk' },
    }, { status: 409 })))
    renderPage()

    const start = await screen.findByLabelText('Earliest lesson start')
    await user.clear(start)
    await user.type(start, '07:30')
    await user.click(screen.getByRole('button', { name: 'Save Rules' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Workspace is still changing. Your draft was kept')
    expect(start).toHaveValue('07:30')
    await user.click(screen.getByRole('button', { name: 'Reload Rules' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Discard Unsaved Rule Changes')
    await user.keyboard('{Escape}')
    expect(start).toHaveValue('07:30')
  })

  it('makes cached controls read-only while canonical rules cannot be refreshed', async () => {
    const { client } = renderPage()
    const start = await screen.findByLabelText('Earliest lesson start')
    server.use(http.get('/api/scheduler/rules', () => HttpResponse.json({ detail: 'offline' }, { status: 503 })))

    await client.invalidateQueries({ queryKey: ['scheduler-rules'] })

    expect(await screen.findByRole('button', { name: 'Retry Rules Workspace' })).toBeVisible()
    expect(start).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save Rules' })).toBeDisabled()
  })

  it('runs the persisted data integrity check in a bounded diagnostic dialog', async () => {
    const user = userEvent.setup()
    renderPage('/schedule/rules/priorities')

    await screen.findByRole('heading', { name: 'Scheduling Rules' })
    await user.click(screen.getByRole('button', { name: 'Check Data Integrity' }))

    const dialog = await screen.findByRole('dialog', { name: 'Data Integrity Check' })
    expect(within(dialog).getByText('Student Two')).toBeVisible()
    expect(within(dialog).getByText('a3')).toBeVisible()
    expect(within(dialog).getByText('2', { selector: 'dd' })).toBeVisible()
    expect(within(dialog).getByText(/does not change the schedule/)).toBeVisible()
  })
})
