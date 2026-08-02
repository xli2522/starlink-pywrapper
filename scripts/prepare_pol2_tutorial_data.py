#!/usr/bin/env python3
"""Download, verify, and safely stage the official JCMT POL-2 Tutorial 1 data."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile
import tempfile
import urllib.request
import uuid

from verify_pol2_raw_inputs import verify_raw_inputs


@dataclass(frozen=True)
class ArchiveSpec:
    url: str
    filename: str
    size: int
    sha256: str
    member_count: int


OFFICIAL_ARCHIVE = ArchiveSpec(
    url=(
        "https://ftp.eao.hawaii.edu/jcmt/usersmeetings/"
        "JCMT_POL-2_tutorial1_2017_raw_only.tar.gz"
    ),
    filename="JCMT_POL-2_tutorial1_2017_raw_only.tar.gz",
    size=1_964_931_434,
    sha256="8071bbb929a9224b34c9b104c7bc3f484f32781c64a3ee0e19854a8079e2086b",
    member_count=238,
)


class PreparationError(RuntimeError):
    """The tutorial data could not be staged safely."""


def is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def verify_archive(path: Path, spec: ArchiveSpec) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise PreparationError(
            f"archive must be a regular non-symlink file: {path}"
        )
    size, digest = hash_file(path)
    if size != spec.size:
        raise PreparationError(
            f"archive size mismatch: got {size}, expected {spec.size}"
        )
    if digest != spec.sha256:
        raise PreparationError(
            f"archive SHA-256 mismatch: got {digest}, expected {spec.sha256}"
        )
    return {"bytes": size, "sha256": digest}


def download_archive(
    destination: Path,
    spec: ArchiveSpec = OFFICIAL_ARCHIVE,
) -> tuple[dict[str, object], bool]:
    if destination.exists():
        return verify_archive(destination, spec), True

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / (
        f".{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.part"
    )
    request = urllib.request.Request(
        spec.url,
        headers={"User-Agent": "starlink-pywrapper-validation/0.4"},
    )
    try:
        print(f"Downloading official POL-2 archive: {spec.url}", file=sys.stderr)
        with urllib.request.urlopen(request, timeout=120) as response:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            downloaded = 0
            next_report = 256 * 1024 * 1024
            with os.fdopen(descriptor, "wb") as stream:
                while chunk := response.read(8 * 1024 * 1024):
                    stream.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= next_report:
                        print(
                            f"Downloaded {downloaded / (1024 ** 3):.2f} GiB",
                            file=sys.stderr,
                        )
                        next_report += 256 * 1024 * 1024
        report = verify_archive(temporary, spec)
        os.replace(temporary, destination)
        destination.chmod(0o444)
        return report, False
    except BaseException:
        if temporary.exists():
            temporary.unlink()
        raise


def validate_members(
    members: list[tarfile.TarInfo],
    spec: ArchiveSpec,
) -> list[tarfile.TarInfo]:
    if len(members) != spec.member_count:
        raise PreparationError(
            f"archive member-count mismatch: got {len(members)}, "
            f"expected {spec.member_count}"
        )
    extractable: list[tarfile.TarInfo] = []
    for member in members:
        raw_name = member.name
        if "\\" in raw_name or raw_name.startswith("/"):
            raise PreparationError(f"unsafe archive member path: {member.name!r}")
        while raw_name.startswith("./"):
            raw_name = raw_name[2:]
        name = PurePosixPath(raw_name)
        if not raw_name or name.is_absolute() or ".." in name.parts:
            raise PreparationError(f"unsafe archive member path: {member.name!r}")
        if not (member.isdir() or member.isfile()):
            raise PreparationError(
                f"unsupported archive member type: {member.name!r}"
            )
        # The official archive was created on macOS. Ignore only recognizable
        # AppleDouble and __MACOSX metadata after path and type validation.
        if any(
            part == "__MACOSX" or part.startswith("._")
            for part in name.parts
        ):
            continue
        if name.parts[0] != "tutorial":
            raise PreparationError(f"unsafe archive member path: {member.name!r}")
        member.name = name.as_posix()
        extractable.append(member)
    return extractable


def make_tree_read_only(root: Path) -> None:
    directories: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise PreparationError(f"extracted symlink is not allowed: {path}")
        if path.is_dir():
            directories.append(path)
        elif path.is_file():
            path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        else:
            raise PreparationError(f"unexpected extracted file type: {path}")
    for directory in sorted(
        directories,
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.chmod(0o555)
    root.chmod(0o555)


def prepare_data(
    workspace: Path,
    repository_root: Path,
    *,
    spec: ArchiveSpec = OFFICIAL_ARCHIVE,
    manifest_path: Path | None = None,
) -> dict[str, object]:
    repository_root = repository_root.expanduser().resolve(strict=True)
    workspace = workspace.expanduser().absolute()
    if is_within(workspace, repository_root) or is_within(
        repository_root, workspace
    ):
        raise PreparationError(
            "data workspace and Git checkout must be disjoint"
        )
    workspace.mkdir(parents=True, exist_ok=True)
    workspace = workspace.resolve(strict=True)
    if is_within(workspace, repository_root) or is_within(
        repository_root, workspace
    ):
        raise PreparationError(
            "resolved data workspace and Git checkout must be disjoint"
        )
    if not workspace.is_dir() or workspace.is_symlink():
        raise PreparationError(
            f"workspace must be a regular directory: {workspace}"
        )

    manifest = (
        manifest_path
        if manifest_path is not None
        else repository_root
        / "tests/integration/pol2/tutorial1_raw_sha256.txt"
    ).resolve(strict=True)
    archive_path = workspace / "downloads" / spec.filename
    tutorial_dir = workspace / "tutorial"
    raw_dir = tutorial_dir / "raw"

    if tutorial_dir.exists():
        if (
            tutorial_dir.is_symlink()
            or not raw_dir.is_dir()
            or raw_dir.is_symlink()
        ):
            raise PreparationError(
                f"existing tutorial directory is incomplete: {tutorial_dir}"
            )
        verification = verify_raw_inputs(raw_dir, manifest)
        return {
            "archive": asdict(spec),
            "archive_path": str(archive_path),
            "archive_reused": archive_path.is_file(),
            "data_reused": True,
            "raw_directory": str(raw_dir),
            "raw_verification": verification,
        }

    archive_report, archive_reused = download_archive(archive_path, spec)
    with tempfile.TemporaryDirectory(
        prefix=".pol2-extract-",
        dir=workspace,
    ) as temporary_name:
        temporary = Path(temporary_name)
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            extractable = validate_members(members, spec)
            archive.extractall(
                temporary,
                members=extractable,
                filter=_safe_tar_filter,
            )

        extracted_tutorial = temporary / "tutorial"
        extracted_raw = extracted_tutorial / "raw"
        if not extracted_raw.is_dir():
            raise PreparationError(
                "verified archive did not contain tutorial/raw"
            )
        verification = verify_raw_inputs(extracted_raw, manifest)
        if tutorial_dir.exists():
            raise PreparationError(
                f"tutorial destination appeared during extraction: {tutorial_dir}"
            )
        extracted_tutorial.rename(tutorial_dir)
        make_tree_read_only(tutorial_dir)

    return {
        "archive": asdict(spec),
        "archive_path": str(archive_path),
        "archive_report": archive_report,
        "archive_reused": archive_reused,
        "data_reused": False,
        "raw_directory": str(raw_dir),
        "raw_verification": verification,
    }


def _safe_tar_filter(
    member: tarfile.TarInfo,
    destination: str,
) -> tarfile.TarInfo:
    """Final extraction gate for the already normalized member list."""

    del destination
    name = PurePosixPath(member.name)
    if (
        name.is_absolute()
        or ".." in name.parts
        or not name.parts
        or name.parts[0] != "tutorial"
        or not (member.isdir() or member.isfile())
    ):
        raise PreparationError(f"unsafe extraction member: {member.name!r}")
    return member


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stage the exact official JCMT POL-2 Tutorial 1 raw data outside "
            "Git. Existing verified data and archive downloads are reused."
        )
    )
    parser.add_argument("workspace", type=Path)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = prepare_data(args.workspace, args.repository_root)
    except (OSError, PreparationError, tarfile.TarError) as error:
        print(f"POL-2 data preparation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
