"""Everything shown in the terminal: banner, plan table, progress bars and summary.

Built with `rich`. Nothing else in the package prints; the extractor reports
progress through the ExtractListener interface, implemented here by ProgressDisplay.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path, PurePosixPath

from rich import box
from rich.console import Console, Group
from rich.filesize import decimal as human_size
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
from rich.progress import (BarColumn, DownloadColumn, MofNCompleteColumn, Progress,
                           SpinnerColumn, TaskProgressColumn, TextColumn,
                           TimeRemainingColumn, TransferSpeedColumn)
from rich.table import Table

from . import __version__
from .archive import NpkEntry
from .extract import INDEX_FOLDER, ExtractListener, GroupResult
from .install import Installation
from .plan import TOP_SECTION, ArchiveSource, OutputGroup, Plan

def _tolerate_limited_encodings() -> None:
    """Output redirected to a file on Windows uses a legacy code page that has no
    '✓' or '…'. Print a replacement character instead of crashing."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


_tolerate_limited_encodings()
console = Console(highlight=False)

MAX_FAILURES_SHOWN = 15


# -- before extraction ---------------------------------------------------------------------------

def show_banner() -> None:
    console.print(Panel.fit(f"[bold cyan]npkext[/] [dim]v{__version__}[/]\n"
                            f"NeoX NXPK archive extractor", border_style="cyan"))


def status(message: str):
    """A spinner shown while a slow step runs: `with ui.status("..."):`."""
    return console.status(message, spinner="dots")


def show_sources(installation: Installation | None, resdb_files: list[Path],
                 manifest_size: int) -> None:
    if installation:
        console.print(f"[bold]Installation[/]  {installation.root}")
    if manifest_size:
        files = ", ".join(str(installation.relative(f) or f) if installation else str(f)
                          for f in resdb_files)
        console.print(f"[bold]File names[/]    {manifest_size:,} paths from {files}")
    else:
        console.print("[yellow]No resdb manifest given or found: files will be saved under "
                      "_unnamed/ with guessed extensions. Use --resdb to name them.[/]")


def show_plan(plan: Plan, out_dir: Path | None) -> None:
    for path, reason in plan.unreadable:
        console.print(f"[yellow]skipping {path}: {reason}[/]")
    if not plan.groups:
        console.print("[yellow]Nothing to unpack.[/]")
        return

    console.print()
    console.rule("[bold]Unpack plan", align="left")
    for section, groups in plan.sections():
        _section_heading(section, groups)
        table = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style="dim")
        table.add_column("Folder", style="cyan", no_wrap=True)
        table.add_column("From (highest priority first)")
        table.add_column("Files", justify="right")
        table.add_column("Packed", justify="right")
        table.add_column("Unpacked", justify="right")
        for group in groups:
            table.add_row(group.folder.name, ", ".join(_origin(s) for s in group.sources),
                          f"{group.entry_count:,}", human_size(group.packed_bytes),
                          human_size(group.raw_bytes))
        console.print(Padding(table, (0, 0, 0, 2)))

    console.rule(style="dim")
    console.print(f"[bold]Total[/]         {_count(len(plan.groups), 'folder')} from "
                  f"{_count(plan.source_count, 'archive')}, {plan.entry_count:,} files, "
                  f"{human_size(plan.packed_bytes)} packed, {human_size(plan.raw_bytes)} unpacked")
    if out_dir is not None:
        free = _free_space(out_dir)
        console.print(f"[bold]Output[/]        {out_dir}  "
                      f"[dim]({human_size(plan.raw_bytes)} to write, {human_size(free)} free)[/]")
        if plan.raw_bytes > free:
            console.print("[bold red]Warning:[/] not enough free disk space for everything.")


# -- during extraction ---------------------------------------------------------------------------

class ProgressDisplay(ExtractListener):
    """Two live progress bars: the current output folder and the whole run.

    Use as a context manager around Extractor.run().
    """

    def __init__(self, plan: Plan):
        self.current = Progress(
            SpinnerColumn(), TextColumn("[cyan]{task.description}"), BarColumn(),
            MofNCompleteColumn(), TextColumn("[dim]{task.fields[source]}"), console=console)
        self.overall = Progress(
            TextColumn("[bold]Total        "), BarColumn(), TaskProgressColumn(),
            DownloadColumn(), TransferSpeedColumn(), TimeRemainingColumn(), console=console)
        self._overall_task = self.overall.add_task("total", total=plan.raw_bytes)
        self._group_task = None
        self._section: PurePosixPath | None = None
        self._live = Live(Group(self.current, self.overall), console=console, refresh_per_second=8)

    def __enter__(self) -> ProgressDisplay:
        self._live.__enter__()
        return self

    def __exit__(self, *exc_info) -> None:
        self._live.__exit__(*exc_info)

    def group_started(self, group: OutputGroup) -> None:
        if group.section != self._section:
            self._section = group.section
            _section_heading(group.section)
        if self._group_task is not None:
            self.current.remove_task(self._group_task)
        self._group_task = self.current.add_task(group.folder_name, total=group.entry_count, source="")

    def source_started(self, source: ArchiveSource) -> None:
        self.current.update(self._group_task, source=source.label)

    def source_failed(self, source: ArchiveSource, reason: str) -> None:
        self.current.advance(self._group_task, source.entry_count)
        self.overall.advance(self._overall_task, source.raw_bytes)

    def entry_finished(self, entry: NpkEntry) -> None:
        self.current.advance(self._group_task)
        self.overall.advance(self._overall_task, entry.raw_size)

    def group_finished(self, result: GroupResult) -> None:
        mark = "[red]✗[/]" if result.failures else "[green]✓[/]"
        details = [f"{result.written:,} files"]
        if result.unnamed:
            details.append(f"{result.unnamed:,} unnamed")
        if result.overridden:
            details.append(f"{result.overridden:,} overridden")
        if result.failures:
            details.append(f"[red]{len(result.failures):,} failed[/]")
        console.print(f"  {mark} [cyan]{result.group.folder.name}[/]  {', '.join(details)}  "
                      f"[dim]{human_size(result.bytes_written)}[/]")


# -- after extraction ----------------------------------------------------------------------------

def show_summary(results: list[GroupResult], seconds: float, out_dir: Path) -> None:
    console.print()
    table = Table(title="Result", title_justify="left", header_style="bold")
    table.add_column("Section", style="bold cyan", no_wrap=True)
    for heading in ("Folders", "Files", "Named", "Unnamed", "Overridden", "Failed", "Written"):
        table.add_column(heading, justify="right")

    by_section: dict[PurePosixPath, list[GroupResult]] = {}
    for result in results:
        by_section.setdefault(result.group.section, []).append(result)
    for section, section_results in by_section.items():
        table.add_row(section_name(section), *_result_cells(section_results))
    table.add_section()
    table.add_row("[bold]Total[/]", *_result_cells(results))
    console.print(table)

    failures = [failure for r in results for failure in r.failures]
    for where, why in failures[:MAX_FAILURES_SHOWN]:
        console.print(f"[red]failed[/] {where}: {why}")
    if len(failures) > MAX_FAILURES_SHOWN:
        console.print(f"[red]… and {len(failures) - MAX_FAILURES_SHOWN} more failures[/] "
                      f"(status 'failed' in the records in {INDEX_FOLDER}/)")

    console.print(f"\nDone in {_duration(seconds)}. Output: [bold]{out_dir}[/]")
    console.print(f"[dim]{INDEX_FOLDER}/ records every archive and where each of its files "
                  f"went; see {INDEX_FOLDER}/README.txt.[/]")


def show_error(message: str) -> None:
    console.print(f"[bold red]error:[/] {message}")


# -- helpers -------------------------------------------------------------------------------------

def _result_cells(results: list[GroupResult]) -> list[str]:
    failed = sum(len(r.failures) for r in results)
    return [
        f"{len(results):,}",
        f"{sum(r.written for r in results):,}",
        f"{sum(r.named for r in results):,}",
        f"{sum(r.unnamed for r in results):,}",
        f"{sum(r.overridden for r in results):,}",
        f"[red]{failed:,}[/]" if failed else "0",
        human_size(sum(r.bytes_written for r in results)),
    ]


def section_name(section: PurePosixPath) -> str:
    """'res/levelsets/', or '(top level)' for folders directly in the output folder."""
    return "(top level)" if section == TOP_SECTION else section.as_posix() + "/"


def _section_heading(section: PurePosixPath, groups: list[OutputGroup] | None = None) -> None:
    summary = ""
    if groups is not None:
        summary = (f"  [dim]{_count(len(groups), 'folder')}, "
                   f"{human_size(sum(g.raw_bytes for g in groups))}[/]")
    console.print(f"\n[bold magenta]▸ {section_name(section)}[/]{summary}")


def _origin(source: ArchiveSource) -> str:
    """Which mount folder a source comes from, or its path if it is not in one."""
    return source.location.mount or source.label


def _count(number: int, noun: str) -> str:
    """'1 folder', '3 folders'."""
    return f"{number:,} {noun}" + ("" if number == 1 else "s")


def _free_space(folder: Path) -> int:
    existing = folder.resolve()
    while not existing.exists():
        existing = existing.parent
    return shutil.disk_usage(existing).free


def _duration(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"
