# AI-Assisted One-to-One Music Lesson Scheduling

Desktop workspace for auditable one-to-one music-instruction scheduling. This glossary is the occupancy, Step 4, and rules-layer judgement language for the 4.7–4.8.3 work. It is not an implementation spec.

## Language

**Occurrence**:
One source request that must remain `assigned XOR unresolved`: one Weekly row, or one dated Studio token (`studio:{row}:{slot}:{time}`).
_Avoid_: Repeat, series-as-one-course, merged studio

**Instructor reservation**:
The hour a teacher has claimed on a weekday at a clock time. Identity is instructor + weekday + clock, not room. Weekly and that teacher's dated studios in the same weekday-clock are contents of this reservation, not fights over it.
_Avoid_: Conflict (for this self-stack), ignore, leak-by-merging-ids

**Reservation magnet**:
The room already holding this instructor reservation. If a Weekly occupies the same weekday-clock, that Weekly room wins. If not, the room of an already-placed sibling Studio in the same weekday-clock wins. Live 2026 data often uses a hole in the teacher's Weekly day, so the magnet is the first placed Studio room, not a Weekly at a different hour.
_Avoid_: Scattering later Studio dates into other rooms because the weekday fold thinks the first date occupies every week

**Lecture**:
A multi-hour academic class that occupies a room for its real start–end interval (types include `lecture`, `academic_lecture`, and `locked_lecture`). In Chinese product talk this is 大课.
_Avoid_: 讲座 (that word means a talk/seminar, not this occupancy object)

**Contention**:
A fight for a room-hour that is not the same teacher's own reservation contents: another instructor, a Lecture lock, or two of the same teacher's studios overlapping on the same calendar date (a preflight miss).
_Avoid_: Calling weekday-folded same-teacher Studio vs Weekly a contention

**Reservation-internal**:
An Occurrence that stays unresolved because the frozen validator will not assign it onto the teacher's own Weekly, yet it belongs to an Instructor reservation. It is not operator work in the reconciliation queue. Export may still list it, with a reservation note.
_Avoid_: Covered, fake assigned, hidden from the ledger

**Reservation note**:
A Python-written, stable explanation on a reservation-internal Occurrence: Optimizer did not place it; the classifier detected it already sits in this teacher's weekday-clock reservation. Not a model-generated paragraph.
_Avoid_: Pi diagnosis as the occupancy reason

**L0 / L1 / Stage / Finalize**:
L0 is the live Step 4 draft (`assignments` + `unassigned_lessons`). Stage copies L0 PI into an independent L1 snapshot (`validation_authority`) and does not write `bookings.json`, set `round_committed`, or clear `dirty`. Ghosts are L1∖L0. Finalize is the only L2 commit. Editing means L0 has diverged from L1 (`unsealed` or stale).
_Avoid_: Treating Stage as Finalize; using committed bookings as the live PI lock while the operator is still editing L0

**Rules impact**:
What saving the canonical Rules document does and does not change. A save governs the next Run Optimizer and every Step 4 validation (room legality, priorities, time-change pool, operating window) but never rewrites existing layers by itself: the current draft keeps its placements until the Optimizer re-runs, and a staged or finalized schedule keeps the rules it was validated under until the operator re-Stages and re-Finalizes.
_Avoid_: Reading "saved" as "applied to the current draft"; assuming a save retroactively re-validates staged or finalized output

**Decision Brief**:
Python projection of one persisted whole-day investigation: options, shared common moves, comparison rows that exist only where A and B disagree, same-day revision effects, and the teacher/room context those options actually touch. Model prose is confined to `focus.question`, `unknowns`, and `agent_note`.
_Avoid_: Using Pi's note as the comparison; dumping both options' full change lists; treating an empty `diffs` as "show all changes"

**Common part**:
The intersection of two feasible options' normalized moves. Listed once; applied once (`scope=common`). Option cards then show only the remainder (`diffs`).
_Avoid_: Asking the operator to authorize the same shared move twice

**Revision**:
A continue turn on the same day, not a new case. Python diffs this investigation against the previous same-day record and reports what the new hard constraints did to the feasible set and the common part.
_Avoid_: Reading continue as "start over"; inventing revision copy in the client

**Operator constraint**:
Protect / time-change phrasing extracted clause-by-clause from the operator message into `protect_teachers` / `allow_time_change_teachers`, then validated by Python before simulation. Unmatched goal text stays a preference.
_Avoid_: Treating the whole goal string as a lock; protecting every named teacher in the sentence; sending constraints only as prompt flavour

**PI Reconciliation locale**:
Chinese/English chrome for the PI Reconciliation panel only (`zh` default, persisted). Known server labels and revision codes are localized in the client; model questions stay as written. The rest of the dashboard is already English.
_Avoid_: Whole-app i18n; translating `focus.question` / rationale; assuming English is the panel default

**Decision Surface Architecture**:
PI Reconciliation is an operational change-review surface, not a solver dashboard. The primary decision unit is the concrete proposed change row: `Teacher | Time span | From room → To room`. Operational time spans aggregate consecutive teacher lessons without losing exact room transition fidelity. Summaries (moves count, placed lessons) remain secondary.
_Avoid_: KPI cards as primary content; scattering teacher, time, and room across separate tables; forcing mental reconstruction of moves.

**Contextual Timetable Verification**:
Temporary, dynamic linkage between the left-side decision surface and the right-side timetable. Hovering or selecting a change row highlights the affected teacher's exact lesson blocks and room positions on the production timetable.
_Avoid_: Permanent visual clutter or arrows on the timetable; redesigning the production timetable layout.

**Difference-first Matrix**:
In A/B comparison mode, the matrix emphasizes points of divergence between candidate packages. Each option column displays its own concrete assignment (e.g. `CC322 → CC405` vs `CC322 → CC407`) rather than comparative diff strings (`X vs Y`).
_Avoid_: Merged cell diff strings; over-tinted comparison cards; strong visual bias that diminishes comparison clarity.
