"""Freeze npkext on the current platform and test it after archive extraction."""

import argparse
from importlib.metadata import distribution, version
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = os.name == "nt"
PLATFORM = "windows" if WINDOWS else "ubuntu"
EXECUTABLE = "npkext.exe" if WINDOWS else "npkext"


def add_docs(bundle: Path) -> None:
    for name in ("README.md", "LICENSE"):
        shutil.copy2(ROOT / name, bundle / name)
    shutil.copytree(ROOT / "docs", bundle / "docs")
    notices = bundle / "licenses"
    notices.mkdir()
    python_version = ".".join(map(str, sys.version_info[:3]))
    with urlopen(f"https://raw.githubusercontent.com/python/cpython/v{python_version}/LICENSE", timeout=30) as source:
        (notices / "CPython.txt").write_bytes(source.read())
    for name in ("lz4", "zstandard", "mmh3", "rich", "rich-argparse", "markdown-it-py",
                 "mdurl", "pygments", "pyinstaller"):
        package = distribution(name)
        for item in package.files or ():
            if ".dist-info" in item.as_posix() and item.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                shutil.copy2(package.locate_file(item), notices / f"{name}-{item.name}")


def smoke_test(command: Path, work: Path, expected_version: str) -> None:
    # Share the format fixture with the test suite, including both native codecs.
    sys.path.insert(0, str(ROOT / "tests"))
    from conftest import Compression, write_npk, write_resdb

    install = work / "test-install"
    (install / "neox_bin").mkdir(parents=True)
    lz4_content = b"lz4 test data\n" * 100
    zstd_content = b"zstandard test data\n" * 100
    write_resdb(install / "res" / "resdb", ["sample.txt", "test\\zstd.txt"])
    write_npk(install / "res.npk", {"sample.txt": lz4_content})
    write_npk(install / "res" / "test.npk", {"zstd.txt": zstd_content}, Compression.ZSTD)
    output = work / "unpacked"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    actual_version = subprocess.check_output([command, "--version"], cwd=work, env=env, text=True).strip()
    if actual_version != f"npkext {expected_version}":
        raise ValueError(f"unexpected CLI version {actual_version!r}")
    subprocess.run([command, "--install", install, "--out", output], cwd=work, env=env, check=True)
    for path, content in (("sample.txt", lz4_content), ("test/zstd.txt", zstd_content)):
        if (output / "res" / path).read_bytes() != content:
            raise ValueError(f"extraction smoke test produced incorrect contents for {path}")


def build(output: Path) -> Path:
    package_version = version("npkext")
    name = f"npkext-{package_version}-{PLATFORM}-x64"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="npkext-release-") as temporary:
        work = Path(temporary)
        scripts = Path(sysconfig.get_path("scripts"))
        smoke_test(scripts / EXECUTABLE, work, package_version)
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--onedir", "--name", "npkext",
             "--distpath", work / "dist", "--workpath", work / "build", "--specpath", work,
             ROOT / "tools/release/launcher.py"],
            cwd=work, check=True,
        )
        bundle = work / "dist" / name
        (bundle.parent / "npkext").rename(bundle)
        add_docs(bundle)
        archive = Path(shutil.make_archive(str(output / name), "zip" if WINDOWS else "gztar",
                                           bundle.parent, bundle.name))
        extracted = work / "extracted"
        shutil.unpack_archive(archive, extracted)
        smoke_test(extracted / name / EXECUTABLE, extracted, package_version)
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    print(build(parser.parse_args().out.resolve()))
