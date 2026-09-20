import styles from '../resolutionPanel.module.css'

interface TeacherConfirmationFieldsProps {
  checked: boolean
  message: string | null | undefined
  note: string
  onCheckedChange: (checked: boolean) => void
  onNoteChange: (note: string) => void
}

export function TeacherConfirmationFields(props: TeacherConfirmationFieldsProps) {
  return (
    <fieldset className={styles.teacherConfirmation}>
      <legend>Teacher confirmation required</legend>
      <p>{props.message ?? 'The proposed day or time differs from the teacher’s original schedule.'}</p>
      <label>
        <input
          checked={props.checked}
          onChange={(event) => props.onCheckedChange(event.target.checked)}
          type="checkbox"
        />
        The teacher confirmed this exact day and time
      </label>
      <label>
        Confirmation note
        <textarea
          maxLength={500}
          onChange={(event) => props.onNoteChange(event.target.value)}
          placeholder="Optional: response, channel, or agreement details"
          rows={2}
          value={props.note}
        />
      </label>
    </fieldset>
  )
}
