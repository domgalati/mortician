"""Fullscreen Textual viewer for `mortician show --render`."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Footer, Markdown, Static


class ShowMarkdownApp(App[None]):
    """Scrollable rendered Markdown; Escape or q to exit."""

    CSS = """
    Screen { align: center middle; }
    #main {
        width: 100%;
        height: 100%;
        padding: 0 1;
    }
    #title {
        dock: top;
        padding: 0 0 1 0;
        text-style: bold;
    }
    #scroll {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "quit", "Quit", show=True),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, issue_id: str, markdown_text: str) -> None:
        super().__init__()
        self._issue_id = issue_id
        self._md = markdown_text

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            yield Static(f"Postmortem — {self._issue_id}", id="title")
            with ScrollableContainer(id="scroll"):
                yield Markdown(self._md)
        yield Footer()

    def action_quit(self) -> None:
        self.exit()


def run_show_markdown_render(issue_id: str, markdown_text: str) -> None:
    ShowMarkdownApp(issue_id, markdown_text).run()
