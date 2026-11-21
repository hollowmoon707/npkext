"""npkext: unpack NeoX engine NXPK (.npk) archives.

The package is built from small modules, bottom-up:

    errors     exception types
    hashing    murmur3 hash used for entry ids and checksums
    pagecache  keeping the kernel's file cache small during large jobs
    archive    reading the NXPK container (header + table of contents)
    codec      turning one stored entry back into the original file
    filetypes  guessing a file extension from a file's first bytes
    names      recovering file names from the resource manifest (resdb)
    mounts     where the game mounts each archive in its file tree, and priority
    install    knowledge about the game installation folder (archives, resdb)
    plan       choosing archives and grouping them into output folders
    extract    running a plan: decode entries and write files
    ui         everything shown in the terminal (rich)
    cli        command-line arguments; wires everything together

See docs/ next to this package for a description of the format and the tool.
"""

__version__ = "0.1.0"
