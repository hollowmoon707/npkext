"""Keeping the kernel's file cache small while reading and writing many gigabytes.

Linux keeps every file it writes in RAM (the page cache): first as "dirty" pages
until they reach the disk, then as clean pages in case somebody reads the file
again. Unpacking a whole installation writes ~60 GB. Left alone, that cache grows
until it fills the RAM; on a machine with little spare memory (a virtual machine,
for example) the desktop is pushed into swap and the system can freeze, even
though npkext itself only uses ~200 MB.

npkext never reads its output again, so caching it is pointless. WriteBehind
therefore collects written files in batches of FLUSH_BYTES and, for each batch:

  1. flushes dirty data to disk (os.sync);
  2. tells the kernel to drop the now-clean pages of those files
     (posix_fadvise DONTNEED).

This happens in a background thread, so unpacking goes on while the previous
batch is written out. At most two batches are in RAM at any time: the one being
flushed and the one being filled. If the disk falls behind, the extractor waits.

Archives are read once, front to back, so their pages are dropped as reading
moves on (forget_file).

Where these calls do not exist (Windows), everything here does nothing.
Windows manages its file cache differently and does not need this.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

FLUSH_BYTES = 256 * 1024 * 1024
"""Written data allowed to sit in the page cache before it is flushed and dropped."""

SUPPORTED = hasattr(os, "posix_fadvise") and hasattr(os, "sync")


def advise_sequential(fd: int) -> None:
    """Tell the kernel a file will be read front to back (larger read-ahead)."""
    if SUPPORTED:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_SEQUENTIAL)


def forget_file(fd: int) -> None:
    """Drop the clean cached pages of an open file."""
    if SUPPORTED:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)


def forget_path(path: Path) -> None:
    """Drop the clean cached pages of a file by path. Missing files are ignored."""
    if not SUPPORTED:
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        forget_file(fd)
    finally:
        os.close(fd)


class WriteBehind:
    """Flushes written files to disk and drops them from the page cache, in batches,
    in a background thread.

    Call written() after each file is written and flush() when done.
    """

    def __init__(self, flush_bytes: int = FLUSH_BYTES):
        self.flush_bytes = flush_bytes
        self.flushes = 0                  # batches handed to the flush thread so far
        self._batch: list[Path] = []
        self._batch_bytes = 0
        self._flushing: threading.Thread | None = None

    def written(self, path: Path, size: int) -> None:
        self._batch.append(path)
        self._batch_bytes += size
        if self._batch_bytes >= self.flush_bytes:
            self._start_flush()

    def flush(self) -> None:
        """Flush everything written so far and wait until it is done."""
        self._start_flush()
        self._wait_for_flush()

    def _start_flush(self) -> None:
        if not self._batch:
            return
        self._wait_for_flush()           # one flush at a time: if the disk is behind, wait here
        batch = self._batch
        self._batch, self._batch_bytes = [], 0
        self._flushing = threading.Thread(target=_flush_batch, args=(batch,),
                                          name="npkext-flush", daemon=True)
        self._flushing.start()
        self.flushes += 1

    def _wait_for_flush(self) -> None:
        if self._flushing is not None:
            self._flushing.join()
            self._flushing = None


def _flush_batch(paths: list[Path]) -> None:
    """Runs in the flush thread. The cache is only a hint, so errors are ignored."""
    if not SUPPORTED:
        return
    try:
        os.sync()                        # dirty pages -> disk; afterwards they are clean...
        for path in paths:               # ...and clean pages can be dropped
            forget_path(path)
    except OSError:
        pass
