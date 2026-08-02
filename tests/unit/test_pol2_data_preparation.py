from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tarfile

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREPARER_PATH = PROJECT_ROOT / "scripts/prepare_pol2_tutorial_data.py"
RUNNER_PATH = PROJECT_ROOT / "scripts/run_optional_pol2_tutorial.py"


def load_script(name: str, path: Path):
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


preparer = load_script("prepare_pol2_tutorial_data", PREPARER_PATH)
runner = load_script("run_optional_pol2_tutorial", RUNNER_PATH)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_bytes(
    archive: tarfile.TarFile,
    name: str,
    content: bytes,
) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(content))


def fixture_archive(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes]]:
    source = tmp_path / "source.tar.gz"
    inputs = {
        "s8a20160125_00043_0001.sdf": b"first",
        "s8b20160125_00043_0001.sdf": b"second",
    }
    with tarfile.open(source, "w:gz") as archive:
        for name in ("tutorial", "tutorial/raw"):
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        for name, content in inputs.items():
            add_bytes(archive, f"tutorial/raw/{name}", content)

    manifest = tmp_path / "manifest.txt"
    manifest.write_text(
        "".join(
            f"{hashlib.sha256(content).hexdigest()}  {name}\n"
            for name, content in sorted(inputs.items())
        ),
        encoding="utf-8",
    )
    return source, manifest, inputs


def archive_spec(source: Path, member_count: int):
    return preparer.ArchiveSpec(
        url=source.as_uri(),
        filename="fixture.tar.gz",
        size=source.stat().st_size,
        sha256=sha256(source),
        member_count=member_count,
    )


def restore_writable(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o644)
    root.chmod(0o755)


def test_prepare_downloads_verifies_extracts_and_reuses(tmp_path: Path):
    repository = tmp_path / "repository"
    repository.mkdir()
    workspace = tmp_path / "external-data"
    source, manifest, inputs = fixture_archive(tmp_path)

    report = preparer.prepare_data(
        workspace,
        repository,
        spec=archive_spec(source, 4),
        manifest_path=manifest,
    )

    raw = Path(report["raw_directory"])
    assert report["archive_reused"] is False
    assert report["data_reused"] is False
    assert report["raw_verification"]["all_inputs_match"] is True
    assert sorted(path.name for path in raw.glob("*.sdf")) == sorted(inputs)
    assert stat.S_IMODE(raw.stat().st_mode) == 0o555
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o444
        for path in raw.glob("*.sdf")
    )

    second = preparer.prepare_data(
        workspace,
        repository,
        spec=archive_spec(source, 4),
        manifest_path=manifest,
    )
    assert second["archive_reused"] is True
    assert second["data_reused"] is True
    restore_writable(workspace / "tutorial")


def test_prepare_rejects_archive_path_escape(tmp_path: Path):
    repository = tmp_path / "repository"
    repository.mkdir()
    workspace = tmp_path / "external-data"
    source = tmp_path / "unsafe.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        add_bytes(archive, "../escape", b"unsafe")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("", encoding="utf-8")

    try:
        preparer.prepare_data(
            workspace,
            repository,
            spec=archive_spec(source, 1),
            manifest_path=manifest,
        )
    except preparer.PreparationError as error:
        assert "unsafe archive member path" in str(error)
    else:
        raise AssertionError("unsafe archive was accepted")

    assert not (tmp_path / "escape").exists()
    assert not (workspace / "tutorial").exists()


def test_prepare_accepts_leading_dot_and_ignores_appledouble(tmp_path: Path):
    repository = tmp_path / "repository"
    repository.mkdir()
    workspace = tmp_path / "external-data"
    source = tmp_path / "macos-origin.tar.gz"
    content = b"raw input"
    filename = "s8a20160125_00043_0001.sdf"
    with tarfile.open(source, "w:gz") as archive:
        add_bytes(archive, "./._tutorial", b"AppleDouble metadata")
        for name in ("./tutorial", "./tutorial/raw"):
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        add_bytes(archive, f"./tutorial/raw/{filename}", content)

    manifest = tmp_path / "manifest.txt"
    manifest.write_text(
        f"{hashlib.sha256(content).hexdigest()}  {filename}\n",
        encoding="utf-8",
    )

    report = preparer.prepare_data(
        workspace,
        repository,
        spec=archive_spec(source, 4),
        manifest_path=manifest,
    )

    assert report["raw_verification"]["all_inputs_match"] is True
    assert not (workspace / "._tutorial").exists()
    restore_writable(workspace / "tutorial")


def test_prepare_rejects_metadata_named_path_escape(tmp_path: Path):
    source = tmp_path / "unsafe-metadata.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        add_bytes(archive, "../._escape", b"unsafe")

    with tarfile.open(source, "r:gz") as archive:
        members = archive.getmembers()

    with pytest.raises(preparer.PreparationError, match="unsafe archive member"):
        preparer.validate_members(members, archive_spec(source, 1))


def test_prepare_refuses_workspace_containing_checkout(tmp_path: Path):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)

    try:
        preparer.prepare_data(workspace, repository)
    except preparer.PreparationError as error:
        assert "must be disjoint" in str(error)
    else:
        raise AssertionError("unsafe workspace relationship was accepted")
