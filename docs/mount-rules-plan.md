# Mount rules: what is assumed, and how to confirm it

npkext rebuilds the game's virtual file tree from the archives. To do that it needs
to know **where** the engine mounts each archive and **which copy wins** when two
archives hold the same file. Today these rules are taken from one game log, not
from the engine's code. This page records what is assumed, what the evidence is,
and the plan for replacing the assumptions with facts once the loader code can be
read.

## What npkext assumes today

All of it lives in one place, [`mounts.py`](../src/npkext/mounts.py), so a
correction is one edit there.

| # | Rule | Evidence | Confidence |
|---|---|---|---|
| 1 | The list of mount folders, with a depth each (`MOUNTS`) | The `Succeeded to create FileLoader … root …, depth N` lines of `log.txt` | High for this game version: copied from the log |
| 2 | Mount folder `R` loads `R.npk` (next to it) as the root of the tree, and `R/…/x.npk` up to `depth` levels below as the branch `…\x\` | The `Package … is loaded` lines printed just before each loader; file names hash correctly with these prefixes (97–100% named) | High |
| 3 | Resource mount folders share one tree; script mount folders form a second one | `script_patch.npk`'s 50 ids are all in `script.npk`; only 1 of 67k script ids is also in `res.npk` (a hash coincidence) | Medium |
| 4 | **First-mounted wins**: when several mount folders hold the same file, the one mounted first provides it | Patch downloads (`Documents/…`) are mounted before the installer's folders, which is what a patch system needs | **Unconfirmed** |
| 5 | **Nested wins**: when `res.npk` and a nested archive (e.g. `res/fx.npk`) hold the same path, the nested archive's copy is used | None; chosen because the nested archive is more specific. Affects only 3 files today | **Unconfirmed** |
| 6 | The `loader discrete` mounts (loose files in `Documents/res`, `Documents/res_silent`, `res`) are ignored | They read files outside archives, which npkext does not unpack | Fine for unpacking |

Rules 4 and 5 decide which copy npkext writes under the real name. Getting them
wrong never loses data: every copy is listed in `_archives/` with its origin, and
`--keep-overridden` writes the losing copies too.

## Why the log is not enough

* The log shows the **order of mounting**, not the **order of lookup**. A VFS can
  search its mounts first-to-last or last-to-first.
* The log mentions an `NpkConflictResolver` (`NpkConflictResolver LoadData=1`),
  right after the mounts are created. The engine has explicit logic for
  duplicate files, and it may use data of its own rather than plain mount order.
* The list is one session's. Mount folders that the client creates only under some
  conditions (other platforms, other download states, the `gray_*` folders) may be
  missing from it.
* The depth rule (rule 2) is inferred from which archives were loaded, not read
  from code. A depth-2 folder could, for example, skip some sub-folders by name.

## Plan

Once the game's loader code can be read (the Python scripts after the script
encryption is removed, or the file-system code in the engine binary):

1. **Find where the mounts are created.** Search for the log strings
   `Succeeded to create FileLoader`, `opener sys`, `loader npk`, `depth`, and the
   folder names (`res_silent`, `res_dlc_patch`, `gray_res`). The code around them
   should hold the mount list and whether it is fixed or built at run time.
2. **Read the lookup.** Find the function that, given a path, asks the loaders in
   turn. Note the direction of the loop and whether it stops at the first hit.
   That settles rule 4.
3. **Read `NpkConflictResolver`.** Find what `LoadData` loads (a file in the
   installation? a table inside an archive?) and how it picks between copies. If
   it uses its own data, npkext should read that data too, and rules 4 and 5
   become "do what the resolver says".
4. **Check how a path maps to an archive inside one mount.** Confirm the `R.npk`
   root plus `R/…` branches rule and the meaning of `depth`, and whether a
   lookup for `model\character\x` tries `model/character.npk` before `R.npk`.
   That settles rule 5.
5. **Check the scripts' tree.** Confirm that script mounts are a separate tree
   and how `script_patch` and the `gray_script*` folders combine with it.

Each answer then maps to a change in npkext:

| Finding | Change |
|---|---|
| Mount list or depths differ | Edit `mounts.MOUNTS` |
| Last-mounted wins | Reverse the ranks in `mounts.MOUNTS` (or `mount_rank`) |
| Conflict resolver uses its own data | Read it in a new module and use it for `ArchiveSource.rank` and `ReplacedPaths` |
| `R.npk` is searched before nested archives | Drop `ReplacedPaths`; parent copies win |
| Mount list is built at run time from game data | Parse that data (or `log.txt`) instead of the fixed table |

Until then, the fixed table matches the installation it was made from, and the
two unconfirmed rules are reported in the docs, in `_archives/README.txt`
(`overridden` rows always name the winning archive), and in this file.

## Reading the mount list from `log.txt` (an alternative)

If the code stays out of reach, npkext could read the list from the newest
`log*.txt` that has `[FILESYSTEM]` lines, instead of using a fixed table. The lines
come from a fixed template, so one regular expression is enough:

```
\[FILESYSTEM\] Succeeded to create FileLoader, opener (\w+), loader (\w+), root (.+), depth (\d+)
```

Keep `loader npk` lines, strip the installation path from `root` (it is the
player's own path, e.g. `C:\Loading Bay Games\Magic Awakened\`), and fall back to
the fixed table when no log matches. This would pick up new mount folders
automatically, but it reads the same evidence as today. It does not settle rules
4 and 5.
