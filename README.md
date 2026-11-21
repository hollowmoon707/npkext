# npkext

Command-line extractor for NeoX engine **NXPK** (`.npk`) archives, written for
*Harry Potter: Magic Awakened*.

It decrypts, decompresses and checksum-verifies every file, recovers real file
names from the game's resource manifest (`resdb`), and rebuilds the game's file
tree: every archive is unpacked where the game mounts it, and archives split
across the patch folders are merged. The output is the original files exactly as
they were packed, plus an index (`_archives/`) that records where every file came
from, so the archives can be rebuilt.

npkext contains only processing logic and ships no game data. It reads the
archives and the `resdb` manifest from **your own installation** at run time.

```bash
# archives by name, searched in the whole installation (all copies merged)
npkext --install "path/to/Magic Awakened" --in character.npk ui --out unpacked

# everything
npkext --install "path/to/Magic Awakened" --out unpacked
```

## Install

Requires Python 3.10 or newer. All dependencies come as ready-made wheels for
Windows, Linux and macOS; no compiler is needed.

**Windows (PowerShell)**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install path\to\npkext
npkext --install "C:\Games\Magic Awakened" --in texture --out D:\unpacked
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install path/to/npkext
npkext --install ~/games/"Magic Awakened" --in texture --out ~/unpacked
```

`path/to/npkext` is the folder containing `pyproject.toml`. From its parent folder,
write `./npkext` (or `.\npkext`); a bare `npkext` makes pip look for a package of
that name online.

For development, install it editable with the test dependencies:
`pip install -e "path/to/npkext[dev]"`, then run `pytest path/to/npkext`.

Without activating the venv, call the command by its path:
`.venv\Scripts\npkext.exe` on Windows, `.venv/bin/npkext` on Linux and macOS.

## Documentation

| | |
|---|---|
| [docs/usage.md](docs/usage.md) | Command-line options, examples, output layout, the `_archives/` index, memory and performance |
| [docs/how-it-works.md](docs/how-it-works.md) | The NXPK format, encryption, compression, checksums, file names, mount folders |
| [docs/mount-rules-plan.md](docs/mount-rules-plan.md) | Which mount rules are assumed, and the plan to confirm them from the game's code |
| [docs/code-map.md](docs/code-map.md) | How the code is organised, how data flows through it, tests, extending it |
| [docs/repacking-notes.md](docs/repacking-notes.md) | Notes for a future packer: what repacking needs and what the output preserves |

## Scope

* Game scripts (`script.npk`) are unpacked and verified like every other archive,
  but their content is protected by a separate, script-specific encryption. They
  are saved as `script/_unnamed/<id>.enc`; decrypting them is outside this tool's scope.
* NeoX's own file formats (`.mesh`, binary XML, `.rawanimation`, …) are written
  as they are, not converted.
