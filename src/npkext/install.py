"""Knowledge about the game installation folder.

The engine mounts several resource "layers" at startup (see the [FILESYSTEM]
lines of log.txt). Which folders are mounted, and in which
order, is in mounts.MOUNTS.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import InputError
from .mounts import mount_rank, place

RESDB_LOCATIONS: tuple[str, ...] = (
    "Documents/res/resdb",   # patched manifest (newer, larger)
    "res/resdb",             # manifest shipped with the installer
)


@dataclass(frozen=True)
class Installation:
    """A game installation folder: the one containing neox_bin/, res/ and Documents/."""

    root: Path

    @classmethod
    def open(cls, folder: str | Path) -> Installation:
        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise InputError(f"installation folder not found: {folder}")
        installation = cls(root)
        if not installation.looks_valid():
            raise InputError(f"{root} does not look like a game installation "
                             f"(expected neox_bin/ or res/resdb + Documents/)")
        return installation

    @classmethod
    def find_above(cls, path: str | Path) -> Installation | None:
        """The installation that contains `path`, found by walking up its folders."""
        for folder in Path(path).resolve().parents:
            candidate = cls(folder)
            if candidate.looks_valid():
                return candidate
        return None

    def looks_valid(self) -> bool:
        has_engine = (self.root / "neox_bin").is_dir()
        has_resources = (self.root / "res" / "resdb").is_file() and (self.root / "Documents").is_dir()
        return has_engine or has_resources

    def archives(self) -> list[Path]:
        """Every .npk file in the installation."""
        return sorted(p for p in self.root.rglob("*") if p.suffix.lower() == ".npk" and p.is_file())

    def resdb_files(self) -> list[Path]:
        """The resource manifests that exist in this installation."""
        return [self.root / location for location in RESDB_LOCATIONS if (self.root / location).is_file()]

    def relative(self, path: str | Path) -> PurePosixPath | None:
        """`path` relative to the installation root, or None if it lies outside."""
        try:
            return PurePosixPath(Path(path).resolve().relative_to(self.root).as_posix())
        except ValueError:
            return None

    def mount_rank(self, archive: str | Path) -> int | None:
        """Priority of the mount folder an archive belongs to: 0 is the highest.
        None if it lies outside the installation or outside every known mount folder."""
        relative = self.relative(archive)
        placement = place(relative) if relative is not None else None
        return mount_rank(placement.root) if placement else None
