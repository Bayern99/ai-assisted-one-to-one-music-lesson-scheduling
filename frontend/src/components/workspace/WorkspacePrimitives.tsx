import type { ComponentPropsWithoutRef, ReactNode } from 'react'
import styles from './WorkspacePrimitives.module.css'

function classes(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(' ')
}

export function WorkspaceHeader({
  actions,
  context,
  title,
}: {
  actions?: ReactNode
  context?: ReactNode
  title: ReactNode
}) {
  return (
    <header className={styles.header}>
      <div className={styles.heading}>
        <h1 data-workspace-heading tabIndex={-1}>{title}</h1>
        {context ? <div className={styles.context}>{context}</div> : null}
      </div>
      {actions ? <div className={styles.headerActions}>{actions}</div> : null}
    </header>
  )
}

export function WorkspaceToolbar(props: ComponentPropsWithoutRef<'div'>) {
  return <div {...props} className={classes(styles.toolbar, props.className)} />
}

export function WorkspaceSurface(props: ComponentPropsWithoutRef<'section'>) {
  return <section {...props} className={classes(styles.surface, props.className)} />
}

export function DockedPane({ side = 'right', ...props }: ComponentPropsWithoutRef<'aside'> & { side?: 'left' | 'right' }) {
  return <aside {...props} className={classes(styles.dockedPane, styles[side], props.className)} />
}

export function Section({
  description,
  title,
  ...props
}: ComponentPropsWithoutRef<'section'> & { description?: ReactNode; title?: ReactNode }) {
  return (
    <section {...props} className={classes(styles.section, props.className)}>
      {title || description ? (
        <div className={styles.sectionHeading}>
          {title ? <h2>{title}</h2> : null}
          {description ? <p>{description}</p> : null}
        </div>
      ) : null}
      {props.children}
    </section>
  )
}

export function EmphasisSurface({ tone = 'status', ...props }: ComponentPropsWithoutRef<'section'> & { tone?: 'status' | 'completion' | 'warning' | 'error' }) {
  return <section {...props} className={classes(styles.emphasis, styles[tone], props.className)} data-tone={tone} />
}

export function CommandBar(props: ComponentPropsWithoutRef<'div'>) {
  return <div {...props} className={classes(styles.commandBar, props.className)} />
}

export function DataTable(props: ComponentPropsWithoutRef<'div'>) {
  return <div {...props} className={classes(styles.tableFrame, props.className)} />
}

export function EmptyState({ action, children, title, ...props }: ComponentPropsWithoutRef<'section'> & { action?: ReactNode; title: ReactNode }) {
  return (
    <section {...props} className={classes(styles.emptyState, props.className)}>
      <h2>{title}</h2>
      <div>{children}</div>
      {action ? <div className={styles.emptyAction}>{action}</div> : null}
    </section>
  )
}
