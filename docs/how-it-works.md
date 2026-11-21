# How it works

What an NPK archive is, how a file is stored in it, and the steps npkext takes
to get it back. Everything here was worked out on the PC client, version 1.5.21.3.

## 1. The container

An `.npk` file is a NeoX **NXPK** archive: a short header, the stored files back
to back, and a table of contents (TOC) at the end. All integers are little-endian
unsigned 32-bit.

| Offset | Content |
|---|---|
| `0x00` | Magic `NXPK` |
| `0x04` | Number of entries |
| `0x08`–`0x13` | Unused (zero) |
| `0x14` | Offset of the TOC |
| `0x18` | Stored file data |
| TOC | One 28-byte row per entry |

A TOC row:

| Field | Meaning |
|---|---|
| `id` | murmur3 hash of the file's path inside the archive |
| `offset` | Where the stored bytes start |
| `packed_size` | Length of the stored bytes |
| `raw_size` | Length of the original file |
| `crc_packed` | murmur3 of the stored bytes, exactly as on disk |
| `crc_raw` | murmur3 of the original file |
| `flags` | Low byte: compression mode. Bit 16 (`0x10000`): encrypted |

Rows are sorted by `id`. The archive stores no file names, only their hashes.

## 2. One hash for everything

NeoX uses **32-bit murmur3 with seed `0x9747B28C`** for the entry id (hash of
the path, UTF-8, backslashes, original case) and for both checksums. See
`hashing.py`.

## 3. Getting a file back

`codec.decode_entry` takes four steps:

```
stored bytes ──check crc_packed──► decrypt ──► decompress ──check crc_raw──► original file
```

### 3.1 Check `crc_packed`
Hash the stored bytes. A mismatch means the archive itself is damaged.

### 3.2 Decrypt (only if bit 16 of `flags` is set)
Only the **first 128 bytes** are scrambled: byte `i` is XORed with `(i + 6) & 0xFF`,
i.e. with `06 07 08 … 85`. Everything after byte 128 is stored in the clear.

This is weak obfuscation rather than real encryption. It works only because LZ4
needs its first bytes to make sense, so generic NPK tools fail on these archives.
It was found by known plaintext: a texture entry must begin with an LZ4 token
followed by `"DDS "` and a fixed header. XORing that expected plaintext with the
stored bytes gave `08 09 0a 0b …`, the byte position plus 6. Trying different
encrypted lengths decrypted every test entry at exactly 128 bytes and almost none
at any other length.

Almost every entry is encrypted (`flags` = `0x10002`, encrypted LZ4). Most Wwise
audio is stored plain (`0`) or zlib (`1`) without encryption.

### 3.3 Decompress (low byte of `flags`)

| Value | Mode |
|---|---|
| 0 | Stored as-is |
| 1 | zlib |
| 2 | LZ4 block, no size prefix; output size is `raw_size` |
| 3 | zstd |

### 3.4 Check `crc_raw`
Hash the result. A match proves the file is byte-identical to the original.
Both checks can be skipped with `--no-verify`, but they cost little.

## 4. File names

The game ships a list of every resource path: **`resdb`**. It starts with a 16-byte
header (`CCZ!` …), followed by a zlib stream of text lines `<flag> <path>`. The
installation has two: `res/resdb` (shipped, ~414k paths) and `Documents/res/resdb`
(patched, ~454k paths). npkext merges them.

An entry id is the hash of the path **relative to where the archive is mounted in
the resource tree** (see section 5):

| Archive | Paths in `resdb` | Hashed (= path inside the archive) |
|---|---|---|
| `res/ui.npk` | `ui\login\bg.png` | `login\bg.png` |
| `res/model/character.npk` | `model\character\f\body.mesh` | `f\body.mesh` |
| `res/levelsets/lake.npk` | `levelsets\lake\terrain.bxml` | `terrain.bxml` |
| `res.npk` (next to `res/`) | `common\shader\x.xml` | `common\shader\x.xml` |

So naming an archive means: take every manifest path under its prefix, strip the
prefix, hash the rest, and match the hashes against the TOC ids
(`names.NameResolver`). Measured coverage: 100% for the patch downloads, 97–99.8% for
the installer's archives (some old files are no longer listed). Scripts are not in the
manifest.

`resdb` lists only the files inside archives, never the archives themselves; which
archives exist is found by scanning the installation for `.npk` files.

An archive that is not inside or next to a mount folder (a copy somewhere else) is
tried with two prefixes: none, and `<archive name>\`. That works for copies of
`res.npk` and of top-level archives like `ui.npk`. Copies of nested archives such as
`model/character.npk` lose their prefix unless they are kept in their original
folder structure (`copies/res/model/character.npk` works: the folder names decide).

## 5. Mount folders

The game never sees archives, only one **virtual file tree**. At startup the engine
creates a "file loader" for each of a fixed list of **mount folders**, and logs
each one in the `[FILESYSTEM]` lines of `log.txt` (installation folder):

```
[FILESYSTEM] Package …\Documents\res.npk under opener sys is loaded.
[FILESYSTEM] Package …\Documents\res\ui.npk under opener sys is loaded.
[FILESYSTEM] Package …\Documents\res\model\character.npk under opener sys is loaded.
[FILESYSTEM] Succeeded to create FileLoader, opener sys, loader npk, root …\Documents\res, depth 2
```

The `Package … loaded` lines just before each loader show the rule. A mount folder
`R` with depth `d` loads:

| Archive | Mounted at |
|---|---|
| `R.npk`, next to the folder | the root of the tree |
| `R/ui.npk` | `ui\` |
| `R/model/character.npk` | `model\character\` |
| … up to `d` folder levels below `R` | |

All resource mount folders fill **one** tree (the one `resdb` describes). The
script mount folders fill a second one: `Documents/script_patch.npk` holds 50
files, all of them newer copies of files in `script.npk`.

The mount folders, in the order they are created (`mounts.MOUNTS`, also written to
`_archives/mounts.csv`):

| # | Mount folder | Depth | | # | Mount folder | Depth |
|---|---|---|---|---|---|---|
| 0 | `Documents/res_dlc_low` | 0 | | 13 | `Documents/res_silent3` | 2 |
| 1 | `Documents/gray_res` | 0 | | 14 | `Documents/res_silent_patch` | 2 |
| 2 | `Documents/res4` | 2 | | 15 | `Documents/res_silent` | 2 |
| 3 | `Documents/res3` | 2 | | 16 | `res` | 2 |
| 4 | `Documents/res2` | 2 | | 17 | `res2` | 2 |
| 5 | `Documents/res` | 2 | | 18 | `res3` | 2 |
| 6 | `Documents/res_silent1` | 4 | | 19 | `res4` | 2 |
| 7 | `Documents/res_dlc_dress` | 3 | | 20 | `Documents/gray_script_patch` | 0 |
| 8 | `Documents/res_dlc_scene` | 3 | | 21 | `Documents/gray_script` | 0 |
| 9 | `Documents/res_dlc_y2` | 3 | | 22 | `Documents/script_patch` | 0 |
| 10 | `Documents/res_dlc_patch` | 3 | | 23 | `Documents/script` | 0 |
| 11 | `Documents/res_dlc` | 3 | | 24 | `script` | 0 |
| 12 | `Documents/res_silent3_patch` | 2 | | | | |

Most are empty in a normal installation; they are listed so that archives that
appear there later (downloaded DLC, silent patches) are placed correctly.

An archive is placed by the **names** of the folders in its path: the nearest
folder above it that is a mount folder name, within that folder's depth; or, for
`R.npk`, its own name. So placement works the same inside the installation and for
copies kept in the same folder structure. Priority needs the full path inside the
installation (`Documents/res` and `res` are different mount folders with the same
name).

Archives mounted at the same place from different folders (six `character.npk`,
four `ui.npk`, …) mostly hold **different** files. For example, the four `ui.npk`
files have ~11k entries each and 41.5k distinct files together, so they are parts
of one set split for size. A minority of ids appear in more than one, almost always
with different content: those are patched files.

npkext therefore merges all archives mounted at one place into one folder and,
for a file present in several of them, keeps the copy from the **first-mounted**
folder. *Assumption:* first-mounted wins. That is the usual rule for patch
directories, and it fits the patch downloads being mounted before the shipped
files, but it has not been confirmed in the engine code. The log also mentions an
`NpkConflictResolver`, so the engine has explicit rules for duplicates that may say
otherwise. The `_archives/` records keep every copy's origin, and
`--keep-overridden` keeps the other copies, so nothing is lost if this turns out to
be wrong.

The output folders nest like the tree (`res/` for `res.npk`, `res/ui/` for
`ui.npk`), so a file of `res.npk` can land at a path a nested archive also fills;
three do, with different contents. The nested archive's copy wins and the
`res.npk` copy is counted as overridden. *Assumption:* the more specific archive
wins; this too is unconfirmed, and the other copy is kept the same way.

How these rules could be confirmed is in [mount-rules-plan.md](mount-rules-plan.md).

## 6. File types

Unnamed entries get an extension guessed from their first bytes (`filetypes.py`):

| Signature | Extension | What it is |
|---|---|---|
| `DDS ` | dds | DirectDraw texture |
| `89 50 4E 47` | png | |
| `34 80 C8 BB` | mesh | NeoX CMesh model |
| `SKEL` | skeleton | NeoX skeleton |
| `RAWA` | rawanimation | NeoX animation |
| `C1 59 41 0D` | bxml | NeoX binary XML (materials `.mtg`, prefabs `.gim`, scenes) |
| `RIFF` / `BKHD` | wem / bnk | Wwise audio / sound bank |
| `1D 04` | enc | Game script, still encrypted by the script layer |
| `<`, `{` | xml / json | |

## 7. What is not handled here

* **Scripts.** `script.npk` entries decode and verify like any other entry, but
  what comes out is protected by a second, script-specific encryption (high
  entropy, `1D 04` header). Decrypting it is outside the scope of this tool.
* **Format conversion.** Meshes, binary XML, animations etc. are written in their
  NeoX formats. Converting them is a separate step.
