from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from conftest import write_resdb
from npkext.errors import InputError, ManifestError
from npkext.extract import extended_length_path, folder_tag, safe_relative_path
from npkext.filetypes import guess_extension
from npkext.hashing import path_id
from npkext.install import Installation
from npkext.mounts import mount_rank, place
from npkext.names import NameResolver, ResourceManifest, candidate_prefixes, read_resdb
from npkext.plan import build_plan, filter_by_name, output_folder


@pytest.mark.parametrize("archive, expected", [
    ("game/res/ui.npk", ["ui\\"]),
    ("game/res/model/character.npk", ["model\\character\\"]),
    ("game/Documents/res2/model/character.npk", ["model\\character\\"]),
    ("game/res/levelsets/lake.npk", ["levelsets\\lake\\"]),
    ("game/res.npk", [""]),
    ("game/Documents/res_dlc/a/b/c.npk", ["a\\b\\c\\"]),     # res_dlc is mounted 3 deep
    ("game/script.npk", []),                                    # scripts are not in resdb
    ("loose/ui.npk", ["", "ui\\"]),
])
def test_candidate_prefixes(archive, expected):
    assert candidate_prefixes(Path(archive)) == expected


def test_read_resdb(tmp_path):
    resdb = write_resdb(tmp_path / "resdb", ["ui\\a.png", "model\\x\\b.mesh"])
    assert read_resdb(resdb) == ["ui\\a.png", "model\\x\\b.mesh"]


def test_read_resdb_rejects_other_files(tmp_path):
    (tmp_path / "resdb").write_bytes(b"garbage")
    with pytest.raises(ManifestError):
        read_resdb(tmp_path / "resdb")


def test_manifest_prefix_search_ignores_case():
    manifest = ResourceManifest(["UI\\a.png", "ui\\b.png", "uix\\c.png", "model\\d"])
    assert manifest.paths_under("ui\\") == ["UI\\a.png", "ui\\b.png"]


def test_resolver_names_entries_relative_to_the_archive():
    resolver = NameResolver(ResourceManifest(["ui\\login\\bg.png", "model\\hero\\body.mesh"]))
    names = resolver.names_for(Path("game/res/ui.npk"))
    assert names == {path_id("login\\bg.png"): "login\\bg.png"}


def test_mount_priority_follows_engine_mount_order(fake_install):
    install = Installation.open(fake_install)
    rank = install.mount_rank
    assert rank(fake_install / "Documents/res4/model/x.npk") < rank(fake_install / "Documents/res/ui.npk")
    assert rank(fake_install / "Documents/res/ui.npk") < rank(fake_install / "res/ui.npk")
    assert rank(fake_install / "res/ui.npk") < rank(fake_install / "res2/ui.npk")


def test_installation_is_found_above_an_archive_not_at_documents(fake_install):
    found = Installation.find_above(fake_install / "Documents" / "res" / "ui.npk")
    assert found is not None and found.root == fake_install.resolve()


def test_open_rejects_a_folder_that_is_not_an_installation(tmp_path):
    with pytest.raises(InputError):
        Installation.open(tmp_path)


def test_plan_merges_same_named_archives_highest_priority_first(fake_install):
    install = Installation.open(fake_install)
    plan = build_plan(install.archives(), install)
    groups = {g.folder_name: g for g in plan.groups}
    assert [g.folder_name for g in plan.groups] == ["res/model/hero", "res/ui", "res", "script"]
    assert [s.label for s in groups["res/ui"].sources] == ["Documents/res/ui.npk", "res/ui.npk"]


@pytest.mark.parametrize("pattern", ["ui.npk", "ui", "UI", "u*"])
def test_filter_by_name(fake_install, pattern):
    archives = Installation.open(fake_install).archives()
    assert {a.name for a in filter_by_name(archives, [pattern])} == {"ui.npk"}


def test_filter_by_name_suggests_close_names(fake_install):
    archives = Installation.open(fake_install).archives()
    with pytest.raises(InputError, match="did you mean hero.npk"):
        filter_by_name(archives, ["heroo.npk"])


@pytest.mark.parametrize("archive, mount, branch", [
    ("res.npk", "res", ()),
    ("Documents/res.npk", "Documents/res", ()),
    ("res/ui.npk", "res", ("ui",)),
    ("Documents/res4/model/character.npk", "Documents/res4", ("model", "character")),
    ("Documents/res_silent1/a/b/c/d.npk", "Documents/res_silent1", ("a", "b", "c", "d")),
    ("Documents/script_patch.npk", "Documents/script_patch", ()),
])
def test_place_finds_the_mount_folder(archive, mount, branch):
    placement = place(PurePosixPath(archive))
    assert placement.root.as_posix() == mount and placement.branch == branch


@pytest.mark.parametrize("archive", ["res/a/b/c.npk", "script/x.npk", "copies/ui.npk"])
def test_place_rejects_archives_outside_mount_rules(archive):
    assert place(PurePosixPath(archive)) is None   # too deep for res, or no mount folder


def test_mount_priority_follows_the_log_order():
    assert mount_rank("Documents/res4") < mount_rank("Documents/res") < mount_rank("res") \
        < mount_rank("res2")
    assert mount_rank("Documents/script_patch") < mount_rank("script")
    assert mount_rank("copies") is None


@pytest.mark.parametrize("archive, folder", [
    ("GAME/res.npk", "res"),
    ("GAME/Documents/res.npk", "res"),
    ("GAME/script.npk", "script"),
    ("GAME/Documents/script_patch.npk", "script"),
    ("GAME/res/ui.npk", "res/ui"),
    ("GAME/Documents/res2/ui.npk", "res/ui"),
    ("GAME/Documents/res4/model/character.npk", "res/model/character"),
    ("GAME/res/levelsets/lake.npk", "res/levelsets/lake"),
    ("copies/loose.npk", "loose"),
])
def test_output_folder_mirrors_the_resource_tree(archive, folder):
    assert output_folder(Path(archive)).as_posix() == folder


@pytest.mark.parametrize("raw, expected", [
    ("a\\b\\c.dds", "a/b/c.dds"),
    ("..\\escape.txt", None),
    ("C:\\abs.txt", None),
    ("", None),
    (None, None),
])
def test_safe_relative_path(raw, expected):
    result = safe_relative_path(raw)
    assert (str(result) if result else None) == expected


@pytest.mark.parametrize("absolute, expected", [
    ("C:\\out\\unpacked", "\\\\?\\C:\\out\\unpacked"),
    ("\\\\server\\share\\out", "\\\\?\\UNC\\server\\share\\out"),
    ("\\\\?\\C:\\already", "\\\\?\\C:\\already"),
])
def test_extended_length_path(absolute, expected):
    assert extended_length_path(absolute) == expected


def test_extended_length_path_keeps_a_usable_windows_path():
    path = PureWindowsPath(extended_length_path("C:\\out")) / "ui" / "login" / "bg.png"
    assert path.drive == "\\\\?\\C:"
    assert str(path.parent) == "\\\\?\\C:\\out\\ui\\login"


def test_folder_tag():
    assert folder_tag("Documents/res/ui.npk") == "Documents_res_ui.npk"


@pytest.mark.parametrize("data, ext", [
    (b"DDS \x7c", "dds"), (b"\x89PNG\r\n", "png"), (b"\x34\x80\xc8\xbbxx", "mesh"),
    (b"<?xml", "xml"), (b"\x1d\x04abc", "enc"), (b"\x00\x01", "bin"),
])
def test_guess_extension(data, ext):
    assert guess_extension(data) == ext
