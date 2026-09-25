# PI Reconciliation: UI/UX Architecture & Interaction Design Specification

**Document Version:** `1.3.0` (Production Polish & Clean Human Decision Surface)  
**Status:** Approved Canonical Design Specification  
**Scope:** Step 5 Resolve Schedule — PI Reconciliation Decision Surface  
**Constraint:** UI/UX presentation layer only. Scheduling backend, optimizer solver, validation rules, data contracts, and timetable logic remain authoritative and unchanged.

---

## 1. Executive Summary & Core Product Principle

### 1.1 The Primary Job of PI Reconciliation
**PI Reconciliation is a human decision surface, not an AI explanation dashboard, KPI monitor, or solver status console.**

Its primary mission is to allow an academic scheduler to answer, within **2 to 3 seconds**:
1. **Who** is being changed?
2. **At what time?**
3. **From which room?**
4. **To which room?**

The most critical, visually dominant information unit on the screen is the **concrete proposed intervention row**:
```text
Teacher012    10:00–19:00    CC320 → CC405
```

Summaries such as *"10 lessons placed"* or *"2 room moves"* are useful secondary outcomes, but they must **never** visually overpower or push the concrete changes out of the center.

### 1.2 Elimination of Internal Design Meta-Labels
Internal design classifications such as:
- `"Change rows"`
- `"Secondary outcome"`

must **never** appear in the user-facing interface. The spatial grouping, typographic hierarchy, and visual adjacency of the change row, followed directly by the checkmark outcome, make their meaning completely self-evident without artificial meta-labels.

---

## 2. Division of Labor & Interactive Verification

| Area | Primary Responsibility | Information Content & Interaction Model |
| :--- | :--- | :--- |
| **Left Side**<br>*(Reconciliation Panel)* | **Decision Surface** | • Compact status & proposal identity<br>• Dominant operational change rows (`Who + When + From + To`)<br>• Secondary placement outcome (`✓ 10 previously unplaced lessons can now be scheduled`)<br>• Directly attached primary decision CTA (`[Apply Option A]` / `[Defer]`)<br>• Progressive disclosures for deep audit (collapsed by default) |
| **Right Side**<br>*(Timetable Grid)* | **Verification Surface** | • Exact lesson blocks with real start/end times and gaps<br>• Visual spatial proof of non-conflict<br>• **Contextual Interactive Verification:** Hovering or selecting a proposed change row on the left temporarily highlights the corresponding exact lesson blocks on the timetable on the right with a clean accent highlight border/glow.<br>• No permanent arrows, overlay clutter, or tangled lines. |

---

## 3. Operational Change Row (The Core Atomic Unit)

### 3.1 The 4-Tuple Visual Adjacency Rule
Every proposed intervention is presented as a unified, self-contained row:
```text
[ Teacher ]        [ Time Span ]        [ Room Change ]
Teacher012         10:00–19:00          CC320 → CC405
Teacher018         10:00–13:00          CC322 → CC407
```
`Who + When + From + To` must remain strictly adjacent in a single horizontal scanning line. The scheduler never has to assemble disconnected information across multiple cards.

### 3.2 Operational Time Span Summarization
On the decision surface, the panel does not burden the user with fragmented individual lessons when a teacher's schedule forms a continuous operational teaching span:
* **Timetable reality:** `10:00–12:00 (Lesson 1)`, `13:00–17:00 (Lessons 2–5)`, `18:00–19:00 (Lesson 6)`
* **Decision summary:** `10:00–19:00` (representing the teacher's day span in that room)
* *Rule:* Genuinely major multi-hour gaps keep their periods separate. The underlying lessons, optimizer data, and timetable rendering remain 100% exact.

---

## 4. Visual Hierarchy & Progressive Disclosure

### 4.1 Strict 4-Level Visual Weight
```text
Level 1 (Dominant Visual Focus)
  └── Concrete Change Rows: "Teacher012 · 10:00–19:00 · CC320 → CC405"

Level 2 (Secondary Structural Weight)
  ├── Secondary outcome: "✓ 10 previously unplaced lessons can now be scheduled"
  ├── Compact status indicator near header (no giant banner)
  └── Attached Primary CTA: "[Apply Option A]"

Level 3 (Progressive Disclosure — Collapsed by Default)
  └── "▾ View 18 lesson changes" (audit table with student, time, rooms)

Level 4 (Secondary Surfaces — Collapsed by Default)
  ├── "▸ Refine conditions with Pi" (secondary text input)
  └── "▸ Technical details" (simulation IDs, logs, validation trace)
```

### 4.2 Compact Top Status Indicator
* **Rule:** Do NOT use a prominent full-width banner row for system status. “Ready to apply / Search cap reached / Validated package ready to apply” must never push the core decision unit down.
* **Refined Placement:** A compact, quiet validity pill (e.g. `● Ready to apply`) sits directly inline or adjacent to the option header, accompanied by a small subtext note if the search bound was reached.

---

## 5. Single-Option Information Architecture

When one package is proposed (Option A), the layout flows top-to-bottom without redundant meta-headers:

```text
┌─────────────────────────────────────────────────────────────┐
│ PI Reconciliation                             [ EN | 中文 ] │
├─────────────────────────────────────────────────────────────┤
│ Option A (Recommended)   ● Ready to apply                   │
│                                                             │
│ Teacher012    10:00–19:00    CC320 → CC405   (hovered) ───┐ │
│ Teacher018    10:00–13:00    CC322 → CC407                │ │
│                                                           │ │
│ ✓ 10 previously unplaced lessons can now be scheduled     │ │
│                                                           │ │
│ [ Apply Option A ]             [ Defer ]                  │ │
├───────────────────────────────────────────────────────────┼─┤
│ ▸ View 18 lesson changes (collapsed)                      │ │
├───────────────────────────────────────────────────────────┤ │
│ ▸ Refine conditions with Pi (collapsed)                   │ │
├───────────────────────────────────────────────────────────┤ │
│ ▸ Technical details (collapsed)                           │ │
└───────────────────────────────────────────────────────────┴─┘
                                                            │
                     Timetable on Right:                    ▼
          ┌────────────────────────────────────────────────────┐
          │ CC320  [ Teacher012 10:00–19:00 ] (highlighted)    │
          │ CC405  [ (Destination target)   ] (highlighted)    │
          └────────────────────────────────────────────────────┘
```

---

## 6. Multiple Feasible Options Architecture (Difference-First)

When both Option A and Option B are feasible, the interface isolates differences into a clean, restrained comparison matrix.

### 6.1 Symmetrical Differentiators & Subtle Recommendation
Both options receive an equivalent short differentiator supported by package data. The `(Recommended)` tag on Option A is kept subtle and quiet so it does not visually bias the page to the point where comparative decision-making is eclipsed:
* **Option A:** `Fewer moves` (with quiet `(Recommended)` label)
* **Option B:** `Keeps preferred studios`

### 6.2 Neutral Surfaces & Restrained State Tinting
- The difference matrix uses **neutral white surfaces (`--raised: #ffffff`)** and subtle hairline borders (`1px solid var(--structure)`).
- Default cell backgrounds are clean and untinted. No permanent green, red, or amber cell fills.
- Accent tinting (`--accent-soft: #f4e3df`) is reserved exclusively for **hover, active selection, and contextual verification states**.

### 6.3 Per-Column Summary Values
In the summary rows, **each option column contains its own distinct numeric value**:

| Metric | Option A *(Fewer moves)* | Option B *(Keeps preferred studios)* |
| :--- | :---: | :---: |
| **Teacher018** `10:00–13:00` | `CC322 → CC405` | `CC322 → CC407` |
| **Teacher021** `09:00–18:00` | `—` | `CC129 → CC320` |
| **Room moves** | `2` | `4` |
| **Lessons placed** | `10` | `10` |
| **Action** | `[ Apply Option A ]` | `[ Apply Option B ]` |

*(Anti-pattern eliminated: Columns never display duplicated strings like `2 vs 4` or `10 vs 10`.)*

### 6.4 Collapsed Shared Changes
Changes that are identical across both options (such as `Teacher012 10:00–19:00 CC320 → CC405`) are collapsed by default under:
```text
▸ Shared changes (12 items) (click to inspect)
```

---

## 7. Visual Language Alignment & Product Continuity (PI Dashboard Tokens)

The Reconciliation screen is not a standalone app or an external dashboard. It belongs strictly inside the existing PI Dashboard design system:

### 7.1 Authoritative Design Tokens (`tokens.css`)
- **Theme:** Strict light mode (`color-scheme: light;`). No dark theme in the workspace.
- **Canvas & Surfaces:**
  - Canvas: `--canvas: #e8eaed`
  - Surface: `--surface: #f4f5f6`
  - Subtle Surface: `--surface-subtle: #f8f8f8`
  - Raised Panels & Cards: `--raised: #ffffff`
  - Grid background: `--grid: #fafbfb`
- **Typography:**
  - UI Font: `'Relative', -apple-system, BlinkMacSystemFont, sans-serif`
  - Monospace: `ui-monospace, 'SFMono-Regular', Menlo, Monaco, monospace` (for times, room codes, numbers)
- **Palette & Contrast:**
  - Primary text / ink: `--ink: #202227`
  - Secondary text: `--ink-soft: #4e525a`, `--muted-readable: #656a73`
  - Borders & Hairlines: `--structure: rgba(32,34,39,0.09)`, `--structure-strong: rgba(32,34,39,0.16)`
- **Accent & State Colors:**
  - Primary Accent: Terracotta Coral `--accent: #c35f49`, `--accent-readable: #a34734`
  - Soft Tint: `--accent-soft: #f4e3df` (used for active highlights and selections)
  - Warning: `--warning-readable: #7f3e31`, `--warning-soft: #f6ebe7`
  - Error: `--error: #a94734`, `--error-soft: #f6ebe7`
  - Valid / Placed: Quiet dark green / neutral checkmark
  - *No saturated primary blues, neon status badges, or rainbow table cells.*
- **Buttons (`global.css`):**
  - Primary CTA (`.button--primary`): Solid dark charcoal ink `#202227` with white text `#ffffff`, border-radius `6px` (`var(--radius-sm)`).
  - Secondary CTA (`.button--secondary`): Light subtle background `#f8f8f8`, charcoal text `#202227`, hairline border `var(--structure-strong)`.
  - Selected / Active (`.button--selected`): Accent readable text `#a34734` on soft peach `#f4e3df`.

### 7.2 Application Shell & Navigation Continuity
- **Sidebar Rail (`WorkspaceRail`):**
  - 176px wide, dark slate `--rail: #27292e`.
  - Brand block: `PI` badge + `Dashboard LOCAL SCHEDULER`.
  - Workspace nav: Overview, Schedule (active highlighted `#383b42`), Source Data, Jury, Assessment.
  - Workflow stepper: `01 Import Lectures`, `02 Import Sources`, `03 Configure Rules`, `04 Run Optimizer`, `05 Resolve Schedule` (active with terracotta `#c35f49` circled `05` and bold white text), `06 Export Schedule`.
  - Bottom rail: `Local workspace active`, `A- 100% A+` text size controls.
- **Top Header (`WorkspaceHeader`):**
  - Title: `Resolve Schedule`, context: `Monday · Teacher blocks`.
  - Mode switches: Pill segmented controls `[ Timetable | Reconciliation 15 ]` and `[ Lessons | Teachers ]`.
- **Right Timetable Grid (`ScheduleGrid`):**
  - Rooms on Y-axis (`CC320`, `CC322`, `CC405`, `CC407`), Hours on X-axis (`09:00` to `19:00`).
  - Day selector tabs (`[ Mon ] Tue Wed Thu Fri Sat Sun`).
  - Timetable verification: Hovering a change row on the left illuminates the corresponding block on the right with a 2px terracotta border (`#c35f49`) and soft tint (`#f4e3df`), removing instantly on unhover.

### 7.3 Code Tokens as Authoritative Source of Truth
Generated mockups serve as visual-direction and layout alignment illustrations. In implementation, the actual existing production shell (`AppShell`, `V7Shell`, `WorkspaceHeader`, `ScheduleGrid`) and CSS tokens (`tokens.css`, `global.css`) are the authoritative source of truth. Any visual or textual artifact from mockups (such as AI-rendered placeholder text) is non-authoritative.

---

## 8. Verification & Pre-Flight Checks

Before deploying any Reconciliation visual asset, verify both criteria:

### Check 1: The 2–3 Second Readability Check
> Can the academic scheduler identify within 2.5 seconds:
> 1. Which teacher?
> 2. At what operational time?
> 3. From which room?
> 4. To which room?

### Check 2: Product Continuity Check
> If the text "PI Reconciliation" were masked out, is it immediately obvious that this screen belongs to the PI Dashboard?
> - Presence of the dark 176px rail with `05 Resolve Schedule` active
> - Off-white canvas and white raised cards with hairline `0.09` borders
> - Relative typography and monospace numerical identifiers
> - PI Dashboard signature dark charcoal ink primary button (`#202227`)
> - Authentic timetable grid with room Y-axis, time X-axis, and subtle terracotta hover highlight

