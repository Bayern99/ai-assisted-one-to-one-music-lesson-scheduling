import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { IssueQueue } from './IssueQueue'

const issues = [
  {
    reason_code: 'room_conflict',
    label: 'Room conflict',
    count: 2,
    items: [
      {
        id: 'issue-open',
        reason_code: 'room_conflict',
        message: 'Needs a room',
        reason: 'Needs a room',
        duration_minutes: 60,
        source_request_id: 'open-1',
        type: 'weekly_lesson',
      },
      {
        id: 'issue-reservation',
        reason_code: 'reservation_internal',
        message: 'Held in instructor reservation',
        reason: 'Held in instructor reservation',
        duration_minutes: 60,
        source_request_id: 'studio-series',
        instructor: 'Piano D',
        reservation_note: 'Optimizer left this studio date in the instructor reservation.',
        type: 'studio_class',
      },
    ],
  },
]

describe('IssueQueue', () => {
  it('keeps reservation-internal issues out of open results but visible in the ledger', () => {
    render(<IssueQueue issues={issues} onSelect={vi.fn()} selectedIssueId={null} />)

    const queue = screen.getByRole('region', { name: 'Needs resolution' })
    expect(within(queue).getByText('2', { selector: 'span.numeric' })).toBeVisible()
    expect(screen.getByRole('button', { name: /Needs a room/ })).toBeVisible()
    expect(screen.queryByRole('button', { name: /Held in instructor reservation/ })).not.toBeInTheDocument()
    expect(screen.getByText('INSTRUCTOR RESERVATIONS')).toBeVisible()
    expect(screen.getByTestId('reservation-ledger-item')).toHaveTextContent('Piano D')
    expect(screen.getByText('Optimizer left this studio date in the instructor reservation.')).toBeVisible()
  })
})
