import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TimeInput } from './TimeInput'

describe('TimeInput', () => {
  it('allows partial editing but exposes an accessible error for an invalid complete value', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<TimeInput aria-label="Start time" onChange={onChange} value="12:99" />)

    const input = screen.getByRole('textbox', { name: 'Start time' })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Enter a valid 24-hour time in HH:MM format.')

    await user.click(input)
    expect(onChange).not.toHaveBeenCalled()
  })
})
