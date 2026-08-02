from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.pol2_tutorial


@pytest.fixture(scope="module")
def evidence() -> tuple[Path, Path, Path]:
    names = (
        "STARLINK_POL2_CLI_OUTPUT",
        "STARLINK_POL2_WRAPPER_OUTPUT",
        "STARLINK_POL2_COMPARISON_DIR",
    )
    values = [os.environ.get(name) for name in names]
    if not all(values):
        pytest.skip(f"set {', '.join(names)} to validate tutorial evidence")
    paths = tuple(Path(value).resolve() for value in values if value)
    if not all(path.is_dir() for path in paths):
        pytest.fail(f"tutorial evidence path is missing: {paths}")
    return paths  # type: ignore[return-value]


def test_tutorial_inputs_are_identical_and_unchanged(
    evidence: tuple[Path, Path, Path],
):
    cli_dir, wrapper_dir, _ = evidence
    assert (cli_dir / "mylist").read_bytes() == (wrapper_dir / "mylist").read_bytes()
    assert (
        cli_dir / "checksums/raw_before.txt"
    ).read_bytes() == (cli_dir / "checksums/raw_after.txt").read_bytes()
    wrapper_before = json.loads(
        (wrapper_dir / "checksums/raw_before.json").read_text(encoding="utf-8")
    )
    wrapper_after = json.loads(
        (wrapper_dir / "checksums/raw_after.json").read_text(encoding="utf-8")
    )
    assert wrapper_before == wrapper_after
    assert len(wrapper_before) == 116


def test_tutorial_products_are_semantically_equivalent(
    evidence: tuple[Path, Path, Path],
):
    cli_dir, wrapper_dir, comparison_dir = evidence
    assert (cli_dir / "CLI_COMPLETE").is_file()
    assert (wrapper_dir / "WRAPPER_COMPLETE").is_file()
    ndf = json.loads(
        (comparison_dir / "ndf/ndf_comparison.json").read_text(encoding="utf-8")
    )
    catalogues = json.loads(
        (comparison_dir / "catalogue_comparison.json").read_text(encoding="utf-8")
    )
    assert ndf["all_semantically_equivalent"] is True
    assert catalogues["all_semantically_equivalent"] is True


def test_tutorial_performance_bound_passes(
    evidence: tuple[Path, Path, Path],
):
    _, _, comparison_dir = evidence
    performance = json.loads(
        (comparison_dir / "performance.json").read_text(encoding="utf-8")
    )
    assert performance["acceptance_bound_passed"] is True
