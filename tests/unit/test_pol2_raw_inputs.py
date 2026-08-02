from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = PROJECT_ROOT / "scripts/verify_pol2_raw_inputs.py"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes]]:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    inputs = {
        "s8a20160125_00043_0001.sdf": b"first raw input",
        "s8b20160125_00043_0001.sdf": b"second raw input",
    }
    for filename, content in inputs.items():
        (raw_dir / filename).write_bytes(content)
    manifest = tmp_path / "raw_sha256.txt"
    manifest.write_text(
        "".join(
            f"{sha256(content)}  {filename}\n"
            for filename, content in sorted(inputs.items())
        ),
        encoding="utf-8",
    )
    return raw_dir, manifest, inputs


def run_verifier(raw_dir: Path, manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFIER), str(raw_dir), str(manifest)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=False,
    )


def test_verifier_accepts_exact_raw_input_set(tmp_path: Path):
    raw_dir, manifest, inputs = write_fixture(tmp_path)

    completed = run_verifier(raw_dir, manifest)

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["all_inputs_match"] is True
    assert report["file_count"] == len(inputs)
    assert report["selected_bytes"] == sum(map(len, inputs.values()))
    assert report["manifest_sha256"] == sha256(manifest.read_bytes())


@pytest.mark.parametrize("mutation", ("missing", "unexpected", "corrupt"))
def test_verifier_rejects_input_mismatch(tmp_path: Path, mutation: str):
    raw_dir, manifest, inputs = write_fixture(tmp_path)
    if mutation == "missing":
        (raw_dir / next(iter(inputs))).unlink()
        expected_message = "missing:"
    elif mutation == "unexpected":
        (raw_dir / "s8c20160125_00043_0001.sdf").write_bytes(b"unexpected")
        expected_message = "unexpected:"
    else:
        (raw_dir / next(iter(inputs))).write_bytes(b"changed")
        expected_message = "SHA-256 mismatch"

    completed = run_verifier(raw_dir, manifest)

    assert completed.returncode == 2
    assert expected_message in completed.stderr
    assert completed.stdout == ""


def test_verifier_rejects_manifest_path_escape(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    manifest = tmp_path / "raw_sha256.txt"
    manifest.write_text(f"{sha256(b'outside')}  ../outside.sdf\n", encoding="utf-8")

    completed = run_verifier(raw_dir, manifest)

    assert completed.returncode == 2
    assert "not a safe basename" in completed.stderr
