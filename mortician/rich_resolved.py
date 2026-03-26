"""Rich prompts for filling required fields when setting an incident to Resolved."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

PathTuple = Tuple[str, ...]


def _read_multiline_field(console: Console, label: str, initial: str) -> str:
    """
    Read multi-line text; user finishes with a line containing only END.

    If the user sends END before entering any new text, the initial value is kept
    (when non-empty).
    """
    console.print(
        Panel(
            f"[bold]{label}[/bold]\n\n"
            "Type or paste text. Blank lines are allowed.\n"
            "When finished, enter a line containing only [bold]END[/bold].",
            title="Resolved field",
            border_style="blue",
        )
    )
    if initial.strip():
        console.print("[dim]Current value:[/dim]")
        console.print(Panel(initial, border_style="dim"))
        console.print(
            "[dim]Enter replacement below, or type END immediately to keep the current value.[/dim]\n"
        )
    lines: List[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "END":
            break
        lines.append(line)
    text = "\n".join(lines).strip()
    if not text and initial.strip():
        return initial.strip()
    return text


def run_resolved_prompts(
    issue_id: str,
    empty_candidates: List[Tuple[Sequence[str], str]],
    preview_values: Dict[PathTuple, str],
) -> Optional[Dict[PathTuple, str]]:
    """
    Prompt for each empty field: whether it is required, then collect text.

    Returns a dict of path tuple -> text for each required non-skipped field.
    Returns ``None`` if the user cancels (Ctrl+C).
    """
    console = Console()
    try:
        console.print(
            Panel(
                f"[bold]Incident {issue_id}[/bold] — set to [green]Resolved[/green]\n"
                "Some fields are empty. Choose which must be filled, then enter each value.",
                title="mortician",
            )
        )

        selected: List[Tuple[Sequence[str], str]] = []
        for path, label in empty_candidates:
            if Confirm.ask(
                f"'{label}' is empty. Require it for Resolved?",
                default=True,
            ):
                selected.append((path, label))

        out: Dict[PathTuple, str] = {}
        for path, label in selected:
            initial = preview_values.get(tuple(path), "")
            text = _read_multiline_field(console, label, initial).strip()
            if not text:
                raise RuntimeError(
                    f"'{label}' is required for Resolved and cannot be empty."
                )
            out[tuple(path)] = text
        return out
    except KeyboardInterrupt:
        console.print("\n[red]Cancelled.[/red]")
        return None
