import { useMemo, type KeyboardEvent } from 'react'

export interface ScheduleFocusCandidate {
  day: number | null
  id: string
  roomIndex: number
  start: number | null
}

type Direction = 'ArrowLeft' | 'ArrowRight' | 'ArrowUp' | 'ArrowDown'

function position(candidate: ScheduleFocusCandidate) {
  return candidate.day === null || candidate.start === null || candidate.roomIndex < 0
    ? null
    : { x: candidate.day * 1440 + candidate.start, y: candidate.roomIndex }
}

export function nearestScheduleCandidate(
  currentId: string,
  direction: Direction,
  candidates: ScheduleFocusCandidate[],
) {
  const current = candidates.find((candidate) => candidate.id === currentId)
  const origin = current ? position(current) : null
  if (!origin) return null
  return candidates
    .filter((candidate) => candidate.id !== currentId)
    .map((candidate) => ({ candidate, point: position(candidate) }))
    .filter((entry): entry is { candidate: ScheduleFocusCandidate; point: { x: number; y: number } } => {
      if (!entry.point) return false
      if (direction === 'ArrowLeft') return entry.point.x < origin.x
      if (direction === 'ArrowRight') return entry.point.x > origin.x
      if (direction === 'ArrowUp') return entry.point.y < origin.y
      return entry.point.y > origin.y
    })
    .sort((a, b) => {
      const aPrimary = direction === 'ArrowLeft' || direction === 'ArrowRight'
        ? Math.abs(a.point.x - origin.x)
        : Math.abs(a.point.y - origin.y) * 1440
      const bPrimary = direction === 'ArrowLeft' || direction === 'ArrowRight'
        ? Math.abs(b.point.x - origin.x)
        : Math.abs(b.point.y - origin.y) * 1440
      const aCross = direction === 'ArrowLeft' || direction === 'ArrowRight'
        ? Math.abs(a.point.y - origin.y) * 1440
        : Math.abs(a.point.x - origin.x)
      const bCross = direction === 'ArrowLeft' || direction === 'ArrowRight'
        ? Math.abs(b.point.y - origin.y) * 1440
        : Math.abs(b.point.x - origin.x)
      return aPrimary + aCross - (bPrimary + bCross)
    })[0]?.candidate ?? null
}

export function useScheduleKeyboard(candidates: ScheduleFocusCandidate[], onOpen: (id: string) => void) {
  return useMemo(() => (id: string, event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      onOpen(id)
      return
    }
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
    const next = nearestScheduleCandidate(id, event.key as Direction, candidates)
    if (!next) return
    event.preventDefault()
    document.querySelector<HTMLElement>(`[data-assignment-id="${CSS.escape(next.id)}"]`)?.focus()
  }, [candidates, onOpen])
}
