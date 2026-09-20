import { FileArrowUp } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { Button } from './Button'
import styles from './NativeFilePicker.module.css'

export interface NativeFileSelection {
  file: File
  location: string | null
  mimeType: string
  source: 'browser' | 'macos'
}

interface NativeFilePickerProps {
  accept: string
  disabled?: boolean
  inputLabel?: string
  kind: 'assessmentData' | 'lectureCSV' | 'schedulerSource' | 'sourceData' | 'workbook'
  label: string
  onSelect: (selection: NativeFileSelection) => void
  selection?: NativeFileSelection | null
}

function decodeFile(result: Awaited<ReturnType<NonNullable<Window['piDesktop']>['openFile']>>) {
  if (!result.selected || !result.name || !result.dataBase64) return null
  const bytes = Uint8Array.from(atob(result.dataBase64), (character) => character.charCodeAt(0))
  const mimeType = result.mimeType || 'application/octet-stream'
  return {
    file: new File([bytes], result.name, { type: mimeType }),
    location: result.location ?? null,
    mimeType,
    source: 'macos' as const,
  }
}

export function NativeFilePicker({ accept, disabled, inputLabel, kind, label, onSelect, selection }: NativeFilePickerProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!selection && inputRef.current) inputRef.current.value = ''
  }, [selection])

  async function choose() {
    const open = window.piDesktop?.openFile
    if (!open) {
      inputRef.current?.click()
      return
    }
    setPending(true)
    setError('')
    try {
      const result = decodeFile(await open(kind))
      if (result) onSelect(result)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The file panel could not be opened.')
    } finally {
      setPending(false)
    }
  }

  const fileType = selection?.file.name.split('.').pop()?.toUpperCase() ?? (kind === 'workbook' ? 'XLSX' : kind === 'assessmentData' || kind === 'schedulerSource' || kind === 'sourceData' ? 'CSV / XLSX' : 'CSV')

  return (
    <div className={styles.picker} data-selected={selection ? 'true' : 'false'}>
      <input
        accept={accept}
        aria-label={inputLabel ?? label}
        disabled={disabled}
        className={styles.hiddenInput}
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (!file) return
          onSelect({ file, location: null, mimeType: file.type || 'application/octet-stream', source: 'browser' })
        }}
        ref={inputRef}
        tabIndex={-1}
        type="file"
      />
      <div className={styles.identity}>
        <FileArrowUp aria-hidden="true" size={17} weight="regular" />
        <div>
          <strong>{selection?.file.name ?? label}</strong>
          <span>{selection ? `${fileType} · ${selection.location ?? 'Selected from browser'}` : `Native ${fileType} selection`}</span>
        </div>
      </div>
      <Button disabled={disabled} loading={pending} loadingLabel="Opening…" onClick={() => void choose()} variant="secondary">
        {selection ? 'Replace' : 'Choose'}
      </Button>
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
    </div>
  )
}
