"""Where every archive is mounted in the game's virtual file tree.

At startup the engine creates one "file loader" per mount folder and logs it in
log.txt (installation folder):

    [FILESYSTEM] Succeeded to create FileLoader, opener sys, loader npk,
                 root C:\\...\\Magic Awakened\\Documents\\res, depth 2

A mount folder R with depth d loads:

    R.npk  (next to the folder)    ->  the root of the tree       Documents/res.npk
    R/<a>.npk                      ->  the branch  <a>\\           Documents/res/ui.npk
    R/<a>/<b>.npk                  ->  the branch  <a>\\<b>\\       Documents/res/model/character.npk
    ... up to d folder levels below R

The archives of all resource mounts (res, res2, res_dlc, ...) build one tree;
the script mounts build a second one.

MOUNTS below is copied from the log of one game session (see
docs/mount-rules-plan.md). The order is the order of mounting. *Assumption:* the
first-mounted folder wins when several hold the same file. Neither the order nor
that rule has been confirmed in the engine's code yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

RESOURCE_TREE = "res"
"""Output folder of the resource tree. Its files are named by resdb."""

SCRIPT_TREE = "script"
"""Output folder of the script tree. resdb does not list scripts."""


@dataclass(frozen=True)
class Mount:
    root: str     # folder relative to the installation, '/'-separated
    depth: int    # how many folder levels below `root` archives are loaded from
    tree: str     # RESOURCE_TREE or SCRIPT_TREE

    @property
    def name(self) -> str:
        return PurePosixPath(self.root).name


MOUNTS: tuple[Mount, ...] = (
    Mount("Documents/res_dlc_low", 0, RESOURCE_TREE),
    Mount("Documents/gray_res", 0, RESOURCE_TREE),
    Mount("Documents/res4", 2, RESOURCE_TREE),
    Mount("Documents/res3", 2, RESOURCE_TREE),
    Mount("Documents/res2", 2, RESOURCE_TREE),
    Mount("Documents/res", 2, RESOURCE_TREE),
    Mount("Documents/res_silent1", 4, RESOURCE_TREE),
    Mount("Documents/res_dlc_dress", 3, RESOURCE_TREE),
    Mount("Documents/res_dlc_scene", 3, RESOURCE_TREE),
    Mount("Documents/res_dlc_y2", 3, RESOURCE_TREE),
    Mount("Documents/res_dlc_patch", 3, RESOURCE_TREE),
    Mount("Documents/res_dlc", 3, RESOURCE_TREE),
    Mount("Documents/res_silent3_patch", 2, RESOURCE_TREE),
    Mount("Documents/res_silent3", 2, RESOURCE_TREE),
    Mount("Documents/res_silent_patch", 2, RESOURCE_TREE),
    Mount("Documents/res_silent", 2, RESOURCE_TREE),
    Mount("res", 2, RESOURCE_TREE),
    Mount("res2", 2, RESOURCE_TREE),
    Mount("res3", 2, RESOURCE_TREE),
    Mount("res4", 2, RESOURCE_TREE),
    Mount("Documents/gray_script_patch", 0, SCRIPT_TREE),
    Mount("Documents/gray_script", 0, SCRIPT_TREE),
    Mount("Documents/script_patch", 0, SCRIPT_TREE),
    Mount("Documents/script", 0, SCRIPT_TREE),
    Mount("script", 0, SCRIPT_TREE),
)
"""Every mount folder, in the order the engine mounts them: highest priority first."""

_BY_NAME: dict[str, Mount] = {}
for _mount in MOUNTS:
    # A name used twice (res in Documents/ and in the root) has the same depth and tree.
    _BY_NAME.setdefault(_mount.name.lower(), _mount)
_RANK = {mount.root.lower(): rank for rank, mount in enumerate(MOUNTS)}
_MAX_DEPTH = max(mount.depth for mount in MOUNTS)


@dataclass(frozen=True)
class Placement:
    """Where one archive is mounted."""

    mount: Mount
    root: PurePosixPath          # the mount folder this archive belongs to, as found on disk
    branch: tuple[str, ...]      # its branch of the tree: () for R.npk, ('model', 'character')

    @property
    def output_folder(self) -> PurePosixPath:
        """'res/model/character' for Documents/res/model/character.npk."""
        return PurePosixPath(self.mount.tree, *self.branch)

    @property
    def name_prefix(self) -> str | None:
        """How the archive's files are listed in resdb: 'model\\\\character\\\\', '' for the
        root, None for trees that resdb does not cover."""
        if self.mount.tree != RESOURCE_TREE:
            return None
        return "".join(part + "\\" for part in self.branch)


def place(archive: Path | PurePosixPath) -> Placement | None:
    """Where `archive` is mounted, found from the folder names in its path, so it
    also works for a copy kept in the same folder structure outside the
    installation. None if it is not inside or next to a known mount folder."""
    parts = PurePosixPath(Path(archive).as_posix()).parts
    stem = PurePosixPath(parts[-1]).stem if parts else ""

    # Inside a mount folder: R/ui.npk is one level below R, R/model/character.npk two.
    for level in range(1, min(_MAX_DEPTH, len(parts) - 1) + 1):
        mount = _BY_NAME.get(parts[-1 - level].lower())
        if mount is not None and level <= mount.depth:
            return Placement(mount, PurePosixPath(*parts[:-level]), (*parts[-level:-1], stem))

    # Next to a mount folder: R.npk holds the root of the tree.
    mount = _BY_NAME.get(stem.lower())
    if mount is not None:
        return Placement(mount, PurePosixPath(*parts[:-1], stem), ())
    return None


def mount_rank(mount_root: PurePosixPath | str) -> int | None:
    """Priority of a mount folder given relative to the installation: 0 is the highest.
    None if it is not one of MOUNTS."""
    return _RANK.get(PurePosixPath(mount_root).as_posix().lower())
