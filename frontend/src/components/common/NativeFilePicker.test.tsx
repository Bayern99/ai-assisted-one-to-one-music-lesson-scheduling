import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NativeFilePicker } from './NativeFilePicker'

afterEach(() => {
  cleanup()
  delete window.piDesktop
})

describe('NativeFilePicker', () => {
  it('uses the macOS bridge and returns a browser File without showing native input chrome', async () => {
    const onSelect = vi.fn()
    window.piDesktop = { openFile: vi.fn().mockResolvedValue({
      selected: true,
      name: 'Scheduler Workbook.xlsx',
      location: '/Users/test/Documents',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      dataBase64: btoa('workbook'),
    }) }
    render(<NativeFilePicker accept=".xlsx" kind="workbook" label="Scheduling workbook" onSelect={onSelect} />)

    await userEvent.click(screen.getByRole('button', { name: 'Choose' }))

    expect(window.piDesktop.openFile).toHaveBeenCalledWith('workbook')
    expect(onSelect).toHaveBeenCalledOnce()
    expect(onSelect.mock.calls[0][0].file).toBeInstanceOf(File)
    expect(onSelect.mock.calls[0][0].file.name).toBe('Scheduler Workbook.xlsx')
    expect(screen.queryByText(/No file chosen/i)).not.toBeInTheDocument()
  })
})
