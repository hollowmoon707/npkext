"""End-to-end tests: run the command line against the synthetic installation."""

import csv
import os
from pathlib import Path

import pytest

from npkext.cli import EXIT_BAD_INPUT, EXIT_OK, main
from npkext.hashing import path_id


def record_rows(out: Path, archive: str) -> list[dict]:
    """The rows of one archive's record in the index."""
    with open(out / "_archives" / f"{archive}.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def index_rows(out: Path) -> list[dict]:
    with open(out / "_archives" / "index.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def tree(out: Path) -> list[str]:
    """The output folders that were unpacked into, from the index."""
    return sorted({row["output_folder"] for row in index_rows(out)})


def test_unpack_whole_installation(fake_install, tmp_path):
    out = tmp_path / "out"
    assert main(["--install", str(fake_install), "--out", str(out)]) == EXIT_OK

    # the output mirrors the resource tree: res.npk at res/, nested archives below it
    assert tree(out) == ["res", "res/model/hero", "res/ui", "script"]
    assert (out / "res/common/x.txt").read_bytes() == b"X" * 100

    # ui.npk exists in two layers: the Documents/ copy of login\bg.png wins
    assert (out / "res/ui/login/bg.png").read_bytes() == b"NEW" * 50
    assert (out / "res/ui/icons/a.png").read_bytes() == b"A" * 300
    assert (out / "res/model/hero/body.mesh").read_bytes().startswith(b"\x34\x80\xc8\xbb")

    # files missing from the manifest keep their id and get a guessed extension
    assert (out / f"res/ui/_unnamed/{path_id('unlisted.xml'):08x}.xml").is_file()
    # script_patch.npk patches script.npk: one script tree, the patch winning
    script = out / f"script/_unnamed/{path_id('anything'):08x}.enc"
    assert script.read_bytes().endswith(b"patched")

    # the index records every archive, and for each entry where it went
    assert {r["archive"] for r in index_rows(out)} == {
        "res.npk", "res/ui.npk", "res/model/hero.npk", "Documents/res/ui.npk", "script.npk",
        "Documents/script_patch.npk"}
    old_ui = {r["status"] for r in record_rows(out, "res/ui.npk")}
    assert old_ui == {"ok", "overridden"}
    new_ui = record_rows(out, "Documents/res/ui.npk")
    assert {r["status"] for r in new_ui} == {"ok"}
    assert "res/ui/login/bg.png" in {r["path"] for r in new_ui}
    assert [int(r["toc_index"]) for r in new_ui] == list(range(len(new_ui)))


def test_nested_archive_wins_over_the_parent_copy(fake_install, tmp_path):
    out = tmp_path / "out"
    assert main(["--install", str(fake_install), "--out", str(out)]) == EXIT_OK
    # res.npk holds its own ui\login\bg.png; the ui.npk copy is the one written
    assert (out / "res/ui/login/bg.png").read_bytes() == b"NEW" * 50
    root_rows = [r for r in record_rows(out, "res.npk") if r["status"] == "overridden"]
    assert len(root_rows) == 1 and "Documents/res/ui.npk" in root_rows[0]["note"]

    out2 = tmp_path / "out2"
    main(["--install", str(fake_install), "--keep-overridden", "--out", str(out2)])
    assert (out2 / "res/_overridden/res.npk/ui/login/bg.png").read_bytes() == b"ROOT" * 50


def test_archives_unpacked_one_at_a_time_build_the_same_tree(fake_install, tmp_path):
    out = tmp_path / "out"
    assert main(["--install", str(fake_install), "--in", "ui", "--out", str(out)]) == EXIT_OK
    assert main(["--install", str(fake_install), "--in", "res.npk", "--out", str(out)]) == EXIT_OK
    # res.npk unpacked last still does not overwrite the ui.npk copy
    assert (out / "res/ui/login/bg.png").read_bytes() == b"NEW" * 50
    # the index keeps the archives of both runs
    assert tree(out) == ["res", "res/ui"]
    assert len(index_rows(out)) == 3


def test_keep_overridden_writes_older_copies(fake_install, tmp_path):
    out = tmp_path / "out"
    main(["--install", str(fake_install), "--unpack", "ui", "--keep-overridden", "--out", str(out)])
    old = out / "res/ui/_overridden/res_ui.npk/login/bg.png"
    assert old.read_bytes() == b"OLD" * 50


def test_unpack_selected_archives_only(fake_install, tmp_path):
    out = tmp_path / "out"
    assert main(["--install", str(fake_install), "--unpack", "hero.npk", "--out", str(out)]) == EXIT_OK
    assert tree(out) == ["res/model/hero"]


def test_in_by_name_searches_every_layer_of_the_installation(fake_install, tmp_path):
    out = tmp_path / "out"
    assert main(["--install", str(fake_install), "--in", "ui", "hero.npk", "--out", str(out)]) == EXIT_OK
    assert tree(out) == ["res/model/hero", "res/ui"]
    assert (out / "res/ui/login/bg.png").read_bytes() == b"NEW" * 50     # both ui layers merged
    assert (out / "res/ui/icons/a.png").is_file()


def test_in_by_wildcard_name(fake_install, tmp_path):
    out = tmp_path / "out"
    assert main(["--install", str(fake_install), "--in", "h*", "--out", str(out)]) == EXIT_OK
    assert tree(out) == ["res/model/hero"]


@pytest.mark.parametrize("relative, content", [
    ("res/ui.npk", b"OLD" * 50),
    ("Documents/res/*.npk", b"NEW" * 50),
])
def test_in_by_path_inside_installation_selects_one_layer(fake_install, tmp_path, relative, content):
    out = tmp_path / "out"
    assert main(["--install", str(fake_install), "--in", relative, "--out", str(out)]) == EXIT_OK
    assert (out / "res/ui/login/bg.png").read_bytes() == content
    assert len(index_rows(out)) == 1


def test_in_by_name_needs_an_installation(tmp_path):
    assert main(["--in", "ui.npk", "--out", str(tmp_path)]) == EXIT_BAD_INPUT


@pytest.mark.parametrize("value", ["heroo", "res/nothing.npk"])
def test_in_unknown_name_or_path_is_reported(fake_install, tmp_path, value):
    assert main(["--install", str(fake_install), "--in", value, "--out", str(tmp_path)]) == EXIT_BAD_INPUT


def test_single_archive_finds_names_through_its_installation(fake_install, tmp_path):
    out = tmp_path / "out"
    archive = fake_install / "res" / "model" / "hero.npk"
    assert main(["--in", str(archive), "--out", str(out)]) == EXIT_OK
    assert (out / "res/model/hero/body.mesh").is_file()


def test_loose_archive_with_explicit_resdb(fake_install, tmp_path):
    loose = tmp_path / "copied" / "ui.npk"
    loose.parent.mkdir()
    loose.write_bytes((fake_install / "res" / "ui.npk").read_bytes())
    out = tmp_path / "out"
    resdb = fake_install / "res" / "resdb"
    assert main(["--in", str(loose), "--resdb", str(resdb), "--out", str(out)]) == EXIT_OK
    assert (out / "ui/login/bg.png").read_bytes() == b"OLD" * 50


def test_loose_archive_without_resdb_still_unpacks(fake_install, tmp_path):
    loose = tmp_path / "copied" / "hero.npk"
    loose.parent.mkdir()
    loose.write_bytes((fake_install / "res" / "model" / "hero.npk").read_bytes())
    out = tmp_path / "out"
    assert main(["--in", str(loose), "--out", str(out)]) == EXIT_OK
    assert len(list((out / "hero/_unnamed").iterdir())) == 1


def test_dry_run_writes_nothing(fake_install, tmp_path):
    out = tmp_path / "out"
    assert main(["--install", str(fake_install), "--dry-run", "--out", str(out)]) == EXIT_OK
    assert not out.exists()


@pytest.mark.parametrize("argv", [
    ["--out", "x"],                                    # no source
    ["--install", "/definitely/not/here", "--out", "x"],
    ["--in", "/definitely/not/here.npk", "--out", "x"],
])
def test_bad_input_is_reported(argv):
    assert main(argv) == EXIT_BAD_INPUT


def test_unknown_archive_name_is_reported(fake_install, tmp_path):
    argv = ["--install", str(fake_install), "--unpack", "nothing.npk", "--out", str(tmp_path)]
    assert main(argv) == EXIT_BAD_INPUT


def test_works_without_page_cache_control(fake_install, tmp_path, monkeypatch):
    """Windows has no posix_fadvise/os.sync: extraction must work the same without them."""
    monkeypatch.setattr("npkext.pagecache.SUPPORTED", False)
    out = tmp_path / "out"
    assert main(["--install", str(fake_install), "--out", str(out)]) == EXIT_OK
    assert (out / "res/ui/login/bg.png").read_bytes() == b"NEW" * 50


# -- optional: real game files -------------------------------------------------------------------
# Set NPKEXT_INSTALL to a game installation folder to run this. It reads the files in
# place; nothing from the game is stored with the tests.

REAL_INSTALL = Path(os.environ.get("NPKEXT_INSTALL", "/nonexistent"))


@pytest.mark.skipif(not (REAL_INSTALL / "res" / "resdb").is_file(),
                    reason="set NPKEXT_INSTALL to a game installation to run")
def test_real_installation_sample(tmp_path):
    out = tmp_path / "out"
    argv = ["--install", str(REAL_INSTALL), "--unpack", "texture.npk", "--limit", "40", "--out", str(out)]
    assert main(argv) == EXIT_OK
    rows = record_rows(out, "res/model/texture.npk")
    assert rows and all(r["status"] in ("ok", "overridden", "skipped") for r in rows)
