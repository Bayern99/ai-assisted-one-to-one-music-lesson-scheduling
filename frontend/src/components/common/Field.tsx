import { cloneElement, isValidElement, useId, type ComponentPropsWithoutRef, type ReactElement, type ReactNode } from 'react'
import styles from './Field.module.css'

export function Field({
  children,
  className,
  error,
  helper,
  label,
  ...props
}: ComponentPropsWithoutRef<'label'> & {
  error?: ReactNode
  helper?: ReactNode
  label: ReactNode
}) {
  const descriptionId = useId()
  const description = error ?? helper
  const child = isValidElement<{ 'aria-describedby'?: string; 'aria-label'?: string }>(children) ? children : null
  const control = description && child
    ? cloneElement(child as ReactElement<{ 'aria-describedby'?: string; 'aria-label'?: string }>, {
      'aria-describedby': [child.props['aria-describedby'], descriptionId].filter(Boolean).join(' '),
      'aria-label': child.props['aria-label'] ?? (typeof label === 'string' ? label : undefined),
    })
    : children

  return (
    <label {...props} className={[styles.field, className].filter(Boolean).join(' ')}>
      <span className={styles.label}>{label}</span>
      {control}
      {error ? <span className={styles.error} id={descriptionId}>{error}</span> : helper ? <span className={styles.helper} id={descriptionId}>{helper}</span> : null}
    </label>
  )
}
