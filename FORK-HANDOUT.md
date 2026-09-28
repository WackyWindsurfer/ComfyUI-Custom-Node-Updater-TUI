# ComfyUI Custom-Node-Updater — Fork & Additions (Hand-out)

**Repo:** `WackyWindsurfer/ComfyUI-Custom-Node-Updater-TUI` · **Branch:** `feature/activity-log`
**Upstream:** `LacklusterOpsec/ComfyUI-Custom-Node-Updater-TUI`

A terminal UI for keeping every git-based ComfyUI custom node up to date — **safely**.
Point it at a `custom_nodes` folder, it scans every repo, fetches upstream in parallel,
and shows exactly which checkouts are behind. Updates are **fast-forward only**: it never
creates a merge commit, never rebases, and never touches a repo that has diverged or
would lose work.

This fork adds three things on top of the upstream tool: a **persistent activity log**,
a **headless runner** for automation, and a **manual `.bat` launcher**.

---

## 1. Setup (5 minutes)

```bat
git clone -b feature/activity-log https://github.com/WackyWindsurfer/ComfyUI-Custom-Node-Updater-TUI.git
cd ComfyUI-Custom-Node-Updater-TUI
```

**Create a project venv and install the two dependencies into it.**
> ⚠️ **Do not use bare `pip install`** if you have more than one Python on your system —
> the install and the run can land in different interpreters and you'll get
> `ModuleNotFoundError: No module named 'rich'`. A venv pins everything to one interpreter.

```bat
python -m venv .venv
.venv\Scripts\python -m pip install textual rich
```

> On Windows, run the tool with `-X utf8` so non-ASCII text renders correctly.

**Run the TUI:**

```bat
.venv\Scripts\python -X utf8 ComfyUI-Custom-Node-Updater-TUI.py --nodes-dir "C:\path\to\your\ComfyUI\custom_nodes"
```

If you omit `--nodes-dir`, it auto-discovers the folder (env var → last-used → walk up the
tree) or opens a folder picker. The choice is remembered for next time.

**Sanity check (optional):**

```bat
.venv\Scripts\python -X utf8 ComfyUI-Custom-Node-Updater-TUI.py --self-test
```
Expected: `OK: scanned 4 repos, pulled demo (kept local edits), skipped overlap ... and diverged ...`

---

## 2. Using the TUI

| Key | Action |
|-----|--------|
| `space` | select / deselect the highlighted repo |
| `a` | select all repos that are behind |
| `u` | clear selection |
| `p` | **Pull** the selected repos (shows a confirm screen first) |
| `s` | toggle **autostash** (stash local edits around the pull) |
| `f` | toggle **fetch** (network on/off) |
| `o` | choose a different `custom_nodes` folder |
| `t` | cycle theme |
| `q` | quit |

**Repo states:** `current` (green) · `behind` (red, updatable) · `ahead` (yellow) ·
`diverged` (magenta — you have commits upstream doesn't; resolve manually) ·
`modified` (yellow, local edits) · `error` (red).

The **Activity** panel (bottom-right) shows live scan/pull progress.

---

## 3. Addition 1 — Persistent activity log

Upstream's Activity panel is in-memory only — gone when you quit. This fork **tees every
line to a file** so you have a durable record of what the tool did.

- **Location:** same folder as `config.json`
  - Windows: `%APPDATA%\ComfyUI-Custom-Node-Updater-TUI\activity.log`
  - Linux/macOS: `~/.config/ComfyUI-Custom-Node-Updater-TUI/activity.log`
- **Format:** plain text (rich markup stripped), each line prefixed with a full timestamp.

```
2026-09-28 10:12:56  scanning C:\...\custom_nodes
2026-09-28 10:12:57  scan complete: 2 behind, 0 errors
2026-09-28 10:12:58  ok   demo - pulled (local edits restored)
```

It's best-effort: a write failure never breaks the TUI. Just open the file any time to
see the history of your scans and pulls.

---

## 4. Addition 2 — Headless runner (automation)

`ComfyUI-Custom-Node-Updater-TUI-headless.py` runs the **same safety gate as the TUI**
(no UI) — so it's just as safe as pressing *Pull*. It scans all repos in parallel,
fast-forwards the safe ones, and writes a report.

```bat
.venv\Scripts\python -X utf8 ComfyUI-Custom-Node-Updater-TUI-headless.py
```

**Flags:**

| Flag | Effect |
|------|--------|
| `--nodes-dir DIR` | process a specific `custom_nodes` dir (repeatable; default = the built-in list) |
| `--no-pull` | **dry run** — scan + report, change nothing |
| `--no-fetch` | compare against local refs only (no network) |

**Output:** appends to `activity.log` and writes `last-headless-run.json` (per-dir
breakdown: pulled list, skipped-by-reason, errors). A **6-hour stale-lock guard** prevents
overlapping runs (e.g. a scheduled run and a manual one) — a second run exits immediately.

> The built-in `DEFAULT_NODES_DIRS` list is machine-specific. If you're on a different
> machine, pass your own dirs with `--nodes-dir`.

---

## 5. Addition 3 — Manual `.bat` launcher

`ComfyUI-Custom-Node-Updater-TUI-headless.bat` is a one-click wrapper around the headless
runner (it auto-finds the venv and pauses so the window stays open):

```bat
ComfyUI-Custom-Node-Updater-TUI-headless.bat            real run — pulls the safe repos
ComfyUI-Custom-Node-Updater-TUI-headless.bat dry       dry run — report only, changes nothing
ComfyUI-Custom-Node-Updater-TUI-headless.bat nofetch   real run, but no network fetch
```

**Double-clicking it in Explorer = a real run.**

---

## 6. (Optional) Schedule it

For a daily unattended run, use your OS task scheduler to invoke the **venv python
directly** (not the `.bat` — it ends with `pause`, which would hang a scheduled task).

Windows example (daily at 03:30):

```bat
schtasks /Create /F /SC DAILY /ST 03:30 /TN "ComfyUI-Custom-Node-Updater-Headless" ^
  /TR "\"<path>\.venv\Scripts\python.exe\" -X utf8 \"<path>\ComfyUI-Custom-Node-Updater-TUI-headless.py\""
```

Manage it:

```bat
schtasks /Query /TN "ComfyUI-Custom-Node-Updater-Headless" /V /FO LIST   inspect
schtasks /Change /TN "ComfyUI-Custom-Node-Updater-Headless" /DISABLE     pause
schtasks /Change /TN "ComfyUI-Custom-Node-Updater-Headless" /ENABLE      resume
schtasks /Delete /TN "ComfyUI-Custom-Node-Updater-Headless" /F          remove
```

---

## Why it's safe

The "never lose work" guarantee comes from two things working together:

1. **`git merge --ff-only`** — the pull is *structurally* fast-forward only, so it can
   never create a merge commit or rewrite history.
2. **A pre-pull gate** — each repo is checked before touching it and **skipped** (not
   forced) if it is diverged, detached, has no upstream, or if your local edits overlap
   the incoming changes (which would leave conflict markers). Diverged and overlap repos
   are always left for you to resolve.

**Autostash** (on by default in the headless runner) temporarily stashes non-overlapping
local edits around the pull and restores them; if the restore conflicts, the update is
kept and the edits stay recoverable in the stash rather than half-applied.

**Limitations (by design):** only immediate subdirectories are scanned (no nested repos);
it never rebases/merges/forces; it does not install dependencies or update ComfyUI itself.

---

*Fork of `LacklusterOpsec/ComfyUI-Custom-Node-Updater-TUI` (GPL-3.0). Additions: activity
log, headless runner, manual launcher — branch `feature/activity-log`.*
