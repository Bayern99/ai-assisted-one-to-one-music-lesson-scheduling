import { useCallback, useRef, useState, type MouseEvent } from 'react'

export function useArtifactSave() {
  const pending = useRef(new Set<string>())
  const [error, setError] = useState('')
  const [savedArtifacts, setSavedArtifacts] = useState<Set<string>>(() => new Set())

  const saveArtifact = useCallback(async (event: MouseEvent<HTMLAnchorElement>, artifactId: string) => {
    const save = window.piDesktop?.saveArtifact
    if (!save) return
    event.preventDefault()
    if (pending.current.has(artifactId)) return
    pending.current.add(artifactId)
    setError('')
    try {
      const result = await save(artifactId)
      if (result && typeof result === 'object' && (result as Record<string, unknown>).saved === true) {
        setSavedArtifacts((current) => new Set(current).add(artifactId))
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The desktop save failed')
    } finally {
      pending.current.delete(artifactId)
    }
  }, [])

  return { clearError: () => setError(''), error, saveArtifact, savedArtifacts }
}
