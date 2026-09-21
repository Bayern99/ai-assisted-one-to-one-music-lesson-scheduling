export const PHASE_LABELS: Record<string, string> = {
  queued: 'Queued for local execution',
  preflight: 'Checking scheduler inputs',
  optimizing: 'Optimizing room assignments',
  persisting: 'Saving the scheduling draft',
  investigating: "Investigating the day's linked adjustments",
  saving_reconciliation: 'Saving the investigation results',
  completed: 'Optimizer run completed',
  failed: 'Optimizer run failed',
}
