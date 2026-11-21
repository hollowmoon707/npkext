"""Reading the NXPK container format.

Layout (all integers are little-endian unsigned 32-bit):

    0x00  magic b"NXPK"
    0x04  number of entries
    0x08  unused (0)
    0x0C  unused (0)
    0x10  unused (0)
    0x14  offset of the table of contents
    0x18  file data, stored back to back
    ....  table of contents: one 28-byte row per entry
            id, offset, packed_size, raw_size, crc_packed, crc_raw, flags
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from . import pagecache
from .errors import ArchiveFormatError, EntryError

MAGIC = b"NXPK"
HEADER_SIZE = 0x18
ENTRY_COUNT_OFFSET = 0x04
TOC_OFFSET_OFFSET = 0x14

_U32 = struct.Struct("<I")
TOC_ROW = struct.Struct("<7I")

READ_BUFFER_SIZE = 1 << 20
"""Reads go through a 1 MiB buffer: small entries stored next to each other cost one read."""

FORGET_READ_DATA_EVERY = 64 << 20
"""After this much data is read, its pages are dropped from the kernel's cache (see pagecache)."""

FLAG_ENCRYPTED = 0x0001_0000
"""Bit 16 of an entry's flags: the start of the stored bytes is scrambled (see codec.decrypt)."""


class Compression(IntEnum):
    """The low byte of an entry's flags."""

    STORED = 0
    ZLIB = 1
    LZ4 = 2
    ZSTD = 3


@dataclass(frozen=True, slots=True)
class NpkEntry:
    """One row of the table of contents."""

    id: int           # murmur3 of the file's path inside the archive
    offset: int       # where the stored bytes start in the .npk file
    packed_size: int  # length of the stored bytes
    raw_size: int     # length of the original file
    crc_packed: int   # murmur3 of the stored bytes, exactly as on disk
    crc_raw: int      # murmur3 of the original file
    flags: int        # compression mode (low byte) | FLAG_ENCRYPTED

    @property
    def compression(self) -> int:
        return self.flags & 0xFF

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & FLAG_ENCRYPTED)


class NpkArchive:
    """An open .npk file. Only the header and the table of contents are read up front;
    entry data is read on demand. Use it as a context manager:

        with NpkArchive(path) as archive:
            for entry in archive.entries:
                stored = archive.read_stored(entry)

    Reading entries in the order they are stored (sorted by offset) is much faster
    than table order, especially on network or shared-folder drives.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file = open(self.path, "rb", buffering=READ_BUFFER_SIZE)
        self._read_since_forget = 0
        try:
            self.size = os.fstat(self._file.fileno()).st_size
            pagecache.advise_sequential(self._file.fileno())
            self.entries: list[NpkEntry] = self._read_table_of_contents()
        except Exception:
            self.close()
            raise

    def read_stored(self, entry: NpkEntry) -> bytes:
        """The entry's bytes exactly as stored in the archive (still encrypted and compressed)."""
        if entry.offset + entry.packed_size > self.size:
            raise EntryError(f"data runs past the end of {self.path.name}")
        data = self._read_at(entry.offset, entry.packed_size)

        self._read_since_forget += len(data)
        if self._read_since_forget >= FORGET_READ_DATA_EVERY:
            pagecache.forget_file(self._file.fileno())
            self._read_since_forget = 0
        return data

    def close(self) -> None:
        if not self._file.closed:
            pagecache.forget_file(self._file.fileno())
            self._file.close()

    def __enter__(self) -> NpkArchive:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- internals ---------------------------------------------------------------------------

    def _read_at(self, offset: int, length: int) -> bytes:
        self._file.seek(offset)
        return self._file.read(length)

    def _read_table_of_contents(self) -> list[NpkEntry]:
        if self.size < HEADER_SIZE:
            raise ArchiveFormatError(f"{self.path}: too small to be an NXPK archive")
        header = self._read_at(0, HEADER_SIZE)
        if header[:4] != MAGIC:
            raise ArchiveFormatError(f"{self.path}: not an NXPK archive (starts with {header[:4]!r})")

        count = _U32.unpack_from(header, ENTRY_COUNT_OFFSET)[0]
        toc_offset = _U32.unpack_from(header, TOC_OFFSET_OFFSET)[0]
        toc_size = count * TOC_ROW.size
        if toc_offset + toc_size > self.size:
            raise ArchiveFormatError(f"{self.path}: table of contents runs past the end of the file")

        table = self._read_at(toc_offset, toc_size)
        return [NpkEntry(*row) for row in TOC_ROW.iter_unpack(table)]
