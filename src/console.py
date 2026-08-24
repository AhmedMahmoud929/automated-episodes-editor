"""Rich console helpers for colored CLI output and progress."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

THEME = Theme(
    {
        "info": "cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "step": "bold magenta",
        "muted": "dim white",
        "accent": "bold bright_cyan",
        "highlight": "bold bright_yellow",
        "option": "bright_white",
        "label": "bold blue",
    }
)

console = Console(theme=THEME)


def print_header() -> None:
    title = Text("Automated Episodes Editor", style="bold bright_white")
    subtitle = Text("Intro · Fade · Watermark · Audio · Export", style="dim cyan")
    console.print()
    console.print(
        Panel(
            Text.assemble(title, "\n", subtitle),
            border_style="bright_cyan",
            padding=(1, 2),
            expand=False,
        )
    )
    console.print()


def print_section(title: str) -> None:
    console.print(Rule(f"[accent]{title}[/accent]", style="bright_cyan"))


def print_success(message: str) -> None:
    console.print(f"[success]OK[/success] {message}")


def print_error(message: str) -> None:
    console.print(f"[error]X[/error] {message}", style="error")


def print_info(message: str) -> None:
    console.print(f"[info]→[/info] {message}")


def print_warning(message: str) -> None:
    console.print(f"[warning]![/warning] {message}")


def create_progress() -> Progress:
    return Progress(
        SpinnerColumn(spinner_name="dots", style="cyan"),
        TextColumn("[step]{task.description}[/step]"),
        BarColumn(bar_width=36, complete_style="bright_green", finished_style="green"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=True,
    )


def create_episode_table(title: str, rows: list[tuple[str, str, str]]) -> Table:
    table = Table(
        title=f"[accent]{title}[/accent]",
        border_style="bright_blue",
        header_style="bold bright_cyan",
        show_lines=False,
        pad_edge=True,
    )
    table.add_column("#", style="highlight", justify="right", width=4)
    table.add_column("ID", style="option", width=12)
    table.add_column("Details", style="white")

    for index, episode_id, details in rows:
        table.add_row(str(index), episode_id, details)

    table.add_row("[A]", "All", "[muted]Process every item[/muted]")
    return table


def print_summary_table(*, use_config: bool, episode_count: int, audio_labels: list[str]) -> None:
    table = Table(
        title="[accent]Run Summary[/accent]",
        border_style="bright_magenta",
        header_style="bold bright_magenta",
        show_header=True,
        pad_edge=True,
    )
    table.add_column("Setting", style="label")
    table.add_column("Value", style="white")

    table.add_row("Config source", "episodes.json" if use_config else "Manual folder selection")
    table.add_row("Videos to process", str(episode_count))
    table.add_row(
        "Audio enhancement",
        ", ".join(audio_labels) if audio_labels else "[muted]none[/muted]",
    )

    console.print()
    console.print(table)
    console.print()
