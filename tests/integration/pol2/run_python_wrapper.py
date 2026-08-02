#!/usr/bin/env python3
"""Run JCMT POL-2 Tutorial 1 through the public wrapper modules."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verify_pol2_raw_inputs import manifest_paths, verify_raw_inputs

from typing import Any, Callable

from starlink import (
    __starlink_source_version__,
    __version__,
    kappa,
    polpack,
    smurf,
    wrapper,
)


HEADER_KEYS = (
    "INBEAM",
    "OBJECT",
    "OBSNUM",
    "SEQ_TYPE",
    "UTDATE",
    "DATE-OBS",
    "DATE-END",
    "SAM_MODE",
)
REQUIRED_NDFS = (
    "iauto.sdf",
    "iext.sdf",
    "qext.sdf",
    "uext.sdf",
    "astmask.sdf",
    "pcamask.sdf",
)
REQUIRED_CATALOGUES = (
    "starlink_cat.FIT",
    "starlink_cat_none.FIT",
    "starlink_cat_as.FIT",
    "starlink_cat_mas.FIT",
)


def _interrupt_as_keyboard_interrupt(
    signum: int, frame: object | None
) -> None:
    """Route orchestration termination through the runner's child cleanup."""

    del frame
    raise KeyboardInterrupt(f"received signal {signum}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def raw_files(raw_dir: Path, manifest: Path) -> list[Path]:
    verify_raw_inputs(raw_dir, manifest)
    return manifest_paths(raw_dir, manifest)


def safe_new_output(raw_dir: Path, requested: Path) -> Path:
    raw_dir = raw_dir.resolve(strict=True)
    parent = requested.expanduser().absolute().parent.resolve(strict=True)
    output = parent / requested.name
    if output.exists():
        raise RuntimeError(f"output must not already exist: {output}")
    if (
        output == raw_dir
        or output in raw_dir.parents
        or raw_dir in output.parents
    ):
        raise RuntimeError(
            f"output and raw trees must be disjoint: raw={raw_dir}, output={output}"
        )
    output.mkdir()
    return output


def json_value(value: Any) -> Any:
    if hasattr(value, "_asdict"):
        return {key: json_value(item) for key, item in value._asdict().items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def capture_call(
    name: str,
    logs: Path,
    function: Callable[[], tuple[object, str, str]],
) -> dict[str, Any]:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started_wall = time.monotonic()
    started_cpu = time.process_time()
    result, stdout, stderr = function()
    elapsed_wall = time.monotonic() - started_wall
    elapsed_python_cpu = time.process_time() - started_cpu
    after = resource.getrusage(resource.RUSAGE_CHILDREN)

    (logs / f"{name}.stdout.log").write_text(stdout, encoding="utf-8")
    (logs / f"{name}.stderr.log").write_text(stderr, encoding="utf-8")
    record = {
        "name": name,
        "wall_seconds": elapsed_wall,
        "python_cpu_seconds": elapsed_python_cpu,
        "child_user_seconds": after.ru_utime - before.ru_utime,
        "child_system_seconds": after.ru_stime - before.ru_stime,
        "child_filesystem_inputs": after.ru_inblock - before.ru_inblock,
        "child_filesystem_outputs": after.ru_oublock - before.ru_oublock,
        "child_maxrss_kib_after": after.ru_maxrss,
        "result": json_value(result),
        "stdout_bytes": len(stdout.encode("utf-8")),
        "stderr_bytes": len(stderr.encode("utf-8")),
    }
    write_json(logs / f"{name}.result.json", record)
    return record


def wrapper_options(output: Path) -> dict[str, object]:
    return {
        "_starlink_cwd": output,
        "_starlink_timeout": 4 * 60 * 60,
        "_starlink_return_stderr": True,
        "returnstdout": True,
    }


def inventory_headers(files: list[Path]) -> dict[str, dict[str, str]]:
    selected = (files[0], files[2], files[-1])
    inventory: dict[str, dict[str, str]] = {}
    for path in selected:
        headers: dict[str, str] = {}
        for key in HEADER_KEYS:
            value = kappa.fitsval(str(path), key, _starlink_timeout=60)
            headers[key] = value.value
        inventory[str(path)] = headers
    science = inventory[str(selected[1])]
    if "pol" not in science["INBEAM"].lower():
        raise RuntimeError(
            f"INBEAM does not identify POL-2 data: {science['INBEAM']!r}"
        )
    if int(science["OBSNUM"]) != 43:
        raise RuntimeError(f"unexpected OBSNUM: {science['OBSNUM']!r}")
    return inventory


def verify_failure_and_recovery(
    sample: Path,
    output: Path,
    logs: Path,
) -> None:
    """Exercise a deterministic ATASK failure, cleanup, and recovery."""

    failure_dir = output / "intentional_failure"
    failure_dir.mkdir()
    try:
        kappa.stats(
            str(sample),
            definitely_not_a_parameter=1,
            _starlink_cwd=failure_dir,
            _starlink_timeout=60,
        )
    except wrapper.StarlinkCommandError as error:
        write_json(
            logs / "intentional_failure.json",
            {
                "type": type(error).__name__,
                "argv": list(error.argv),
                "returncode": error.returncode,
                "stdout": error.stdout,
                "stderr": error.stderr,
                "cwd": error.cwd,
                "adam_dir": error.adam_dir,
            },
        )
        if (Path(error.adam_dir) / "stats.sdf").exists():
            raise RuntimeError(
                "intentional failure left stale stats ADAM state"
            )
    else:
        raise RuntimeError("intentional invalid KAPPA invocation unexpectedly passed")

    recovery = kappa.fitsval(str(sample), "INBEAM", _starlink_timeout=60)
    if "pol" not in recovery.value.lower():
        raise RuntimeError("valid command after intentional failure did not recover")


def main() -> int:
    signal.signal(signal.SIGTERM, _interrupt_as_keyboard_interrupt)
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("starlink_dir", type=Path)
    parser.add_argument(
        "--manifest", type=Path,
        default=Path(__file__).with_name("tutorial1_raw_sha256.txt"),
    )
    args = parser.parse_args()

    raw_dir = args.raw_dir.resolve(strict=True)
    manifest = args.manifest.resolve(strict=True)
    output = safe_new_output(raw_dir, args.output_dir)
    for directory in ("maps", "qudata", "tmp", "logs", "metadata", "checksums"):
        (output / directory).mkdir()
    logs = output / "logs"

    files = raw_files(raw_dir, manifest)
    mylist = "".join(f"{path}\n" for path in files)
    (output / "mylist").write_text(mylist, encoding="utf-8")
    before_hashes = {str(path): sha256(path) for path in files}
    write_json(output / "checksums/raw_before.json", before_hashes)

    wrapper.change_starpath(args.starlink_dir.resolve(strict=True))
    smurf_threads = os.environ.get("SMURF_THREADS", "1")
    if not smurf_threads.isdigit():
        raise RuntimeError("SMURF_THREADS must be a non-negative integer")
    wrapper.env["SMURF_THREADS"] = smurf_threads
    environment_record = {
        "wrapper_version": __version__,
        "generated_starlink_source": __starlink_source_version__,
        "starlink_dir": wrapper.starpath,
        "starlink_version_file": (
            Path(wrapper.starpath) / "manifests/starlink.version"
        ).read_text(encoding="utf-8").splitlines(),
        "adam_user": wrapper.adamdir,
        "star_temp": wrapper.env["STAR_TEMP"],
        "smurf_threads": wrapper.env["SMURF_THREADS"],
        "python": sys.version,
        "executable": sys.executable,
        "platform": sys.platform,
        "raw_dir": str(raw_dir),
        "output_dir": str(output),
        "raw_file_count": len(files),
    }
    write_json(output / "metadata/environment.json", environment_record)
    write_json(output / "metadata/header_inventory.json", inventory_headers(files))

    timings: list[dict[str, Any]] = []
    options = wrapper_options(output)
    timings.append(
        capture_call(
            "pol2map_step1",
            logs,
            lambda: smurf.pol2map(
                in_="^mylist",
                iout="iauto",
                qout="!",
                uout="!",
                mapdir="maps",
                qudir="qudata",
                **options,
            ),
        )
    )
    qu_count = len(list((output / "qudata").glob("*.sdf")))
    if qu_count < 12:
        raise RuntimeError(f"pol2map step 1 produced only {qu_count} qudata files")

    timings.append(
        capture_call(
            "pol2map_step2",
            logs,
            lambda: smurf.pol2map(
                in_="qudata/*",
                iout="iext",
                qout="qext",
                uout="uext",
                mapdir="maps",
                mask="iauto",
                maskout1="astmask",
                maskout2="pcamask",
                ipref="iext",
                cat="starlink_cat",
                debias=True,
                binsize=12,
                **options,
            ),
        )
    )

    for suffix, debias_type in (
        ("none", "none"),
        ("as", "as"),
        ("mas", "mas"),
    ):
        timings.append(
            capture_call(
                f"poledit_{suffix}",
                logs,
                lambda suffix=suffix, debias_type=debias_type: polpack.poledit(
                    "starlink_cat",
                    f"starlink_cat_{suffix}",
                    mode="debias",
                    debiastype=debias_type,
                    **options,
                ),
            )
        )

    for relative in REQUIRED_NDFS + REQUIRED_CATALOGUES:
        if not (output / relative).is_file():
            raise RuntimeError(f"required tutorial product is missing: {relative}")

    verify_failure_and_recovery(files[2], output, logs)

    after_hashes = {str(path): sha256(path) for path in files}
    write_json(output / "checksums/raw_after.json", after_hashes)
    if after_hashes != before_hashes:
        raise RuntimeError("raw tutorial data changed during wrapper reduction")

    products = sorted(
        path
        for path in output.rglob("*")
        if path.is_file() and path.suffix.lower() in {".sdf", ".fit", ".fits"}
    )
    write_json(
        output / "checksums/products.json",
        {str(path.relative_to(output)): sha256(path) for path in products},
    )
    write_json(output / "metadata/timings.json", timings)
    (output / "WRAPPER_COMPLETE").write_text(
        "Official JCMT POL-2 Tutorial 1 wrapper reduction completed.\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
