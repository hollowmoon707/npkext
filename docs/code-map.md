# Code map

```
npkext/
├── pyproject.toml          package metadata, dependencies, `npkext` command
├── README.md
├── docs/                   this documentation
├── src/npkext/
│   ├── cli.py              arguments → steps; the only place that knows about argparse
│   ├── ui.py               everything printed (rich): plan, progress, summary
│   ├── plan.py             pick archives (--in, --unpack), group by output folder, sections
│   ├── extract.py          run a plan: decode, name, write; the _archives/ index
│   ├── install.py          the installation folder: archives, resdb, mount priority
│   ├── mounts.py           mount folders (from log.txt): placement and priority
│   ├── names.py            resdb reader, prefix rule, id → name lookup
│   ├── codec.py            one entry → original file (decrypt, decompress, verify)
│   ├── archive.py          NXPK header + table of contents, reading stored bytes
│   ├── pagecache.py        keeps the kernel's file cache small (flush + drop written/read data)
│   ├── filetypes.py        extension from signature
│   ├── hashing.py          murmur3 with the NeoX seed
│   └── errors.py           exception types
└── tests/                  pytest; synthetic archives only (no game data)
```

Each module depends only on modules below it in this list, so the stack can be
read from the bottom up. `extract.py` never prints anything: it reports progress
through `ExtractListener`, which `ui.ProgressDisplay` implements.

## Data flow

```
cli.run
 ├─ find_archives          Installation.archives(), or resolve_inputs(--in):
 │                         file paths / names searched in the installation / paths inside it
 ├─ filter_by_name         --unpack patterns
 ├─ build_plan             open each archive, read its TOC → ArchiveSource
 │                         locate each: mounts.place → output folder, mount rank, record path
 │                         group by output folder → OutputGroup (sources by mount rank),
 │                         sorted by section (nested sections first)
 ├─ ResourceManifest       read + merge resdb files
 ├─ ui.show_plan
 └─ Extractor.run(plan)
     ├─ ReplacedPaths.find     parent files that a nested archive (anywhere in the
     │                         installation) also holds → treated as overridden
     ├─ for each OutputGroup → _GroupJob
         └─ for each ArchiveSource (highest priority first)
             ├─ NameResolver.names_for(archive)      id → path inside archive
             └─ for each entry, in storage order
                 ├─ provided by a higher-priority or nested archive? → overridden
                 ├─ codec.decode_entry                 check, decrypt, decompress, check
                 ├─ name or _unnamed/<id>.<guessed ext>
                 ├─ FileWriter.write   → WriteBehind: every 256 MB, sync + drop from page cache
                 └─ ArchiveRecord.set      (written per archive to _archives/<path>.csv)
     └─ ArchiveIndex.save      index.csv (merged with earlier runs), mounts.csv, README.txt
```

## Main types

| Type | Module | What it is |
|---|---|---|
| `NpkEntry` | archive | One TOC row (frozen dataclass) |
| `NpkArchive` | archive | An open `.npk`; `.entries`, `.read_stored(entry)` |
| `ResourceManifest` | names | Sorted path list with prefix search |
| `NameResolver` | names | `names_for(archive_path) → {id: inner path}`, cached per prefix |
| `Mount`, `MOUNTS` | mounts | One mount folder (root, depth, tree); the list in mount order |
| `Placement` | mounts | Where one archive is mounted: `place(path)` → output folder, resdb prefix |
| `Installation` | install | Root folder; `archives()`, `resdb_files()`, `mount_rank()` |
| `Location` | plan | Where an archive belongs: output folder, label, rank, mount, record path |
| `ArchiveSource` | plan | One archive with its `Location` and sizes |
| `OutputGroup` | plan | Archives mounted at one place (all mount folders) → one output folder, e.g. `res/model/character/`; `.section` is its parent |
| `Plan` | plan | All groups plus archives that could not be read; `.sections()` |
| `Extractor` | extract | Runs a plan; returns one `GroupResult` per group |
| `ExtractListener` | extract | Progress callbacks (no-op by default) |
| `ReplacedPaths` | extract | Parent-archive files that a nested archive replaces |
| `ArchiveRecord`, `ArchiveIndex` | extract | One archive's record; the `_archives/` folder |
| `WriteBehind` | pagecache | Batches written files; flushes them and drops their cached pages |

## Tests

```bash
pip install -e "path/to/npkext[dev]"
pytest path/to/npkext
```

The tests run on Linux, macOS and Windows.

`tests/conftest.py` writes small NXPK archives and resdb files using the same rules
the extractor reverses, plus a miniature installation with two mount folders, a `res.npk` and a script patch (`fake_install`).
The tests cover:
* every compression mode, with and without encryption;
* checksum failures;
* mount placement, the prefix rule and priority;
* the index, including unpacking archives in separate runs;
* name filtering;
* the full command line, including a run with page-cache control switched off
  (as on Windows);
* Windows extended-length path handling.

One extra test runs against a real game installation. Set the `NPKEXT_INSTALL`
environment variable to its folder to enable it; otherwise it is skipped. It reads
the files in place and stores nothing.

## Extending

* **New compression mode:** add it to `archive.Compression` and to `codec.decompress`.
* **New file signature:** add a line to `filetypes._SIGNATURES`.
* **Different mount folders or order:** edit `mounts.MOUNTS` (see
  [mount-rules-plan.md](mount-rules-plan.md)).
* **Another name source** (e.g. paths from the client's resource logs): build a
  `ResourceManifest` from those paths and pass it to `NameResolver`.
