"""Regression tests for the machine-readable public API contract."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE = PROJECT_ROOT / "manifests" / "api_manifest_baseline.json"
GENERATOR = PROJECT_ROOT / "scripts" / "generate_api_manifest.py"
COMPARATOR = PROJECT_ROOT / "scripts" / "compare_api_manifests.py"

EXPECTED_MODULES = {
    "atools",
    "ccdpack",
    "convert",
    "cupid",
    "figaro",
    "fluxes",
    "hdsutils",
    "kappa",
    "picard",
    "polpack",
    "smurf",
    "utilities",
    "wrapper",
}


def run_script(script: Path, *arguments: object) -> None:
    subprocess.run(
        [sys.executable, str(script), *(str(argument) for argument in arguments)],
        check=True,
        capture_output=True,
        text=True,
    )


def generate_current(output: Path) -> None:
    run_script(
        GENERATOR,
        "--source-root",
        PROJECT_ROOT,
        "--source-label",
        "test-working-tree",
        "--package-version",
        "0.4.0.dev1",
        "--output",
        output,
    )


def test_frozen_baseline_describes_the_released_03_surface() -> None:
    manifest = json.loads(BASELINE.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 1
    assert manifest["source"] == {
        "artifact": "starlink_pywrapper-0.3-py3-none-any.whl",
        "artifact_sha256": (
            "a7882049760bb46c5d8a8fc6f8624582f349f18725b45bacd6f4669fa73dd82e"
        ),
        "label": "pypi-starlink-pywrapper-0.3-wheel",
        "package_version": "0.3",
    }
    assert set(manifest["modules"]) == EXPECTED_MODULES
    assert sum(
        len(module["public_callables"])
        for module in manifest["modules"].values()
    ) == 734
    assert sum(
        len(module["public_result_types"])
        for module in manifest["modules"].values()
    ) == 1


def test_manifest_generation_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    generate_current(first)
    generate_current(second)

    assert first.read_bytes() == second.read_bytes()


def test_current_source_preserves_the_baseline_api(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    comparison = tmp_path / "comparison.json"
    generate_current(current)
    run_script(
        COMPARATOR,
        "--before",
        BASELINE,
        "--after",
        current,
        "--output",
        comparison,
    )

    summary = json.loads(comparison.read_text(encoding="utf-8"))["summary"]
    assert summary["modules_removed"] == 0
    assert summary["callables_removed"] == 0
    assert summary["signatures_changed"] == 0
    assert summary["result_types_removed"] == 0
    assert summary["result_types_changed"] == 0


def test_comparator_detects_a_signature_change(tmp_path: Path) -> None:
    before = {
        "source": {"label": "before"},
        "modules": {
            "demo": {
                "public_callables": [
                    {
                        "doc_summary": "Example.",
                        "kind": "function",
                        "name": "example",
                        "signature": "(value)",
                    }
                ],
                "public_result_types": [],
            }
        },
    }
    after = json.loads(json.dumps(before))
    after["source"] = {"label": "after"}
    after["modules"]["demo"]["public_callables"][0]["signature"] = (
        "(value, extra = None)"
    )

    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    output = tmp_path / "comparison.json"
    before_path.write_text(json.dumps(before), encoding="utf-8")
    after_path.write_text(json.dumps(after), encoding="utf-8")

    run_script(
        COMPARATOR,
        "--before",
        before_path,
        "--after",
        after_path,
        "--output",
        output,
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["summary"]["callables_changed"] == 1
    assert result["summary"]["signatures_changed"] == 1
    assert result["modules"]["demo"]["callables"]["changed"][0][
        "changed_fields"
    ] == ["signature"]
