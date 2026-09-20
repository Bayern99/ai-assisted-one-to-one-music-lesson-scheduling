export type StatusKind = 'auth' | 'api' | 'file-conflict' | 'save'
export type StatusTone = 'neutral' | 'warning' | 'error'

export interface StatusBannerProps {
  kind?: StatusKind
  message?: string
  tone?: StatusTone
}

export function StatusBanner({ kind, message, tone = 'neutral' }: StatusBannerProps) {
  const isError = Boolean(message) && tone === 'error'

  return (
    <section
      aria-label="System status"
      className="statusBanner"
      data-kind={kind}
      data-state={message ? tone : 'empty'}
    >
      <p
        aria-atomic="true"
        aria-live="polite"
        className="statusBanner__message"
        data-tone={message && !isError ? tone : 'neutral'}
        role="status"
      >
        {isError ? null : message}
      </p>
      {isError ? (
        <p
          aria-atomic="true"
          aria-live="assertive"
          className="statusBanner__message statusBanner__alert"
          data-tone="error"
          role="alert"
        >
          {message}
        </p>
      ) : null}
    </section>
  )
}
