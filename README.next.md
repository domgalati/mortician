<p align="center">
  <img src="mortician.png" style="width:40%;" alt="Mortician logo"/><br>
  <strong>A Git-friendly CLI for incident postmortems.</strong>
</p>

## Philosophy

Mortician is built on a simple belief: **the best postmortem is the one you record while the incident is still happening**, not the polished narrative you reconstruct days later from Slack scrollback and bad memory.

To make that practical, Mortician keeps each incident as a **small folder of plain files**—mostly Markdown and YAML—rather than a single opaque document or a proprietary database. That choice drives everything else:

- **Git is a first-class home.** Small, structured files produce readable diffs, audit trails, and branching or review workflows that match how engineering teams already work.
- **Tools stay optional.** Editors, scripts, `grep`, and CI can operate on the bundle directly. The CLI and dashboard are conveniences layered on the same source of truth.
- **Capture should be low-friction.** Quick appends (timeline, actions), pipe-friendly commands, and an optional guided flow reduce the gap between “we should write this down” and “it’s on disk.”
- **Humans and machines share one format.** The same bundle powers terminal output, a local web UI, and a small HTTP API for integrations.

One mental model covers the whole tool: **one incident is one bundle directory** under `incidents/`. Every command reads or updates that bundle.

---

## Table of contents

- [Installation](#installation)
- [Optional dependencies](#optional-dependencies)
- [What you get at a glance](#what-you-get-at-a-glance)
- [Data layout](#data-layout)
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

## Installation

From the repository root (development install):

```bash
pip install .
```

For a normal end-user install once published, use the same pattern with your package index or a version pin as you prefer.

After install, the `mortician` entry point is available on your `PATH`.

---

## Optional dependencies

Core functionality includes Rich-based rendering and prompts (see `pyproject.toml`). Additional behavior is gated behind extras:

| Extra | Install command | What it enables |
|--------|-----------------|-----------------|
| **textual** | `pip install 'mortician[textual]'` | Fullscreen scrollable Markdown viewer for `mortician show <id> --render textual` (interactive TTY). |

Environment variable (no extra package):

| Variable | Effect |
|----------|--------|
| `MORTICIAN_SHOW_RENDER` | If set to `1`, `true`, or `yes`, `mortician show <id>` defaults to Rich rendering unless `--plain` is passed. |
| `MORTICIAN_ADD_CMD` | When piping into `mortician add`, can supply the command string to record alongside captured output (see [Timeline capture](#5-timeline-capture)). |

---

## What you get at a glance

- **CLI** for creating incidents, editing metadata and narrative fields, appending timeline and action items, listing and exporting.
- **Local dashboard** (`mortician serve`) with live refresh when files under `incidents/` change.
- **HTTP + SSE API** for summaries, full JSON, section updates, actions, assets, and ZIP export.
- **Readable on-disk format** you can open in any editor or track in version control.

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

## Feature sets

Below, each section describes one feature area. Drop in screenshots or GIFs where noted when you have them.

### 1. Bundles and Git-native storage

Incidents are directories of YAML and Markdown, not rows in a remote service. That supports reviewable diffs, backup via Git, and ad-hoc scripting without a custom SDK.

**Media (optional):**  
<!-- ![Bundle layout in explorer or tree view](docs/images/bundle-tree.png) -->

---

### 2. Creating incidents and guided capture

`mortician create "Title"` creates a new bundle under `incidents/`, derives a short id from the title, selects it as active, and prints suggested next steps.

With **`--guide`**, an interactive workflow collects owner, participants, summary (with `$date`, `$utc`, `$host` placeholders), impact, optional severity, timeline entries, and resolution-oriented fields—skipping resolution prompts when you indicate the incident is still ongoing. Interrupting guided mode after create removes the unfinished bundle (see implementation for edge cases).

**Media (optional):**  
<!-- ![create command and output](docs/images/create.gif) -->
<!-- ![guided wizard excerpt](docs/images/guide.png) -->

---

### 3. Active incident (`select`)

Many commands target “the current incident” so you do not repeat ids:

- `mortician select <issue_id>` sets the active id for subsequent `edit`, `add`, and `action` commands.
- `mortician select` with no id prints the active incident (id and title when available).

**Media (optional):**  
<!-- ![select and follow-up edit](docs/images/select.gif) -->

---

### 4. Editing incidents

`mortician edit [issue_id] [flags]` updates fields in the bundle. If `issue_id` is omitted, the active incident is used (or the most recently created one, per existing behavior).

- **Flag with value:** immediate update (e.g. `--status Resolved`).
- **Flag without value:** open `$EDITOR` with the current value for round-trip editing.
- **No flags:** open the full bundle in `$EDITOR` (`meta.yaml`, `index.md`, `timeline.yaml`, `actions.yaml`).

- **`--add-entry KEY=VALUE ...`:** append one timeline row (only the first `=` splits key and value, so values may contain `=`).

Setting status to **Resolved** can trigger prompts for missing required fields: Rich prompts in a TTY, with a non-TTY fallback.

**Media (optional):**  
<!-- ![edit flags vs open in editor](docs/images/edit.gif) -->

---

### 5. Timeline capture

- **`mortician timeline add <issue_id>`** appends one event; `--time` defaults to current UTC; `--action` or stdin supplies the body.
- **`mortician add`** appends to the **active** incident with an interactive flow. Piped stdin can capture command output; use **`--cmd`** (or `MORTICIAN_ADD_CMD`) because the shell does not pass the left-hand command through the pipe.

**Media (optional):**  
<!-- ![timeline add one-liner vs stdin](docs/images/timeline.gif) -->
<!-- ![piped add with --cmd](docs/images/add-pipe.gif) -->

---

### 6. Follow-up actions

`mortician action` manages `actions.yaml` for the active incident:

- `add` — new item (`--task` or stdin; optional `--owner`, `--due`)
- `list` — checkbox-style listing
- `done` / `undo` — toggle completion by **1-based** index from `list`

The dashboard API can also append or patch action rows (see below).

**Media (optional):**  
<!-- ![action list and done](docs/images/actions.gif) -->

---

### 7. Listing, filtering, and export

- **`mortician list`** and **`mortician show`** (without an id) list incidents with optional `--status` (case-insensitive) and `--date YYYY-MM-DD`.
- **`mortician show <id>`** prints one incident as Markdown (default: raw text, ideal for `>` redirection and pipes).

**Media (optional):**  
<!-- ![list with filters](docs/images/list.png) -->

---

### 8. Terminal rendering (`show`)

- **`--plain`** forces raw Markdown.
- **`--render` / `--render rich`** uses Rich in the terminal.
- **`--render textual`** uses the Textual fullscreen viewer (**requires** `mortician[textual]` and an interactive TTY).

**Media (optional):**  
<!-- ![show --render rich](docs/images/show-rich.png) -->
<!-- ![show --render textual](docs/images/show-textual.gif) -->

---

### 9. Local dashboard and HTTP API

`mortician serve [--host 127.0.0.1] [--port 8765]` runs a local dashboard; the server watches `incidents/` and notifies clients when files change.

**HTTP API (summary):**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/postmortems` | Summary rows: `id`, `title`, `status`, `date` |
| GET | `/api/postmortems/{issue_id}` | Full incident JSON from the bundle |
| PUT | `/api/postmortems/{issue_id}/index.md` | Replace `index.md` (atomic write) |
| GET | `/api/postmortems/{issue_id}/export.zip` | ZIP of bundle (sensible omissions for dotfiles / temp) |
| PUT | `/api/postmortems/{issue_id}/sections/{section}` | Update one logical section of `index.md`: `summary`, `impact`, `root_cause`, `resolution_temporary`, `resolution_permanent` |
| POST | `/api/postmortems/{issue_id}/actions` | JSON: `task` (required), optional `owner`, `due` |
| PATCH | `/api/postmortems/{issue_id}/actions/{action_index}` | Merge into **0-based** action row: `done`, `completed`, `task`, `title`, `owner`, `due` |
| GET | `/api/postmortems/{issue_id}/assets/{asset_path}` | Serve from `assets/` (path traversal blocked) |
| GET | `/api/events` | Server-Sent Events stream for live updates |

**Media (optional):**  
<!-- ![dashboard overview](docs/images/dashboard.png) -->
<!-- ![section edit or live refresh](docs/images/dashboard-live.gif) -->

---

### 10. Shell completion

Dynamic tab completion (flags and incident ids) is available via **argcomplete**.

**bash:**

```bash
eval "$(register-python-argcomplete mortician)"
```

**zsh:**

```bash
eval "$(register-python-argcomplete --shell zsh mortician)"
```

**Media (optional):**  
<!-- ![tab completion demo](docs/images/completion.gif) -->

---

### 11. Tips and external tools

- `mortician show <id> | glow -p` — external terminal Markdown preview.
- `mortician show <id> | pandoc -o postmortem.pdf` — quick PDF export.
- You may edit bundle files directly; the next CLI or server read will pick up changes.

**Media (optional):**  
<!-- ![glow or pandoc pipeline](docs/images/pipe-tools.png) -->

---

## Requirements

- **Python** 3.8 or newer (see `pyproject.toml`).

For dependency versions, refer to `[project]` / `[project.optional-dependencies]` in `pyproject.toml`.
