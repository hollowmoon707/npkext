"""Guessing a file extension from a file's first bytes.

Only used for entries whose name could not be recovered from the manifest.
"""

# (signature, extension), checked in order, so longer/more specific signatures come first.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"DDS ", "dds"),
    (b"\x89PNG", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"\xabKTX", "ktx"),
    (b"\x34\x80\xc8\xbb", "mesh"),          # NeoX CMesh
    (b"SKEL", "skeleton"),                  # NeoX skeleton
    (b"RAWA", "rawanimation"),              # NeoX raw animation
    (b"\xc1\x59\x41\x0d", "bxml"),          # NeoX binary XML (materials, prefabs, scenes)
    (b"RIFF", "wem"),                       # Wwise audio
    (b"BKHD", "bnk"),                       # Wwise sound bank
    (b"OggS", "ogg"),
    (b"NTRK", "ntrk"),
    (b"TZif", "tzif"),                      # time zone data
    (b"PK\x03\x04", "zip"),
    (b"\x1d\x04", "enc"),                   # game script, still encrypted by the script layer
    (b"<?xml", "xml"),
    (b"\xef\xbb\xbf<", "xml"),
    (b"<", "xml"),
    (b"{", "json"),
]

UNKNOWN_EXTENSION = "bin"


def guess_extension(data: bytes) -> str:
    """A file extension (without the dot) that fits the file's signature."""
    for signature, extension in _SIGNATURES:
        if data.startswith(signature):
            return extension
    return UNKNOWN_EXTENSION
