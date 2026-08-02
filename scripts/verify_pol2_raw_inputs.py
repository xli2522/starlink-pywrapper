#!/usr/bin/env python3
"""Verify the exact official JCMT POL-2 Tutorial 1 raw input selection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable


MANIFEST_LINE = re.compile(
    r"(?P<digest>[0-9a-f]{64})  (?P<filename>[^\r\n]+)\Z"
)


class RawInputVerificationError(ValueError):
    """The raw directory does not match the frozen input manifest."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, str]:
    """Load a strict sha256sum-style basename-only manifest."""

    entries: dict[str, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = MANIFEST_LINE.fullmatch(line)
        if match is None:
            raise RawInputVerificationError(
                f"invalid manifest line {line_number}: expected "
                "'<64 lowercase hex digits><two spaces><basename>'"
            )
        filename = match.group("filename")
        filename_path = Path(filename)
        if (
            filename in {".", ".."}
            or filename_path.is_absolute()
            or filename_path.name != filename
        ):
            raise RawInputVerificationError(
                f"manifest line {line_number} is not a safe basename: {filename!r}"
            )
        if filename in entries:
            raise RawInputVerificationError(
                f"duplicate manifest filename on line {line_number}: {filename}"
            )
        entries[filename] = match.group("digest")
    if not entries:
        raise RawInputVerificationError("raw-input manifest is empty")
    return entries


def _format_names(names: Iterable[str]) -> str:
    ordered = sorted(names)
    shown = ordered[:5]
    suffix = (
        ""
        if len(ordered) <= len(shown)
        else f" (+{len(ordered) - len(shown)} more)"
    )
    return ", ".join(shown) + suffix


def manifest_paths(raw_dir: Path, manifest_path: Path) -> list[Path]:
    """Return the frozen manifest's exact input paths after structural checks."""

    raw_dir = raw_dir.resolve(strict=True)
    expected = load_manifest(manifest_path.resolve(strict=True))
    paths = []
    for filename in expected:
        path = raw_dir / filename
        if not path.is_file() or path.is_symlink():
            raise RawInputVerificationError(
                f"manifest input is not a regular non-symlink file: {path}"
            )
        paths.append(path)
    unexpected = {
        path.name
        for path in raw_dir.glob("*.sdf")
        if path.name not in expected
    }
    if unexpected:
        raise RawInputVerificationError(
            f"unexpected: {_format_names(unexpected)}"
        )
    return paths


def verify_raw_inputs(raw_dir: Path, manifest_path: Path) -> dict[str, object]:
    """Verify selected filenames and bytes, returning compact provenance."""

    raw_dir = raw_dir.resolve(strict=True)
    manifest_path = manifest_path.resolve(strict=True)
    if not raw_dir.is_dir():
        raise RawInputVerificationError(f"raw path is not a directory: {raw_dir}")

    expected = load_manifest(manifest_path)
    try:
        selected_paths = manifest_paths(raw_dir, manifest_path)
    except RawInputVerificationError as error:
        details = []
        missing = {name for name in expected if not (raw_dir / name).is_file()}
        if missing:
            details.append(f"missing: {_format_names(missing)}")
        details.append(str(error))
        raise RawInputVerificationError(
            "selected raw-input set does not match the frozen manifest ("
            + "; ".join(details)
            + ")"
        ) from error

    total_bytes = 0
    for path in selected_paths:
        expected_digest = expected[path.name]
        total_bytes += path.stat().st_size
        actual_digest = _sha256(path)
        if actual_digest != expected_digest:
            raise RawInputVerificationError(
                f"SHA-256 mismatch for {path.name}: "
                f"expected {expected_digest}, got {actual_digest}"
            )

    return {
        "all_inputs_match": True,
        "file_count": len(expected),
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "raw_directory": str(raw_dir),
        "selected_bytes": total_bytes,
        "selection_source": "frozen manifest",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the selected JCMT POL-2 Tutorial 1 raw files against a "
            "basename-only SHA-256 manifest."
        )
    )
    parser.add_argument("raw_directory", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)

    try:
        report = verify_raw_inputs(args.raw_directory, args.manifest)
    except (OSError, RawInputVerificationError) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
