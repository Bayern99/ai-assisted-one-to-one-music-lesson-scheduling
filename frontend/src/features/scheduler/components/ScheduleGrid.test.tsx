import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SchedulerSession } from '../api'
import { adaptAssignment } from './AssignmentBlock'
import { clockToMinutes, ScheduleGrid } from './ScheduleGrid'

const assignments: SchedulerSession['assignments'] = [
  { id: 'a', title: 'Morning lesson', type: 'weekly_lesson', resourceId: 'R1', daysOfWeek: [1], startTime: '08:30', endTime: '09:30', extendedProps: { Instructor: 'A. Teacher' } },
  { id: 'b', title: 'Malformed legacy event', resourceId: 10, startTime: 'later' },
]
const rooms: SchedulerSession['rooms'] = [{ id: 'R1' }, { id: 'R2' }]

afterEach(cleanup)

describe('ScheduleGrid', () => {
  it('renders the exact time range as the primary visible assignment label', () => {
    const readable = {
      id: 'readable', title: 'Cello lesson', type: 'weekly_lesson', resourceId: 'R1',
      daysOfWeek: [1], startTime: '09:00', endTime: '10:00', extendedProps: { Instructor: 'A. Teacher' },
    }
    render(<ScheduleGrid activeDay={1} assignments={[readable]} issueMatchIds={new Set()} onDayChange={vi.fn()} onSelect={vi.fn()} rooms={rooms} selectedId={null} />)
    const assignment = screen.getByRole('button', { name: /Cello lesson/ })
    expect(within(assignment).getByText('09:00–10:00').className).toMatch(/assignmentTime/)
  })
  it('maps valid clock strings to presentation minutes without interpreting schedule validity', () => {
    expect(clockToMinutes('08:30')).toBe(510)
    expect(clockToMinutes('2026-03-03T14:15:00')).toBe(855)
    expect(clockToMinutes('later')).toBeNull()
  })

  it('uses the fixed 09-21 V7 scale and keeps out-of-range records discoverable', () => {
    const onSelect = vi.fn()
    render(<ScheduleGrid activeDay={1} assignments={assignments} issueMatchIds={new Set()} onDayChange={vi.fn()} onSelect={onSelect} rooms={rooms} selectedId={null} />)
    const grid = screen.getByTestId('schedule-grid-canvas')
    expect(grid).toHaveAttribute('data-time-start', '09:00')
    expect(grid).toHaveAttribute('data-time-end', '22:00')
    expect(within(grid).getAllByTestId('schedule-hour')).toHaveLength(13)
    expect(within(grid).getByText('09')).toBeVisible()
    expect(within(grid).getByText('21')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Outside 09:00-22:00' })).toBeVisible()
    const assignment = within(screen.getByRole('region', { name: 'Assignments outside the visible schedule' })).getByRole('button', { name: /Weekly.*Morning lesson/ })
    fireEvent.click(assignment)
    expect(onSelect).toHaveBeenCalledWith('a')
    const malformed = screen.getByRole('button', {
      name: /Weekly.*Malformed legacy event.*Instructor unavailable.*room unavailable.*Day unavailable.*later to time unavailable/,
    })
    expect(malformed).toHaveAttribute('data-kind', 'weekly')
    fireEvent.click(malformed)
    expect(onSelect).toHaveBeenLastCalledWith('b')
  })

  it('places 21:00 lessons in the thirteenth fixed hourly division without changing bounds', () => {
    const evening = {
      id: 'c', title: 'Evening lesson', type: 'weekly_lesson', resourceId: 'R2',
      daysOfWeek: [5], startTime: '21:00', endTime: '22:00', extendedProps: { Instructor: 'N. Teacher' },
    }
    const view = render(<ScheduleGrid activeDay={5} assignments={[...assignments, evening]} issueMatchIds={new Set()} onDayChange={vi.fn()} onSelect={vi.fn()} rooms={rooms} selectedId={null} />)
    const rendered = within(view.container)

    const assignment = rendered.getByRole('button', { name: /Weekly.*Evening lesson.*21:00 to 22:00/ })
    expect(assignment.getAttribute('style')).toContain('grid-column: 2')
    expect(within(rendered.getByRole('region', { name: 'Assignments outside the visible schedule' })).queryByRole('button', { name: /Evening lesson/ })).not.toBeInTheDocument()
    expect(rendered.getByTestId('schedule-grid-canvas')).toHaveAttribute('data-time-start', '09:00')
    expect(rendered.getByTestId('schedule-grid-canvas')).toHaveAttribute('data-time-end', '22:00')
  })

  it('shows one weekday at a time with real counts and does not classify another weekday as unplaced', () => {
    const tuesday = { id: 'tue', title: 'Tuesday lesson', resourceId: 'R1', daysOfWeek: [2], startTime: '10:00', endTime: '11:00' }
    const weekend = { id: 'weekend', title: 'Weekend record', resourceId: 'R1', daysOfWeek: [6], startTime: '10:00', endTime: '11:00' }
    const onDayChange = vi.fn()
    const view = render(<ScheduleGrid activeDay={1} assignments={[...assignments, tuesday, weekend]} issueMatchIds={new Set()} onDayChange={onDayChange} onSelect={vi.fn()} rooms={rooms} selectedId={null} />)

    const rendered = within(view.container)
    const tabs = rendered.getByRole('group', { name: 'Schedule weekday' })
    expect(within(tabs).getByRole('button', { name: 'Monday, 1 assignment' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(tabs).getByRole('button', { name: 'Tuesday, 1 assignment' })).toBeVisible()
    expect(rendered.queryByRole('button', { name: /Tuesday lesson/ })).not.toBeInTheDocument()
    expect(within(rendered.getByRole('region', { name: 'Assignments outside the visible schedule' })).queryByText('Tuesday lesson')).not.toBeInTheDocument()
    expect(within(rendered.getByRole('region', { name: 'Assignments outside the visible schedule' })).queryByText('Weekend record')).not.toBeInTheDocument()
    expect(within(tabs).getByRole('button', { name: 'Saturday, 1 assignment' })).toBeVisible()
    fireEvent.click(within(tabs).getByRole('button', { name: 'Tuesday, 1 assignment' }))
    expect(onDayChange).toHaveBeenCalledWith(2)
  })

  it('keeps adjacent same-day assignments readable on the single time axis', () => {
    const dense = [
      { id: 'd1', title: 'Lesson one', resourceId: 'R1', daysOfWeek: [1], startTime: '09:00', endTime: '10:00' },
      { id: 'd2', title: 'Lesson two', resourceId: 'R1', daysOfWeek: [1], startTime: '10:00', endTime: '11:00' },
      { id: 'd3', title: 'Lesson three', resourceId: 'R1', daysOfWeek: [1], startTime: '11:00', endTime: '12:00' },
    ]
    render(<ScheduleGrid activeDay={1} assignments={dense} issueMatchIds={new Set()} onDayChange={vi.fn()} onSelect={vi.fn()} rooms={rooms} selectedId={null} />)

    for (const title of ['Lesson one', 'Lesson two', 'Lesson three']) {
      const block = screen.getByRole('button', { name: new RegExp(title) })
      expect(block.getAttribute('style')).toContain('grid-column: 2')
      expect(block.getAttribute('style')).toMatch(/width: 7\.69/)
    }
  })

  it('removes leading legacy decoration from visible and accessible titles only', () => {
    const decorated = { id: 'legacy-title', title: '👤 WU, Yan', resourceId: 'R1', daysOfWeek: [1], startTime: '12:00', endTime: '13:00' }
    const canonical = structuredClone(decorated)
    render(<ScheduleGrid activeDay={1} assignments={[decorated]} issueMatchIds={new Set()} onDayChange={vi.fn()} onSelect={vi.fn()} rooms={rooms} selectedId={null} />)

    expect(screen.getByRole('button', { name: /WU, Yan/ })).toHaveTextContent('WU, Yan')
    expect(screen.getByRole('button', { name: /WU, Yan/ })).not.toHaveAccessibleName(/👤/)
    expect(adaptAssignment(decorated).title).toBe('WU, Yan')
    expect(decorated).toEqual(canonical)
  })

  it('filters the presentation by instructor room and search without mutating canonical input', () => {
    const canonical = [
      { id: 'one', title: 'Cello lesson', type: 'weekly_lesson', resourceId: 'R1', daysOfWeek: [1], startTime: '09:00', endTime: '10:00', extendedProps: { Instructor: 'A. Teacher' } },
      { id: 'two', title: 'Piano lesson', type: 'studio_class', resourceId: 'R2', daysOfWeek: [1], startTime: '10:00', endTime: '11:00', extendedProps: { Instructor: 'B. Teacher' } },
    ]
    const snapshot = structuredClone(canonical)
    const view = render(<ScheduleGrid activeDay={1} assignments={canonical} issueMatchIds={new Set()} onDayChange={vi.fn()} onSelect={vi.fn()} rooms={rooms} selectedId={null} />)
    const rendered = within(view.container)

    fireEvent.change(rendered.getByLabelText('Filter by instructor'), { target: { value: 'B. Teacher' } })
    expect(rendered.queryByRole('button', { name: /Cello lesson/ })).not.toBeInTheDocument()
    expect(rendered.getByRole('button', { name: /Piano lesson/ })).toBeVisible()
    fireEvent.change(rendered.getByLabelText('Filter by room'), { target: { value: 'R1' } })
    expect(rendered.queryByRole('button', { name: /Piano lesson/ })).not.toBeInTheDocument()
    fireEvent.change(rendered.getByLabelText('Search assignments'), { target: { value: 'Cello' } })
    expect(canonical).toEqual(snapshot)
  })

  it('presents contiguous same-teacher rooms as one teacher block without mutating assignments', () => {
    const contiguous = [
      { id: 't1', title: 'S1', type: 'weekly_lesson', resourceId: 'R1', daysOfWeek: [1], startTime: '13:00', endTime: '14:00', extendedProps: { Instructor: 'Dr. Merge' } },
      { id: 't2', title: 'S2', type: 'weekly_lesson', resourceId: 'R1', daysOfWeek: [1], startTime: '14:00', endTime: '15:00', extendedProps: { Instructor: 'Dr. Merge' } },
      { id: 't3', title: 'S3', type: 'weekly_lesson', resourceId: 'R1', daysOfWeek: [1], startTime: '15:00', endTime: '16:00', extendedProps: { Instructor: 'Dr. Merge' } },
      { id: 't4', title: 'Other', type: 'weekly_lesson', resourceId: 'R2', daysOfWeek: [1], startTime: '13:00', endTime: '14:00', extendedProps: { Instructor: 'Dr. Other' } },
    ]
    const snapshot = structuredClone(contiguous)
    const onSelect = vi.fn()
    render(<ScheduleGrid activeDay={1} assignments={contiguous} issueMatchIds={new Set()} onDayChange={vi.fn()} onSelect={onSelect} presentationMode="teachers" rooms={rooms} selectedId={null} />)
    const segments = screen.getAllByTestId('teacher-segment')
    expect(segments).toHaveLength(2)
    const merged = screen.getByLabelText(/Teacher block, Dr\. Merge.*13:00–16:00/)
    expect(within(merged).getByText('13:00–16:00')).toBeVisible()
    expect(within(merged).getByText('Dr. Merge')).toBeVisible()
    expect(screen.queryByText('S1')).not.toBeInTheDocument()
    fireEvent.click(merged)
    expect(onSelect).not.toHaveBeenCalled()
    expect(contiguous).toEqual(snapshot)
  })

  it('shows the truthful current-time marker only for the active weekday and visible range', () => {
    const mondayAtNoon = new Date(2026, 6, 13, 12, 30)
    const threeRooms = [...rooms, { id: 'R3' }]
    const view = render(<ScheduleGrid activeDay={1} assignments={[]} issueMatchIds={new Set()} now={mondayAtNoon} onDayChange={vi.fn()} onSelect={vi.fn()} rooms={threeRooms} selectedId={null} />)
    const marker = within(view.container).getByTestId('current-time-marker')
    expect(marker).toHaveAttribute('data-minute', '750')
    expect(marker).toHaveStyle({ gridRow: '2 / span 3' })

    view.rerender(<ScheduleGrid activeDay={2} assignments={[]} issueMatchIds={new Set()} now={mondayAtNoon} onDayChange={vi.fn()} onSelect={vi.fn()} rooms={threeRooms} selectedId={null} />)
    expect(within(view.container).queryByTestId('current-time-marker')).not.toBeInTheDocument()
  })

  it('在教师模式下按 reconciliationHighlight 高亮源教师区块并显示目标预览', () => {
    const sample = [
      { id: 't1', title: 'S1', type: 'weekly_lesson', resourceId: 'R1', daysOfWeek: [1], startTime: '10:00', endTime: '12:00', extendedProps: { Instructor: 'Teacher012' } },
    ]
    const view = render(
      <ScheduleGrid
        activeDay={1}
        assignments={sample}
        issueMatchIds={new Set()}
        onDayChange={vi.fn()}
        onSelect={vi.fn()}
        presentationMode="teachers"
        reconciliationHighlight={{
          teacher: 'Teacher012',
          fromRoom: 'R1',
          toRoom: 'R2',
          start: '10:00',
          end: '12:00',
        }}
        rooms={rooms}
        selectedId={null}
      />
    )

    const segment = screen.getByTestId('teacher-segment')
    expect(segment).toHaveAttribute('data-reconciliation-highlight', 'source')

    const targetPreview = screen.getByTestId('reconciliation-target-preview')
    expect(targetPreview).toBeVisible()
    expect(targetPreview).toHaveTextContent('Teacher012')
    expect(targetPreview).toHaveTextContent('→ R2')

    // 清除高亮时预览消失
    view.rerender(
      <ScheduleGrid
        activeDay={1}
        assignments={sample}
        issueMatchIds={new Set()}
        onDayChange={vi.fn()}
        onSelect={vi.fn()}
        presentationMode="teachers"
        reconciliationHighlight={null}
        rooms={rooms}
        selectedId={null}
      />
    )
    expect(screen.queryByTestId('reconciliation-target-preview')).not.toBeInTheDocument()
    expect(screen.getByTestId('teacher-segment')).not.toHaveAttribute('data-reconciliation-highlight')
  })

  it('在课程模式下按 reconciliationHighlight 高亮匹配的课表卡片', () => {
    const sample = [
      { id: 'c1', title: 'Lesson 1', type: 'weekly_lesson', resourceId: 'R1', daysOfWeek: [1], startTime: '10:00', endTime: '11:00', extendedProps: { Instructor: 'Teacher018' } },
    ]
    render(
      <ScheduleGrid
        activeDay={1}
        assignments={sample}
        issueMatchIds={new Set()}
        onDayChange={vi.fn()}
        onSelect={vi.fn()}
        presentationMode="lessons"
        reconciliationHighlight={{
          teacher: 'Teacher018',
          fromRoom: 'R1',
          toRoom: 'R2',
          start: '10:00',
          end: '11:00',
        }}
        rooms={rooms}
        selectedId={null}
      />
    )

    const block = screen.getByRole('button', { name: /Teacher018/ })
    expect(block).toHaveAttribute('data-reconciliation-highlight', 'source')
    expect(screen.getByTestId('reconciliation-target-preview')).toBeVisible()
  })
})
