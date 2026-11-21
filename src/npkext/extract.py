"""Running a plan: decode every entry and write the files.

Output layout (see plan for where each archive goes):

    <out>/
        _archives/                       the index: everything needed to rebuild the archives
            index.csv                    one row per archive ever unpacked into <out>
            mounts.csv                   the mount folders and their priority
            README.txt                   what the columns mean
            <archive path>.csv           one record per archive, e.g. Documents/res/ui.npk.csv
        res/                             the resource tree
            <path in the tree>           files whose name was recovered
            ui/_unnamed/<id>.<ext>       files whose name is unknown, in their archive's folder
            ui/_overridden/<source>/...  lower-priority copies, only with keep_overridden
        script/                          the script tree

Output folders nest (res/ holds res/ui/), so a parent archive can hold a file at
a path a nested archive also fills. The nested archive's copy wins; the parent's
is treated like a lower-priority copy (see ReplacedPaths).
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .archive import NpkArchive, NpkEntry
from .codec import decode_entry
from .errors import EntryError, NpkextError
from .filetypes import guess_extension
from .hashing import path_id
from .mounts import MOUNTS
from .names import NameResolver
from .pagecache import WriteBehind
from .plan import ArchiveSource, OutputGroup, Plan, locate, selected_entries

INDEX_FOLDER = "_archives"
UNNAMED_FOLDER = "_unnamed"
OVERRIDDEN_FOLDER = "_overridden"


@dataclass
class ExtractOptions:
    out_dir: Path
    verify: bool = True             # check both checksums of every entry
    keep_overridden: bool = False   # also write lower-priority copies of files
    limit: int | None = None        # only the first N entries of each archive


@dataclass
class GroupResult:
    """What happened while unpacking one output folder."""

    group: OutputGroup
    named: int = 0          # files written under their real name
    unnamed: int = 0        # files written to _unnamed/
    overridden: int = 0     # entries also provided by a higher-priority or nested archive
    bytes_written: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)   # (which entry, why)

    @property
    def written(self) -> int:
        return self.named + self.unnamed


class ExtractListener:
    """Receives progress events. The default does nothing; the terminal UI overrides it."""

    def group_started(self, group: OutputGroup) -> None: ...
    def source_started(self, source: ArchiveSource) -> None: ...
    def source_failed(self, source: ArchiveSource, reason: str) -> None: ...
    def entry_finished(self, entry: NpkEntry) -> None: ...
    def group_finished(self, result: GroupResult) -> None: ...


class Extractor:
    """Unpacks the groups of a plan, one after another, and updates the index."""

    def __init__(self, resolver: NameResolver, options: ExtractOptions,
                 listener: ExtractListener | None = None):
        self.resolver = resolver
        self.options = options
        self.listener = listener or ExtractListener()
        self.write_behind = WriteBehind()   # keeps written files from filling RAM
        self.index = ArchiveIndex(options.out_dir / INDEX_FOLDER)

    def run(self, plan: Plan) -> list[GroupResult]:
        replaced = ReplacedPaths.find(plan, self.resolver, self.options.limit)
        try:
            return [self.extract_group(group, replaced) for group in plan.groups]
        finally:
            self.write_behind.flush()
            self.index.save()

    def extract_group(self, group: OutputGroup,
                      replaced: ReplacedPaths | None = None) -> GroupResult:
        self.listener.group_started(group)
        folder = self.options.out_dir.joinpath(*group.folder.parts)
        job = _GroupJob(group, FileWriter(folder, self.write_behind), self.resolver,
                        self.options, self.listener, replaced or ReplacedPaths({}), self.index)
        result = job.run()
        self.listener.group_finished(result)
        return result


class _GroupJob:
    """Unpacks all sources of one output group into one folder."""

    def __init__(self, group: OutputGroup, writer: FileWriter, resolver: NameResolver,
                 options: ExtractOptions, listener: ExtractListener,
                 replaced: ReplacedPaths, index: ArchiveIndex):
        self.group = group
        self.writer = writer
        self.resolver = resolver
        self.options = options
        self.listener = listener
        self.replaced = replaced
        self.index = index
        self.result = GroupResult(group)
        self.provided: dict[int, str] = {}   # id -> the higher-priority source that wrote it

    def run(self) -> GroupResult:
        for source in self.group.sources:   # highest priority first
            self._unpack_source(source)
        return self.result

    def _unpack_source(self, source: ArchiveSource) -> None:
        self.listener.source_started(source)
        try:
            archive = NpkArchive(source.path)
        except (NpkextError, OSError) as exc:
            self.result.failures.append((source.label, str(exc)))
            self.listener.source_failed(source, str(exc))
            return

        with archive:
            record = ArchiveRecord(archive.entries)
            names = self.resolver.names_for(source.path)
            try:
                for entry in selected_entries(archive.entries, self.options.limit):
                    self._unpack_entry(archive, entry, source, names, record)
                    self.listener.entry_finished(entry)
            finally:
                self.index.add(source, record)

    def _unpack_entry(self, archive: NpkArchive, entry: NpkEntry, source: ArchiveSource,
                      names: dict[int, str], record: ArchiveRecord) -> None:
        name = safe_relative_path(names.get(entry.id))
        winner = self.provided.get(entry.id)
        if winner is None and name is not None:
            winner = self.replaced.by(self.group, name)
        note = f"replaced by {winner}" if winner else ""

        if winner:
            self.result.overridden += 1
            if not self.options.keep_overridden:
                record.set(entry, "overridden", note=note)
                return

        try:
            data = decode_entry(archive, entry, verify=self.options.verify)
        except EntryError as exc:
            # Not marked as provided, so a lower-priority copy can still fill the gap.
            self._fail(entry, source, record, str(exc))
            return

        relative = name or PurePosixPath(UNNAMED_FOLDER, f"{entry.id:08x}.{guess_extension(data)}")
        if winner:
            relative = PurePosixPath(OVERRIDDEN_FOLDER, folder_tag(source.label)) / relative

        try:
            self.writer.write(relative, data)
        except OSError as exc:
            self._fail(entry, source, record, f"cannot write {relative}: {exc}")
            return

        self.result.bytes_written += len(data)
        record.set(entry, "overridden" if winner else "ok",
                   path=(self.group.folder / relative).as_posix(), note=note)
        if not winner:
            self.provided[entry.id] = source.label
            if name:
                self.result.named += 1
            else:
                self.result.unnamed += 1

    def _fail(self, entry: NpkEntry, source: ArchiveSource, record: ArchiveRecord,
              reason: str) -> None:
        self.result.failures.append((f"{source.label} entry {entry.id:08x}", reason))
        record.set(entry, "failed", note=reason)


class ReplacedPaths:
    """Files of a parent archive that a nested archive replaces.

    res.npk holds the whole resource tree, so it can contain a file such as
    model/character/a.gim that res/model/character.npk also contains, with
    different bytes. Both would land at res/model/character/a.gim. The nested
    (more specific) archive's copy wins; the parent's is treated like a
    lower-priority copy.

    The nested archives are looked up in the whole installation, not only in
    this run, so the result is the same whichever archives are unpacked and in
    which order.
    """

    def __init__(self, replaced: dict[tuple[str, str], str]):
        self._replaced = replaced   # (parent folder, path in it), lower case -> archive that wins

    def by(self, group: OutputGroup, name: PurePosixPath) -> str | None:
        """The nested archive whose copy of `name` wins over this group's, if any."""
        return self._replaced.get((_key(group.folder), _key(name)))

    @classmethod
    def find(cls, plan: Plan, resolver: NameResolver, limit: int | None) -> ReplacedPaths:
        nested = _NestedArchives(plan)
        replaced: dict[tuple[str, str], str] = {}
        for group in plan.groups:
            if not nested.has_any_below(group.folder):
                continue
            for source in group.sources:
                names = resolver.names_for(source.path)
                try:
                    with NpkArchive(source.path) as archive:
                        ids = [e.id for e in selected_entries(archive.entries, limit)]
                except (NpkextError, OSError):
                    continue   # reported when the group is unpacked
                for entry_id in ids:
                    name = safe_relative_path(names.get(entry_id))
                    winner = nested.holder_of(group.folder, name) if name else None
                    if winner:
                        replaced[_key(group.folder), _key(name)] = winner
        return cls(replaced)


class _NestedArchives:
    """Every known archive by output folder, with their ids read on demand."""

    def __init__(self, plan: Plan):
        self._by_folder: dict[str, list[tuple[int, str, Path]]] = {}
        archives = {*plan.known_archives, *(s.path for g in plan.groups for s in g.sources)}
        for path in archives:
            location = locate(path, plan.installation)
            self._by_folder.setdefault(_key(location.folder), []).append(
                (location.rank, location.label, path))
        for holders in self._by_folder.values():
            holders.sort()
        self._ids: dict[Path, set[int]] = {}

    def has_any_below(self, folder: PurePosixPath) -> bool:
        prefix = _key(folder) + "/"
        return any(key.startswith(prefix) for key in self._by_folder)

    def holder_of(self, parent: PurePosixPath, name: PurePosixPath) -> str | None:
        """The highest-priority archive in a folder nested in `parent` that holds `name`
        (a path relative to `parent`). The deepest such folder decides."""
        for depth in range(len(name.parts) - 1, 0, -1):
            holders = self._by_folder.get(_key(parent.joinpath(*name.parts[:depth])))
            if holders is None:
                continue
            inner_id = path_id("\\".join(name.parts[depth:]))
            for _rank, label, path in holders:
                if inner_id in self._ids_of(path):
                    return label
            return None
        return None

    def _ids_of(self, path: Path) -> set[int]:
        if path not in self._ids:
            try:
                with NpkArchive(path) as archive:
                    self._ids[path] = {e.id for e in archive.entries}
            except (NpkextError, OSError):
                self._ids[path] = set()
        return self._ids[path]


class ArchiveRecord:
    """One archive's table of contents plus what happened to each entry.

    Written to _archives/<archive path>.csv, rows in the archive's own table order.
    Entries not looked at (because of --limit) have the status 'skipped'.
    """

    COLUMNS = ("toc_index", "id", "offset", "packed_size", "raw_size", "crc_packed",
               "crc_raw", "flags", "status", "path", "note")

    def __init__(self, entries: list[NpkEntry]):
        self.entries = entries
        self._outcome: dict[int, tuple[str, str, str]] = {}   # toc index -> (status, path, note)
        self._toc_index = {id(entry): index for index, entry in enumerate(entries)}

    def set(self, entry: NpkEntry, status: str, path: str = "", note: str = "") -> None:
        self._outcome[self._toc_index[id(entry)]] = (status, path, note)

    @property
    def looked_at(self) -> int:
        return len(self._outcome)

    def write(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", newline="", encoding="utf-8") as fh:
            out = csv.writer(fh)
            out.writerow(self.COLUMNS)
            for index, e in enumerate(self.entries):
                status, path, note = self._outcome.get(index, ("skipped", "", ""))
                out.writerow((index, f"{e.id:08x}", e.offset, e.packed_size, e.raw_size,
                              f"{e.crc_packed:08x}", f"{e.crc_raw:08x}", f"{e.flags:#x}",
                              status, path, note))


class ArchiveIndex:
    """The _archives/ folder. Each run adds or replaces the records of the archives
    it unpacked and keeps the others, so archives can be unpacked one at a time."""

    COLUMNS = ("archive", "mount", "priority", "output_folder", "entries", "looked_at",
               "size", "record")

    def __init__(self, folder: Path):
        self.folder = folder
        self._rows: dict[str, dict[str, str]] = {}
        self._loaded = False

    def add(self, source: ArchiveSource, record: ArchiveRecord) -> None:
        self._load()
        location = source.location
        record.write(self.folder.joinpath(*location.record.parts))
        self._rows[location.label] = {
            "archive": location.label,
            "mount": location.mount,
            "priority": str(location.rank) if location.mount else "",
            "output_folder": location.folder.as_posix(),
            "entries": str(len(record.entries)),
            "looked_at": str(record.looked_at),
            "size": str(source.path.stat().st_size),
            "record": location.record.as_posix(),
        }

    def save(self) -> None:
        if not self._loaded:
            return   # nothing was unpacked
        with open(self.folder / "index.csv", "w", newline="", encoding="utf-8") as fh:
            out = csv.DictWriter(fh, self.COLUMNS)
            out.writeheader()
            out.writerows(sorted(self._rows.values(), key=lambda r: r["archive"].lower()))
        with open(self.folder / "mounts.csv", "w", newline="", encoding="utf-8") as fh:
            out = csv.writer(fh)
            out.writerow(("priority", "mount", "depth", "tree"))
            out.writerows((rank, m.root, m.depth, m.tree) for rank, m in enumerate(MOUNTS))
        (self.folder / "README.txt").write_text(INDEX_README, encoding="utf-8")

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self.folder.mkdir(parents=True, exist_ok=True)
        existing = self.folder / "index.csv"
        if existing.is_file():
            with open(existing, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("archive"):
                        self._rows[row["archive"]] = {c: row.get(c) or "" for c in self.COLUMNS}


INDEX_README = """\
This folder records where every unpacked file came from, so the original .npk
archives can be rebuilt. Written by npkext.

index.csv     one row per archive unpacked into this output folder
  archive         path of the .npk, relative to the game installation
  mount           the mount folder it belongs to (Documents/res, res2, ...)
  priority        rank of that mount folder, 0 = highest (see mounts.csv)
  output_folder   where its files went, relative to the output folder
  entries         number of files in the archive
  looked_at       how many were processed (less than entries with --limit)
  size            size of the .npk in bytes
  record          its record file, relative to this folder

mounts.csv    the folders the game loads archives from, highest priority first
  depth           how many folder levels below the mount folder archives are found
  tree            res (resources) or script

<archive>.csv one record per archive, rows in the archive's own table order
  toc_index       position in the archive's table of contents
  id              hash of the file's path inside the archive (hex)
  offset          where the stored bytes start in the .npk (storage order)
  packed_size, raw_size, crc_packed, crc_raw, flags
                  the table-of-contents values, unchanged
  status          ok          written to path
                  overridden  another archive's copy was used (see note);
                              written to path only with --keep-overridden
                  failed      could not be decoded (see note)
                  skipped     not processed (--limit)
  path            the written file, relative to the output folder
  note            which archive replaced this copy, or the error
"""


class FileWriter:
    """Writes files below one folder, creating each sub-folder only once.

    Every written file is reported to `write_behind`, which flushes it to disk and
    drops it from RAM in batches (see pagecache).
    """

    def __init__(self, root: Path, write_behind: WriteBehind | None = None):
        self.root = without_length_limit(root)
        self.write_behind = write_behind or WriteBehind()
        self._created: set[Path] = set()

    def write(self, relative: PurePosixPath, data: bytes) -> None:
        target = self.root.joinpath(*relative.parts)
        if target.parent not in self._created:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._created.add(target.parent)
        target.write_bytes(data)
        self.write_behind.written(target, len(data))


def without_length_limit(folder: Path) -> Path:
    """On Windows, return `folder` in extended-length form (\\\\?\\C:\\...).

    Windows refuses paths longer than 260 characters unless long paths are
    enabled system-wide. Deep archive paths below a deep output folder can exceed
    that; the extended form has no such limit. Elsewhere `folder` is returned as is.
    """
    if os.name != "nt":
        return folder
    return Path(extended_length_path(str(folder.resolve())))


def extended_length_path(absolute: str) -> str:
    """'C:\\out' -> '\\\\?\\C:\\out', '\\\\server\\share' -> '\\\\?\\UNC\\server\\share'."""
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def safe_relative_path(inner_path: str | None) -> PurePosixPath | None:
    """Turn a backslash path from the manifest into a relative path that cannot escape the
    output folder. Returns None for missing or suspicious paths."""
    if not inner_path:
        return None
    parts = [p for p in re.split(r"[\\/]", inner_path) if p not in ("", ".")]
    if not parts or any(p == ".." or ":" in p for p in parts):
        return None
    return PurePosixPath(*parts)


def _key(path: PurePosixPath) -> str:
    return path.as_posix().lower()


def folder_tag(label: str) -> str:
    """'Documents/res/ui.npk' -> 'Documents_res_ui.npk' (one folder name per source)."""
    return re.sub(r"[\\/:]+", "_", label).strip("_")
