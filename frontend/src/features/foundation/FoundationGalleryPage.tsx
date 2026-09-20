import { useState } from 'react'
import { Button } from '../../components/common/Button'
import { Field } from '../../components/common/Field'
import { TimeInput } from '../../components/common/TimeInput'
import {
  DataTable,
  EmphasisSurface,
  Section,
  WorkspaceHeader,
  WorkspaceSurface,
  WorkspaceToolbar,
} from '../../components/workspace/WorkspacePrimitives'
import styles from './foundationGallery.module.css'

export function FoundationGalleryPage() {
  const [selected, setSelected] = useState('R103')
  const [startTime, setStartTime] = useState('09:00')
  const [invalidTime, setInvalidTime] = useState('25:00')

  return (
    <div className={styles.page}>
      <WorkspaceHeader context="Development-only visual contract" title="Foundation Proof" />
      <WorkspaceToolbar>
        <Button>Primary action</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="quiet">Quiet</Button>
        <Button variant="destructive">Destructive</Button>
        <Button variant="selected">Selected</Button>
        <Button disabled>Disabled</Button>
        <Button loading loadingLabel="Working…">Loading</Button>
      </WorkspaceToolbar>
      <WorkspaceSurface className={styles.content}>
        <Section description="Relative Book, Medium and Bold at operational sizes." title="Typography">
          <div className={styles.typeSpecimen}>
            <h2>Resolve Schedule</h2>
            <h3>Needs Resolution</h3>
            <p>Review the selected assignment, validate the proposal, and preserve the canonical schedule.</p>
            <span className={styles.meta}>R103 · Monday · 09:00–10:00 · workspace-version</span>
          </div>
        </Section>
        <Section description="Native controls share one label, help, error and focus contract." title="Controls">
          <div className={styles.controlGrid}>
            <Field helper="Canonical room used for this proposal." label="Room">
              <select onChange={(event) => setSelected(event.target.value)} value={selected}>
                <option>R103</option>
                <option>R104</option>
              </select>
            </Field>
            <Field label="Start time"><TimeInput onChange={(event) => setStartTime(event.target.value)} value={startTime} /></Field>
            <Field error="Choose a time within the visible schedule." label="Invalid time">
              <TimeInput aria-invalid="true" onChange={(event) => setInvalidTime(event.target.value)} value={invalidTime} />
            </Field>
            <Field helper="Unavailable while a command is pending." label="Disabled field">
              <input disabled value="Canonical draft" readOnly />
            </Field>
          </div>
        </Section>
        <Section description="Representative dense table state." title="Data Table">
          <DataTable>
            <table>
              <thead><tr><th>Student</th><th>Course</th><th>Room</th><th>Total</th><th>Status</th></tr></thead>
              <tbody>
                <tr><td>Student 0001</td><td>MUS101</td><td className="room">R103</td><td className="numeric">84.5</td><td>Ready</td></tr>
                <tr><td>Student 0002</td><td>MUS201</td><td className="room">R104</td><td className="numeric">78.0</td><td>Needs review</td></tr>
              </tbody>
            </table>
          </DataTable>
        </Section>
        <div className={styles.messages}>
          <EmphasisSurface tone="completion"><strong>Schedule saved</strong><p>The canonical draft is up to date.</p></EmphasisSurface>
          <EmphasisSurface tone="warning"><strong>Proposal needs review</strong><p>The preferred room is not available.</p></EmphasisSurface>
          <EmphasisSurface tone="error"><strong>Validation failed</strong><p>Keep the current draft and revise the affected field.</p></EmphasisSurface>
        </div>
      </WorkspaceSurface>
    </div>
  )
}
