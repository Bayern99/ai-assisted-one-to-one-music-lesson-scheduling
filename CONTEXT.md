# AI-Assisted One-to-One Music Lesson Scheduling

Desktop workspace for auditable one-to-one music-instruction scheduling. This glossary is the occupancy, Step 4, and rules-layer judgement language for the 4.7–4.8.1 work. It is not an implementation spec.

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
