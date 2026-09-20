import { useId, useState, type ChangeEvent, type InputHTMLAttributes } from 'react'
import { isCanonicalTime } from './timeInputUtils'
import styles from './TimeInput.module.css'

type TimeInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value' | 'onChange'> & {
  onChange: (event: ChangeEvent<HTMLInputElement>) => void
  value: string
}

export function TimeInput({ onChange, value, ...props }: TimeInputProps) {
  const [touched, setTouched] = useState(false)
  const errorId = `time-input-error-${useId().replaceAll(':', '')}`
  const invalid = (touched || value.length === 5) && !isCanonicalTime(value)
  return (
    <>
      <input
        {...props}
        aria-describedby={[props['aria-describedby'], invalid ? errorId : null].filter(Boolean).join(' ') || undefined}
        aria-invalid={invalid || props['aria-invalid'] ? true : undefined}
        className={`${styles.timeInput} ${props.className ?? ''}`.trim()}
        inputMode="numeric"
        maxLength={5}
        onBlur={(event) => {
          setTouched(true)
          props.onBlur?.(event)
        }}
        onChange={onChange}
        pattern="(?:[01][0-9]|2[0-3]):[0-5][0-9]"
        placeholder="HH:MM"
        type="text"
        value={value}
      />
      {invalid ? <span className={styles.error} id={errorId} role="alert">Enter a valid 24-hour time in HH:MM format.</span> : null}
    </>
  )
}
