from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

import pytest

from starlink import kappa, wrapper
from starlink._environment import (
    capture_starlink_environment,
    configure_session_environment,
)


pytestmark = pytest.mark.starlink_smoke


@pytest.fixture(scope="module")
def starlink_root() -> Path:
    configured = os.environ.get("STARLINK_TEST_DIR")
    if not configured:
        pytest.skip("set STARLINK_TEST_DIR to run Starlink smoke tests")
    root = Path(configured).resolve()
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


@pytest.fixture()
def cli_env(starlink_root: Path, tmp_path: Path) -> dict[str, str]:
    adam = tmp_path / "CLI ADAM state"
    star_temp = tmp_path / "CLI Starlink temp"
    adam.mkdir()
    star_temp.mkdir()
    return configure_session_environment(
        capture_starlink_environment(starlink_root),
        adam,
        star_temp,
    )


def direct_cli_result(
    env: dict[str, str],
    application: str,
    arguments: list[str],
    result_names: tuple[str, ...],
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, str]]:
    parameter_file = Path(env["ADAM_USER"]) / f"{application}.sdf"
    parameter_file.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(Path(env["KAPPA_DIR"]) / application), *arguments],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        pytest.fail(
            f"direct {application} failed with {completed.returncode}:\n"
            f"stdout={completed.stdout.decode('utf-8', 'replace')}\n"
            f"stderr={completed.stderr.decode('utf-8', 'replace')}"
        )
    values: dict[str, str] = {}
    for name in result_names:
        parget = subprocess.run(
            [
                str(Path(env["KAPPA_DIR"]) / "parget"),
                f"parname={name}",
                f"applic={application}",
                "vector=yes",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        values[name] = parget.stdout.decode("utf-8", "replace").strip()
    parameter_file.unlink(missing_ok=True)
    return completed, values


def test_cli_and_wrapper_header_and_statistics_match(
    sample_ndf: Path,
    cli_env: dict[str, str],
):
    _, cli_header = direct_cli_result(
        cli_env,
        "fitsval",
        [str(sample_ndf), "OBJECT"],
        ("value",),
    )
    wrapper_header = kappa.fitsval(str(sample_ndf), "OBJECT")
    assert cli_header["value"].strip("'") == wrapper_header.value

    _, cli_stats = direct_cli_result(
        cli_env,
        "stats",
        [str(sample_ndf)],
        ("mean", "sigma", "minimum", "maximum", "numgood", "numbad"),
    )
    wrapper_stats = kappa.stats(str(sample_ndf))
    assert float(cli_stats["mean"]) == pytest.approx(wrapper_stats.mean)
    assert float(cli_stats["sigma"]) == pytest.approx(wrapper_stats.sigma)
    assert float(cli_stats["minimum"]) == pytest.approx(wrapper_stats.minimum)
    assert float(cli_stats["maximum"]) == pytest.approx(wrapper_stats.maximum)
    assert int(cli_stats["numgood"]) == wrapper_stats.numgood
    assert int(cli_stats["numbad"]) == wrapper_stats.numbad


def test_cli_and_wrapper_ndf_outputs_are_exact(
    sample_ndf: Path,
    cli_env: dict[str, str],
    tmp_path: Path,
):
    input_with_space = tmp_path / "input sample.sdf"
    input_with_space.symlink_to(sample_ndf)
    cli_output = tmp_path / "CLI output with spaces"
    wrapper_output = tmp_path / "wrapper output with spaces"

    direct_cli_result(
        cli_env,
        "cadd",
        [
            f'in="{input_with_space}"',
            "scalar=2.5",
            f'out="{cli_output}"',
        ],
        (),
    )
    kappa.cadd(
        str(input_with_space),
        2.5,
        str(wrapper_output),
        _starlink_timeout=60,
    )
    comparison = kappa.ndfcompare(
        str(cli_output),
        str(wrapper_output),
        accdat="0",
        accvar="0",
        accpos=0.0,
        nbad="0",
        _starlink_timeout=60,
    )
    assert comparison.similar is True


def test_real_invalid_parameter_has_structured_diagnostics(sample_ndf: Path):
    with pytest.raises(wrapper.StarlinkCommandError) as caught:
        kappa.stats(
            str(sample_ndf),
            definitely_not_a_parameter=1,
            _starlink_timeout=60,
        )
    error = caught.value
    assert error.returncode
    assert error.argv
    assert error.stdout or error.stderr
    assert Path(error.adam_dir).is_absolute()
    assert not (Path(error.adam_dir) / "stats.sdf").exists()


def test_real_command_survives_chdir_and_repetition(
    sample_ndf: Path,
    tmp_path: Path,
):
    original = Path.cwd()
    os.chdir(tmp_path)
    try:
        for _ in range(10):
            result = kappa.fitsval(str(sample_ndf), "OBJECT")
            assert result.value
            assert not (Path(wrapper.adamdir) / "fitsval.sdf").exists()
    finally:
        os.chdir(original)


def test_independent_python_processes_do_not_share_adam_state(
    starlink_root: Path,
    sample_ndf: Path,
):
    code = (
        "from starlink import kappa,wrapper;"
        f"r=kappa.fitsval({str(sample_ndf)!r},'OBJECT');"
        "print(wrapper.adamdir);print(r.value)"
    )
    environment = dict(os.environ)
    environment["STARLINK_DIR"] = str(starlink_root)

    def run_process() -> list[str]:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return completed.stdout.strip().splitlines()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: run_process(), range(2)))
    assert len(first) == 2
    assert len(second) == 2
    assert first[0] != second[0]
    assert first[1] == second[1]
