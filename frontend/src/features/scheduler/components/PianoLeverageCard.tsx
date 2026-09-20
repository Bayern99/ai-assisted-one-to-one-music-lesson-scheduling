import { useState } from 'react'
import type { ResolutionAdvice } from '../api'
import styles from '../resolutionPanel.module.css'

const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
type Proposal = ResolutionAdvice['piano_leverage'][number]

interface PianoLeverageCardProps {
  disabled: boolean
  onApply: (proposalId: string, note: string) => void
  proposal: Proposal
}

export function PianoLeverageCard({ disabled, onApply, proposal }: PianoLeverageCardProps) {
  const [confirmed, setConfirmed] = useState(false)
  const [note, setNote] = useState('')

  return (
    <section className={styles.leverageCard}>
      <strong>Piano leverage · +{proposal.gain}</strong>
      <p>{proposal.instructor} · {proposal.moves.length} block moves</p>
      <p>→ {dayNames[proposal.target_day]} {proposal.target_start}–{proposal.target_end} · {proposal.target_room}</p>
      <details>
        <summary>Preview complete package</summary>
        <ul>
          {proposal.moves.map((move) => (
            <li key={move.assignment_id}>{move.label}: {dayNames[move.from_day]} {move.from_start} {move.from_room} → {dayNames[move.to_day]} {move.to_start} {move.to_room}</li>
          ))}
          {proposal.fills.map((fill) => (
            <li key={fill.issue_id}>Resolve {fill.label} ({fill.instructor}) in {fill.room} · {fill.start}</li>
          ))}
        </ul>
      </details>
      <fieldset className={styles.packageConfirmation}>
        <legend>Teacher approval</legend>
        <label><input checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} type="checkbox" /> {proposal.instructor} confirmed this full block move</label>
        <label>Confirmation note<textarea maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="Optional response details" rows={2} value={note} /></label>
      </fieldset>
      <button disabled={disabled || !confirmed} onClick={() => onApply(proposal.id, note)} type="button">Apply teacher-approved package</button>
    </section>
  )
}
