import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Field } from './Field'

describe('Field', () => {
  it('associates helper and error text with its control', () => {
    const { rerender } = render(<Field helper="Use canonical time." label="Start time"><input /></Field>)
    expect(screen.getByRole('textbox', { name: 'Start time' })).toHaveAccessibleDescription('Use canonical time.')

    rerender(<Field error="Start time is required." label="Start time"><input /></Field>)
    expect(screen.getByRole('textbox', { name: 'Start time' })).toHaveAccessibleDescription('Start time is required.')
  })
})
