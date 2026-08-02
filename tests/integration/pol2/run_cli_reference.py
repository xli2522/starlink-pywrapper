#!/usr/bin/env python3
"""Run the fixed JCMT POL-2 Tutorial 1 with direct command arrays."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verify_pol2_raw_inputs import manifest_paths, verify_raw_inputs
from starlink._environment import (
    capture_starlink_environment,
    configure_session_environment,
)


REQUIRED_PRODUCTS = (
    "iauto.sdf", "iext.sdf", "qext.sdf", "uext.sdf", "astmask.sdf",
    "pcamask.sdf", "starlink_cat.FIT", "starlink_cat_none.FIT",
    "starlink_cat_as.FIT", "starlink_cat_mas.FIT",
)
HEADER_KEYS = (
    "INBEAM", "OBJECT", "OBSNUM", "SEQ_TYPE", "UTDATE", "DATE-OBS",
    "DATE-END", "SAM_MODE",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def new_output(raw_dir: Path, requested: Path) -> Path:
    raw_dir = raw_dir.resolve(strict=True)
    parent = requested.expanduser().absolute().parent.resolve(strict=True)
    output = parent / requested.name
    if output.exists():
        raise RuntimeError(f"output must not already exist: {output}")
    if output == raw_dir or output in raw_dir.parents or raw_dir in output.parents:
        raise RuntimeError("raw and output trees must be disjoint")
    output.mkdir()
    for name in ("maps", "qudata", "logs", "metadata", "checksums"):
        (output / name).mkdir()
    return output


def run_call(
    name: str,
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    logs: Path,
) -> dict[str, object]:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        start_new_session=True,
    )
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    (logs / f"{name}.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (logs / f"{name}.stderr.log").write_text(completed.stderr, encoding="utf-8")
    record = {
        "name": name,
        "argv": argv,
        "wall_seconds": time.monotonic() - started,
        "child_user_seconds": after.ru_utime - before.ru_utime,
        "child_system_seconds": after.ru_stime - before.ru_stime,
        "child_maxrss_kib_after": after.ru_maxrss,
        "child_filesystem_inputs": after.ru_inblock - before.ru_inblock,
        "child_filesystem_outputs": after.ru_oublock - before.ru_oublock,
        "returncode": completed.returncode,
    }
    if completed.returncode:
        raise RuntimeError(
            f"{name} failed with status {completed.returncode}; "
            f"see {logs / (name + '.stderr.log')}"
        )
    return record


def header_inventory(
    files: list[Path], fitsval: str, env: dict[str, str]
) -> dict[str, dict[str, str]]:
    inventory = {}
    for path in (files[0], files[2], files[-1]):
        values = {}
        for key in HEADER_KEYS:
            completed = subprocess.run(
                [fitsval, str(path), key],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            values[key] = completed.stdout.strip()
        inventory[str(path)] = values
    if "pol" not in inventory[str(files[2])]["INBEAM"].lower():
        raise RuntimeError("canonical science input does not identify POL-2")
    return inventory


def main() -> int:
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
    starlink_dir = args.starlink_dir.resolve(strict=True)
    verify_raw_inputs(raw_dir, manifest)
    files = manifest_paths(raw_dir, manifest)
    output = new_output(raw_dir, args.output_dir)
    logs = output / "logs"

    mylist = "".join(str(path) + "\n" for path in files)
    (output / "mylist").write_text(mylist, encoding="utf-8")
    hashes = {str(path): sha256(path) for path in files}
    checksum_text = "".join(
        f"{digest}  {path}\n" for path, digest in sorted(hashes.items())
    )
    (output / "checksums/raw_before.txt").write_text(
        checksum_text, encoding="utf-8"
    )

    with tempfile.TemporaryDirectory(prefix="pol2-cli-adam-") as adam_dir:
        with tempfile.TemporaryDirectory(prefix="pol2-cli-temp-") as star_temp:
            captured = capture_starlink_environment(starlink_dir)
            env = configure_session_environment(captured, adam_dir, star_temp)
            env["SMURF_THREADS"] = os.environ.get("SMURF_THREADS", "1")
            if not env["SMURF_THREADS"].isdigit():
                raise RuntimeError("SMURF_THREADS must be a non-negative integer")
            pol2map = str(Path(env["SMURF_DIR"]) / "pol2map.py")
            poledit = str(Path(env["POLPACK_DIR"]) / "poledit")
            fitsval = str(Path(env["KAPPA_DIR"]) / "fitsval")
            write_json(
                output / "metadata/environment_and_headers.json",
                {
                    "starlink_dir": str(starlink_dir),
                    "python": sys.version,
                    "executable": sys.executable,
                    "raw_dir": str(raw_dir),
                    "output_dir": str(output),
                    "raw_file_count": len(files),
                    "smurf_threads": env["SMURF_THREADS"],
                    "headers": header_inventory(files, fitsval, env),
                },
            )
            calls = []
            calls.append(run_call(
                "pol2map_step1",
                [pol2map, "in=^mylist", "iout=iauto", "qout=!", "uout=!",
                 "mapdir=maps", "qudir=qudata"],
                cwd=output, env=env, logs=logs,
            ))
            qu_count = len(list((output / "qudata").glob("*.sdf")))
            if qu_count < 12:
                raise RuntimeError(
                    f"pol2map step 1 produced only {qu_count} qudata files"
                )
            calls.append(run_call(
                "pol2map_step2",
                [pol2map, "in=qudata/*", "iout=iext", "qout=qext", "uout=uext",
                 "mapdir=maps", "mask=iauto", "maskout1=astmask",
                 "maskout2=pcamask", "ipref=iext", "cat=starlink_cat",
                 "debias=yes", "binsize=12"],
                cwd=output, env=env, logs=logs,
            ))
            for debias in ("none", "as", "mas"):
                calls.append(run_call(
                    "poledit_" + debias,
                    [poledit, "starlink_cat", "starlink_cat_" + debias,
                     "mode=debias", "debiastype=" + debias],
                    cwd=output, env=env, logs=logs,
                ))
            write_json(output / "metadata/timings.json", calls)

    for relative in REQUIRED_PRODUCTS:
        if not (output / relative).is_file():
            raise RuntimeError(f"required tutorial product is missing: {relative}")
    after = {str(path): sha256(path) for path in files}
    after_text = "".join(
        f"{digest}  {path}\n" for path, digest in sorted(after.items())
    )
    (output / "checksums/raw_after.txt").write_text(
        after_text, encoding="utf-8"
    )
    if after != hashes:
        raise RuntimeError("raw tutorial data changed during CLI reduction")
    products = {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.suffix.lower() in {".sdf", ".fit", ".fits"}
    }
    write_json(output / "checksums/products.json", products)
    (output / "CLI_COMPLETE").write_text(
        "Official JCMT POL-2 Tutorial 1 CLI reduction completed.\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
