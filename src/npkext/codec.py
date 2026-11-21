"""Turning one stored entry back into the original file.

    stored bytes
      -> 1. check crc_packed   (murmur3 of the stored bytes)
      -> 2. decrypt            (only if the entry's encrypted flag is set)
      -> 3. decompress         (stored / zlib / lz4 / zstd, from the flags)
      -> 4. check crc_raw      (murmur3 of the result)
      -> original file
"""

from __future__ import annotations

import zlib

import lz4.block
import zstandard

from .archive import Compression, NpkArchive, NpkEntry
from .errors import EntryError
from .hashing import npk_hash

XOR_LENGTH = 128
XOR_START = 6
_XOR_KEY = bytes((XOR_START + i) & 0xFF for i in range(XOR_LENGTH))

_zstd = zstandard.ZstdDecompressor()


def decrypt(stored: bytes) -> bytes:
    """Undo the NPK entry encryption.

    Only the first 128 bytes are scrambled: byte i is XORed with (i + 6) & 0xFF.
    The rest is untouched. XOR is its own inverse, so this also encrypts.
    """
    head = bytes(byte ^ key for byte, key in zip(stored[:XOR_LENGTH], _XOR_KEY))
    return head + stored[XOR_LENGTH:]


def decompress(data: bytes, compression: int, raw_size: int) -> bytes:
    """Decompress `data` with the given compression mode into `raw_size` bytes."""
    if raw_size == 0:
        return b""
    try:
        if compression == Compression.STORED:
            return data
        if compression == Compression.ZLIB:
            return zlib.decompress(data)
        if compression == Compression.LZ4:
            return lz4.block.decompress(data, uncompressed_size=raw_size)
        if compression == Compression.ZSTD:
            return _zstd.decompress(data, max_output_size=raw_size)
    except (zlib.error, lz4.block.LZ4BlockError, zstandard.ZstdError) as exc:
        mode = Compression(compression).name.lower()
        raise EntryError(f"{mode} decompression failed: {exc}") from exc
    raise EntryError(f"unknown compression mode {compression}")


def decode_entry(archive: NpkArchive, entry: NpkEntry, verify: bool = True) -> bytes:
    """Return the original file stored in `entry`.

    With `verify`, both checksums are checked, so a returned file is
    guaranteed to be byte-identical to the one that was packed.
    """
    stored = archive.read_stored(entry)
    if verify and npk_hash(stored) != entry.crc_packed:
        raise EntryError("stored data is damaged (crc_packed does not match)")

    data = decrypt(stored) if entry.encrypted else stored
    data = decompress(data, entry.compression, entry.raw_size)

    if len(data) != entry.raw_size:
        raise EntryError(f"decoded {len(data)} bytes, expected {entry.raw_size}")
    if verify and npk_hash(data) != entry.crc_raw:
        raise EntryError("decoded data is wrong (crc_raw does not match)")
    return data
