export const PAGE_TITLES = {
  overview: 'Overview',
  sourceData: 'Source Data',
  sourceImport: 'Import Sources',
  lectureLocks: 'Lecture Locks',
  schedulingRules: 'Scheduling Rules',
  optimizer: 'Optimizer',
  scheduleResolution: 'Resolve Schedule',
  scheduleExport: 'Schedule Export',
} as const

export const WORKFLOW_LABELS = {
  lectures: 'Import Lectures',
  import: 'Import Sources',
  rules: 'Configure Rules',
  optimize: 'Run Optimizer',
  resolve: 'Resolve Schedule',
  export: 'Export Schedule',
} as const

export const SECTION_TITLES = {
  activeWorkspace: 'Active Workspace',
  canonicalRules: 'Canonical Rules',
  canonicalSchedulePreview: 'Canonical Schedule Preview',
  exportReadiness: 'Export Readiness',
  generatedArtifacts: 'Generated Artifacts',
  lectureLocks: 'Lecture Locks',
  needsResolution: 'Needs Resolution',
  nextSchedulingRound: 'Next Scheduling Round',
  unresolvedCauses: 'Unresolved Causes',
  recentActivity: 'Recent Activity',
  runInformation: 'Run Information',
  schedulerWorkbook: 'Scheduler Workbook',
  schedulingSession: 'Scheduling Session',
  selectStudentRecord: 'Select a Student Record',
  studentRecords: 'Student Records',
  workflowContinuation: 'Workflow Continuation',
  workflowState: 'Workflow State',
  workspaceHealth: 'Workspace Health',
  workspaceReadiness: 'Workspace Readiness',
} as const

export function titleCaseLabel(value: string) {
  return value
    .replaceAll('_', ' ')
    .replaceAll('-', ' ')
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase())
}

export function workflowStageLabel(value: string | null | undefined) {
  if (!value) return 'Not Selected'

  const normalized = value.trim().toLowerCase().replaceAll('_', ' ')
  const aliases: Record<string, string> = {
    conflicts: WORKFLOW_LABELS.resolve,
    export: WORKFLOW_LABELS.export,
    import: WORKFLOW_LABELS.import,
    'import lectures': WORKFLOW_LABELS.lectures,
    lectures: WORKFLOW_LABELS.lectures,
    optimize: WORKFLOW_LABELS.optimize,
    optimizer: WORKFLOW_LABELS.optimize,
    resolve: WORKFLOW_LABELS.resolve,
    rules: WORKFLOW_LABELS.rules,
    'step 1: import': WORKFLOW_LABELS.import,
    'step 4: interactive editor': WORKFLOW_LABELS.resolve,
  }

  return aliases[normalized] ?? titleCaseLabel(value)
}

export function workspaceRevisionLabel(version: string | null | undefined) {
  if (!version) return 'Unavailable'
  return version.length >= 20 ? `Revision ${version.slice(0, 8)}…` : version
}
