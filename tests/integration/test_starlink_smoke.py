from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import shlex
from string import Template

import pytest

from starlink import figaro, kappa, wrapper


pytestmark = pytest.mark.starlink_smoke


@pytest.fixture(scope="module")
def starlink_root() -> Path:
    configured = os.environ.get("STARLINK_TEST_DIR")
    if not configured:
        pytest.skip("set STARLINK_TEST_DIR to run Starlink smoke tests")
    root = Path(configured).resolve()
    if not (root / "etc/profile").is_file():
        pytest.fail(f"STARLINK_TEST_DIR is not a Starlink installation: {root}")
    wrapper.change_starpath(root)
    return root


@pytest.fixture(scope="module")
def sample_ndf(starlink_root: Path) -> Path:
    configured = os.environ.get("STARLINK_SMOKE_NDF")
    sample = (
        Path(configured).resolve()
        if configured
        else starlink_root / "examples/sc7/object2d.sdf"
    )
    if not sample.is_file():
        pytest.fail(f"smoke-test NDF is missing: {sample}")
    return sample


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_default_result_reader_returns_typed_application_values(sample_ndf: Path):
    before = _sha256(sample_ndf)
    result, stdout = kappa.stats(
        str(sample_ndf),
        returnstdout=True,
        _starlink_timeout=60,
    )

    assert result.numpix == 537600
    assert result.minimum == pytest.approx(-1094.00012207031)
    assert result.mean == pytest.approx(8.02818643065752)
    assert result.maximum == pytest.approx(777.666564941406)
    assert "Number of pixels" in stdout
    assert _sha256(sample_ndf) == before
    assert Path(wrapper.adamdir).is_absolute()


def test_int64_vectors_and_ndf_metadata_are_retrieved(sample_ndf: Path):
    result = kappa.ndftrace(str(sample_ndf), _starlink_timeout=60)

    assert result.dims == [1024, 525]
    assert all(type(value) is int for value in result.dims)
    assert result.ndim == 2
    assert isinstance(result.units, str)


def test_output_command_changes_science_values_without_touching_input(
    sample_ndf: Path,
    tmp_path: Path,
):
    before = _sha256(sample_ndf)
    output = tmp_path / "cadd-output"

    kappa.cadd(
        str(sample_ndf),
        2.5,
        str(output),
        _starlink_timeout=60,
    )
    original = kappa.stats(str(sample_ndf), _starlink_timeout=60)
    shifted = kappa.stats(str(output), _starlink_timeout=60)

    assert output.with_suffix(".sdf").is_file()
    assert shifted.numpix == original.numpix
    assert shifted.mean - original.mean == pytest.approx(2.5, abs=1e-9)
    assert _sha256(sample_ndf) == before


def test_removed_figaro_exam_has_explicit_compatibility_error():
    with pytest.raises(
        wrapper.StarlinkApplicationUnavailableError,
        match="Starlink 2025A removed FIGARO EXAM; use HDSTRACE instead",
    ):
        figaro.exam()


def test_generated_additions_target_installed_applications(
    starlink_root: Path,
):
    comparison_path = (
        Path(__file__).resolve().parents[2]
        / "manifests"
        / "api_manifest_comparison_2025a.json"
    )
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    generated_modules = {
        "atools",
        "ccdpack",
        "convert",
        "cupid",
        "figaro",
        "kappa",
        "polpack",
        "smurf",
    }
    checked = []

    for module_name in sorted(generated_modules):
        module = importlib.import_module(f"starlink.{module_name}")
        additions = comparison["modules"][module_name]["callables"]["added"]
        for item in additions:
            function = getattr(module, item["name"])
            commands = [
                value
                for value in function.__code__.co_consts
                if isinstance(value, str) and value.startswith("$")
            ]
            assert len(commands) == 1, f"{module_name}.{item['name']}"
            expanded = Template(commands[0]).safe_substitute(wrapper.env)
            executable = Path(shlex.split(expanded)[0])
            assert executable.is_file(), f"{module_name}.{item['name']}"
            assert os.access(executable, os.X_OK), (
                f"{module_name}.{item['name']}"
            )
            checked.append(f"{module_name}.{item['name']}")

    assert len(checked) == 22
