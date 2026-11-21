"""Test helpers: build small, synthetic NXPK archives and resdb manifests.

No game data is used anywhere in the tests. The archives are written with the
same rules the extractor undoes, so a passing round trip shows the reader and the
format description agree.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import lz4.block
import pytest
import zstandard

from npkext.archive import FLAG_ENCRYPTED, HEADER_SIZE, MAGIC, TOC_ROW, Compression
from npkext.codec import decrypt
from npkext.hashing import npk_hash, path_id


def compress(content: bytes, compression: Compression) -> bytes:
    if compression == Compression.STORED:
        return content
    if compression == Compression.ZLIB:
        return zlib.compress(content)
    if compression == Compression.LZ4:
        return lz4.block.compress(content, store_size=False)
    if compression == Compression.ZSTD:
        return zstandard.ZstdCompressor().compress(content)
    raise ValueError(compression)


def write_npk(path: Path, files: dict[str, bytes], compression=Compression.LZ4,
              encrypted: bool = True) -> Path:
    """Write an NXPK archive holding `files` (path inside the archive -> content)."""
    body = bytearray()
    rows = []
    for inner_path, content in files.items():
        stored = compress(content, compression)
        if encrypted:
            stored = decrypt(stored)   # XOR is symmetric: decrypt() also encrypts
        flags = int(compression) | (FLAG_ENCRYPTED if encrypted else 0)
        rows.append((path_id(inner_path), HEADER_SIZE + len(body), len(stored), len(content),
                     npk_hash(stored), npk_hash(content), flags))
        body += stored
    rows.sort()

    toc_offset = HEADER_SIZE + len(body)
    header = MAGIC + struct.pack("<5I", len(rows), 0, 0, 0, toc_offset)
    toc = b"".join(TOC_ROW.pack(*row) for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(body) + toc)
    return path


def write_resdb(path: Path, resource_paths: list[str]) -> Path:
    text = "\n".join(f"0 {p}" for p in resource_paths).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"CCZ!" + bytes(12) + zlib.compress(text))
    return path


@pytest.fixture
def fake_install(tmp_path: Path) -> Path:
    """A miniature installation with two layers.

        res/resdb                       names for everything below
        res.npk                         root of the tree: common\\x.txt, and its own
                                        (different) copy of ui\\login\\bg.png
        res/ui.npk                      login\\bg.png (old), icons\\a.png
        res/model/hero.npk              body.mesh
        Documents/res/ui.npk            login\\bg.png (new), an unlisted file
        script.npk                      one file not in the manifest
        Documents/script_patch.npk      a newer copy of that file
    """
    root = tmp_path / "install"
    (root / "neox_bin").mkdir(parents=True)
    write_resdb(root / "res" / "resdb", [
        "ui\\login\\bg.png", "ui\\icons\\a.png", "model\\hero\\body.mesh", "common\\x.txt",
    ])
    write_npk(root / "res.npk", {"common\\x.txt": b"X" * 100, "ui\\login\\bg.png": b"ROOT" * 50})
    write_npk(root / "res" / "ui.npk", {"login\\bg.png": b"OLD" * 50, "icons\\a.png": b"A" * 300})
    write_npk(root / "res" / "model" / "hero.npk", {"body.mesh": b"\x34\x80\xc8\xbb" + b"m" * 500})
    write_npk(root / "Documents" / "res" / "ui.npk",
              {"login\\bg.png": b"NEW" * 50, "unlisted.xml": b"<?xml version='1.0'?><a/>"})
    write_npk(root / "script.npk", {"anything": b"\x1d\x04" + bytes(range(200))})
    write_npk(root / "Documents" / "script_patch.npk", {"anything": b"\x1d\x04" + b"patched" * 30})
    return root
