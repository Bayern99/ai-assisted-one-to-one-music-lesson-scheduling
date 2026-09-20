import * as Dialog from '@radix-ui/react-dialog'
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Navigate, useParams } from 'react-router-dom'
import { PAGE_TITLES } from '../../../app/productLanguage'
import { ApiClientError, apiRequest, type ApiEnvelope } from '../../../api/client'
import { Button } from '../../../components/common/Button'
import { Field } from '../../../components/common/Field'
import { TimeInput } from '../../../components/common/TimeInput'
import { isCanonicalTime } from '../../../components/common/timeInputUtils'
import { WorkspaceHeader, WorkspaceSurface, WorkspaceToolbar } from '../../../components/workspace/WorkspacePrimitives'
import {
  getSchedulerRules,
  saveSchedulerRules,
  schedulerRulesKey,
  schedulerSessionKey,
  type SchedulerRulesView,
  type SchedulerSession,
  useSchedulerSession,
} from '../api'
import pageStyles from './RulesPage.module.css'
import workspaceStyles from '../schedulerWorkspace.module.css'

const styles = new Proxy(workspaceStyles, { get: (target, key: string) => target[key] ?? pageStyles[key] })

const RULE_SECTIONS = [
  { id: 'constraints', label: 'Constraints', description: 'Operating hours and lesson continuity' },
  { id: 'priorities', label: 'Priorities', description: 'Room affinity and instructor order' },
  { id: 'resolution', label: 'Resolution Pool', description: 'Time-change proposal eligibility' },
  { id: 'rooms', label: 'Rooms & Preferences', description: 'Room capability and instructor choices' },
] as const
type RuleSection = typeof RULE_SECTIONS[number]['id']
const ROOM_TYPES = ['Piano', 'Percussion', 'Voice', 'Instrumental'] as const

type ReconciliationReport = {
  source_row_count: number
  source_request_count?: number
  assignment_count: number
  assigned_count?: number
  unresolved_count?: number
  accounted_request_count?: number
  duplicates?: Array<{ source_request_id?: string; assignment_ids?: string[] }>
  matches: Array<{ assignment_id?: string; details?: string }>
  missing: Array<{ Instructor?: string; Day?: string; Time?: string; Student?: string }>
  phantom: Array<{ assignment_id?: string; details?: string }>
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function asStringList(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function fieldValue(value: unknown) {
  return typeof value === 'string' || typeof value === 'number' ? value : ''
}

function compactPath(path: string) {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts.length > 1 ? `…/${parts.at(-1)}` : path
}

function InlineError({ error }: { error: Error | null }) {
  if (!error) return null
  const details = error instanceof ApiClientError ? error.details : null
  const messages = details ? Object.values(details).flatMap((value) => Array.isArray(value) ? value : [value]) : []
  return <div className={`${styles.inlineError} ${styles.rulesInlineError}`} role="alert"><strong>{error.message}</strong>{messages.map((message, index) => <p key={index}>{typeof message === 'object' ? JSON.stringify(message) : String(message)}</p>)}</div>
}

function RulesMetadata({ view }: { view: SchedulerRulesView }) {
  const trace = asRecord(view.trace)
  const ignored = [...asStringList(trace.ignored_top_level_keys), ...asStringList(trace.ignored_nested_keys)]
  const hidden = asStringList(trace.hidden_ui_fields)
  return <dl className={styles.rulesMetadata} aria-label="Rules metadata">
    <div><dt>Source</dt><dd className={`${styles.rulesMetadataPath} meta`} title={view.source_path}>{compactPath(view.source_path)}</dd></div>
    <div><dt>Compatibility</dt><dd>{hidden.length ? `${hidden.length} preserved field${hidden.length === 1 ? '' : 's'}` : 'Canonical only'}</dd></div>
    <div><dt>Ignored keys</dt><dd>{ignored.length || 'None'}</dd></div>
  </dl>
}

function ConstraintsEditor({ disabled, onChange, rules }: { disabled: boolean; onChange: (path: string[], value: unknown) => void; rules: Record<string, unknown> }) {
  const constraints = asRecord(rules.constraints)
  const timeRange = asRecord(constraints.time_range)
  return <fieldset className={`${styles.editorScope} ${styles.rulesEditorScope}`} disabled={disabled}>
    <legend className={styles.scopeLegend}>Scheduling Constraints</legend>
    <div className={styles.rulesSectionIntro}><h2>Scheduling Constraints</h2><p>Define the canonical operating window before the Optimizer runs.</p></div>
    <div className={styles.constraintGrid}>
      <Field helper="Use 24-hour HH:MM." label="Earliest Lesson Start"><TimeInput aria-label="Earliest lesson start" onChange={(event) => onChange(['constraints', 'time_range', 'start'], event.target.value)} value={String(fieldValue(timeRange.start))} /></Field>
      <Field helper="Use 24-hour HH:MM." label="Latest Lesson End"><TimeInput aria-label="Latest lesson end" onChange={(event) => onChange(['constraints', 'time_range', 'end'], event.target.value)} value={String(fieldValue(timeRange.end))} /></Field>
      <label className={styles.checkboxField}><input checked={Boolean(constraints.enforce_instructor_blocks)} onChange={(event) => onChange(['constraints', 'enforce_instructor_blocks'], event.target.checked)} type="checkbox" /><span><strong>Keep Adjacent Instructor Lessons Together</strong><small>Same-teacher same-day lessons with a gap of at most 60 minutes share a room search. Turn this off to let each lesson pick a room independently.</small></span></label>
    </div>
  </fieldset>
}

function PrioritiesEditor({
  disabled, instructors, onChange, rules,
}: {
  disabled: boolean
  instructors: string[]
  onChange: (path: string[], value: unknown) => void
  rules: Record<string, unknown>
}) {
  const priorities = asRecord(rules.priorities)
  const instructorPriority = asRecord(rules.instructor_priority)
  const [query, setQuery] = useState('')
  const instructorKeys = useMemo(() => [...new Set([...Object.keys(instructorPriority), ...instructors])].sort(), [instructorPriority, instructors])
  const visibleInstructors = instructorKeys.filter((name) => name.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  const [selectedInstructorOverride, setSelectedInstructor] = useState('')
  const selectedInstructor = instructorKeys.includes(selectedInstructorOverride) ? selectedInstructorOverride : instructorKeys[0] ?? ''

  return <fieldset className={`${styles.editorScope} ${styles.rulesEditorScope}`} disabled={disabled}>
    <legend className={styles.scopeLegend}>Scheduling Priorities</legend>
    <div className={styles.rulesSectionIntro}><h2>Scheduling Priorities</h2><p>Scores are bounded and explicit: room affinity 0–10, instructor priority 1–10.</p></div>
    <section aria-labelledby="affinity-heading" className={styles.rulesSubsection}>
      <div className={`${styles.sectionHeading} ${styles.rulesSubsectionHeading}`}><div><h3 id="affinity-heading">Room Affinity Matrix</h3><p>Higher values make that student type a better fit for the room type.</p></div></div>
      <div className={`${styles.tableFrame} ${styles.priorityMatrix}`}><table><thead><tr><th>Room Type</th><th>Student Type</th><th>Priority</th></tr></thead><tbody>
        {Object.entries(priorities).flatMap(([roomType, studentMap]) => Object.entries(asRecord(studentMap)).map(([studentType, priority]) => <tr key={`${roomType}-${studentType}`}><th scope="row">{roomType}</th><td>{studentType}</td><td><input aria-label={`${roomType} room priority for ${studentType}`} max={10} min={0} onChange={(event) => onChange(['priorities', roomType, studentType], Number(event.target.value))} type="number" value={fieldValue(priority)} /></td></tr>))}
      </tbody></table></div>
    </section>
    <section aria-labelledby="instructor-priority-heading" className={styles.rulesSubsection}>
      <div className={`${styles.sectionHeading} ${styles.rulesSubsectionHeading}`}><div><h3 id="instructor-priority-heading">Instructor Priority</h3><p>Teachers without an override use the canonical default of 5.</p></div></div>
      <div className={styles.selectionWorkbench}>
        <div className={styles.selectionList}>
          <Field label="Find Instructor"><input aria-label="Find instructor priority" onChange={(event) => setQuery(event.target.value)} value={query} /></Field>
          <div className={styles.selectionRows}>{visibleInstructors.map((instructor) => <button aria-pressed={selectedInstructor === instructor} key={instructor} onClick={() => setSelectedInstructor(instructor)} type="button"><span>{instructor}</span><strong className="numeric">{Number(instructorPriority[instructor] ?? 5)}</strong></button>)}</div>
        </div>
        <div className={styles.selectionInspector}>{selectedInstructor ? <Field helper="Allowed range: 1–10. Default: 5." label={selectedInstructor}><input aria-label={`Priority for ${selectedInstructor}`} max={10} min={1} onChange={(event) => onChange(['instructor_priority', selectedInstructor], Number(event.target.value))} type="number" value={fieldValue(instructorPriority[selectedInstructor] ?? 5)} /></Field> : <p className={styles.empty}>No instructors are available.</p>}</div>
      </div>
    </section>
  </fieldset>
}

function ResolutionRulesEditor({
  disabled, instructors, onChange, rules,
}: {
  disabled: boolean
  instructors: string[]
  onChange: (path: string[], value: unknown) => void
  rules: Record<string, unknown>
}) {
  const eligibility = asRecord(rules.instructor_time_change_eligibility)
  const [query, setQuery] = useState('')
  const instructorKeys = useMemo(
    () => [...new Set([...Object.keys(eligibility), ...instructors])].sort(),
    [eligibility, instructors],
  )
  const visibleInstructors = instructorKeys.filter((name) => name.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  const eligibleCount = instructorKeys.filter((name) => eligibility[name] !== false).length

  return <fieldset className={`${styles.editorScope} ${styles.rulesEditorScope}`} disabled={disabled}>
    <legend className={styles.scopeLegend}>Resolution Pool</legend>
    <div className={styles.rulesSectionIntro}>
      <h2>Time-change Proposal Pool</h2>
      <p>Checked instructors may receive proposals that change their requested day or time. Room-only options at the original time remain available for everyone.</p>
    </div>
    <section aria-labelledby="time-change-pool-heading" className={styles.rulesSubsection}>
      <div className={`${styles.sectionHeading} ${styles.rulesSubsectionHeading}`}>
        <div><h3 id="time-change-pool-heading">Who may be moved?</h3><p>Checked: may move to a different day or time. Unchecked: keep the original day and time.</p></div>
        <strong className="numeric">{eligibleCount} / {instructorKeys.length} may move</strong>
      </div>
      <div className={styles.eligibilityWorkbench}>
        <Field label="Find Instructor"><input aria-label="Find instructor time-change eligibility" onChange={(event) => setQuery(event.target.value)} value={query} /></Field>
        <div className={styles.eligibilityList}>
          {visibleInstructors.map((instructor) => {
            const included = eligibility[instructor] !== false
            return <label key={instructor}>
              <input
                aria-label={`Allow time changes for ${instructor}`}
                checked={included}
                onChange={(event) => onChange(['instructor_time_change_eligibility', instructor], event.target.checked)}
                type="checkbox"
              />
              <span><strong>{instructor}</strong><small>{included ? 'May move to a different day or time' : 'Keep original day and time'}</small></span>
            </label>
          })}
          {!visibleInstructors.length ? <p className={styles.empty}>No matching instructors.</p> : null}
        </div>
      </div>
    </section>
  </fieldset>
}

function RoomsEditor({
  disabled, instructors, onChange, roomIds, rules, sourcePreferences,
}: {
  disabled: boolean
  instructors: string[]
  onChange: (path: string[], value: unknown) => void
  roomIds: string[]
  rules: Record<string, unknown>
  sourcePreferences: SchedulerSession['source_preferences']
}) {
  const roomTypes = asRecord(rules.room_types)
  const preferredRooms = asRecord(rules.instructor_preferred_rooms)
  const instructorPriority = asRecord(rules.instructor_priority)
  const instructorKeys = useMemo(() => [...new Set([...Object.keys(instructorPriority), ...Object.keys(preferredRooms), ...instructors, ...sourcePreferences.map((item) => item.instructor)])].sort(), [instructorPriority, instructors, preferredRooms, sourcePreferences])
  const roomKeys = [...new Set([...Object.keys(roomTypes), ...roomIds])].sort()
  const sourceByInstructor = new Map(sourcePreferences.map((item) => [item.instructor, item]))
  const [query, setQuery] = useState('')
  const [selectedInstructorOverride, setSelectedInstructor] = useState('')
  const visibleInstructors = instructorKeys.filter((name) => name.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  const selectedInstructor = instructorKeys.includes(selectedInstructorOverride) ? selectedInstructorOverride : instructorKeys[0] ?? ''

  const saved = asStringList(preferredRooms[selectedInstructor])
  const source = sourceByInstructor.get(selectedInstructor)
  const unknownSaved = saved.filter((room) => !roomIds.includes(room))

  function setRoomType(room: string, type: string, checked: boolean) {
    const current = new Set(asStringList(roomTypes[room]))
    if (checked) current.add(type); else current.delete(type)
    onChange(['room_types', room], ROOM_TYPES.filter((value) => current.has(value)))
  }

  function setPreferredRoom(room: string, checked: boolean) {
    const known = new Set(saved.filter((value) => roomIds.includes(value)))
    if (checked) known.add(room); else known.delete(room)
    onChange(['instructor_preferred_rooms', selectedInstructor], [...roomIds.filter((value) => known.has(value)), ...unknownSaved])
  }

  return <fieldset className={`${styles.editorScope} ${styles.rulesEditorScope}`} disabled={disabled}>
    <legend className={styles.scopeLegend}>Rooms and Preferences</legend>
    <div className={styles.rulesSectionIntro}><h2>Rooms & Preferences</h2><p>Room capability is constrained to supported types; instructor-wide choices remain separate from imported requests.</p></div>
    <section className={styles.rulesSubsection}>
      <div className={`${styles.sectionHeading} ${styles.rulesSubsectionHeading}`}><div><h3>Room Capabilities</h3><p>Choose only the lesson types each room can support.</p></div></div>
      <div className={`${styles.tableFrame} ${styles.roomTypesTable}`}><table><thead><tr><th>Room</th>{ROOM_TYPES.map((type) => <th key={type}>{type}</th>)}</tr></thead><tbody>{roomKeys.map((room) => <tr key={room}><th className="room" scope="row">{room}</th>{ROOM_TYPES.map((type) => <td key={type}><input aria-label={`${type} room type for ${room}`} checked={asStringList(roomTypes[room]).includes(type)} onChange={(event) => setRoomType(room, type, event.target.checked)} type="checkbox" /></td>)}</tr>)}</tbody></table></div>
      {!roomKeys.length ? <p className={styles.empty}>No rooms are available.</p> : null}
    </section>
    <section className={styles.rulesSubsection}>
      <div className={`${styles.sectionHeading} ${styles.rulesSubsectionHeading}`}><div><h3>Instructor Room Preferences</h3><p>Inspect one instructor at a time instead of expanding every room choice.</p></div></div>
      <div className={styles.selectionWorkbench}>
        <div className={styles.selectionList}>
          <Field label="Find Instructor"><input aria-label="Find instructor room preferences" onChange={(event) => setQuery(event.target.value)} value={query} /></Field>
          <div className={styles.selectionRows}>{visibleInstructors.map((instructor) => <button aria-pressed={selectedInstructor === instructor} key={instructor} onClick={() => setSelectedInstructor(instructor)} type="button"><span>{instructor}</span><strong className="numeric">{asStringList(preferredRooms[instructor]).length}</strong></button>)}</div>
        </div>
        <div aria-label={selectedInstructor ? `Source preferences for ${selectedInstructor}` : undefined} className={styles.preferenceInspector}>
          {selectedInstructor ? <>
            <h4>{selectedInstructor}</h4>
            <div><strong>Imported Per-Request Venues</strong><p className="meta">{source?.request_count ?? 0} imported request{source?.request_count === 1 ? '' : 's'}</p><div className={styles.chipRow}>{source?.room_variants.length ? source.room_variants.map((variant) => <span className={styles.readOnlyChip} key={variant.join('\u0000')}>{variant.join(' + ')}</span>) : <span className={styles.emptyChip}>None Specified</span>}</div>{source?.unknown_rooms.length ? <p className={styles.preferenceWarning}>Unknown source rooms: {source.unknown_rooms.join(', ')}</p> : null}</div>
            <fieldset className={styles.preferenceChoices}><legend>Additional Instructor-Wide Rooms</legend>{roomIds.map((room) => <label key={room}><input aria-label={`Additional room ${room} for ${selectedInstructor}`} checked={saved.includes(room)} onChange={(event) => setPreferredRoom(room, event.target.checked)} type="checkbox" /><span>{room}</span></label>)}</fieldset>
            {unknownSaved.length ? <p className={styles.preferenceWarning}>Unknown saved rooms preserved: {unknownSaved.join(', ')}</p> : null}
          </> : <p className={styles.empty}>No instructors are available.</p>}
        </div>
      </div>
    </section>
  </fieldset>
}

export function RulesPage() {
  const { section } = useParams<{ section?: string }>()
  const activeSection = (section ?? 'constraints') as RuleSection
  const validSection = RULE_SECTIONS.some((item) => item.id === activeSection)
  const queryClient = useQueryClient()
  const sessionQuery = useSchedulerSession()
  const rulesQuery = useQuery({ queryKey: schedulerRulesKey, queryFn: ({ signal }) => getSchedulerRules(signal) })
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null)
  const [baseline, setBaseline] = useState<Record<string, unknown> | null>(null)
  const [baselineVersion, setBaselineVersion] = useState<string | null>(null)
  const [view, setView] = useState<SchedulerRulesView | null>(null)
  const [message, setMessage] = useState('')
  const [reloadOpen, setReloadOpen] = useState(false)
  const [reconciliationOpen, setReconciliationOpen] = useState(false)

  /* eslint-disable react-hooks/set-state-in-effect -- The editable draft is hydrated once from an asynchronously versioned workspace snapshot. */
  useEffect(() => {
    const loaded = rulesQuery.data?.data
    if (!loaded || draft !== null) return
    setDraft(structuredClone(loaded.rules))
    setBaseline(structuredClone(loaded.rules))
    setBaselineVersion(rulesQuery.data?.workspace_version ?? null)
    setView(loaded)
  }, [draft, rulesQuery.data])
  /* eslint-enable react-hooks/set-state-in-effect */

  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(baseline)
  const readOnly = sessionQuery.isError || rulesQuery.isError
  const rooms = (sessionQuery.data?.data?.rooms ?? []).map((room) => room.id)
  const timeRange = draft ? asRecord(asRecord(draft.constraints).time_range) : {}
  const validTimes = isCanonicalTime(String(fieldValue(timeRange.start))) && isCanonicalTime(String(fieldValue(timeRange.end)))
  const saveMutation = useMutation({
    mutationFn: async () => {
      try {
        return await saveSchedulerRules(draft!, baselineVersion!)
      } catch (error) {
        if (!(error instanceof ApiClientError) || error.status !== 409) throw error
        let latest
        try {
          latest = await getSchedulerRules()
        } catch {
          throw new Error('Workspace changed and the latest rules could not be checked. Your draft was kept.', { cause: error })
        }
        if (!latest.data || !latest.workspace_version) {
          throw new Error('Workspace changed and the latest rules could not be checked. Your draft was kept.', { cause: error })
        }
        if (JSON.stringify(latest.data.rules) !== JSON.stringify(baseline)) {
          throw new Error('Rules changed elsewhere. Your draft was kept; reload when you are ready to review the latest rules.', { cause: error })
        }
        try {
          return await saveSchedulerRules(draft!, latest.workspace_version)
        } catch (retryError) {
          if (retryError instanceof ApiClientError && retryError.status === 409) {
            throw new Error('Workspace is still changing. Your draft was kept; try Save Rules again.', { cause: retryError })
          }
          throw retryError
        }
      }
    },
    onSuccess: async (response) => {
      if (response.data) {
        const saved = structuredClone(response.data.rules)
        setDraft(saved); setBaseline(structuredClone(saved)); setView(response.data)
      }
      setBaselineVersion(response.workspace_version ?? baselineVersion)
      setMessage(response.warnings.join(' ') || 'Scheduling Rules Saved.')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: schedulerSessionKey }),
        queryClient.invalidateQueries({ queryKey: schedulerRulesKey }),
      ])
    },
  })
  const reconciliationMutation = useMutation<ApiEnvelope<ReconciliationReport>, Error>({
    mutationFn: () => apiRequest<ReconciliationReport>('/api/scheduler/rules/reconciliation'),
    onSuccess: () => setReconciliationOpen(true),
  })

  function updateRule(path: string[], value: unknown) {
    setDraft((current) => {
      const next = structuredClone(current ?? {})
      let target = next
      for (const key of path.slice(0, -1)) {
        if (!target[key] || typeof target[key] !== 'object' || Array.isArray(target[key])) target[key] = {}
        target = target[key] as Record<string, unknown>
      }
      target[path.at(-1)!] = value
      return next
    })
    setMessage('')
  }

  async function reloadCanonical() {
    const response = await rulesQuery.refetch()
    if (!response.data?.data) return
    const fresh = structuredClone(response.data.data.rules)
    setDraft(fresh); setBaseline(structuredClone(fresh)); setView(response.data.data)
    setBaselineVersion(response.data.workspace_version); setMessage('Canonical Rules Reloaded.'); setReloadOpen(false)
  }

  if (!validSection) return <Navigate replace to="/schedule/rules/constraints" />

  return <div className={`${styles.page} ${styles.workspacePage}`}>
    <WorkspaceHeader
      actions={<span className={styles.dirtyState}>{dirty ? 'Unsaved Changes' : 'Workspace Aligned'}</span>}
      context={baselineVersion ? 'Canonical Constraints and Preferences' : 'Rules Workspace Needs Review'}
      title={PAGE_TITLES.schedulingRules}
    />
    <div className={styles.rulesWorkbench}>
      <nav aria-label="Rules sections" className={styles.rulesNavigation}>
        <p className={`${styles.scopeLegend} ${styles.rulesNavigationLabel}`}>Configuration</p>
        {RULE_SECTIONS.map((item) => <Link aria-current={activeSection === item.id ? 'page' : undefined} key={item.id} to={`/schedule/rules/${item.id}`}><strong>{item.label}</strong><span>{item.description}</span></Link>)}
        {view ? <RulesMetadata view={view} /> : null}
      </nav>
      <WorkspaceSurface className={styles.rulesEditorSurface}>
        <WorkspaceToolbar className={styles.actionRail}><div><strong>Canonical Rules</strong><span>Each editor updates one shared draft; saving commits the complete rules document.</span></div><div className={styles.rulesToolbarActions}><Button loading={reconciliationMutation.isPending} loadingLabel="Checking Data Integrity" onClick={() => reconciliationMutation.mutate()} variant="secondary">Check Data Integrity</Button><Button onClick={() => dirty ? setReloadOpen(true) : void reloadCanonical()} variant="secondary">Reload Rules</Button></div></WorkspaceToolbar>
        {sessionQuery.isPending || rulesQuery.isPending || !draft ? <div aria-label="Loading scheduler rules" className={`${styles.skeleton} ${styles.rulesSkeleton}`} /> : null}
        <InlineError error={sessionQuery.error ?? rulesQuery.error ?? saveMutation.error ?? reconciliationMutation.error} />
        {sessionQuery.isError || rulesQuery.isError ? <Button onClick={() => void Promise.all([sessionQuery.refetch(), rulesQuery.refetch()])} variant="secondary">Retry Rules Workspace</Button> : null}
        {draft && activeSection === 'constraints' ? <ConstraintsEditor disabled={readOnly || saveMutation.isPending} onChange={updateRule} rules={draft} /> : null}
        {draft && activeSection === 'priorities' ? <PrioritiesEditor disabled={readOnly || saveMutation.isPending} instructors={sessionQuery.data?.data?.instructors ?? []} onChange={updateRule} rules={draft} /> : null}
        {draft && activeSection === 'resolution' ? <ResolutionRulesEditor disabled={readOnly || saveMutation.isPending} instructors={sessionQuery.data?.data?.instructors ?? []} onChange={updateRule} rules={draft} /> : null}
        {draft && activeSection === 'rooms' ? <RoomsEditor disabled={readOnly || saveMutation.isPending} instructors={sessionQuery.data?.data?.instructors ?? []} onChange={updateRule} roomIds={rooms} rules={draft} sourcePreferences={sessionQuery.data?.data?.source_preferences ?? []} /> : null}
        {message ? <p className={`${styles.persistentStatus} ${styles.rulesPersistentStatus}`} role="status">{message}</p> : null}
        <div className={styles.rulesCommandBar}><span>{dirty ? 'Canonical draft has unsaved changes.' : 'Canonical rules are up to date.'}{dirty && !validTimes ? ' Enter both operating times as HH:MM before saving.' : ''}</span><Button disabled={!dirty || !validTimes || !baselineVersion || saveMutation.isPending || readOnly} onClick={() => saveMutation.mutate()}>Save Rules</Button></div>
      </WorkspaceSurface>
    </div>
    <Dialog.Root onOpenChange={setReloadOpen} open={reloadOpen}><Dialog.Portal><Dialog.Overlay className={styles.dialogOverlay} /><Dialog.Content className={styles.dialogContent}><Dialog.Title>Discard Unsaved Rule Changes?</Dialog.Title><Dialog.Description>Reloading replaces the shared Rules draft with the latest canonical workspace version.</Dialog.Description><div className={styles.dialogActions}><Dialog.Close asChild><Button variant="secondary">Keep Editing</Button></Dialog.Close><Button onClick={() => void reloadCanonical()}>Discard and Reload</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root onOpenChange={setReconciliationOpen} open={reconciliationOpen}><Dialog.Portal><Dialog.Overlay className={styles.dialogOverlay} /><Dialog.Content className={`${styles.dialogContent} ${styles.reconciliationDialog}`}><Dialog.Title>Data Integrity Check</Dialog.Title><Dialog.Description>Compare imported source rows with the current Resolution draft. This diagnostic does not change the schedule.</Dialog.Description>{reconciliationMutation.data?.data ? <ReconciliationResults report={reconciliationMutation.data.data} /> : null}<div className={styles.dialogActions}><Dialog.Close asChild><Button variant="secondary">Close</Button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}

function ReconciliationResults({ report }: { report: ReconciliationReport }) {
  const sourceRequests = report.source_request_count ?? report.source_row_count
  const assigned = report.assigned_count ?? report.matches.filter((item) => item.assignment_id).length
  const unresolved = report.unresolved_count ?? report.matches.filter((item) => !item.assignment_id).length
  const accounted = report.accounted_request_count ?? report.matches.length
  const duplicateCount = report.duplicates?.length ?? 0
  return <div className={styles.reconciliationResults}>
    <dl><div><dt>Source Rows</dt><dd>{report.source_row_count}</dd></div><div><dt>Source Requests</dt><dd>{sourceRequests}</dd></div><div><dt>Assigned</dt><dd>{assigned}</dd></div><div><dt>Unresolved</dt><dd>{unresolved}</dd></div><div><dt>Accounted</dt><dd>{accounted}/{sourceRequests}</dd></div><div><dt>Needs Review</dt><dd>{report.missing.length + report.phantom.length + duplicateCount}</dd></div></dl>
    {!report.source_row_count ? <p className={styles.reconciliationEmpty}>Import Weekly or Studio source data before running this check.</p> : null}
    {report.missing.length ? <section><h3>Missing Assignments</h3><div className={styles.reconciliationTable}><table><thead><tr><th>Student</th><th>Instructor</th><th>Day</th><th>Time</th></tr></thead><tbody>{report.missing.map((item, index) => <tr key={`${item.Student}-${index}`}><td>{item.Student || 'Unknown'}</td><td>{item.Instructor || 'Unknown'}</td><td>{item.Day || '—'}</td><td>{item.Time || '—'}</td></tr>)}</tbody></table></div></section> : null}
    {report.phantom.length ? <section><h3>Assignments Without a Source Row</h3><ul>{report.phantom.map((item, index) => <li key={`${item.assignment_id}-${index}`}><strong>{item.assignment_id || 'Unknown assignment'}</strong><span>{item.details || 'No matching source row.'}</span></li>)}</ul></section> : null}
    {duplicateCount ? <section><h3>Duplicate Source Requests</h3><ul>{report.duplicates?.map((item, index) => <li key={`${item.source_request_id}-${index}`}><strong>{item.source_request_id || 'Unknown request'}</strong><span>{item.assignment_ids?.join(', ') || 'Multiple assignments'}</span></li>)}</ul></section> : null}
    {report.source_row_count > 0 && !report.missing.length && !report.phantom.length ? <p className={styles.reconciliationSuccess}>Every current assignment matches an imported source row.</p> : null}
  </div>
}
