import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'quiet' | 'destructive' | 'selected' | 'icon'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  loading?: boolean
  loadingLabel?: ReactNode
  variant?: ButtonVariant
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { children, className, disabled, loading = false, loadingLabel, type = 'button', variant = 'primary', ...props },
  ref,
) {
  const classes = ['button', `button--${variant}`, className].filter(Boolean).join(' ')

  return (
    <button
      aria-busy={loading || undefined}
      className={classes}
      data-loading={loading || undefined}
      disabled={disabled || loading}
      ref={ref}
      type={type}
      {...props}
    >
      {loading ? (loadingLabel ?? children) : children}
    </button>
  )
})
