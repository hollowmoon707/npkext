"""WriteBehind bookkeeping. Whether the kernel really drops pages cannot be checked
in a unit test; that was measured by hand (see docs/usage.md, "Memory")."""

from npkext.pagecache import WriteBehind, forget_path


def test_flushes_once_the_budget_is_reached(tmp_path):
    behind = WriteBehind(flush_bytes=100)
    for i in range(5):
        path = tmp_path / f"f{i}"
        path.write_bytes(b"x" * 40)
        behind.written(path, 40)
    # 40+40+40 >= 100 -> flush; 40+40 left pending
    assert behind.flushes == 1
    behind.flush()
    assert behind.flushes == 2


def test_flush_without_pending_files_does_nothing():
    behind = WriteBehind()
    behind.flush()
    assert behind.flushes == 0


def test_missing_files_are_ignored(tmp_path):
    forget_path(tmp_path / "gone")
    behind = WriteBehind(flush_bytes=1)
    behind.written(tmp_path / "gone", 10)
    behind.flush()
    assert behind.flushes == 1


def test_flush_waits_for_the_background_thread(tmp_path):
    behind = WriteBehind(flush_bytes=1)
    path = tmp_path / "f"
    path.write_bytes(b"data")
    behind.written(path, 4)
    behind.flush()
    assert behind._flushing is None
