"""Choosing which archives to unpack and grouping them into output folders.

The output mirrors the game's virtual file tree (see mounts). Each archive is
unpacked where it is mounted:

    res.npk, Documents/res.npk          ->  <out>/res/
    res/ui.npk, Documents/res2/ui.npk   ->  <out>/res/ui/
    res/model/character.npk             ->  <out>/res/model/character/
    script.npk, script_patch.npk        ->  <out>/script/

Archives mounted at the same place from different mount folders hold parts of
one set, so they share one output folder. Within a folder the sources are
ordered by priority (mounts.MOUNTS): if the same file appears in several of
them, the first source provides it.

Output folders are listed by section, the folder that holds them
(res/levelsets, res/model, res, top level), nested sections first.
"""

from __future__ import annotations

import difflib
import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .archive import NpkArchive, NpkEntry
from .errors import InputError, NpkextError
from .install import Installation
from .mounts import MOUNTS, mount_rank, place

TOP_SECTION = PurePosixPath(".")
"""The section of output folders that sit directly in the output folder (res, script)."""

OUTSIDE_RECORDS = "_outside"
"""Index folder for the records of archives that are not inside the installation."""


@dataclass(frozen=True)
class Location:
    """Where one archive belongs: in the game, in the output and in the index."""

    folder: PurePosixPath   # output folder, relative to --out: res/model/character
    label: str              # shown to the user: path relative to the installation, if known
    rank: int               # lower = higher priority
    mount: str              # mount folder relative to the installation ('Documents/res'), or ''
    record: PurePosixPath   # its record in the index, relative to _archives/


@dataclass
class ArchiveSource:
    """One .npk file that is part of an output folder."""

    path: Path
    location: Location
    entry_count: int   # entries that will be processed (after --limit)
    total_entries: int
    packed_bytes: int
    raw_bytes: int

    @property
    def label(self) -> str:
        return self.location.label

    @property
    def rank(self) -> int:
        return self.location.rank


@dataclass
class OutputGroup:
    """All archives mounted at the same place in the tree, unpacked into one folder."""

    folder: PurePosixPath          # relative to the output folder, e.g. res/model/character
    sources: list[ArchiveSource]   # highest priority first

    @property
    def folder_name(self) -> str:
        return self.folder.as_posix()

    @property
    def section(self) -> PurePosixPath:
        """The folder that holds this one: res/model for res/model/character."""
        return self.folder.parent

    @property
    def entry_count(self) -> int:
        return sum(s.entry_count for s in self.sources)

    @property
    def packed_bytes(self) -> int:
        return sum(s.packed_bytes for s in self.sources)

    @property
    def raw_bytes(self) -> int:
        return sum(s.raw_bytes for s in self.sources)


@dataclass
class Plan:
    groups: list[OutputGroup]                    # sorted by section, see group_order
    unreadable: list[tuple[Path, str]] = field(default_factory=list)   # (archive, reason)
    installation: Installation | None = None
    known_archives: list[Path] = field(default_factory=list)
    """Every archive that could be mounted below a planned folder, also those not
    being unpacked. Used to tell when a parent archive's file is replaced."""

    @property
    def source_count(self) -> int:
        return sum(len(g.sources) for g in self.groups)

    @property
    def entry_count(self) -> int:
        return sum(g.entry_count for g in self.groups)

    @property
    def packed_bytes(self) -> int:
        return sum(g.packed_bytes for g in self.groups)

    @property
    def raw_bytes(self) -> int:
        return sum(g.raw_bytes for g in self.groups)

    def sections(self) -> list[tuple[PurePosixPath, list[OutputGroup]]]:
        """The groups split by section, in plan order."""
        result: list[tuple[PurePosixPath, list[OutputGroup]]] = []
        for group in self.groups:
            if not result or result[-1][0] != group.section:
                result.append((group.section, []))
            result[-1][1].append(group)
        return result


def output_folder(archive_path: Path) -> PurePosixPath:
    """Where an archive is unpacked, relative to the output folder (see module docstring).

    An archive outside every known mount folder (a loose copy) gets a folder named
    after it at the top.
    """
    placement = place(archive_path)
    return placement.output_folder if placement else PurePosixPath(archive_path.stem)


def locate(path: Path, installation: Installation | None, order: int = 0) -> Location:
    """Everything about where `path` belongs. `order` (its position on the command line)
    ranks archives outside the installation's mount folders, after all of those."""
    relative = installation.relative(path) if installation else None
    placement = place(relative if relative is not None else path)
    rank = mount_rank(placement.root) if placement and relative is not None else None
    if relative is not None:
        record = PurePosixPath(relative.as_posix() + ".csv")
    else:
        record = PurePosixPath(OUTSIDE_RECORDS, _flat_name(str(path.resolve())) + ".csv")
    return Location(
        folder=placement.output_folder if placement else PurePosixPath(path.stem),
        label=str(relative) if relative is not None else str(path),
        rank=rank if rank is not None else len(MOUNTS) + order,
        mount=placement.root.as_posix() if placement and relative is not None else "",
        record=record,
    )


def tree_order(folder: PurePosixPath) -> tuple[str, ...]:
    """Sort key: alphabetical, but every folder after the folders nested in it
    (res/model/character, res/ui, res, then the top level)."""
    parts = () if folder == TOP_SECTION else folder.parts
    return (*(part.lower() for part in parts), "\U0010ffff")


def group_order(group: OutputGroup) -> tuple:
    """Groups sorted by section (nested sections first), then by name."""
    return tree_order(group.section), group.folder.name.lower()


def selected_entries(entries: list[NpkEntry], limit: int | None) -> list[NpkEntry]:
    """The entries of an archive that will be processed, in the order they are stored
    on disk (sequential reading is much faster). All of them, or the first `limit`."""
    in_storage_order = sorted(entries, key=lambda e: e.offset)
    return in_storage_order[:limit] if limit else in_storage_order


def resolve_inputs(inputs: list[str], installation: Installation | None) -> list[Path]:
    """Turn the values given to --in into archive files.

    Each value is one of:
      * a path to an archive file                          path/to/ui.npk
      * with an installation: an archive name, searched    ui.npk, ui, 'res_dlc_*'
        in every mount folder of the installation
      * with an installation: a path relative to it        res/ui.npk, 'Documents/res/*.npk'
        (selects specific mount folders; wildcards allowed)
    """
    found: list[Path] = []
    names: list[str] = []
    for value in inputs:
        path = Path(value).expanduser()
        if path.is_file():
            found.append(path)
        elif installation is None or path.is_absolute():
            raise InputError(f"archive not found: {value}"
                             + ("" if installation else " (to search by name, also give --install DIR)"))
        elif "/" in value or "\\" in value:
            found.extend(_glob_in_installation(installation, value))
        else:
            names.append(value)

    if names:
        found.extend(filter_by_name(installation.archives(), names))
    return list(dict.fromkeys(found))   # drop duplicates, keep order


def filter_by_name(archives: list[Path], patterns: list[str]) -> list[Path]:
    """Keep archives whose file name matches any of the patterns.

    A pattern is a file name with or without '.npk' and may use wildcards:
    'ui.npk', 'ui', 'res_dlc_*'. Matching ignores upper/lower case.
    """
    selected: list[Path] = []
    unmatched: list[str] = []
    for pattern in patterns:
        matches = [a for a in archives if _name_matches(a.name, pattern)]
        if not matches:
            unmatched.append(pattern)
        selected.extend(matches)

    if unmatched:
        raise InputError(_no_match_message(unmatched, archives))
    return list(dict.fromkeys(selected))   # drop duplicates, keep order


def build_plan(archives: list[Path], installation: Installation | None = None,
               limit: int | None = None) -> Plan:
    """Read the table of contents of every archive and group them into output folders."""
    by_folder: dict[str, list[ArchiveSource]] = {}
    unreadable: list[tuple[Path, str]] = []

    for order, path in enumerate(archives):
        try:
            source = _describe(path, locate(path, installation, order), limit)
        except (NpkextError, OSError) as exc:
            unreadable.append((path, str(exc)))
            continue
        by_folder.setdefault(source.location.folder.as_posix().lower(), []).append(source)

    groups = [
        OutputGroup(folder=sources[0].location.folder,
                    sources=sorted(sources, key=lambda s: (s.rank, s.label)))
        for sources in by_folder.values()
    ]
    groups.sort(key=group_order)
    known = installation.archives() if installation else list(archives)
    return Plan(groups, unreadable, installation, known)


# -- internals ---------------------------------------------------------------------------------

def _describe(path: Path, location: Location, limit: int | None) -> ArchiveSource:
    with NpkArchive(path) as archive:
        entries = selected_entries(archive.entries, limit)
        total = len(archive.entries)
    return ArchiveSource(
        path=path,
        location=location,
        entry_count=len(entries),
        total_entries=total,
        packed_bytes=sum(e.packed_size for e in entries),
        raw_bytes=sum(e.raw_size for e in entries),
    )


def _flat_name(path: str) -> str:
    """'/home/me/copies/ui.npk' -> 'home_me_copies_ui.npk' (one file name per path)."""
    return re.sub(r"[\\/:]+", "_", path).strip("_")


def _glob_in_installation(installation: Installation, pattern: str) -> list[Path]:
    matches = sorted(p for p in installation.root.glob(pattern.replace("\\", "/"))
                     if p.is_file() and p.suffix.lower() == ".npk")
    if not matches:
        raise InputError(f"no archive at '{pattern}' in {installation.root}")
    return matches


def _name_matches(name: str, pattern: str) -> bool:
    name, pattern = name.lower(), pattern.lower()
    return fnmatch.fnmatchcase(name, pattern) or fnmatch.fnmatchcase(name, pattern + ".npk")


def _no_match_message(patterns: list[str], archives: list[Path]) -> str:
    known = sorted({a.name for a in archives})
    lines = []
    for pattern in patterns:
        close = difflib.get_close_matches(pattern, known, n=4, cutoff=0.5)
        hint = f" (did you mean {', '.join(close)}?)" if close else ""
        lines.append(f"no archive named '{pattern}'{hint}")
    return "\n".join(lines)
