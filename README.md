# Mortician

Mortician is a CLI + local web dashboard for incident/postmortem capture stored as plain files.

Mortician is built on the idea that **the best postmortem is the one you record while the incident is still happening**, not the narrative reconstructed days later from Slack scrollback and bad memory.

![intro gif](assets/intro.gif)

To make that practical, Mortician keeps each incident as a **small folder of plain files**—mostly Markdown and YAML—rather than a single opaque document or a proprietary database. That choice drives everything else:

## What you get at a glance

- **CLI** for creating incidents, editing metadata and narrative fields, appending timeline and action items, listing and exporting.
- **Local dashboard** (`mortician serve`) with live refresh when files under `incidents/` change.
- **HTTP + SSE API** for summaries, full JSON, section updates, actions, assets, and ZIP export.
- **Readable on-disk format** you can open in any editor or track in version control.



## Table of Contents

- [Quick Start](#quick-start)
- [Installation](#installation)
- [Optional dependencies](#optional-dependencies)
- [Data layout](#data-layout)
- [Full documentation](#1-full-documentation)
- [Feature sets](#feature-sets)
  - [Bundles and Git-native storage](#1-bundles-and-git-native-storage)
  - [Creating incidents and guided capture](#2-creating-incidents-and-guided-capture)
  - [Active incident (`select`)](#3-active-incident-select)
  - [Editing incidents](#4-editing-incidents)
  - [Timeline capture](#5-timeline-capture)
  - [Follow-up actions](#6-follow-up-actions)
  - [Listing, filtering, and export](#7-listing-filtering-and-export)
  - [Terminal rendering (`show`)](#8-terminal-rendering-show)
  - [Local dashboard and HTTP API](#9-local-dashboard-and-http-api)
  - [Shell completion](#10-shell-completion)
  - [Tips and external tools](#11-tips-and-external-tools)
- [Requirements](#requirements)

---

## Quick Start

Create an incident:

```bash
mortician create "PostgreSQL connection saturation"
```

Capture timeline updates (replace `<issue-id>` with the id printed by `create`):

```bash
mortician timeline add <issue-id> --action "Declared incident and started investigation"
echo "Applied connection pool limits to protect primary." | mortician timeline add <issue-id>
```

Update status and summary:

```bash
mortician edit <issue-id> --status "Temporary Resolution" --temp_fix "Enabled connection throttling" --summary "Connections saturated under burst load."
```

Render/export:

```bash
mortician show <issue-id> > postmortem-<issue-id>.md
mortician show <issue-id> --render
mortician show <issue-id> --render textual
```

---

## Installation

From the repository root (development install):

```bash
pip install .
```

After install, the `mortician` entry point is available on your `PATH`.

### Tab Completion
It is highly recommended to enable tab completion for Mortician. See [10. Shell completion](#10-shell-completion) for instructions.

### Incidents Directory
Choose where incident bundles are stored.

Mortician **requires** `MORTICIAN_INCIDENTS_DIR` to be set.

Setting `MORTICIAN_INCIDENTS_DIR` lets you run `mortician` commands from any working directory and still edit the same incident bundles.

Example (Bash):
```bash
export MORTICIAN_INCIDENTS_DIR="/path/to/your/incidents"
```

Example (PowerShell):
```powershell
$env:MORTICIAN_INCIDENTS_DIR="C:\path\to\your\incidents"
```

## Optional dependencies

Core functionality includes Rich-based rendering and prompts (see `pyproject.toml`). Additional behavior is gated behind extras:

| Extra | Install command | What it enables |
|--------|-----------------|-----------------|
| **textual** | `pip install 'mortician[textual]'` | Fullscreen scrollable Markdown viewer for `mortician show <issue-id> --render textual` (interactive TTY). |

Environment variable (no extra package):

| Variable | Effect |
|----------|--------|
| `MORTICIAN_SHOW_RENDER` | If set to `1`, `true`, or `yes`, `mortician show <issue-id>` defaults to Rich rendering unless `--plain` is passed. |
| `MORTICIAN_ADD_CMD` | When piping into `mortician add`, can supply the command string to record alongside captured output (see [Timeline capture](#5-timeline-capture)). |

---
## Data layout

Each incident lives at `incidents/{id}-{title-slug}/`.

| Path | Role |
|------|------|
| `meta.yaml` | Id, title, status, severity, owner, timestamps, participants |
| `index.md` | Main narrative (summary, impact, root cause, resolution) |
| `timeline.yaml` | Ordered `events:` with `time` and `action` (Markdown-friendly) |
| `actions.yaml` | Follow-up checklist (`items:`) |
| `assets/` | Attachments (screenshots, logs, etc.) |

This layout is the **single source of truth** for both CLI and web UI.

---

## 1. Full documentation

Full command reference and API details live in `DOCS.md`.

---

### 2. Creating incidents and guided capture

`mortician create "Title"` creates a new bundle under `incidents/`, derives a short id from the title, selects it as active, and prints suggested next steps.

With **`--guide`**, an interactive workflow collects owner, participants, summary (with `$date`, `$utc`, `$host` placeholders), impact, optional severity, timeline entries, and resolution-oriented fields—skipping resolution prompts when you indicate the incident is still ongoing. Interrupting guided mode after create removes the unfinished bundle (see implementation for edge cases).

![create command and output](assets/guide.cast.gif)

---

### 3. Active incident (`select`)

Many commands target “the current incident” so you do not repeat ids:

- `mortician select <issue-id>` sets the active id for subsequent `edit`, `add`, and `action` commands.
- `mortician select` with no id prints the active incident (id and title when available).

![select and follow-up edit](assets/select.cast.gif)

---

### 4. Editing incidents

`mortician edit [issue-id] [flags]` updates fields in the bundle. If `issue-id` is omitted, the active incident is used (or the most recently created one, per existing behavior).

- **Flag with value:** immediate update (e.g. `--status Resolved`).
- **Flag without value:** open `$EDITOR` with the current value for round-trip editing.
- **No flags:** open the full bundle in `$EDITOR` (`meta.yaml`, `index.md`, `timeline.yaml`, `actions.yaml`).

- **`--add-entry KEY=VALUE ...`:** append one timeline row (only the first `=` splits key and value, so values may contain `=`).

Setting status to **Resolved** can trigger prompts for missing required fields: Rich prompts in a TTY, with a non-TTY fallback.

---

### 5. Timeline capture

- **`mortician timeline add <issue-id>`** appends one event; `--time` defaults to current UTC; `--action` or stdin supplies the body.
- **`mortician add`** appends to the **active** incident with an interactive flow. Piped stdin can capture command output; use **`--cmd`** (or `MORTICIAN_ADD_CMD`) because the shell does not pass the left-hand command through the pipe.

---

### 6. Follow-up actions

`mortician action` manages `actions.yaml` for the active incident:

- `add` — new item (`--task` or stdin; optional `--owner`, `--due`)
- `list` — checkbox-style listing
- `done` / `undo` — toggle completion by **1-based** index from `list`

The dashboard API can also append or patch action rows (see below).

---

### 7. Listing, filtering, and export

- **`mortician list`** and **`mortician show`** (without an id) list incidents with optional `--status` (case-insensitive) and `--date YYYY-MM-DD`.
- **`mortician show <issue-id>`** prints one incident as Markdown (default: raw text, ideal for `>` redirection and pipes).

---

### 8. Terminal rendering (`show`)

- **`--plain`** forces raw Markdown.
- **`--render` / `--render rich`** uses Rich in the terminal.
- **`--render textual`** uses the Textual fullscreen viewer (**requires** `mortician[textual]` and an interactive TTY).


---

### 9. Local dashboard and HTTP API

`mortician serve [--host 127.0.0.1] [--port 8765]` runs a local dashboard; the server watches `incidents/` and notifies clients when files change.

**HTTP API (summary):**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/postmortems` | Summary rows: `id`, `title`, `status`, `date` |
| GET | `/api/postmortems/{issue-id}` | Full incident JSON from the bundle |
| PUT | `/api/postmortems/{issue-id}/index.md` | Replace `index.md` (atomic write) |
| GET | `/api/postmortems/{issue-id}/export.zip` | ZIP of bundle (sensible omissions for dotfiles / temp) |
| PUT | `/api/postmortems/{issue-id}/sections/{section}` | Update one logical section of `index.md`: `summary`, `impact`, `root_cause`, `resolution_temporary`, `resolution_permanent` |
| POST | `/api/postmortems/{issue-id}/actions` | JSON: `task` (required), optional `owner`, `due` |
| PATCH | `/api/postmortems/{issue-id}/actions/{action_index}` | Merge into **0-based** action row: `done`, `completed`, `task`, `title`, `owner`, `due` |
| GET | `/api/postmortems/{issue-id}/assets/{asset_path}` | Serve from `assets/` (path traversal blocked) |
| GET | `/api/events` | Server-Sent Events stream for live updates |


---

### 10. Shell completion

Dynamic tab completion (flags and incident ids) is available via **argcomplete**. Add the following to `.bashrc` or your environment’s equivalent: 
**bash:**

```bash
eval "$(register-python-argcomplete mortician)"
```

**zsh:**

```bash
eval "$(register-python-argcomplete --shell zsh mortician)"
```

---

### 11. Tips and external tools

- `mortician show <issue-id> | glow -p` — external terminal Markdown preview.
- `mortician show <issue-id> | pandoc -o postmortem.pdf` — quick PDF export.
- You may edit bundle files directly; the next CLI or server read will pick up changes.


-->

---

## Requirements

- **Python** 3.8 or newer (see `pyproject.toml`).

For dependency versions, refer to `[project]` / `[project.optional-dependencies]` in `pyproject.toml`.
