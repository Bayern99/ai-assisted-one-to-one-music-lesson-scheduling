# Swift + React macOS application

Optional native shell for **AI-Assisted One-to-One Music Lesson Scheduling**.
The research demonstration is also runnable in the browser (see the root README).
Installer scripts still use the legacy `Music Lesson Scheduler.app` bundle name.

## Architecture under test

```text
Music Lesson Scheduler.app (SwiftUI/AppKit owner)
├── WKWebView → bundled React production build
├── native save panel → fixed artifact API routes only
└── Swift Process → bundled Python FastAPI application source
                    └── unchanged scheduling core
```

Swift owns the application, window, Dock lifecycle, startup recovery, native
save panel, and child-process cleanup. React remains the complete product UI.
Python remains the only scheduling authority.

## Build and run

From the repository root:

```bash
./script/build_and_run.sh
```

The Codex workspace Run action calls the same command. For a build, launch, and
process/health assertion in one command:

```bash
./script/build_and_run.sh --verify
```

The script builds React, runs the Swift tests, builds the Swift executable,
stages and ad-hoc signs a real `.app`, then launches:

```text
dist/Music Lesson Scheduler.app
```

For the installed production app, use:

```bash
./script/build_and_run.sh --install
```

This safely replaces the user-local `~/Applications/Music Lesson Scheduler.app` only after code
signing verification succeeds.

## Data and current distribution boundary

Installed and development Swift builds use the app-owned data directory by default:

```text
~/Library/Application Support/Music Lesson Scheduler/Data
```

On the first install, an empty app-owned directory is seeded from the
repository's existing `data/` directory. Later upgrades preserve the app-owned
workspace and never overwrite it. This avoids macOS privacy and File Provider
failures when the external Python child process runs from a signed native app.
Set `PI_SWIFT_DATA_DIR` only for isolated development or verification.

The app bundle contains the React production build and Python application source,
so runtime startup does not depend on reading the repository from `Documents`.
When Pi is available during the build, the bundle records its absolute
executable path for the optional Step 4 investigation; `PI_EXECUTABLE` can override
that path for a development launch.
The app is locally installable but not yet a notarized standalone distribution:
it records the verified local Python executable and uses that interpreter's
installed dependencies. A public distribution would additionally embed Python,
sign with a Developer ID, notarize, and staple the ticket.

## Native window chrome

The main scene uses a transparent hidden macOS title bar with full-size content.
The native close, minimize, and full-screen controls remain system-owned above
the React sidebar. A narrow AppKit drag region occupies only the otherwise empty
top band after the traffic-light controls; React navigation and controls remain
outside that hit region. Standard resizing, shadows, full-screen behavior, and
SwiftUI window restoration remain enabled.

## Desktop bridge boundary

The WebKit bridge keeps the existing compatibility namespace but exposes only
three narrow capabilities:

```text
window.piDesktop.openFile(fixedFileKind)
window.piDesktop.saveArtifact(opaqueArtifactId)
window.piDesktop.revealArtifact(opaqueArtifactId)
```

The open panel accepts only workbook, lecture CSV, or assessment CSV/XLSX roles.
Swift validates artifact IDs, fetches only fixed scheduler or assessment routes,
and writes only to a location chosen through `NSSavePanel`. Reveal works only
for a file saved during the current app session. The bridge exposes no arbitrary
filesystem path, URL, or command execution.
