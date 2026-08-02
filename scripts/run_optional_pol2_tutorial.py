#!/usr/bin/env python3
"""Run the opt-in, self-preparing full JCMT POL-2 developer validation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import traceback
from typing import Sequence

from prepare_pol2_tutorial_data import PreparationError, is_within, prepare_data


COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
STARLINK_RELEASE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])2025A(?![A-Za-z0-9])"
)
PATCH1_MARKER = Path("include/star/hds_types.h")
PATCH1_MARKER_SHA256 = (
    "91b6a51f982af54847a3761768f5ccdbf130aa295b4a9bf9a353ecf628d525c1"
)
REQUIRED_STARLINK_APPLICATIONS = (
    Path("bin/kappa/fitsval"),
    Path("bin/kappa/ndfcompare"),
    Path("bin/kappa/ndftrace"),
    Path("bin/kappa/parget"),
    Path("bin/kappa/stats"),
    Path("bin/polpack/poledit"),
    Path("bin/smurf/pol2map.py"),
)


class OptionalValidationError(RuntimeError):
    """An optional validation prerequisite or step failed."""


class StepFailed(OptionalValidationError):
    """A subprocess step failed after producing recordable evidence."""

    def __init__(self, name: str, result: dict[str, object]) -> None:
        super().__init__(
            f"{name} failed with status {result['returncode']}"
        )
        self.result = result


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_capture(argv: Sequence[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise OptionalValidationError(
            f"command failed ({completed.returncode}): {shlex.join(argv)}"
            + (f"\n{detail}" if detail else "")
        )
    return completed.stdout.strip()


def run_step(
    name: str,
    argv: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, object]:
    command = list(argv)
    print(f"\n== {name} ==")
    print(shlex.join(command))
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
    )
    result = {
        "name": name,
        "argv": command,
        "returncode": completed.returncode,
        "seconds": round(time.monotonic() - started, 3),
    }
    if completed.returncode != 0:
        raise StepFailed(name, result)
    return result


def write_new_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def validate_checkout(checkout: Path, expected_commit: str) -> str:
    checkout = checkout.expanduser().resolve(strict=True)
    if COMMIT_PATTERN.fullmatch(expected_commit) is None:
        raise OptionalValidationError(
            "--expected-commit must be exactly 40 lowercase hexadecimal characters"
        )
    actual = run_capture(["git", "-C", str(checkout), "rev-parse", "HEAD"])
    if actual != expected_commit:
        raise OptionalValidationError(
            f"checkout commit is {actual}; expected {expected_commit}"
        )
    if run_capture(["git", "-C", str(checkout), "status", "--porcelain"]):
        raise OptionalValidationError("candidate checkout must be clean")
    return actual


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_starlink(
    starlink_dir: Path,
    *,
    expected_patch1_sha256: str = PATCH1_MARKER_SHA256,
) -> dict[str, object]:
    try:
        root = starlink_dir.expanduser().resolve(strict=True)
    except OSError as error:
        raise OptionalValidationError(
            f"Starlink installation is unavailable: {starlink_dir}"
        ) from error
    if not root.is_dir():
        raise OptionalValidationError(
            f"Starlink installation is not a directory: {root}"
        )

    profile = root / "etc/profile"
    manifest = root / "manifests/starlink.version"
    marker = root / PATCH1_MARKER
    for label, path in (
        ("profile", profile),
        ("release manifest", manifest),
        ("Patch 1 marker", marker),
    ):
        if not path.is_file():
            raise OptionalValidationError(
                f"Starlink {label} is missing: {path}"
            )

    manifest_text = manifest.read_text(encoding="utf-8", errors="replace")
    if STARLINK_RELEASE_PATTERN.search(manifest_text) is None:
        raise OptionalValidationError(
            f"Starlink release manifest does not identify 2025A: {manifest}"
        )

    marker_sha256 = file_sha256(marker)
    if marker_sha256 != expected_patch1_sha256:
        raise OptionalValidationError(
            "Starlink installation does not match the verified 2025A "
            f"Errata Patch 1 marker: {marker} has SHA-256 {marker_sha256}"
        )

    missing = [
        str(root / relative)
        for relative in REQUIRED_STARLINK_APPLICATIONS
        if not (root / relative).is_file()
        or not os.access(root / relative, os.X_OK)
    ]
    if missing:
        raise OptionalValidationError(
            "Starlink installation is missing required executable(s): "
            + ", ".join(missing)
        )

    return {
        "directory": str(root),
        "release": "2025A",
        "release_manifest": str(manifest),
        "release_manifest_sha256": file_sha256(manifest),
        "patch": "Errata Patch 1",
        "patch_marker": str(marker),
        "patch_marker_sha256": marker_sha256,
        "required_applications": [
            str(relative) for relative in REQUIRED_STARLINK_APPLICATIONS
        ],
    }


def resolve_starlink(
    requested: str,
    *,
    environment: dict[str, str] | None = None,
    which=shutil.which,
    expected_patch1_sha256: str = PATCH1_MARKER_SHA256,
) -> tuple[Path, dict[str, object]]:
    environment = os.environ if environment is None else environment
    candidates: list[tuple[str, Path]] = []
    if requested != "auto":
        candidates.append(("command-line argument", Path(requested)))
    else:
        configured = environment.get("STARLINK_DIR")
        if configured:
            candidates.append(("STARLINK_DIR", Path(configured)))
        parget = which("parget", path=environment.get("PATH"))
        if parget:
            parget_path = Path(parget).expanduser().resolve(strict=False)
            if (
                parget_path.name == "parget"
                and parget_path.parent.name == "kappa"
                and parget_path.parent.parent.name == "bin"
            ):
                candidates.append(("parget on PATH", parget_path.parents[2]))

    if not candidates:
        raise OptionalValidationError(
            "no existing Starlink installation was found; set STARLINK_DIR, "
            "put Starlink KAPPA parget on PATH, or pass an explicit path"
        )

    failures = []
    seen: set[Path] = set()
    for source, candidate in candidates:
        normalized = candidate.expanduser().absolute()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            validation = validate_starlink(
                candidate,
                expected_patch1_sha256=expected_patch1_sha256,
            )
        except (OSError, OptionalValidationError) as error:
            failures.append(f"{source}: {error}")
            continue
        validation["discovered_from"] = source
        return Path(str(validation["directory"])), validation

    raise OptionalValidationError(
        "no accessible Starlink 2025A Errata Patch 1 installation passed "
        "preflight (" + "; ".join(failures) + ")"
    )


def outcome_exit_code(outcome: str, strict: bool) -> int:
    if outcome == "passed":
        return 0
    return 1 if strict else 0


def outcome_banner(outcome: str, strict: bool) -> str:
    if outcome == "passed":
        return "PASSED"
    return "INCOMPLETE (fatal)" if strict else "INCOMPLETE (non-fatal)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Opt-in developer validation: obtain the frozen official POL-2 "
            "data, run bounded Python and Starlink smoke tests, then execute "
            "the complete CLI/wrapper reduction and comparison. Failures are "
            "reported but non-fatal unless --strict is supplied."
        )
    )
    parser.add_argument("workspace", type=Path)
    parser.add_argument(
        "starlink_dir",
        help=(
            "existing Starlink installation path, or 'auto' to use "
            "STARLINK_DIR / KAPPA parget on PATH; never installs Starlink"
        ),
    )
    parser.add_argument(
        "--python", type=Path, default=Path(sys.executable),
        help="Python executable; defaults to the current interpreter",
    )
    parser.add_argument(
        "--checkout",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--expected-commit")
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument(
        "--order",
        choices=("cli-first", "wrapper-first"),
        default="cli-first",
    )
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--strict", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    started_utc = utc_now()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    checkout = args.checkout.expanduser().resolve(strict=True)
    workspace = args.workspace.expanduser().absolute()
    if is_within(workspace, checkout) or is_within(checkout, workspace):
        print(
            "Optional POL-2 validation refused: workspace and checkout "
            "must be disjoint",
            file=sys.stderr,
        )
        return 2
    workspace.mkdir(parents=True, exist_ok=True)
    workspace = workspace.resolve(strict=True)
    try:
        discovered_commit = run_capture(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"]
        )
    except OptionalValidationError:
        discovered_commit = None
    if args.release_gate and not args.expected_commit:
        print(
            "Optional POL-2 validation refused: --release-gate requires "
            "--expected-commit",
            file=sys.stderr,
        )
        return 2
    candidate_label = (
        args.expected_commit or discovered_commit or "nogit"
    )[:7]


    run_root = (
        args.run_root.expanduser().absolute()
        if args.run_root is not None
        else workspace
        / "runs"
        / f"pol2-{args.order}-{candidate_label}-{timestamp}"
    )
    run_root.parent.mkdir(parents=True, exist_ok=True)
    run_root = run_root.parent.resolve(strict=True) / run_root.name
    if not is_within(run_root, workspace):
        print(
            "Optional POL-2 validation refused: run root must be inside "
            "the external workspace",
            file=sys.stderr,
        )
        return 2
    if run_root.exists():
        print(
            f"Optional POL-2 validation refused: run root exists: {run_root}",
            file=sys.stderr,
        )
        return 2

    report_path = (
        workspace
        / "reports"
        / f"{run_root.name}-optional-validation.json"
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "started_utc": started_utc,
        "finished_utc": None,
        "outcome": "incomplete",
        "strict": args.strict,
        "non_fatal_default": True,
        "checkout": str(checkout),
        "expected_commit": args.expected_commit,
        "actual_commit": discovered_commit,
        "workspace": str(workspace),
        "run_root": str(run_root),
        "requested_starlink_dir": args.starlink_dir,
        "starlink_validation": None,
        "python_executable": str(args.python.expanduser().absolute()),
        "order": args.order,
        "data": None,
        "steps": [],
        "error": None,
    }

    try:
        if args.release_gate:
            report["actual_commit"] = validate_checkout(
                checkout, args.expected_commit
            )
        starlink_dir, starlink_validation = resolve_starlink(
            args.starlink_dir
        )
        report["starlink_validation"] = starlink_validation
        python_executable = args.python.expanduser().resolve(
            strict=True
        )
        if not python_executable.is_file() or not os.access(
            python_executable, os.X_OK
        ):
            raise OptionalValidationError(
                f"Python executable is unavailable: {python_executable}"
            )

        data_started = time.monotonic()
        data_report = prepare_data(workspace, checkout)
        data_report["seconds"] = round(time.monotonic() - data_started, 3)
        report["data"] = data_report
        raw_dir = Path(str(data_report["raw_directory"]))

        env = {
            **os.environ,
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "SMURF_THREADS": os.environ.get("SMURF_THREADS", "1"),
        }
        steps = report["steps"]
        assert isinstance(steps, list)
        steps.append(
            run_step(
                "unit and generator tests",
                [
                    str(python_executable),
                    "-m",
                    "pytest",
                    "-q",
                    "tests/unit",
                    "tests/generator",
                ],
                cwd=checkout,
                env=env,
            )
        )
        smoke_env = {
            **env,
            "STARLINK_TEST_DIR": str(starlink_dir),
        }
        steps.append(
            run_step(
                "Starlink smoke tests",
                [
                    str(python_executable),
                    "-m",
                    "pytest",
                    "-q",
                    "-m",
                    "starlink_smoke",
                ],
                cwd=checkout,
                env=smoke_env,
            )
        )
        runner = checkout / "tests/integration/pol2/run_paired_validation.py"
        paired_command = [
            str(python_executable),
            str(runner),
            str(raw_dir),
            str(run_root),
            str(starlink_dir),
            "--python",
            str(python_executable),
            "--order",
            args.order,
        ]
        if args.release_gate:
            paired_command.extend(
                [
                    "--release-gate",
                    "--expected-commit",
                    args.expected_commit,
                ]
            )
        steps.append(
            run_step(
                "paired POL-2 Tutorial 1 validation",
                paired_command,
                cwd=checkout,
                env=env,
            )
        )
        if not (run_root / "POL2_PAIR_COMPLETE").is_file():
            raise OptionalValidationError(
                "paired runner returned success without POL2_PAIR_COMPLETE"
            )
        report["outcome"] = "passed"
    except KeyboardInterrupt:
        report["outcome"] = "interrupted"
        report["error"] = "operator interrupted validation"
        report["finished_utc"] = utc_now()
        write_new_json(report_path, report)
        print(f"Validation interrupted; report: {report_path}", file=sys.stderr)
        return 130
    except (
        OSError,
        OptionalValidationError,
        PreparationError,
        subprocess.SubprocessError,
    ) as error:
        if isinstance(error, StepFailed):
            steps = report["steps"]
            assert isinstance(steps, list)
            steps.append(error.result)
        report["outcome"] = "incomplete"
        report["error"] = {
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }

    report["finished_utc"] = utc_now()
    write_new_json(report_path, report)
    outcome = str(report["outcome"])
    banner = outcome_banner(outcome, args.strict)
    print(f"\nOPTIONAL POL-2 VALIDATION: {banner}")
    print(f"Outcome report: {report_path}")
    if report["error"] is not None:
        error = report["error"]
        assert isinstance(error, dict)
        print(f"Reason: {error['message']}", file=sys.stderr)
    return outcome_exit_code(outcome, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
