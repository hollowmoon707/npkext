# Notes for a future packer

npkext only unpacks. These notes record what a tool that packs the files back
into `.npk` archives would need, and what the current output does and does not
keep for that.

## Names are not needed to repack

An NXPK archive stores no file names, only each entry's **id** (murmur3 hash of
its path inside the archive). A table-of-contents row needs: id, offset, sizes,
both checksums and flags. None of these needs the name.

| What a TOC row needs | Where it comes from after unpacking |
|---|---|
| `id`, named file | murmur3 of the file's path inside its archive's output folder (e.g. `res/ui/`) (backslashes, original case); also in the archive's record |
| `id`, unnamed file | the file name itself (`_unnamed/<id>.<ext>`); also in the archive's record |
| `raw_size`, `crc_raw` | recomputed from the file |
| `packed_size`, `crc_packed` | recomputed after compressing and encrypting |
| `flags` (compression mode, encryption bit) | `flags` column of the archive's record |
| `offset` | chosen by the packer |

So unnamed files can be repacked like any other, **as long as they are not
renamed**: their id lives only in the file name and the manifest.

Packing is the reverse of `codec.decode_entry`: compress by the mode in `flags`,
then, if the encryption bit is set, XOR the first 128 bytes with `(i + 6) & 0xFF`
(`codec.decrypt` is its own inverse), then compute both checksums.

## What the output preserves

Every unpacked archive has a record, `_archives/<archive path>.csv` (see
[usage.md](usage.md#the-index-_archives)): its full table of contents in the
original order, with the original offsets, sizes, checksums and flags, and for
each entry the path of the file it became. To rebuild `Documents/res/ui.npk`:
read `_archives/Documents/res/ui.npk.csv`, and for each row in `toc_index` order
take the file at `path`, pack it by `flags`, and write it.

* **Which archive a file belongs to:** the record lists exactly the archive's own
  entries, even though archives mounted at one place share an output folder.
* **Entry order:** `toc_index` is the table order, `offset` the storage order.

## What is not preserved yet

1. **Overridden copies.** By default only the highest-priority copy of a file is
   written; the records of lower-priority archives then have `overridden` rows
   with an empty `path`. Unpack with `--keep-overridden` to keep those copies
   (under `_overridden/<archive>/`, and `path` points there); otherwise those
   archives cannot be rebuilt exactly.
2. **Compressed bytes.** Recompressing with another LZ4/zlib/zstd version or other
   settings can produce different but valid bytes, so `crc_packed` and
   `packed_size` will differ from the original. That is only a problem if the
   engine compares these values against something other than the archive's own
   table. Not verified.
3. **Header fields.** The header words at 0x08–0x10 are not recorded; they have
   been zero in every archive seen.

For modding (change some files, rebuild, load in the game) none of these matter;
they only matter for an exact round trip.

## Where file names come from

All names come from the resource manifests `res/resdb` and `Documents/res/resdb`
(merged, ~455k paths), mapped to archives by the mount rules in
[how-it-works.md](how-it-works.md#5-mount-folders). Entries with no match are
unnamed. They are mainly:

* old files in the installer's archives that newer manifests no longer list (1–3%
  of those archives);
* all game scripts: the manifest lists resources, not code.

Possible extra name sources (feed the paths into a `ResourceManifest` for
`NameResolver`):

* the client's per-session resource traces, `Documents/res_<account>/*_log.txt_res`:
  trees of paths actually loaded, including missing ones;
* the resource-load logs `log_res*.txt` in the installation folder (`load: …`,
  `not_found_file: …`);
* for scripts: candidate module paths, hashed and matched; once script contents
  are readable, their imports name other modules.
