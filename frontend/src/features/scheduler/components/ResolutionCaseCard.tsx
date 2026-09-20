import { useState } from 'react'
import type { ResolutionAdvice } from '../api'
import type { MoveTarget } from '../hooks/useAssignmentCommands'
import type { Issue } from './IssueQueue'
import styles from '../resolutionPanel.module.css'

const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
type ResolutionCase = ResolutionAdvice['cases'][number]

export interface ResolutionSelectionContext { adviceReason: string; caseId: string; status: ResolutionAdvice['cases'][number]['issues'][number]['status']; timeChangeAllowed: boolean; waiting: boolean; waitingNote: string }

interface ResolutionCaseCardProps {
  allIssues: Issue[]
  disabled: boolean
  onSelect: (issue: Issue, context: ResolutionSelectionContext) => void
  onSetWaiting: (caseId: string, waiting: boolean, note: string) => void
  onUseOption: (issue: Issue, target: MoveTarget, context: ResolutionSelectionContext) => void
  resolutionCase: ResolutionCase
  selectedIssueId: string | null
  selectedProposal: MoveTarget | null
  typeFilter: 'weekly' | 'studio' | 'other'
}

function workType(type: string) {
  const value = type.toLowerCase()
  return value.includes('studio') ? 'studio' : value.includes('weekly') ? 'weekly' : 'other'
}

function instrumentLabel(issue: Issue | undefined) {
  const instrument = issue?.instrument?.trim()
  if (instrument && !['instrumental', 'unknown', 'n/a'].includes(instrument.toLowerCase())) return instrument
  const course = issue?.course_code ?? ''
  const parenthetical = Array.from(course.matchAll(/\(([^()]+)\)/g), (match) => match[1].trim())
    .find((value) => !/^\d+$/.test(value))
  const discipline = parenthetical ?? course.match(/\b(Piano|Voice|Vocal|Percussion|Woodwinds?|Brass|Strings?|Cello|Violin|Viola|Flute|Clarinet|Guitar|Guzheng|Pipa|Chinese Instruments?)\b/i)?.[0]
  return discipline ?? instrument ?? issue?.room_types?.[0] ?? 'Instrument not specified'
}

function sameTarget(left: MoveTarget | null, right: MoveTarget) {
  return Boolean(left
    && left.room === right.room
    && left.day === right.day
    && left.start === right.start
    && left.end === right.end)
}

export function ResolutionCaseCard(props: ResolutionCaseCardProps) {
  const { resolutionCase } = props
  const [note, setNote] = useState(resolutionCase.waiting_note)
  const visibleIssues = resolutionCase.issues.filter((item) => workType(item.type) === props.typeFilter)

  return (
    <section className={styles.resolutionCase}>
      <header>
        <span><strong>{resolutionCase.instructor}</strong><small>{resolutionCase.date ?? dayNames[resolutionCase.day ?? 0]}</small></span>
        {resolutionCase.waiting ? (
          <button disabled={props.disabled} onClick={() => props.onSetWaiting(resolutionCase.id, false, '')} type="button">Resume case</button>
        ) : null}
      </header>
      {resolutionCase.waiting ? (
        <div className={styles.waitingStatus} role="status">
          <strong>Waiting for response</strong>
          <p>{resolutionCase.waiting_note}</p>
          <small>Resume this case when the requested information or teacher decision arrives.</small>
        </div>
      ) : (
        <div className={styles.waitingForm}>
          <label>Waiting note<input maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="What response or decision is needed?" value={note} /></label>
          <button disabled={props.disabled || !note.trim()} onClick={() => props.onSetWaiting(resolutionCase.id, true, note)} type="button">Move to Waiting</button>
        </div>
      )}
      {visibleIssues.map((item) => {
        const issue = props.allIssues.find((candidate) => candidate.id === item.issue_id)
        const instrument = instrumentLabel(issue)
        const originalTime = issue?.original_time ?? issue?.original_start
        const context: ResolutionSelectionContext = { adviceReason: item.reason, caseId: resolutionCase.id, status: item.status, timeChangeAllowed: item.time_change_allowed, waiting: resolutionCase.waiting, waitingNote: resolutionCase.waiting_note }
        return <div className={styles.resolutionIssue} data-selected={props.selectedIssueId === item.issue_id} key={item.issue_id}>
          <div className={styles.issueIdentity}><strong>{item.label}</strong><span><em>{instrument}</em>{originalTime ? <em>{originalTime}</em> : null}{item.placement_group_size && item.placement_group_size > 1 ? <em>{item.single_room === false ? `No single room · ${item.placement_group_size} lessons` : `Same-room group · ${item.placement_group_size} lessons`}</em> : null}</span></div>
          <p>{item.reason}</p>
          <div className={styles.issueActions}>
            <button disabled={!issue} onClick={() => issue && props.onSelect(issue, context)} type="button">Inspect timetable</button>
            {item.options.map((option) => {
              const confirmation = option.requires_teacher_confirmation ? ' · teacher confirmation' : ''
              const target = { day: option.day, room: option.room, start: option.start, end: option.end }
              return (
                <button
                  aria-pressed={props.selectedIssueId === item.issue_id && sameTarget(props.selectedProposal, target)}
                  disabled={!issue || props.disabled || resolutionCase.waiting}
                  key={`${option.room}-${option.day}-${option.start}`}
                  onClick={() => issue && props.onUseOption(issue, target, context)}
                  type="button"
                >{option.room} · {option.start}{confirmation}</button>
              )
            })}
          </div>
        </div>
      })}
    </section>
  )
}
