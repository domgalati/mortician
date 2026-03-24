<p align="center">
  <img src="mortician.png" style="width:40%;"/><br>
  A Git-friendly CLI for incident postmortems.
</p>

## What Mortician Is

Mortician helps incident responders capture postmortems while an incident is happening, not days later from memory.

Instead of storing everything in one large document, each incident is saved as a small folder of readable files (Markdown + YAML). That gives you:

- clean Git diffs
- easy manual editing in any editor
- scriptable automation
- a local dashboard and HTTP API when you want a UI

If you are new to incident tooling, the mental model is simple: one incident equals one folder bundle, and every command reads or updates that bundle.

## How It Stores Data

Each incident lives at `incidents/{id}-{title-slug}/`.

| File / directory | Purpose |
|---|---|
| `meta.yaml` | Metadata: id, title, status, severity, owner, timestamps, participants |
| `index.md` | Main narrative: summary, impact, root cause, resolution |
| `timeline.yaml` | Ordered `events:` list (`time` + `action`, supports multi-line Markdown) |
| `actions.yaml` | Follow-up items (`items:` list) |
| `assets/` | Attachments like screenshots or logs |

This structure is the source of truth for both CLI output and the dashboard API.

## Installation

From the project root:

```bash
pip install .
```

Optional extras:

- `pip install 'mortician[textual]'` enables the Textual fullscreen Markdown viewer for `mortician show <id> --render textual`.

Rich-based terminal Markdown rendering (`mortician show <id> --render` / `--render rich`) and Rich prompts when resolving incidents with missing required fields are included in the default install.

## Quick Start

Create an incident:

```bash
mortician create "PostgreSQL connection saturation"
```

Capture timeline updates as you respond (replace `<incident-id>` with the id printed by `create`):

```bash
mortician timeline add <incident-id> --action "Declared incident and started investigation"
echo "Applied connection pool limits to protect primary." | mortician timeline add <incident-id>
```

Update status and summary:

```bash
mortician edit <incident-id> --status "Temporary Resolution" --temp_fix "Enabled connection throttling" --summary "Connections saturated under burst load."
```

Export or render:

```bash
mortician show <incident-id> > postmortem-<incident-id>.md
mortician show <incident-id> --render
mortician show <incident-id> --render textual
```

## Command Reference

CLI shape:

```text
mortician {create,edit,show,list,timeline,serve} ...
```

### `create`

```text
mortician create TITLE [--guide]
```

- Creates a new incident bundle under `incidents/`.
- Derives a short incident id from `TITLE` automatically.
- Prints suggested next commands after creation.
- `--guide` launches an interactive workflow tailored for live incidents.

#### Guided mode (`--guide`)

Guided mode collects:

- incident owner and participants
- **Summary:** short narrative of what is going on (Markdown). Placeholders `$date`, `$utc`, and `$host` are expanded when saved (shown with example values before you edit).
- impact details and optional severity label
- timeline entries
- status/resolution fields (unless incident is still ongoing)

If you answer that the incident is ongoing, status is set to `Unresolved` and resolution prompts are skipped.

### `list`

```text
mortician list [--status STATUS] [--date YYYY-MM-DD]
```

- Shows a summary table (`ID`, `Title`, `Status`, `Date`).
- `--status` match is case-insensitive.
- `--date` expects exact `YYYY-MM-DD`.

### `show`

```text
mortician show [issue_id] [--status STATUS] [--date YYYY-MM-DD] [--plain | --render [rich|textual]]
```

Two modes:

- with `issue_id`: prints one incident as Markdown
- without `issue_id`: lists incidents (same behavior as `list`)

Output options:

- default: raw Markdown (good for piping to files/tools)
- `--render` or `--render rich`: Rich-based rendering in the terminal (requires `mortician[rich]`)
- `--render textual`: Textual fullscreen scrollable viewer (requires `mortician[textual]` and an interactive TTY)
- `--plain`: force raw Markdown output

Environment toggle:

- `MORTICIAN_SHOW_RENDER=1` (also accepts `true`/`yes`) is equivalent to `--render rich` for `mortician show <id>` unless `--plain` is passed.

### `select`

```text
mortician select [issue_id]
```

- If `issue_id` is provided: sets the active incident id used by later `mortician edit` and `mortician add` commands.
- If `issue_id` is omitted: prints the currently active incident (id + title when available).

### `edit`

```text
mortician edit [issue_id]
  [--status [STATUS]]
  [--severity [SEVERITY]]
  [--owner [OWNER]]
  [--participants [PARTICIPANTS]]
  [--summary [SUMMARY]]
  [--affected-services [AFFECTED_SERVICES]]
  [--duration [DURATION]]
  [--business-impact [BUSINESS_IMPACT]]
  [--root-cause [ROOT_CAUSE]]
  [--temp-fix [TEMP_FIX]]
  [--perm-fix [PERM_FIX]]
  [--no-input]
  [--add-entry KEY=VALUE [KEY=VALUE ...]]
```

Edits selected fields in the chosen incident bundle.

Stateful behavior:
- If `issue_id` is omitted, the CLI uses the active id from `mortician select` (or the most recently created incident).
- If no edit flags are provided (just `mortician edit [issue_id]`), Mortician opens the full incident bundle in `$EDITOR` for roundtrip editing of `meta.yaml`, `index.md`, `timeline.yaml`, and `actions.yaml`.

Editor behavior:
- If a field flag is provided **without** a value (for example `--duration`), Mortician opens `$EDITOR` prefilled with the current value and saves what you write back to the bundle.
- If a field flag includes a value (for example `--duration "~1h"`), the field is overwritten immediately.
- When `--status Resolved` is set, Mortician checks required fields and (if they are empty) walks you through filling them. In a normal interactive terminal (stdin/stdout TTY), it uses Rich prompts (`Confirm` for each empty field, then multi-line entry; finish each field with a line containing only `END`). **Ctrl+C** cancels without saving and leaves status unchanged. Without a TTY, it falls back to yes/no prompts and a single `$EDITOR` session with one section per field.

`--add-entry` (back-compat) appends exactly one timeline object:
- Pass fragments as `KEY=VALUE`.
- Only the first `=` splits key/value, so values can contain additional `=`.

### `add`

```text
mortician add [--time TIME] [--action ACTION] [--cmd CMD]
```

Adds one timeline entry to the active incident.

- If stdin is piped and `--action` is not provided, Mortician will:
  - try to extract a timestamp from the piped text as `Stamp (...)` (if parsing succeeds)
  - prompt for time with `Stamp (...)`, `Now (...)`, and `Enter manually` (when `questionary` is installed)
  - prefill the `What happened?` editor: by default with the piped text only. The shell does **not** pass the command on the left of the pipe (e.g. `uptime` in `uptime | mortician add`). To record that command in the entry, use **`--cmd`** (e.g. `uptime | mortician add --cmd uptime`), or set **`MORTICIAN_ADD_CMD`**, or answer the optional **Command (optional, Enter to skip):** prompt when a TTY is available. The saved text is then a minimal block: `$ <cmd>`, a blank line, then the piped output.
- If timestamp parsing fails, the `Stamp (...)` option is omitted, but `What happened?` is still prefilled.

### `timeline add`

```text
mortician timeline add issue_id [--time TIME] [--action ACTION]
```

- Appends one timeline event (`time`, `action`).
- `--time` defaults to current UTC time (`YYYY-MM-DD HH:MM UTC`).
- `--action` is optional:
  - if set, it is used directly
  - if omitted, full `stdin` is read (great for multi-line notes/pipes)
- Returns a non-zero exit code if no action text is provided.

### `serve`

```text
mortician serve [--host 127.0.0.1] [--port 8765]
```

Starts a local dashboard server with live updates when files under `incidents/` change.

## HTTP API

The dashboard exposes a local HTTP API:

- `GET /api/postmortems`  
  Returns incident summary rows (`id`, `title`, `status`, `date`).

- `GET /api/postmortems/{issue_id}`  
  Returns full incident JSON assembled from the bundle.

- `PUT /api/postmortems/{issue_id}/index.md`
  Replaces `index.md` with UTF-8 Markdown body (atomic write).

- `GET /api/postmortems/{issue_id}/export.zip`
  Downloads a ZIP of the incident bundle directory (dotfiles under the bundle, such as temp writes, are omitted).

- `PUT /api/postmortems/{issue_id}/sections/{section}`
  Updates a single logical section of `index.md` and rewrites the file atomically. Request body is UTF-8 plain text (the section body). Valid `{section}` values: `summary`, `impact`, `root_cause`, `resolution_temporary`, `resolution_permanent`. Other bundle files are not modified.

- `POST /api/postmortems/{issue_id}/actions`
  Appends one follow-up item. Request body is JSON: `task` (required string), `owner` and `due` (optional strings).

- `PATCH /api/postmortems/{issue_id}/actions/{action_index}`
  Merges fields into one row of `actions.yaml` (`items` list). `{action_index}` is **0-based**. Request body is JSON object with any of: `done`, `completed` (booleans), `task`, `title`, `owner`, `due` (strings). Unknown keys are rejected. Empty `{}` is a no-op.

- `GET /api/postmortems/{issue_id}/assets/{asset_path}`
  Serves files from the incident `assets/` directory (path traversal blocked).

- `GET /api/events`  
  Server-Sent Events stream for live update notifications.

## Feature List

- Git-native storage (human-readable Markdown/YAML per incident)
- fast incident creation with generated ids
- guided incident capture flow
- direct field edits from CLI
- timeline appends from flags or stdin
- list/filter incidents by status/date
- Markdown export and terminal rendering
- local dashboard with live refresh
- JSON + SSE API for integrations
- safe asset serving and atomic markdown writes

## Shell Completion (WSL/Linux)

Mortician supports shell tab completion via `argcomplete` (dynamic, flag + incident-id aware).

For bash:

```bash
eval "$(register-python-argcomplete mortician)"
```

For zsh:

```bash
eval "$(register-python-argcomplete --shell zsh mortician)"
```

After enabling completion, `mortician select <TAB>` (and `mortician edit <TAB>` when you provide `issue_id`) will suggest existing incident ids.

## Tips

- `mortician show <id> | glow -p` works well if you prefer external Markdown viewers.
- `mortician show <id> | pandoc -o postmortem.pdf` is a simple PDF export path.
- You can always edit bundle files directly; Mortician will read them on next command.
