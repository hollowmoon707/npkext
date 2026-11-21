"""Recovering file names.

An archive stores only a hash of each file's path (the entry id). The game also
ships a plain list of every resource path, the resource manifest `resdb`.
Names are recovered by hashing paths from that list and matching them to ids.

The hashed path is relative to where the archive is mounted in the resource
tree (see mounts):

    res/model/character.npk  ->  files listed under 'model\\character\\'
    res/levelsets/lake.npk   ->  files listed under 'levelsets\\lake\\'
    res/ui.npk               ->  files listed under 'ui\\'
    res.npk  (next to res/)  ->  every file, no prefix

So for res/ui.npk the manifest path 'ui\\login\\bg.png' is hashed as
'login\\bg.png', and that is also the file's path inside the archive.
"""

from __future__ import annotations

import bisect
import zlib
from pathlib import Path

from .errors import ManifestError
from .hashing import path_id
from .mounts import place

RESDB_MAGIC = b"CCZ!"
RESDB_HEADER_SIZE = 16


def read_resdb(path: str | Path) -> list[str]:
    """All resource paths listed in one resdb file.

    Format: a 16-byte header starting with b"CCZ!", then a zlib stream of text
    lines "<flag> <path>" with backslash-separated paths.
    """
    blob = Path(path).read_bytes()
    if blob[:4] != RESDB_MAGIC:
        raise ManifestError(f"{path}: not a resdb manifest (does not start with CCZ!)")
    try:
        text = zlib.decompressobj().decompress(blob[RESDB_HEADER_SIZE:])
    except zlib.error as exc:
        raise ManifestError(f"{path}: cannot decompress: {exc}") from exc

    paths = []
    for line in text.decode("utf-8", errors="replace").splitlines():
        _flag, _, resource_path = line.partition(" ")
        if resource_path:
            paths.append(resource_path)
    return paths


class ResourceManifest:
    """A sorted list of resource paths that can be searched by prefix."""

    def __init__(self, paths):
        self._paths = sorted(set(paths), key=str.lower)
        self._keys = [p.lower() for p in self._paths]

    @classmethod
    def from_files(cls, resdb_files) -> ResourceManifest:
        """Merge the paths of several resdb files (e.g. the shipped one and a patched one)."""
        paths: list[str] = []
        for resdb in resdb_files:
            paths.extend(read_resdb(resdb))
        return cls(paths)

    def __len__(self) -> int:
        return len(self._paths)

    def paths_under(self, prefix: str) -> list[str]:
        """Every path that starts with `prefix` (ignoring upper/lower case)."""
        key = prefix.lower()
        start = bisect.bisect_left(self._keys, key)
        end = start
        while end < len(self._keys) and self._keys[end].startswith(key):
            end += 1
        return self._paths[start:end]


def candidate_prefixes(archive_path: Path) -> list[str]:
    """Where in the resource tree the files of this archive are listed (see module docstring).

    Empty for archives that resdb does not cover (scripts).
    """
    placement = place(archive_path)
    if placement is not None:
        prefix = placement.name_prefix
        return [] if prefix is None else [prefix]
    # Not in or next to a mount folder: a loose copy. Try it as a root archive
    # (like res.npk) and as a top-level branch (like res/ui.npk).
    return ["", archive_path.stem + "\\"]


class NameResolver:
    """Finds the names of the entries in an archive."""

    def __init__(self, manifest: ResourceManifest):
        self.manifest = manifest
        self._tables: dict[str, dict[int, str]] = {}

    def names_for(self, archive_path: Path) -> dict[int, str]:
        """Map entry id -> path inside the archive (backslash separated)."""
        names: dict[int, str] = {}
        for prefix in candidate_prefixes(archive_path):
            for entry_id, inner_path in self._table_for(prefix).items():
                names.setdefault(entry_id, inner_path)
        return names

    def _table_for(self, prefix: str) -> dict[int, str]:
        # Archives mounted at one place from several folders share a prefix, so cache per prefix.
        if prefix not in self._tables:
            table = {}
            for full_path in self.manifest.paths_under(prefix):
                inner_path = full_path[len(prefix):]
                table[path_id(inner_path)] = inner_path
            self._tables[prefix] = table
        return self._tables[prefix]
