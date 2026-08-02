from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import sys
from types import SimpleNamespace

import pytest

from starlink import wrapper
from tests.integration.pol2._scratch import (
    ADAM_PATH_LIMIT,
    PREDICTED_SUFFIX,
    ShortScratch,
)
from tests.integration.pol2 import run_paired_validation as paired
from tests.integration.pol2 import run_python_wrapper


def write_manifest(raw: Path, manifest: Path, count: int = 3) -> None:
    lines = []
    for index in range(count):
        path = raw / f"input-{index}.sdf"
        path.write_bytes(f"input-{index}".encode())
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    manifest.write_text("".join(lines), encoding="utf-8")


def test_short_scratch_aliases_long_workspace_and_cleans_everything(tmp_path):
    workspace = tmp_path / ("long-workspace-" + "x" * 100)
    workspace.mkdir()
    with ShortScratch(workspace) as scratch:
        assert scratch.physical is not None
        assert workspace in scratch.physical.parents
        assert scratch.alias is not None
        assert scratch.alias.is_symlink()
        assert len(str(scratch.visible / PREDICTED_SUFFIX)) <= ADAM_PATH_LIMIT
        physical = scratch.physical
        alias = scratch.alias
        (scratch.visible / "owned.txt").write_text("owned", encoding="utf-8")
    assert not alias.exists()
    assert not physical.exists()


def test_short_scratch_cleans_after_interrupt(tmp_path):
    workspace = tmp_path / ("interrupt-workspace-" + "x" * 90)
    workspace.mkdir()
    physical = alias = None
    with pytest.raises(KeyboardInterrupt):
        with ShortScratch(workspace) as scratch:
            physical, alias = scratch.physical, scratch.alias
            raise KeyboardInterrupt
    assert physical is not None and not physical.exists()
    if alias is not None:
        assert not alias.exists()


@pytest.mark.parametrize(
    ("order", "expected"),
    (
        ("cli-first", ["direct CLI reduction", "public wrapper reduction"]),
        ("wrapper-first", ["public wrapper reduction", "direct CLI reduction"]),
    ),
)
def test_portable_pair_runs_both_orders_without_resource_manager_requirements(
    tmp_path, monkeypatch, order, expected
):
    raw = tmp_path / "raw"
    raw.mkdir()
    manifest = tmp_path / "manifest.txt"
    write_manifest(raw, manifest)
    starlink = tmp_path / "starlink"
    starlink.mkdir()
    run_parent = tmp_path / "runs"
    run_parent.mkdir()
    labels = []

    monkeypatch.setattr(
        paired, "verify_raw_inputs",
        lambda *_args, **_kwargs: {"all_inputs_match": True, "file_count": 3},
    )
    monkeypatch.setattr(
        paired, "git_identity",
        lambda _checkout: {"commit": "a" * 40, "dirty": False},
    )

    def fake_run(label, argv, **kwargs):
        labels.append(label)
        return {
            "name": label, "argv": argv, "returncode": 0, "seconds": 0.01
        }

    monkeypatch.setattr(paired, "run_child", fake_run)
    result = paired.main([
        str(raw),
        str(run_parent / "pair"),
        str(starlink),
        "--manifest", str(manifest),
        "--order", order,
    ])

    assert result == 0
    assert labels[:2] == expected
    assert labels[2:] == [
        "semantic NDF comparison",
        "catalogue comparison",
        "performance summary",
        "paired evidence pytest",
    ]
    assert (run_parent / "pair/POL2_PAIR_COMPLETE").is_file()
    record = json.loads(
        (run_parent / "pair/orchestration.json").read_text(encoding="utf-8")
    )
    assert record["outcome"] == "passed"
    assert record["environment_limits"]["SMURF_THREADS"] == os.environ.get(
        "SMURF_THREADS"
    )


def test_release_gate_requires_exact_clean_identity(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    manifest = tmp_path / "manifest.txt"
    write_manifest(raw, manifest)
    starlink = tmp_path / "starlink"
    starlink.mkdir()
    monkeypatch.setattr(
        paired, "verify_raw_inputs",
        lambda *_args, **_kwargs: {"all_inputs_match": True},
    )
    monkeypatch.setattr(
        paired, "git_identity",
        lambda _checkout: {"commit": "b" * 40, "dirty": True},
    )
    with pytest.raises(RuntimeError, match="exact clean"):
        paired.main([
            str(raw), str(tmp_path / "run"), str(starlink),
            "--manifest", str(manifest),
            "--release-gate", "--expected-commit", "a" * 40,
        ])


def test_wrapper_runner_uses_deterministic_failure_and_recovers(
    tmp_path, monkeypatch
):
    output = tmp_path / "wrapper"
    logs = output / "logs"
    logs.mkdir(parents=True)
    sample = tmp_path / "science.sdf"
    sample.touch()
    adam_dir = tmp_path / "adam"
    adam_dir.mkdir()
    calls = []

    def failed_stats(*args, **kwargs):
        calls.append(("stats", args, kwargs))
        raise wrapper.StarlinkCommandError(
            ("/path/to/starlink/bin/kappa/stats", "bad=1"),
            1, "", "Unknown parameter",
            cwd=kwargs["_starlink_cwd"], adam_dir=adam_dir,
        )

    def recovered(*args, **kwargs):
        calls.append(("fitsval", args, kwargs))
        return SimpleNamespace(value="POL")

    monkeypatch.setattr(run_python_wrapper.kappa, "stats", failed_stats)
    monkeypatch.setattr(run_python_wrapper.kappa, "fitsval", recovered)
    run_python_wrapper.verify_failure_and_recovery(sample, output, logs)

    assert [call[0] for call in calls] == ["stats", "fitsval"]
    report = json.loads(
        (logs / "intentional_failure.json").read_text(encoding="utf-8")
    )
    assert report["returncode"] == 1
    assert not (adam_dir / "stats.sdf").exists()


def test_failed_pair_child_preserves_stdout_stderr_and_result(tmp_path):
    logs = tmp_path / "orchestration-logs"
    command = [
        sys.executable,
        "-c",
        (
            "import sys; "
            "print('preserved stdout'); "
            "print('preserved stderr', file=sys.stderr); "
            "raise SystemExit(3)"
        ),
    ]

    with pytest.raises(paired.ChildFailed) as failure:
        paired.run_child(
            "failing child",
            command,
            cwd=tmp_path,
            env=os.environ.copy(),
            log_dir=logs,
        )

    record = failure.value.record
    assert record["returncode"] == 3
    assert (logs / "failing-child.stdout.log").read_text(
        encoding="utf-8"
    ) == "preserved stdout\n"
    assert (logs / "failing-child.stderr.log").read_text(
        encoding="utf-8"
    ) == "preserved stderr\n"
    saved = json.loads(
        (logs / "failing-child.result.json").read_text(encoding="utf-8")
    )
    assert saved == record


def test_pair_termination_kills_process_group():
    process = SimpleNamespace(pid=123, poll=lambda: None)
    process.wait = pytest.fail
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            paired.os, "killpg",
            lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
        )
        paired.terminate(process)
