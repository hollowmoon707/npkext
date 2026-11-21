"""Exceptions raised by npkext.

Everything derives from NpkextError, so the command line can report any of them in one place.
"""


class NpkextError(Exception):
    """Base class for all npkext errors."""


class InputError(NpkextError):
    """The command-line input does not point at anything usable."""


class ArchiveFormatError(NpkextError):
    """A file is not a readable NXPK archive."""


class EntryError(NpkextError):
    """One entry inside an archive could not be decoded."""


class ManifestError(NpkextError):
    """A resdb manifest file could not be read."""
