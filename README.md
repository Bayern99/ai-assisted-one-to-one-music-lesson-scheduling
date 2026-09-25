# AI-Assisted One-to-One Music Lesson Scheduling

Local workspace for building one-to-one music-lesson timetables in a higher-education music programme. Import weekly and studio requests, lock lecture rooms, allocate with a deterministic solver, reconcile the leftovers on the board, then Finalize and export. Companion to the ICEMT 2026 paper *An AI-Assisted Coordination Framework for Music Programme Administration in Higher Education*.

The central student-record and room-booking systems stay the record of truth. This app is a local coordination layer for demo and research: it produces a checked timetable you can hand over.

Version: `0.1.0`.

## Platform

| | |
|---|---|
| OS | macOS 14+ for the native app; any Unix with Python/Node for browser development |
| Runtime | Loopback only (`127.0.0.1`). Not a hosted service. |
| Native app | SwiftUI/AppKit shell (`native-shell/`) owns the window and starts FastAPI as a child process; WKWebView loads the React UI |
| Development | Vite on port **5173**, FastAPI/uvicorn on port **8502** |
| Data | JSON workspace in `PI_DATA_DIR` (default `./data`). Keep live student files out of git. |

## Architecture

```text
Operator
  ├─ macOS app (Swift + WKWebView)     or     browser (Vite)
  └─ React  (collects intent, draws the board)
        │  HTTP /api
        ▼
     FastAPI  (Python 3.9+)
        ├─ RoomAllocator          deterministic assignment
        ├─ Step 4 validator       assign / move / unassign
        ├─ Stage / Finalize       L0 draft → L1 snapshot → L2 commit
        └─ Pi RPC (optional)      local coding-agent subprocess
              inspect → simulate in Python sandbox → submit brief
              operator applies; Pi never writes the ledger
        │
        ▼
     PI_DATA_DIR  (students, rooms, bookings, session, rules)
```

Python is the only scheduling authority. React does not decide occupancy. Mutations keep canonical identity, `assigned XOR unresolved`, workspace-version freshness, and atomic JSON writes. **Stage** copies the live draft (L0) into a non-locking snapshot (L1). **Finalize** is the only commit to current occupancy (L2).

## Pi agent

“AI-Assisted” here means a **bounded Pi investigator on Resolve**, not a model that writes the timetable.

On `/schedule/resolve` the operator can start a whole-day investigation. Pi runs as a local subprocess (`~/.pi/agent` by default, Cursor provider `cursor-grok-4.5` unless you pick another model in the panel). It may only:

1. **Inspect** the day’s unresolved work and linked occupancy (aliased student ids).
2. **Simulate** complete room-change packages against the Python sandbox.
3. **Submit one brief** — a recommended package plus disclosed costs (second room, a named sacrifice, a time-change exception if you authorised it).

Python projects the brief into a **Decision Brief**:
- **Decision Surface Architecture**: The reconciliation panel acts as a human decision surface. The primary visual unit is the concrete proposed change row: `Teacher | Operational time span | From room → To room` (e.g., `Teacher012 10:00–19:00 CC320 → CC405`), keeping Who + When + From + To visually adjacent while secondary counts (room moves, lessons placed) remain subordinate.
- **Contextual Timetable Verification**: Hovering or selecting any proposed change row on the left temporarily highlights the affected teacher's exact lesson blocks and room positions on the production timetable on the right, enabling rapid visual verification without cluttering or altering the board.
- **Difference-First Matrix**: In A/B comparison mode, options are compared side-by-side with hairline borders and subtle hover/active states. Each column displays its own concrete assignment rather than combined diff strings, while common shared moves, lesson-level audits, Pi refinements, and technical diagnostics remain collapsed by default.
- Continue turns are same-day revisions (diffing against previous constraints). Phrases like “leave this teacher alone” / “may change time” become hard constraints before the next sandbox run; unmatched goal text stays a preference. The PI Reconciliation panel is Chinese by default with an English switch; the rest of the app stays English.

Scheduled times stay fixed unless the operator listed a time-change exception. Pi cannot assign, move, unassign, Stage, or Finalize. Applying a brief still goes through Python validation; the human confirms teachers and presses apply.

A long investigation is not a black box: the panel shows the run’s phases (`investigating`, `saving_reconciliation`), elapsed time, provider retries, and tool-call / simulation counts from a bounded operation event stream, and it re-attaches to a running operation after a page reload.

Without Pi installed the rest of the product still runs: import, rules, optimizer, manual Resolve, Stage, Finalize, export.

## How to use a round

1. **Source Data** (`/students`) — roster context used for identity matching.
2. **Lectures** (`/schedule/lectures`) — import registry classes that occupy specialised rooms.
3. **Import** (`/schedule/import`) — Weekly and Studio workbooks; times and student numbers are normalised here.
4. **Rules** (`/schedule/rules`) — time windows, room types, instructor preference, piano / voice constraints. Rules live in JSON, not in the solver code. The page states what a save does and does not change (it governs the next Optimizer run and every Step 4 validation, but never rewrites the current draft, staged, or finalized layers by itself), shows live workspace state, and guards an unsaved draft when you leave.
5. **Optimize** (`/schedule/optimize`) — `RoomAllocator` fills the board. Every leftover lesson has a stable `reason_code`.
6. **Resolve** (`/schedule/resolve`) — drag or command assign / move / unassign. Optional: run Pi on the day, review the sandbox brief, apply. Then **Stage**, then **Finalize**.
7. **Export** (`/schedule/export`) — Master, Weekly, and Studio workbooks for central booking.

Start a new round only after exports are saved. Committed assignments carry forward as locks.

## Requirements

**Always**

- Python **3.9+** (3.12 is fine) with pip
- Node.js **^20.19**, **^22.12**, or newer
- Python packages: `requirements.txt`  
  pandas, pydantic, openpyxl, xlsxwriter, python-docx, FastAPI, uvicorn, python-multipart
- Frontend: `frontend/package.json` (React 19, Vite 8, TanStack Query, dnd-kit)

**Native macOS app**

- Xcode Command Line Tools (`swift`, `xcrun`, `codesign`)
- Double-click `Install Scheduler.command`, or `./script/build_and_run.sh --install`

**Pi investigator**

- Pi coding agent on the machine (`pi` on `PATH`, settings under `~/.pi/agent`)
- Cursor provider extension at `~/.pi/agent/npm/node_modules/@rahularya01/pi-cursor/` for the default Cursor models
- Override with `PI_CODING_AGENT_DIR`, `PI_PROVIDER`, `PI_PROVIDER_EXTENSION` if needed

## Run (browser development)

```bash
python3 -m pip install -r requirements.txt
cd frontend && npm install && cd ..

export PI_BOOTSTRAP_TOKEN="local-development-token"
export PI_DATA_DIR="$PWD/data"
python3 -m uvicorn modules.api.runtime:app --host 127.0.0.1 --port 8502
```

Second terminal:

```bash
cd frontend && npm run dev
```

Open `http://127.0.0.1:5173/?bootstrap=local-development-token`. Vite proxies `/api` to port 8502. The first hit exchanges the bootstrap token for an HttpOnly session cookie.

## Run (macOS app)

```bash
./Install\ Scheduler.command
```

or `./script/build_and_run.sh --install`, then `./Start\ Scheduler.command`. The app listens on a free loopback port and tears FastAPI down when the window closes.

## Tests

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
cd frontend && npm test
```

## License

[GNU General Public License v3.0](LICENSE) or later. Copyright © 2026 Jiarui Duan.

Fork, change, and share. If you distribute your version, it must stay under GPL-3.0 (or later): same license, source included. Using it only inside your own organization does not require publishing your changes.
