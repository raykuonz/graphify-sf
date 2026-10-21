"""Fail if a PyInstaller one-file binary needs a newer glibc than allowed.

A one-file binary is a small launcher plus an embedded archive of the Python
runtime and every shared library PyInstaller collected from the build machine.
The launcher alone says little (it needs GLIBC_2.14 even when the payload needs
2.38), so this extracts every embedded ELF file and reads its GNU version-needs
(the GLIBC_x.y symbol versions it requires at load time).

Usage: check-glibc.py <binary> [--max 2.28]
Requires: pyinstaller (archive reader), pyelftools.
"""

from __future__ import annotations

import argparse
import io
import re
import sys

from elftools.elf.elffile import ELFFile
from elftools.elf.gnuversions import GNUVerNeedSection
from PyInstaller.archive.readers import CArchiveReader


def glibc_versions(stream) -> set[tuple[int, int]]:
    """GLIBC_x.y versions an ELF file requires, as (x, y) tuples."""
    found: set[tuple[int, int]] = set()
    for section in ELFFile(stream).iter_sections():
        if not isinstance(section, GNUVerNeedSection):
            continue
        for _verneed, auxiliaries in section.iter_versions():
            for aux in auxiliaries:
                m = re.fullmatch(r"GLIBC_(\d+)\.(\d+)(?:\.\d+)?", aux.name)
                if m:
                    found.add((int(m.group(1)), int(m.group(2))))
    return found


def fmt(version: tuple[int, int] | None) -> str:
    return f"{version[0]}.{version[1]}" if version else "-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("binary")
    parser.add_argument("--max", default="2.28", help="highest GLIBC version allowed (default 2.28)")
    args = parser.parse_args()
    limit = tuple(int(p) for p in args.max.split("."))

    with open(args.binary, "rb") as f:
        launcher = glibc_versions(f)
    results = [("<launcher>", launcher)]

    archive = CArchiveReader(args.binary)
    for name in archive.toc:
        data = archive.extract(name)
        if data and data[:4] == b"\x7fELF":
            results.append((name, glibc_versions(io.BytesIO(data))))

    too_new = [(name, max(vs)) for name, vs in results if vs and max(vs) > limit]
    overall = max((max(vs) for _, vs in results if vs), default=None)
    print(
        f"{args.binary}: {len(results)} ELF files checked, highest GLIBC requirement {fmt(overall)}, limit {args.max}"
    )
    for name, top in sorted(too_new, key=lambda r: r[1], reverse=True):
        print(f"  needs GLIBC_{fmt(top)}: {name}")
    if too_new:
        print(f"FAIL: {len(too_new)} bundled file(s) need a glibc newer than {args.max}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
