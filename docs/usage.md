# Using npkext

The examples use `GAME` for the game's installation folder: the folder that contains
`neox_bin/`, `res/` and `Documents/`. For example, `"C:\Games\Magic Awakened"` on
Windows or `~/games/"Magic Awakened"` on Linux. Paths inside the installation may be
written with `/` or `\` on every system.

## Quick examples

```bash
# Everything in the installation (~690 archives, ~60 GB of output)
npkext --install GAME --out unpacked

# Some archives, by name only: searched in the whole installation,
# every mount folder that has an archive of that name is included and merged
npkext --install GAME --in character.npk ui --out unpacked

# Wildcards: all DLC packs
npkext --install GAME --in "res_dlc_*" --out unpacked

# One specific mount folder: a path relative to the installation
npkext --install GAME --in Documents/res/ui.npk --out unpacked
npkext --install GAME --in "Documents/res/levelsets/*.npk" --out unpacked

# Look before writing: show the plan and stop
npkext --install GAME --in character --dry-run

# One archive by its full path. Names are found through the installation it sits in.
npkext --in GAME/res/model/texture.npk --out unpacked

# An archive copied out of the installation: point at the name manifest yourself
npkext --in copies/ui.npk --resdb GAME/res/resdb --out unpacked
```

Quote wildcard patterns (`"res_dlc_*"`) so the shell does not expand them.

## Options

### Where to read

| Option | Meaning |
|---|---|
| `--install DIR` | The game installation folder. Used alone, every `.npk` inside it is unpacked. With `--in`, archives can be given by name and are searched for here. The installation also supplies file names and mount priority. |
| `--in NPK [NPK ...]` | The archives to unpack. Each value can be: **a path to an archive file**; or, with `--install`, **just an archive name** (`character.npk`, `character`, `"res_dlc_*"`), searched in every mount folder of the installation, all matches merged; or, with `--install`, **a path inside the installation** (`res/ui.npk`, `"Documents/res/*.npk"`), to pick specific mount folders. If `--install` is not given, npkext walks up from the first archive to find the installation it belongs to. |
| `--resdb FILE [FILE ...]` | Resource manifest(s) used to name files. By default both `Documents/res/resdb` (patched) and `res/resdb` (shipped) are used when the installation is known. Needed for archives that are not inside an installation. |

At least one of `--install` and `--in` is required.

### What to unpack

| Option | Meaning |
|---|---|
| `--unpack NAME [NAME ...]` | Keep only archives with these file names, after `--install`/`--in` have chosen the candidates. `.npk` is optional, case is ignored, and `*`/`?` wildcards work. Without it, everything is unpacked. `--install GAME --unpack ui` is the same as `--install GAME --in ui`. |
| `--limit N` | Only the first N entries of each archive (in storage order). For quick tests. |

Names given to `--in` or `--unpack` that match nothing are an error, with suggestions of similar archive names.

### Where to write

| Option | Meaning |
|---|---|
| `--out DIR` | Output folder. Required unless `--dry-run`. |
| `--keep-overridden` | Also write the copies of files that a higher-priority archive replaces (see *Mount folders* below), to `_overridden/<archive>/` in the archive's folder. |

### Other

| Option | Meaning |
|---|---|
| `--dry-run` | Print the plan (folders by section, archives, sizes, free disk space) and exit. Writes nothing. |
| `--no-verify` | Skip both checksum checks. Not recommended; they cost very little. |
| `--version`, `--help` | |

## Output layout

The output rebuilds the game's **virtual file tree**: the single tree of files
the game sees once it has loaded all its archives. Each archive holds one branch of
that tree, and is unpacked where that branch belongs:

| Archive | Output folder |
|---|---|
| `res.npk`, `Documents/res.npk` | `res/` (the root of the tree) |
| `res/ui.npk`, `res2/ui.npk`, `Documents/res/ui.npk` | `res/ui/` |
| `res/model/character.npk` (and its five other copies) | `res/model/character/` |
| `res/levelsets/lake.npk` | `res/levelsets/lake/` |
| `script.npk`, `Documents/script.npk`, `Documents/script_patch.npk` | `script/` |
| a loose copy outside any mount folder, `copies/ui.npk` | `ui/` |

```
unpacked/
├── _archives/                           the index: where everything came from
│   ├── index.csv                        one row per archive
│   ├── mounts.csv                       mount folders and their priority
│   ├── README.txt                       what the columns mean
│   ├── res.npk.csv                      one record per archive, at its path
│   ├── res/ui.npk.csv                   in the installation
│   └── Documents/res/ui.npk.csv
├── res/                                 the resource tree
│   ├── <files of res.npk>               e.g. common/…, maps/…
│   ├── _unnamed/                        res.npk's files without a known name
│   ├── ui/                              the ui.npk archives
│   ├── model/
│   │   └── character/                   the character.npk archives
│   │       ├── <path inside the archive>      e.g. female/body/body_01.mesh
│   │       ├── _unnamed/<id>.<ext>            names not in resdb; extension guessed
│   │       └── _overridden/<archive>/<path>   only with --keep-overridden
│   └── levelsets/
│       ├── lake/                        res/levelsets/lake.npk
│       └── …
└── script/
```

A file the game calls `model\character\female\body_01.mesh` is written to
`res/model/character/female/body_01.mesh`, whichever archive it came from. Folders
starting with `_` are npkext's own and never clash with the game's files.

### Unpacking one archive at a time

Every archive is placed by its own location in the installation, so you do not
need to unpack the whole tree, or `res.npk`, to get one archive in the right place.
Unpacking more archives later into the same `--out` fills in more of the tree, and
`_archives/` keeps the records of every run:

```bash
npkext --install GAME --in ui --out unpacked
npkext --install GAME --in "res_dlc_*" --out unpacked     # added next to res/ui/
```

### Mount folders: several archives, one folder

The game loads archives from a fixed list of **mount folders**: the installer's
`res/`, `res2/`, …, and the patch downloads in `Documents/res`, `Documents/res2`,
`Documents/res4`, and so on. A mount folder `R` loads `R.npk` next to it (the root
of the tree) and the archives inside it, up to a fixed depth (2 for `res`, so
`res/ui.npk` and `res/model/character.npk`). The full list is in
`_archives/mounts.csv` and in [how-it-works.md](how-it-works.md#5-mount-folders).

So an installation contains six `character.npk` and four `ui.npk` files, mounted at
the same place from different folders. They are mostly **different** parts of one
set, so npkext unpacks all of them into the same `res/model/character/` folder.

When a file appears in more than one of them, the copy from the
**highest-priority** mount folder is written and the rest are counted as
*overridden*. Priority is the order in which the engine mounts the folders, as
recorded in the game's `log.txt`. The ones present in a normal installation, highest
first:

1. `Documents/res4`, `Documents/res3`, `Documents/res2`, `Documents/res` (patch downloads)
2. `res`, `res2` (the installer)
3. `Documents/script_patch`, `Documents/script`, `script`

Archives outside every mount folder keep the order they were given on the command
line. The plan lists every folder's mount folders, highest priority first. If a
high-priority copy fails to decode, the next copy is used instead.

`res.npk` holds a few files at paths that a nested archive also holds, with
different contents (for example `model\character\…` in both `res.npk` and
`res/model/character.npk`). The nested archive's copy is written; the `res.npk`
copy is handled like a lower-priority copy. This is decided from the archives in
the installation, not only from those being unpacked, so the result does not
depend on which archives you unpack or in which order.

Both "first mounted wins" and "nested wins" are assumptions based on the log, not
yet confirmed in the engine's code; see [mount-rules-plan.md](mount-rules-plan.md).
Overridden copies are never lost: `--keep-overridden` writes them, and the index
always records them.

### The index: `_archives/`

Everything needed to rebuild the original archives is kept in one place.

**`index.csv`**: one row per archive ever unpacked into this output folder.

| Column | Content |
|---|---|
| `archive` | Path of the `.npk`, relative to the installation |
| `mount` | The mount folder it belongs to (`Documents/res`, `res2`, …) |
| `priority` | Rank of that mount folder, 0 = highest (see `mounts.csv`) |
| `output_folder` | Where its files went, relative to the output folder |
| `entries`, `looked_at` | Files in the archive, and how many were processed (fewer with `--limit`) |
| `size` | Size of the `.npk` in bytes |
| `record` | Its record file, relative to `_archives/` |

**`<archive path>.csv`**: one record per archive, for example
`_archives/Documents/res/ui.npk.csv`. One row per entry, in the archive's own
table order, so an archive can be rebuilt from its record alone:

| Column | Content |
|---|---|
| `toc_index` | Position in the archive's table of contents |
| `id` | Entry id (hash of the path inside the archive), hex |
| `offset` | Where the stored bytes start in the `.npk` (gives the storage order) |
| `packed_size`, `raw_size`, `crc_packed`, `crc_raw`, `flags` | The table-of-contents values, unchanged |
| `status` | `ok` written; `overridden` another archive's copy was used (written only with `--keep-overridden`); `failed` could not be decoded; `skipped` not processed (`--limit`) |
| `path` | The written file, relative to the output folder |
| `note` | For `overridden`: which archive's copy was used. For `failed`: the error |

Archives that are not inside the installation get their records in
`_archives/_outside/`, named after their full path.

**`mounts.csv`**: the mount folders npkext knows, with depth, tree and priority.

### Unnamed files

An entry without a name in the manifest is written as `_unnamed/<id>.<ext>`. The
extension is guessed from the first bytes: `dds`, `png`, `mesh`, `bxml` (NeoX binary
XML), `wem`/`bnk` (Wwise), `enc` (encrypted script), …, or `bin` if unknown.
Typical coverage: 97–100% named for resource archives, about 0% for scripts.

## What the terminal shows

The plan, the progress and the result are grouped by **section**: the folder that
holds a set of output folders. Nested sections come first:

```
▸ res/levelsets/  371 folders, 8.8 GB
  Folder         From (highest priority first)   Files   Packed   Unpacked
  azikaban_rtt   Documents/res, res                 16   807.7 kB   1.2 MB
  …
▸ res/model/  9 folders, 14.0 GB
  …
▸ res/  37 folders, 36.0 GB
  …
▸ (top level)  2 folders, 1.2 GB
  res      Documents/res, res     …
  script   Documents/script_patch, Documents/script, script   …
```

`(top level)` holds the folders directly inside `--out`: the roots of the
resource tree (`res`) and the script tree (`script`).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Everything unpacked and verified |
| 1 | Finished, but some entries failed (listed at the end and in the records in `_archives/`) |
| 2 | Bad input: missing folders or files, unknown archive name, … |
| 130 | Interrupted with Ctrl+C |

## Performance

Disk I/O is the bottleneck, not the CPU. Entries are read in the order they are
stored, so each archive is read front to back; reading in table order instead was
measured to be more than 20× slower on a network-style (VirtualBox shared) folder.
Writing hundreds of thousands of small files is the slowest part: the full
character set (six archives, 105k files, 11 GB) takes on the order of 10 minutes.

On Windows, real-time antivirus scanning slows down writing many small files a lot.
Excluding the output folder from scanning for the duration of a large run helps.

## Memory

npkext itself stays around 200 MB, whatever the size of the job.

The operating system's file cache is another matter. Linux keeps every file written
in RAM until the memory is needed elsewhere. Left alone during a full run, that
cache can fill all RAM, push the desktop into swap and freeze a machine with little
spare memory, such as a virtual machine.

To prevent that, every 256 MB of output npkext flushes the data to disk and tells
the kernel to drop those pages (`pagecache.py`). This runs in a background thread
while unpacking continues, so at most two batches (~512 MB) are ever cached.
Archives being read are dropped from the cache the same way. Measured on 1.5 GB of
output, the cache follows a sawtooth: up to 400–500 MB, then back down to
100–280 MB after each flush, while the system's available memory stays flat.

On Windows these calls do not exist and are skipped. Windows keeps written files
in its "standby" cache, which it gives back to programs on demand.

On Linux, if you want a hard safety net anyway, run large jobs in a memory-capped
scope. If memory runs away, the kernel then stops npkext instead of freezing the
machine:

```bash
systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=0 \
    npkext --install GAME --out unpacked
```

## Windows notes

* Install and run exactly as on Linux (see the README); no extra steps.
* Long output paths are handled: npkext writes through Windows' extended-length
  paths (`\\?\C:\…`), so the 260-character limit does not apply.
* Paths given to `--in` may use `\` or `/`.
