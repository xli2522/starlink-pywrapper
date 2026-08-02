#!/usr/bin/env python3
"""Portable paired CLI/public-wrapper POL-2 Tutorial 1 orchestrator."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verify_pol2_raw_inputs import verify_raw_inputs
try:
    from ._scratch import ShortScratch
except ImportError:
    from _scratch import ShortScratch


class ChildFailed(RuntimeError):
    """A child command failed after its output and result were preserved."""

    def __init__(self, record: dict[str, object]) -> None:
        self.record = record
        super().__init__(
            f"{record['name']} failed with status {record['returncode']}"
        )


def git_identity(checkout: Path) -> dict[str, object]:
    result = {"commit": None, "dirty": None}
    try:
        commit = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            check=False,
        )
        status = subprocess.run(
            ["git", "-C", str(checkout), "status", "--porcelain"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            check=False,
        )
    except OSError:
        return result
    if commit.returncode == 0:
        result["commit"] = commit.stdout.strip()
    if status.returncode == 0:
        result["dirty"] = bool(status.stdout.strip())
    return result


def terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait()


def _log_stem(label: str) -> str:
    return "".join(
        character if character.isalnum() else "-" for character in label.lower()
    ).strip("-")


def _tee(source, destination, mirror) -> None:
    try:
        for line in source:
            destination.write(line)
            destination.flush()
            mirror.write(line)
            mirror.flush()
    finally:
        source.close()


def run_child(
    label: str,
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_dir: Path,
) -> dict[str, object]:
    print(f"\n== {label} ==")
    print(" ".join(argv))
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = _log_stem(label)
    stdout_path = log_dir / f"{stem}.stdout.log"
    stderr_path = log_dir / f"{stem}.stderr.log"
    result_path = log_dir / f"{stem}.result.json"
    started = time.monotonic()
    with stdout_path.open("w", encoding="utf-8") as stdout_log, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_log:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        pumps = (
            threading.Thread(
                target=_tee,
                args=(process.stdout, stdout_log, sys.stdout),
                daemon=True,
            ),
            threading.Thread(
                target=_tee,
                args=(process.stderr, stderr_log, sys.stderr),
                daemon=True,
            ),
        )
        for pump in pumps:
            pump.start()
        try:
            returncode = process.wait()
        except BaseException:
            terminate(process)
            raise
        finally:
            for pump in pumps:
                pump.join()

    record = {
        "name": label,
        "argv": argv,
        "returncode": returncode,
        "seconds": time.monotonic() - started,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }
    result_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if returncode:
        raise ChildFailed(record)
    return record


def new_run_root(raw_dir: Path, requested: Path) -> Path:
    raw_dir = raw_dir.resolve(strict=True)
    parent = requested.expanduser().absolute().parent.resolve(strict=True)
    run_root = parent / requested.name
    if run_root.exists():
        raise RuntimeError(f"run root already exists: {run_root}")
    if (
        run_root == raw_dir
        or run_root in raw_dir.parents
        or raw_dir in run_root.parents
    ):
        raise RuntimeError("raw and run trees must be disjoint")
    run_root.mkdir()
    return run_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("starlink_dir", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument(
        "--manifest", type=Path,
        default=Path(__file__).with_name("tutorial1_raw_sha256.txt"),
    )
    parser.add_argument(
        "--order", choices=("cli-first", "wrapper-first"), default="cli-first"
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--expected-commit")
    parser.add_argument("--alias-root", type=Path)
    args = parser.parse_args(argv)

    raw_dir = args.raw_dir.resolve(strict=True)
    manifest = args.manifest.resolve(strict=True)
    starlink_dir = args.starlink_dir.resolve(strict=True)
    python = args.python.resolve(strict=True)
    verify_report = verify_raw_inputs(raw_dir, manifest)
    identity = git_identity(REPOSITORY_ROOT)
    if args.release_gate:
        if not args.expected_commit:
            raise RuntimeError("--release-gate requires --expected-commit")
        if identity["commit"] != args.expected_commit or identity["dirty"] is not False:
            raise RuntimeError(
                "release gate requires the exact clean expected checkout"
            )
    if args.validate_only:
        print(json.dumps({
            "git": identity,
            "raw": verify_report,
            "starlink": str(starlink_dir),
            "python": str(python),
            "order": args.order,
        }, indent=2, sort_keys=True))
        return 0

    run_root = new_run_root(raw_dir, args.run_root)
    (run_root / "raw_input_verification.json").write_text(
        json.dumps(verify_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    cli = run_root / "cli"
    wrapped = run_root / "wrapper"
    comparison = run_root / "comparison"
    child_logs = run_root / "orchestration-logs"
    orchestration = {
        "schema_version": 2,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "git": identity,
        "raw_dir": str(raw_dir),
        "run_root": str(run_root),
        "starlink_dir": str(starlink_dir),
        "python": str(python),
        "order": args.order,
        "environment_limits": {
            name: os.environ.get(name)
            for name in (
                "SMURF_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
                "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
            )
        },
        "steps": [],
    }
    env = os.environ.copy()
    for name in (
        "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        env.setdefault(name, "1")
    env.setdefault("SMURF_THREADS", "1")
    cli_command = [
        str(python), str(Path(__file__).with_name("run_cli_reference.py")),
        str(raw_dir), str(cli), str(starlink_dir), "--manifest", str(manifest),
    ]
    wrapper_command = [
        str(python), str(Path(__file__).with_name("run_python_wrapper.py")),
        str(raw_dir), str(wrapped), str(starlink_dir), "--manifest", str(manifest),
    ]
    ordered = (
        (("direct CLI reduction", cli_command), ("public wrapper reduction", wrapper_command))
        if args.order == "cli-first"
        else (("public wrapper reduction", wrapper_command), ("direct CLI reduction", cli_command))
    )
    try:
        with ShortScratch(
            run_root,
            alias_root=args.alias_root,
        ) as scratch:
            env.update(scratch.environment())
            orchestration["scratch"] = {
                "physical": str(scratch.physical),
                "visible": str(scratch.visible),
                "short_alias_used": scratch.alias is not None,
            }
            for label, command in ordered:
                orchestration["steps"].append(
                    run_child(
                        label,
                        command,
                        cwd=REPOSITORY_ROOT,
                        env=env,
                        log_dir=child_logs,
                    )
                )
        comparison.mkdir()
        commands = (
            (
                "semantic NDF comparison",
                [str(python), str(SCRIPTS_DIR / "compare_ndf_products.py"),
                 str(cli), str(wrapped), str(starlink_dir),
                 str(comparison / "ndf")],
            ),
            (
                "catalogue comparison",
                [str(python), str(SCRIPTS_DIR / "compare_pol_catalogues.py"),
                 str(cli), str(wrapped),
                 str(comparison / "catalogue_comparison.json")],
            ),
            (
                "performance summary",
                [str(python), str(SCRIPTS_DIR / "summarize_pol2_performance.py"),
                 "--run-order", args.order, str(cli), str(wrapped),
                 str(comparison / "performance.json")],
            ),
        )
        for label, command in commands:
            orchestration["steps"].append(
                run_child(
                    label,
                    command,
                    cwd=REPOSITORY_ROOT,
                    env=env,
                    log_dir=child_logs,
                )
            )
        evidence_env = {
            **env,
            "STARLINK_POL2_CLI_OUTPUT": str(cli),
            "STARLINK_POL2_WRAPPER_OUTPUT": str(wrapped),
            "STARLINK_POL2_COMPARISON_DIR": str(comparison),
        }
        evidence_command = [
            str(python), "-m", "pytest", "-q", "-m", "pol2_tutorial",
            str(Path(__file__).with_name("test_tutorial_outputs.py")),
        ]
        orchestration["steps"].append(
            run_child(
                "paired evidence pytest",
                evidence_command,
                cwd=REPOSITORY_ROOT,
                env=evidence_env,
                log_dir=child_logs,
            )
        )
    except BaseException as error:
        if isinstance(error, ChildFailed):
            steps = orchestration["steps"]
            assert isinstance(steps, list)
            steps.append(error.record)
        orchestration["finished_utc"] = datetime.now(timezone.utc).isoformat()
        orchestration["outcome"] = "incomplete"
        (run_root / "orchestration.json").write_text(
            json.dumps(orchestration, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise

    orchestration["finished_utc"] = datetime.now(timezone.utc).isoformat()
    orchestration["outcome"] = "passed"
    (run_root / "orchestration.json").write_text(
        json.dumps(orchestration, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_root / "POL2_PAIR_COMPLETE").write_text(
        "Official JCMT POL-2 Tutorial 1 paired validation completed.\n"
        f"Repository commit: {identity['commit']}\n"
        f"CLI output: {cli}\nWrapper output: {wrapped}\n"
        f"Comparison output: {comparison}\n",
        encoding="utf-8",
    )
    print(run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
