"""Command line: parse arguments, then run the steps in order.

    1. find the archives        (--install / --in, filtered by --unpack)
    2. build the plan           (read every table of contents, group by name)
    3. load the name manifest   (resdb from the installation, or --resdb)
    4. unpack                   (Extractor, with live progress)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from rich_argparse import RawDescriptionRichHelpFormatter

from . import __version__, ui
from .errors import InputError, NpkextError
from .extract import ExtractOptions, Extractor
from .install import Installation
from .names import NameResolver, ResourceManifest
from .plan import build_plan, filter_by_name, resolve_inputs

EXIT_OK = 0
EXIT_ENTRIES_FAILED = 1
EXIT_BAD_INPUT = 2
EXIT_INTERRUPTED = 130

EXAMPLES = """\
examples:
  # everything in the installation
  npkext --install "path/to/Magic Awakened" --out unpacked

  # some archives, by name: found anywhere in the installation, all mount folders merged
  npkext --install "path/to/Magic Awakened" --in character.npk ui "res_dlc_*" --out unpacked

  # one specific mount folder: a path inside the installation
  npkext --install "path/to/Magic Awakened" --in Documents/res/ui.npk --out unpacked

  # show what would be unpacked, write nothing
  npkext --install "path/to/Magic Awakened" --dry-run

  # archives given by their file path
  npkext --in path/to/res/model/texture.npk --out unpacked
  npkext --in copy/ui.npk --resdb path/to/res/resdb --out unpacked
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="npkext",
        description="Unpack NeoX NXPK (.npk) archives. The output mirrors the game's "
                    "file tree: res.npk goes to <out>/res/, res/ui.npk to <out>/res/ui/, "
                    "res/model/character.npk to <out>/res/model/character/. Archives mounted "
                    "at the same place from several folders (res, res2, Documents/res, ...) "
                    "are merged, the higher-priority one winning. <out>/_archives/ records "
                    "every archive, so they can be rebuilt; unpacking more archives later "
                    "into the same <out> adds to it.",
        epilog=EXAMPLES,
        formatter_class=RawDescriptionRichHelpFormatter,
    )

    source = parser.add_argument_group("where to read")
    source.add_argument("--install", type=Path, metavar="DIR",
                        help="game installation folder. Alone: unpack every archive in it. "
                             "With --in: search archives there by name, and use it for file "
                             "names and mount priority.")
    source.add_argument("--in", dest="inputs", nargs="+", metavar="NPK",
                        help="archives to unpack: paths to .npk files, or with --install just "
                             "their names (ui.npk, ui, 'res_dlc_*'; every mount folder is included) or "
                             "paths inside the installation (res/ui.npk, 'Documents/res/*.npk')")
    source.add_argument("--resdb", type=Path, nargs="+", metavar="FILE",
                        help="resource manifest(s) used to name files. Default: found in the "
                             "installation (given, or found above the --in files).")

    selection = parser.add_argument_group("what to unpack")
    selection.add_argument("--unpack", nargs="+", metavar="NAME",
                           help="keep only archives with these file names (applied after "
                                "--install/--in); '.npk' is optional and wildcards work. "
                                "Default: all.")
    selection.add_argument("--limit", type=int, metavar="N",
                           help="only the first N entries of each archive (for quick tests)")

    output = parser.add_argument_group("where to write")
    output.add_argument("--out", type=Path, metavar="DIR",
                        help="output folder; archives are unpacked into folders below it "
                             "that mirror the resource tree (DIR/res/ui/, ...)")
    output.add_argument("--keep-overridden", action="store_true",
                        help="also write lower-priority copies of files, "
                             "to <folder>/_overridden/<archive>/")

    options = parser.add_argument_group("other")
    options.add_argument("--dry-run", action="store_true",
                         help="show the plan and stop; nothing is written")
    options.add_argument("--no-verify", action="store_true",
                         help="skip the checksum checks (slightly faster, not recommended)")
    options.add_argument("--version", action="version", version=f"npkext {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except NpkextError as exc:
        ui.show_error(str(exc))
        return EXIT_BAD_INPUT
    except KeyboardInterrupt:
        ui.show_error("interrupted")
        return EXIT_INTERRUPTED


def run(args: argparse.Namespace) -> int:
    if args.out is None and not args.dry_run:
        raise InputError("--out DIR is required (or use --dry-run to only look)")
    if args.limit is not None and args.limit < 1:
        raise InputError("--limit must be at least 1")

    installation, archives = find_archives(args)
    if args.unpack:
        archives = filter_by_name(archives, args.unpack)
    resdb_files = args.resdb or (installation.resdb_files() if installation else [])
    for resdb in resdb_files:
        if not resdb.is_file():
            raise InputError(f"resdb file not found: {resdb}")

    ui.show_banner()
    with ui.status(f"Reading {len(archives)} archive tables…"):
        plan = build_plan(archives, installation, args.limit)
    with ui.status("Loading file names…"):
        manifest = ResourceManifest.from_files(resdb_files)
    ui.show_sources(installation, resdb_files, len(manifest))
    ui.show_plan(plan, args.out)
    if args.dry_run or not plan.groups:
        return EXIT_OK

    options = ExtractOptions(out_dir=args.out, verify=not args.no_verify,
                             keep_overridden=args.keep_overridden, limit=args.limit)
    started = time.monotonic()
    with ui.ProgressDisplay(plan) as progress:
        results = Extractor(NameResolver(manifest), options, progress).run(plan)
    ui.show_summary(results, time.monotonic() - started, args.out)

    return EXIT_ENTRIES_FAILED if any(r.failures for r in results) else EXIT_OK


def find_archives(args: argparse.Namespace) -> tuple[Installation | None, list[Path]]:
    """The installation (if known) and the archives to consider."""
    installation = Installation.open(args.install) if args.install else None

    if args.inputs:
        archives = resolve_inputs(args.inputs, installation)
        if installation is None:
            installation = Installation.find_above(archives[0])
        return installation, archives

    if installation:
        archives = installation.archives()
        if not archives:
            raise InputError(f"no .npk files found in {installation.root}")
        return installation, archives

    raise InputError("nothing to unpack: give --install DIR and/or --in ...")
