import struct

import pytest

from conftest import write_npk
from npkext.archive import Compression, NpkArchive
from npkext.codec import XOR_LENGTH, decode_entry, decrypt
from npkext.errors import ArchiveFormatError, EntryError
from npkext.hashing import NPK_HASH_SEED, npk_hash, path_id


def reference_murmur3_32(data: bytes, seed: int) -> int:
    """Plain-Python murmur3 x86_32, to check the library and the seed we use."""
    c1, c2, h = 0xCC9E2D51, 0x1B873593, seed
    rotl = lambda x, r: ((x << r) | (x >> (32 - r))) & 0xFFFFFFFF  # noqa: E731
    blocks = len(data) // 4
    for i in range(blocks):
        k = struct.unpack_from("<I", data, i * 4)[0]
        k = rotl((k * c1) & 0xFFFFFFFF, 15) * c2 & 0xFFFFFFFF
        h = (rotl(h ^ k, 13) * 5 + 0xE6546B64) & 0xFFFFFFFF
    k = 0
    for i, byte in enumerate(data[blocks * 4:]):
        k |= byte << (8 * i)
    if k or len(data) % 4:
        h ^= rotl((k * c1) & 0xFFFFFFFF, 15) * c2 & 0xFFFFFFFF
    h ^= len(data)
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    return h ^ (h >> 16)


@pytest.mark.parametrize("data", [b"", b"a", b"abcd", b"textures\\hero_face.dds"])
def test_hash_is_murmur3_with_neox_seed(data):
    assert npk_hash(data) == reference_murmur3_32(data, NPK_HASH_SEED)


def test_path_id_hashes_utf8_path():
    assert path_id("a\\b.dds") == npk_hash(b"a\\b.dds")


def test_decrypt_scrambles_only_the_first_128_bytes():
    plain = bytes(300)
    scrambled = decrypt(plain)
    assert scrambled[:4] == bytes([6, 7, 8, 9])            # 0 XOR (i + 6)
    assert scrambled[XOR_LENGTH - 1] == (XOR_LENGTH - 1 + 6) & 0xFF
    assert scrambled[XOR_LENGTH:] == plain[XOR_LENGTH:]
    assert decrypt(scrambled) == plain                     # XOR undoes itself


def test_decrypt_handles_blobs_shorter_than_the_key():
    assert decrypt(decrypt(b"short")) == b"short"


@pytest.mark.parametrize("compression", list(Compression))
@pytest.mark.parametrize("encrypted", [True, False])
def test_round_trip_every_storage_mode(tmp_path, compression, encrypted):
    files = {"a.txt": b"hello " * 100, "dir\\b.bin": bytes(range(256)) * 3, "empty": b""}
    npk = write_npk(tmp_path / "t.npk", files, compression=compression, encrypted=encrypted)
    with NpkArchive(npk) as archive:
        decoded = {e.id: decode_entry(archive, e) for e in archive.entries}
    assert decoded == {path_id(name): content for name, content in files.items()}


def test_damaged_data_is_reported(tmp_path):
    npk = write_npk(tmp_path / "t.npk", {"a": b"x" * 1000})
    raw = bytearray(npk.read_bytes())
    raw[0x18 + 5] ^= 0xFF                                  # flip a byte inside the stored data
    npk.write_bytes(bytes(raw))
    with NpkArchive(npk) as archive, pytest.raises(EntryError, match="crc_packed"):
        decode_entry(archive, archive.entries[0])


def test_non_npk_file_is_rejected(tmp_path):
    bogus = tmp_path / "bogus.npk"
    bogus.write_bytes(b"NOPE" + bytes(100))
    with pytest.raises(ArchiveFormatError):
        NpkArchive(bogus)
