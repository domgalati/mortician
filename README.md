<p align="center"><img src="mortician.png" style="width:40%;"/><br>A tool for quickly generating and editing postmortem reports.</p>

## How it Works

Mortician stores each incident as a **directory bundle** under `incidents/` (YAML + Markdown + optional assets). Long-form narrative lives in `index.md`; structured metadata in `meta.yaml`; the timeline in `timeline.yaml` (multi-line Markdown supported with literal block scalars); follow-up actions in `actions.yaml`. This keeps diffs readable in Git and avoids a single giant JSON file.

When you are ready to share a flat document, you can export any incident to Markdown from the CLI.

## Installation

1. Clone the project into a local directory.
2. Use `pip install .` from the project directory to install.

Optional extras:

- **`pip install 'mortician[rich]'`** — terminal Markdown rendering for `mortician show --render`.

## Usage

Mortician is designed to capture incident information **as it happens**, not after the fact. Instead of scrambling to retrieve details hours or days later, you document timeline events, fixes, and observations in real time during the incident response.

### Incident bundle layout

Each incident lives in `incidents/{id}-{title-slug}/`:

| File / directory | Contents |
|------------------|----------|
| `meta.yaml` | `id`, `title`, `status`, `severity`, `owner`, `created_at`, `date`, `time`, `participants` |
| `index.md` | Sections: Summary, Impact & Severity, Root Cause, Resolution (Temporary / Permanent) |
| `timeline.yaml` | `events:` with `time` and `action` (multi-line Markdown) |
| `actions.yaml` | Structured follow-up items |
| `assets/` | Screenshots and attachments |

### CLI overview

```
usage: mortician [-h] {create,edit,show,list,timeline,serve} ...
```

### Create incidents

```
usage: mortician create [-h] TITLE [--guide]
```

- **TITLE** is the human-readable title. A **short id** is derived automatically (it is not a custom id you choose).
- After create, the CLI prints suggested next steps (`timeline add`, `edit`, `serve`, bundle path).
- **`--guide`**: interactive wizard tuned for live incidents. It asks whether the incident is still ongoing; if yes, it records current known state (owner, participants, summary, impact, severity, timeline) and skips resolution prompts, marking status as `Unresolved`. It also uses [questionary](https://github.com/tmbo/questionary) for duration presets and timeline time (“now” vs manual).

### List

```
usage: mortician list [-h] [--status STATUS] [--date DATE]
```

Same table as `mortician show` with no `issue_id`. Status filter is case-insensitive.

### Edit

```
usage: mortician edit [-h] [--status STATUS] [--severity SEVERITY] [--owner OWNER] [--participants PARTICIPANTS]
                      [--summary SUMMARY] [--root_cause ROOT_CAUSE] [--temp_fix TEMP_FIX] [--perm_fix PERM_FIX]
                      [--no-input] [--add-entry KEY=VALUE [KEY=VALUE ...]]
                      issue_id
```

- **`--add-entry`**: appends **one** timeline row.
- Each fragment is `KEY=VALUE`; only the **first** `=` splits key and value, so values may contain `=`.
- **`--status`**: with `Resolved` / `Temporary Resolution`, you are prompted for the fix unless you pass **`--perm_fix`** / **`--temp_fix`** or **`--no-input`** (for scripts).
- **`--severity`**: updates the severity label in `meta.yaml` (e.g. `P1`).

### Timeline (stdin-friendly)

```
usage: mortician timeline add [-h] [--time TIME] [--action ACTION] issue_id
```

- **`--time`**: optional; defaults to current time (UTC string).
- **`--action`**: one line. If omitted, the **entire stdin** is used as the Markdown body (good for pipes and multi-line snippets).

Example:

```bash
echo "Seeing elevated 503s from checkout API." | mortician timeline add websfail
mortician timeline add websfail --action "Rollback complete"
```

### Show

```
usage: mortician show [-h] [--plain | --render] [--status STATUS] [--date DATE] [issue_id]
```

Omit `issue_id` to list (same as `mortician list`).

- **Default:** raw Markdown (good for pipes and files).
- **`--render`:** render in the terminal with [Rich](https://github.com/Textualize/rich) when installed (`pip install 'mortician[rich]'`). If Rich is missing, a one-line hint is printed to stderr and the Markdown is still printed as plain text.
- **`--plain`:** force raw Markdown (overrides `MORTICIAN_SHOW_RENDER=1`).
- **Environment:** `MORTICIAN_SHOW_RENDER=1` (or `true` / `yes`) enables `--render` behavior for `mortician show <id>` without the flag.

You can also pipe Markdown to an external viewer, for example [glow](https://github.com/charmbracelet/glow):

```bash
mortician show incident-id | glow -p
```

### Export to Markdown

```bash
mortician show incident-123 > postmortem-incident-123.md
mortician show incident-123 | pandoc -o postmortem.pdf
```

### Local dashboard

```bash
mortician serve --host 127.0.0.1 --port 8765
```

Open the printed URL for a live-updating list and detail view (file changes trigger updates).

**HTTP API (selected):**

- `GET /api/postmortems` — list summaries
- `GET /api/postmortems/{issue_id}` — full incident as JSON (assembled from the bundle)
- `PUT /api/postmortems/{issue_id}/index.md` — raw Markdown body for `index.md` (UTF-8)
- `GET /api/postmortems/{issue_id}/assets/{path}` — files under `assets/` (path traversal blocked)
- `GET /api/events` — Server-Sent Events when bundle files change

## Note

I am aware that a pathologist usually conducts post-mortems. However, Mortician is a much cooler name.
