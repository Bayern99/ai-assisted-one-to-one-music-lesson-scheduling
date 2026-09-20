import type { CSSProperties } from 'react'
import { reservationChipLabel, type ReservationMarker } from '../scheduleAuthority'
import styles from '../scheduleGrid.module.css'

interface ReservationDateChipsProps {
  marker: ReservationMarker
  placement: CSSProperties
}

export function ReservationDateChips({ marker, placement }: ReservationDateChipsProps) {
  const chips = [
    ...marker.placed_dates.map((date) => ({ date, kind: 'placed' as const })),
    ...marker.unplaced_dates.map((date) => ({ date, kind: 'unplaced' as const })),
  ]
  if (!chips.length) return null
  return (
    <div
      aria-label={`Reservation dates for ${marker.instructor} in ${marker.magnet_room}`}
      className={styles.reservationChips}
      data-testid="reservation-date-chips"
      style={placement}
    >
      {chips.map((chip) => (
        <span className={styles.reservationChip} data-chip-kind={chip.kind} key={`${chip.kind}:${chip.date}`}>
          {reservationChipLabel(chip.date)}
        </span>
      ))}
    </div>
  )
}
