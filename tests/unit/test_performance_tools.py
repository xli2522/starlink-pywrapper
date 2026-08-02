from __future__ import annotations

import json
from pathlib import Path
import signal
from types import SimpleNamespace
from unittest import mock

import pytest

from scripts.monitor_process_tree import descendants, load_summary
from scripts import summarize_pol2_performance as performance
from tests.integration.pol2 import run_python_wrapper as wrapper_runner


def usage(
    *,
    user: float,
    system: float,
    rss: int,
    inputs: int,
    outputs: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        ru_utime=user,
        ru_stime=system,
        ru_maxrss=rss,
        ru_inblock=inputs,
        ru_oublock=outputs,
    )


def test_wrapper_capture_records_child_filesystem_io(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    before = usage(user=1.0, system=2.0, rss=100, inputs=3, outputs=4)
    after = usage(user=2.5, system=2.75, rss=250, inputs=10, outputs=16)

    with mock.patch.object(
        wrapper_runner.resource, "getrusage", side_effect=(before, after)
    ), mock.patch.object(
        wrapper_runner.time, "monotonic", side_effect=(20.0, 23.0)
    ), mock.patch.object(
        wrapper_runner.time, "process_time", side_effect=(5.0, 5.25)
    ):
        record = wrapper_runner.capture_call(
            "example",
            logs,
            lambda: (None, "stdout", "stderr"),
        )

    assert record["child_filesystem_inputs"] == 7
    assert record["child_filesystem_outputs"] == 12
    assert record["child_user_seconds"] == pytest.approx(1.5)
    assert record["child_system_seconds"] == pytest.approx(0.75)
    assert record["child_maxrss_kib_after"] == 250


def test_descendants_follows_transitive_process_tree():
    parents = {10: 1, 11: 10, 12: 11, 20: 1}
    assert descendants(10, parents) == {10, 11, 12}


def test_load_summary_records_each_machine_load_window():
    summary = load_summary([(0.5, 1.0, 1.5), (1.5, 2.0, 2.5)])

    assert summary["sample_count"] == 2
    assert summary["one_minute"] == {
        "minimum": 0.5,
        "maximum": 1.5,
        "mean": 1.0,
    }
    assert summary["fifteen_minutes"]["mean"] == 2.0


def test_wrapper_runner_routes_sigterm_through_child_cleanup():
    with pytest.raises(KeyboardInterrupt, match="received signal"):
        wrapper_runner._interrupt_as_keyboard_interrupt(signal.SIGTERM, None)


def write_time_report(path: Path, elapsed: str = "0:10.00") -> None:
    path.write_text(
        "Command being timed: \"example\"\n"
        "User time (seconds): 1.0\n"
        "System time (seconds): 0.5\n"
        f"Elapsed (wall clock) time (h:mm:ss or m:ss): {elapsed}\n"
        "Maximum resident set size (kbytes): 1024\n"
        "File system inputs: 2\n"
        "File system outputs: 3\n"
        "Exit status: 0\n",
        encoding="utf-8",
    )


def make_performance_evidence(root: Path) -> tuple[Path, Path]:
    cli = root / "cli"
    wrapper = root / "wrapper"
    (cli / "metadata").mkdir(parents=True)
    (wrapper / "metadata").mkdir(parents=True)

    wrapper_calls = [
        {
            "name": f"call-{index}",
            "wall_seconds": 10.1,
            "python_cpu_seconds": 0.01,
            "child_user_seconds": 1.0,
            "child_system_seconds": 0.5,
            "child_maxrss_kib_after": 2048,
            "child_filesystem_inputs": 4,
            "child_filesystem_outputs": 6,
        }
        for index in range(5)
    ]
    cli_calls = [
        {
            "name": f"call-{index}",
            "wall_seconds": 10.0,
            "child_user_seconds": 1.0,
            "child_system_seconds": 0.5,
            "child_maxrss_kib_after": 1024,
            "child_filesystem_inputs": 2,
            "child_filesystem_outputs": 3,
            "returncode": 0,
        }
        for index in range(5)
    ]
    (cli / "metadata" / "timings.json").write_text(
        json.dumps(cli_calls), encoding="utf-8"
    )
    (wrapper / "metadata" / "timings.json").write_text(
        json.dumps(wrapper_calls),
        encoding="utf-8",
    )
    tree = {
        "schema_version": 1,
        "root_pid": 123,
        "sampling_interval_seconds": 0.1,
        "samples": 2,
        "maximum_processes_including_worker": 3,
        "maximum_descendants": 2,
        "maximum_tree_rss_kib": 4096,
        "machine_load": {
            "sample_count": 2,
            "one_minute": {
                "minimum": 0.5,
                "maximum": 0.75,
                "mean": 0.625,
            },
            "five_minutes": {
                "minimum": 1.0,
                "maximum": 1.25,
                "mean": 1.125,
            },
            "fifteen_minutes": {
                "minimum": 1.5,
                "maximum": 1.75,
                "mean": 1.625,
            },
        },
        "started_unix": 1.0,
        "finished_unix": 2.0,
        "final_status": "exit:0",
        "monitor_pid": 124,
    }
    for output in (cli, wrapper):
        (output / "metadata" / "process_tree.json").write_text(
            json.dumps(tree),
            encoding="utf-8",
        )
    (cli / "map.sdf").write_bytes(b"cli")
    (wrapper / "map.sdf").write_bytes(b"wrapper")
    return cli, wrapper


def test_performance_summary_parses_portable_json_and_wrapper_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cli, wrapper = make_performance_evidence(tmp_path)
    output = tmp_path / "performance.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "summarize_pol2_performance.py",
            "--run-order",
            "wrapper-first",
            str(cli),
            str(wrapper),
            str(output),
        ],
    )

    assert performance.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["cli"]["wall_seconds"] == pytest.approx(50.0)
    assert report["cli"]["filesystem_inputs"] == 10
    assert report["wrapper"]["filesystem_inputs"] == 20
    assert report["wrapper"]["filesystem_outputs"] == 30
    assert report["wrapper"]["maximum_child_rss_kib"] == 2048
    assert report["cli"]["scientific_product_bytes"] == 3
    assert report["wrapper"]["scientific_product_bytes"] == 7
    assert report["run_order"] == "wrapper-first"
    assert "CLI ran second" in report["cache_context"]
    assert report["acceptance_bound_passed"] is True


def test_performance_summary_rejects_incomplete_timing_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cli, wrapper = make_performance_evidence(tmp_path)
    (cli / "metadata/timings.json").write_text(
        json.dumps([{"wall_seconds": 1.0}]), encoding="utf-8"
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "summarize_pol2_performance.py",
            str(cli),
            str(wrapper),
            str(tmp_path / "performance.json"),
        ],
    )

    with pytest.raises(RuntimeError, match="expected five timing records"):
        performance.main()
