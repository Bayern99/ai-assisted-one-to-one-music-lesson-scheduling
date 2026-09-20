import * as Dialog from '@radix-ui/react-dialog'
import { Button } from '../../../components/common/Button'
import styles from '../schedulerWorkspace.module.css'

interface FinalizeDialogProps {
  baselineVersion: string | null
  disabled: boolean
  finalizeHint?: string | null
  onCloseAutoFocus?: (event: Event) => void
  onConfirm: (expectedVersion: string) => void
  onOpenChange: (open: boolean) => void
  open: boolean
  pending: boolean
  unresolvedCount?: number
  workspaceVersion: string | null
}

export function FinalizeDialog({ baselineVersion, disabled, finalizeHint, onCloseAutoFocus, onConfirm, onOpenChange, open, pending, unresolvedCount = 0, workspaceVersion }: FinalizeDialogProps) {
  function changeOpen(nextOpen: boolean) {
    if (pending && !nextOpen) return
    onOpenChange(nextOpen)
  }

  return (
    <Dialog.Root onOpenChange={changeOpen} open={open}>
      <span className={styles.finalizeTriggerWrap}>
        <Dialog.Trigger asChild>
          <Button disabled={disabled || !workspaceVersion}>Finalize schedule</Button>
        </Dialog.Trigger>
        {finalizeHint ? <span className={styles.finalizeHint}>{finalizeHint}</span> : null}
      </span>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.dialogOverlay} />
        <Dialog.Content
          className={styles.dialogContent}
          onCloseAutoFocus={onCloseAutoFocus}
          onEscapeKeyDown={(event) => { if (pending) event.preventDefault() }}
          onPointerDownOutside={(event) => { if (pending) event.preventDefault() }}
        >
          <Dialog.Title>Finalize this scheduling round?</Dialog.Title>
          <Dialog.Description>
            {unresolvedCount > 0
              ? `${unresolvedCount} lesson${unresolvedCount === 1 ? '' : 's'} remain unresolved. Finalizing will commit the current schedule and include those lessons in export as unassigned rows instead of blocking export.`
              : 'This commits the current scheduling round after every assignment passes validation. The committed result becomes the canonical export source.'}
          </Dialog.Description>
          <div className={styles.dialogActions}>
            <Dialog.Close asChild><Button disabled={pending} variant="secondary">Cancel</Button></Dialog.Close>
            <Button disabled={disabled || pending || !baselineVersion} onClick={() => baselineVersion && onConfirm(baselineVersion)}>
              {pending ? 'Finalizing schedule' : 'Confirm finalize'}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
