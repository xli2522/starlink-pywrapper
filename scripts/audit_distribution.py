#!/usr/bin/env python3
"""Reject data, diagnostics, and non-runtime files in built distributions."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import tarfile
import zipfile


FORBIDDEN_SUFFIXES = {
    ".fits", ".fit", ".sdf", ".ipynb", ".npy", ".npz", ".tar", ".tgz"
}
FORBIDDEN_PARTS = {
    ".agents", "tests", "scripts", "benchmarks", "evidence", "__pycache__"
}
SDIST_METADATA = {
    "CHANGELOG.rst", "LICENSE", "MANIFEST.in", "PKG-INFO", "README.rst",
    "pyproject.toml", "setup.cfg", "setup.py",
}


def member_names(archive: Path) -> list[str]:
    if archive.suffix == ".whl":
        with zipfile.ZipFile(archive) as handle:
            return handle.namelist()
    with tarfile.open(archive, "r:*") as handle:
        return handle.getnames()


def audit(archive: Path) -> None:
    wheel = archive.suffix == ".whl"
    problems = []
    for raw_name in member_names(archive):
        path = PurePosixPath(raw_name)
        parts = path.parts
        if not parts or path.name == "":
            continue
        relative = path if wheel else PurePosixPath(*parts[1:])
        if not relative.parts:
            continue
        lowered = {part.lower() for part in relative.parts}
        if lowered & FORBIDDEN_PARTS or relative.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(str(relative))
            continue
        if wheel:
            if not (
                relative.parts[0] == "starlink"
                or relative.parts[0].endswith(".dist-info")
            ):
                problems.append(str(relative))
        elif (
            relative.parts[0] != "starlink"
            and not relative.parts[0].endswith(".egg-info")
            and relative.name not in SDIST_METADATA
        ):
            problems.append(str(relative))
    if problems:
        listing = "\n".join(" - " + name for name in sorted(problems))
        raise SystemExit(f"{archive} contains non-runtime payload:\n{listing}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", type=Path)
    args = parser.parse_args()
    archives = sorted(args.dist.glob("*.whl")) + sorted(args.dist.glob("*.tar.gz"))
    if not archives:
        raise SystemExit(f"No distributions found in {args.dist}")
    for archive in archives:
        audit(archive)
        print(f"payload passed: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
