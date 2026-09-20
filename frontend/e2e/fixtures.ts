/* eslint-disable no-empty-pattern, react-hooks/rules-of-hooks */
import { test as base, expect, type Page } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { createServer } from 'node:net'
import { once } from 'node:events'
import { cpSync, createWriteStream, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(here, '../..')
const token = 'music-lesson-scheduler-e2e-token'

const workbookScript = String.raw`
import pathlib, sys
import pandas as pd

target = pathlib.Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
with pd.ExcelWriter(target / 'scheduler.xlsx') as writer:
    weekly_rows = [
        {
            'Instructor': 'Instructor 0001', 'Day of Week': 'Monday',
            'Class Time': '09:00-10:00', 'Student No': 'S1',
            'Student Name': 'Student 0001', 'Course Code': 'MUS101 (Piano)',
            'Preferred Venue': 'R103',
        },
        {
            'Instructor': 'Instructor 0001', 'Day of Week': 'Monday',
            'Class Time': '10:00-11:00', 'Student No': 'S2',
            'Student Name': 'Student 0002', 'Course Code': 'MUS101 (Piano)',
            'Preferred Venue': 'R103',
        },
        {
            'Instructor': 'Instructor 0005', 'Day of Week': 'Monday',
            'Class Time': '09:00-10:00', 'Student No': 'S3',
            'Student Name': 'Cara Lim', 'Course Code': 'MUS101 (Piano)',
            'Preferred Venue': 'R103',
        },
        {
            'Instructor': 'Instructor 0006', 'Day of Week': 'Monday',
            'Class Time': '09:00-10:00', 'Student No': 'S4',
            'Student Name': 'Dan Wu', 'Course Code': 'MUS101 (Piano)',
            'Preferred Venue': 'R103',
        },
    ]
    pd.DataFrame(weekly_rows).to_excel(writer, sheet_name='Weekly Schedule', index=False)
    pd.DataFrame([{
        'Instructor': 'Instructor 0004', 'Instruments': 'Piano',
        'Studio 1 Date': '2026年3月30日 星期一',
        'Studio 1 Time': '13:00-14:00', 'Preferred Venue': 'R103',
    }]).to_excel(
        writer, sheet_name='Studio Schedule ', index=False, startrow=1,
    )
    pd.DataFrame([{
        'Room Number': 'R103', 'Piano Specifications': 'Yamaha upright piano',
    }]).to_excel(writer, sheet_name='Room', index=False)
    pd.DataFrame([
        {
            'Student No': 'S1', 'English Name': 'Student 0001', 'Chinese Name': '学生一',
            'Study Year': 1, 'Programme': 'Music', 'Instructor': 'Instructor 0001',
            'Instrument': 'Piano', 'Course Code': 'MUS101 (Piano)',
        },
        {
            'Student No': 'S2', 'English Name': 'Student 0002', 'Chinese Name': '学生二',
            'Study Year': 2, 'Programme': 'Music', 'Instructor': 'Instructor 0001',
            'Instrument': 'Piano', 'Course Code': 'MUS101 (Piano)',
        },
        {
            'Student No': 'S3', 'English Name': 'Cara Lim', 'Chinese Name': '',
            'Study Year': 1, 'Programme': 'Music', 'Instructor': 'Instructor 0005',
            'Instrument': 'Piano', 'Course Code': 'MUS101 (Piano)',
        },
        {
            'Student No': 'S4', 'English Name': 'Dan Wu', 'Chinese Name': '',
            'Study Year': 2, 'Programme': 'Music', 'Instructor': 'Instructor 0006',
            'Instrument': 'Piano', 'Course Code': 'MUS101 (Piano)',
        },
    ]).to_excel(writer, sheet_name='Student Info', index=False)
    pd.DataFrame([
        {'Instructor': 'Instructor 0001'},
        {'Instructor': 'Instructor 0005'},
        {'Instructor': 'Instructor 0006'},
    ]).to_excel(writer, sheet_name='Instructor', index=False)
    pd.DataFrame([{'Course Code': 'MUS101', 'Title': 'Piano'}]).to_excel(writer, sheet_name='Course Code', index=False)
`

const students = [
  { student_id: 's1', name_en: 'Student 0001', name_ch: '学生一', display_name: 'Student 0001 学生一', year: 1, instructor: 'Instructor 0001', instrument: 'Piano', type: 'Piano', course_code: 'MUS101', status: 'active', meta: { source: 'e2e' } },
  { student_id: 's2', name_en: 'Student 0002', name_ch: '学生二', display_name: 'Student 0002 学生二', year: 2, instructor: 'Instructor 0001', instrument: 'Piano', type: 'Piano', course_code: 'MUS201', status: 'active', meta: { source: 'e2e' } },
  { student_id: 's3', name_en: 'Cara Lim', year: 1, instrument: 'Violin', status: 'active' },
  { student_id: 's4', name_en: 'Dan Wu', year: 2, instrument: 'Cello', status: 'active' },
]

function writeJson(directory: string, name: string, value: unknown) {
  writeFileSync(path.join(directory, name), `${JSON.stringify(value, null, 2)}\n`, 'utf8')
}

function seedData(dataDir: string) {
  writeJson(dataDir, 'students.json', students)
  writeJson(dataDir, 'instructors.json', [{ name: 'Instructor 0001' }, { name: 'Instructor 0004' }, { name: 'Instructor 0005' }, { name: 'Instructor 0006' }])
  writeJson(dataDir, 'rooms.json', [{ id: 'R103', types: ['Piano'], capacity: 20 }])
  writeJson(dataDir, 'bookings.json', [])
  writeJson(dataDir, 'scheduling_rules.json', {
    room_types: { R103: ['Piano'] },
    priorities: { Piano: { Piano: 1 } },
    constraints: { time_range: { start: '08:00', end: '20:00' }, min_break_between_lessons: 0, enforce_instructor_blocks: false },
  })
  writeJson(dataDir, 'semester_config.json', { start_date: '2026-03-01', end_date: '2026-06-15' })
  writeJson(dataDir, 'workflow_state.json', { current_phase: 'scheduling' })
  writeJson(dataDir, 'activity_cache.json', {
    page_title: 'Smart Scheduler', page_name: 'Smart Scheduler',
    timestamp: '2026-07-12 09:30',
  })
  writeJson(dataDir, 'session_cache.json', {
    wk_df: [{ 'Student No': 's1', Instructor: 'Instructor 0001' }],
    stu_df: null,
    round_committed: false,
    step4_edit_session: {
      assignments: [{
        id: 'seed-assignment', type: 'weekly_lesson', title: 'Piano lesson',
        resourceId: 'R103', daysOfWeek: [1], startTime: '09:00:00', endTime: '10:00:00',
        extendedProps: { Instructor: 'Instructor 0001', 'Student Name': 'Student 0001', 'Student No': 's1' },
      }],
      unassigned_lessons: [
        {
          id: 'seed-issue-cara', issue_id: 'seed-issue-cara', source_request_id: 'seed-request-cara',
          type: 'weekly_lesson', reason_code: 'no_feasible_room_time', reason: 'No compatible room',
          raw_row: {
            Instructor: 'Instructor 0005', 'Student Name': 'Cara Lim', 'Student No': 's3',
            Instrument: 'Piano', 'Course Code': 'MUS101 (Piano)', 'Day of Week': 'Monday',
            'Class Time': '10:00-11:00', 'Preferred Venue': 'R103',
          },
        },
        {
          id: 'seed-issue-dan', issue_id: 'seed-issue-dan', source_request_id: 'seed-request-dan',
          type: 'weekly_lesson', reason_code: 'time_collision', reason: 'Time collision',
          raw_row: {
            Instructor: 'Instructor 0006', 'Student Name': 'Dan Wu', 'Student No': 's4',
            Instrument: 'Piano', 'Course Code': 'MUS101 (Piano)', 'Day of Week': 'Monday',
            'Class Time': '11:00-12:00', 'Preferred Venue': 'R103',
          },
        },
      ], history: [], redo_stack: [], dirty: false, last_save_outcome: null,
    },
  })
  writeJson(dataDir, 'jury_sessions.json', [{
    id: 'j1', name: 'Piano 1', instrument_filter: ['Piano'], cohort_filter: ['1'],
    room_id: 'R103', date: '2026-07-12', time_slot: 'Morning', time_start: '09:00',
    jury_panel: ['Instructor 0001'], jury_captain: 'Instructor 0001', students: ['s1', 's2', 's3', 's4'],
  }])
  writeJson(dataDir, 'conveners.json', [{ course_code: 'MUS101', course_title: 'Demo Course I (Piano)', convener_name: 'Instructor 0001', teachers: [], instrument_family: 'Piano', year_level: 1 }])
  writeJson(dataDir, 'assessments.json', [])
  writeJson(dataDir, 'jury_scores.json', [])
  writeJson(dataDir, 'score_templates.json', [{ id: 't1', name: 'Piano Jury', semester: 'Semester II', instrument_family: 'Piano', categories: [{ name: 'Technique', max_score: 40, description: '' }], total_score: 40, version: '1.0', created_at: '2026-01-01' }])
}

async function freePort() {
  const server = createServer()
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Could not allocate an E2E port')
  const port = address.port
  server.close()
  await once(server, 'close')
  return port
}

export function hasExited(child: Pick<ChildProcess, 'exitCode' | 'signalCode'>) {
  return child.exitCode !== null || child.signalCode !== null
}

export async function waitForExit(child: ChildProcess, timeout: number) {
  if (hasExited(child)) return true
  return new Promise<boolean>((resolve) => {
    let timer: NodeJS.Timeout | null = null
    let settled = false
    const finish = (exited: boolean) => {
      if (settled) return
      settled = true
      child.off('exit', onExit)
      if (timer) clearTimeout(timer)
      resolve(exited)
    }
    const onExit = () => finish(true)
    child.once('exit', onExit)
    // Close the gap between the initial state check and listener registration.
    if (hasExited(child)) {
      finish(true)
      return
    }
    timer = setTimeout(() => finish(false), timeout)
  })
}

async function waitForServer(
  baseURL: string,
  child: ChildProcess,
  logPath: string,
  getLogError: () => Error | null,
) {
  const deadline = Date.now() + 15_000
  while (Date.now() < deadline) {
    const logError = getLogError()
    if (logError) throw new Error(`Could not write E2E API log ${logPath}: ${logError.message}`, { cause: logError })
    if (hasExited(child)) {
      const outcome = child.exitCode !== null ? `code ${child.exitCode}` : `signal ${child.signalCode}`
      throw new Error(`E2E API exited early (${outcome}); log: ${logPath}`)
    }
    try {
      const response = await fetch(`${baseURL}/api/health`)
      if (response.ok) return
    } catch {
      // uvicorn has not bound its socket yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  throw new Error(`Timed out starting E2E API; log: ${logPath}`)
}

export interface E2EWorkspace {
  baseURL: string
  dataDir: string
  uploadsDir: string
  stopServer: () => Promise<void>
}

type Fixtures = { authenticatedPage: Page; e2e: E2EWorkspace }

export const test = base.extend<Fixtures>({
  e2e: async ({}, use) => {
    const root = mkdtempSync(path.join(tmpdir(), 'music-lesson-scheduler-e2e-'))
    const dataDir = path.join(root, 'data')
    const uploadsDir = path.join(root, 'uploads')
    mkdirSync(dataDir)
    mkdirSync(uploadsDir)
    cpSync(path.join(repoRoot, 'tests/fixtures/scheduler_harness'), path.join(root, 'scheduler_harness'), { recursive: true })
    seedData(dataDir)
    const generated = spawnSync(process.env.PYTHON ?? 'python3', ['-c', workbookScript, uploadsDir], { cwd: repoRoot, encoding: 'utf8' })
    if (generated.status !== 0) throw new Error(`Could not generate E2E workbooks: ${generated.stderr}`)
    writeFileSync(
      path.join(uploadsDir, 'lectures.csv'),
      'Course Code,Course Title & Session,Teachers,Class Schedule,Hours,Classroom\nMUS100,E2E Theory,Instructor 0007,Tue 16:00-17:00,1,R103\n',
      'utf8',
    )
    writeFileSync(path.join(uploadsDir, 'scores.csv'), 'Student Number,Student Name,Weekly Prep,Studio,Report\ns1,Student 0001,25,18,9\n', 'utf8')

    const port = await freePort()
    const baseURL = `http://127.0.0.1:${port}`
    const logPath = path.join(root, 'uvicorn.log')
    const log = createWriteStream(logPath)
    const child = spawn(process.env.PYTHON ?? 'python3', ['-m', 'uvicorn', 'modules.api.runtime:app', '--host', '127.0.0.1', '--port', String(port), '--no-access-log'], {
      cwd: repoRoot,
      env: { ...process.env, PI_BOOTSTRAP_TOKEN: token, PI_DATA_DIR: dataDir },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let logError: Error | null = null
    log.on('error', (error) => { logError = error })
    child.stdout?.pipe(log, { end: false })
    child.stderr?.pipe(log, { end: false })
    let childClosed = false
    const childClose = new Promise<void>((resolve) => {
      child.once('close', () => {
        childClosed = true
        resolve()
      })
    })
    const waitForClose = async (timeout: number) => {
      if (childClosed) return true
      return Promise.race([
        childClose.then(() => true),
        new Promise<false>((resolve) => setTimeout(() => resolve(false), timeout)),
      ])
    }
    let stopped = false
    const stopServer = async () => {
      if (stopped) return
      stopped = true
      if (!hasExited(child)) {
        child.kill('SIGTERM')
        if (!await waitForExit(child, 3_000)) {
          child.kill('SIGKILL')
          if (!await waitForExit(child, 3_000)) throw new Error(`Could not stop E2E API process ${child.pid ?? 'unknown'}`)
        }
      }
      if (!await waitForClose(3_000)) throw new Error(`E2E API output did not close for process ${child.pid ?? 'unknown'}`)
      if (!log.writableEnded && !log.destroyed) {
        const finished = Promise.race([
          once(log, 'finish'),
          once(log, 'error').then(([error]) => { throw error }),
        ])
        log.end()
        await finished
      }
      if (logError) throw new Error(`Could not write E2E API log ${logPath}: ${logError.message}`, { cause: logError })
    }

    try {
      await waitForServer(baseURL, child, logPath, () => logError)
      await use({ baseURL, dataDir, uploadsDir, stopServer })
    } finally {
      try {
        await stopServer()
      } finally {
        rmSync(root, { recursive: true, force: true })
      }
    }
  },

  authenticatedPage: async ({ browser, e2e }, use) => {
    const context = await browser.newContext({
      colorScheme: 'light',
      locale: 'en-SG',
      reducedMotion: 'reduce',
      timezoneId: 'Asia/Singapore',
      viewport: { width: 1440, height: 900 },
    })
    const page = await context.newPage()
    await page.goto(`${e2e.baseURL}/?bootstrap=${encodeURIComponent(token)}`)
    await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible()
    await expect(page).not.toHaveURL(/bootstrap=/)
    const session = await page.request.get(`${e2e.baseURL}/api/auth/session`)
    expect(session.status()).toBe(200)
    expect((await session.json()).data).toEqual({ authenticated: true })
    await page.goto('about:blank')
    await use(page)
    await context.close()
  },
})

export { expect }
