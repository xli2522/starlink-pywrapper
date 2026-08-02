from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
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


runner = load_script("run_optional_pol2_tutorial", RUNNER_PATH)


def fixture_starlink(
    root: Path,
    *,
    version: str = "Starlink 2025A test fixture\n",
    marker: bytes = b"verified patch fixture",
) -> tuple[Path, str]:
    (root / "etc").mkdir(parents=True)
    (root / "manifests").mkdir()
    (root / "include/star").mkdir(parents=True)
    (root / "etc/profile").write_text("", encoding="utf-8")
    (root / "manifests/starlink.version").write_text(
        version, encoding="utf-8"
    )
    (root / runner.PATCH1_MARKER).write_bytes(marker)
    for relative in runner.REQUIRED_STARLINK_APPLICATIONS:
        application = root / relative
        application.parent.mkdir(parents=True, exist_ok=True)
        application.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        application.chmod(0o755)
    return root, hashlib.sha256(marker).hexdigest()


def test_optional_result_is_nonfatal_unless_strict():
    assert runner.outcome_exit_code("passed", strict=False) == 0
    assert runner.outcome_exit_code("incomplete", strict=False) == 0
    assert runner.outcome_exit_code("incomplete", strict=True) == 1
    assert runner.outcome_banner("passed", strict=True) == "PASSED"
    assert runner.outcome_banner("incomplete", strict=False).endswith("non-fatal)")
    assert runner.outcome_banner("incomplete", strict=True).endswith("fatal)")


def test_starlink_preflight_accepts_existing_2025a_patch1(tmp_path: Path):
    starlink, marker_sha256 = fixture_starlink(tmp_path / "star-2025A")

    report = runner.validate_starlink(
        starlink, expected_patch1_sha256=marker_sha256
    )

    assert report["directory"] == str(starlink.resolve())
    assert report["release"] == "2025A"
    assert report["patch"] == "Errata Patch 1"
    assert report["patch_marker_sha256"] == marker_sha256


def test_starlink_preflight_rejects_wrong_release(tmp_path: Path):
    starlink, marker_sha256 = fixture_starlink(
        tmp_path / "star-2024A",
        version="Starlink 2024A test fixture\n",
    )

    with pytest.raises(runner.OptionalValidationError, match="identify 2025A"):
        runner.validate_starlink(
            starlink, expected_patch1_sha256=marker_sha256
        )


def test_starlink_preflight_rejects_unpatched_installation(tmp_path: Path):
    starlink, _ = fixture_starlink(tmp_path / "star-2025A")

    with pytest.raises(runner.OptionalValidationError, match="Patch 1 marker"):
        runner.validate_starlink(
            starlink, expected_patch1_sha256="0" * 64
        )


def test_auto_starlink_uses_existing_environment_installation(tmp_path: Path):
    starlink, marker_sha256 = fixture_starlink(tmp_path / "star-2025A")

    resolved, report = runner.resolve_starlink(
        "auto",
        environment={"STARLINK_DIR": str(starlink), "PATH": ""},
        which=lambda _name, path=None: None,
        expected_patch1_sha256=marker_sha256,
    )

    assert resolved == starlink.resolve()
    assert report["discovered_from"] == "STARLINK_DIR"


def test_auto_starlink_infers_existing_installation_from_path(tmp_path: Path):
    starlink, marker_sha256 = fixture_starlink(tmp_path / "star-2025A")
    parget = starlink / "bin/kappa/parget"

    resolved, report = runner.resolve_starlink(
        "auto",
        environment={"PATH": str(parget.parent)},
        which=lambda _name, path=None: str(parget),
        expected_patch1_sha256=marker_sha256,
    )

    assert resolved == starlink.resolve()
    assert report["discovered_from"] == "parget on PATH"


def test_auto_starlink_reports_missing_installation():
    with pytest.raises(
        runner.OptionalValidationError,
        match="no existing Starlink installation",
    ):
        runner.resolve_starlink(
            "auto",
            environment={"PATH": ""},
            which=lambda _name, path=None: None,
        )


def test_missing_starlink_stops_before_data_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", checkout], check=True)
    subprocess.run(
        ["git", "-C", checkout, "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", checkout, "config", "user.name", "Test User"],
        check=True,
    )
    subprocess.run(["git", "-C", checkout, "add", "."], check=True)
    subprocess.run(
        ["git", "-C", checkout, "commit", "-q", "-m", "fixture"],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", checkout, "rev-parse", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    data_called = False

    def reject_starlink(_requested: str):
        raise runner.OptionalValidationError("no matching Starlink fixture")

    def unexpected_prepare(*_args, **_kwargs):
        nonlocal data_called
        data_called = True
        raise AssertionError("tutorial data preparation must not run")

    workspace = tmp_path / "external-workspace"
    monkeypatch.setattr(runner, "resolve_starlink", reject_starlink)
    monkeypatch.setattr(runner, "prepare_data", unexpected_prepare)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(RUNNER_PATH),
            "--checkout",
            str(checkout),
            "--expected-commit",
            commit,
            str(workspace),
            "auto",
            "--python",
            sys.executable,
        ],
    )

    assert runner.main() == 0
    assert data_called is False
    reports = list((workspace / "reports").glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["outcome"] == "incomplete"
    assert report["data"] is None
    assert "no matching Starlink fixture" in report["error"]["message"]
