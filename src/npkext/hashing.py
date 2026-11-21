"""The hash function NPK archives are built on.

NeoX uses 32-bit murmur3 with a fixed seed for three things:

* an entry's id is the hash of its path inside the archive,
* `crc_packed` is the hash of the stored (encrypted, compressed) bytes,
* `crc_raw` is the hash of the original file.
"""

import mmh3

NPK_HASH_SEED = 0x9747B28C


def npk_hash(data: bytes) -> int:
    """murmur3_32 of `data` with the NeoX seed, as an unsigned integer."""
    return mmh3.hash(data, NPK_HASH_SEED, signed=False)


def path_id(path: str) -> int:
    """The entry id of a file path inside an archive.

    The path uses backslashes and keeps its original upper/lower case,
    e.g. 'textures\\hero.dds'.
    """
    return npk_hash(path.encode("utf-8"))
