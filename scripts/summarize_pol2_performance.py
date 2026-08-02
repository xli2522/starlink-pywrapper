#!/usr/bin/env python3
"""Summarize portable paired POL-2 timing and resource records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_calls(root: Path) -> list[dict[str, Any]]:
    calls = json.loads(
        (root / "metadata/timings.json").read_text(encoding="utf-8")
    )
    if not isinstance(calls, list) or len(calls) != 5:
        raise RuntimeError(f"expected five timing records under {root}")
    for call in calls:
        if not isinstance(call, dict) or not isinstance(
            call.get("wall_seconds"), (int, float)
        ):
            raise RuntimeError(f"invalid timing record under {root}: {call!r}")
        if call.get("returncode", 0) != 0:
            raise RuntimeError(f"failed timed command under {root}: {call!r}")
    return calls


def tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def product_bytes(root: Path) -> int:
    return sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".sdf", ".fit", ".fits"}
    )


def resource_summary(calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "calls": calls,
        "wall_seconds": sum(float(call["wall_seconds"]) for call in calls),
        "child_user_seconds": sum(
            float(call.get("child_user_seconds", 0)) for call in calls
        ),
        "child_system_seconds": sum(
            float(call.get("child_system_seconds", 0)) for call in calls
        ),
        "maximum_child_rss_kib": max(
            int(call.get("child_maxrss_kib_after", 0)) for call in calls
        ),
        "filesystem_inputs": sum(
            int(call.get("child_filesystem_inputs", 0)) for call in calls
        ),
        "filesystem_outputs": sum(
            int(call.get("child_filesystem_outputs", 0)) for call in calls
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-order", choices=("cli-first", "wrapper-first"), default="cli-first"
    )
    parser.add_argument("cli_dir", type=Path)
    parser.add_argument("wrapper_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    cli_dir = args.cli_dir.resolve(strict=True)
    wrapper_dir = args.wrapper_dir.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f"output must not exist: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    cli = resource_summary(load_calls(cli_dir))
    wrapped = resource_summary(load_calls(wrapper_dir))
    cli["output_bytes"] = tree_bytes(cli_dir)
    cli["scientific_product_bytes"] = product_bytes(cli_dir)
    wrapped["output_bytes"] = tree_bytes(wrapper_dir)
    wrapped["scientific_product_bytes"] = product_bytes(wrapper_dir)
    extra = wrapped["wall_seconds"] - cli["wall_seconds"]
    allowed_extra = max(cli["wall_seconds"] * 0.05, 60.0)
    passed = extra <= allowed_extra
    second = "wrapper" if args.run_order == "cli-first" else "CLI"
    report = {
        "schema_version": 2,
        "run_order": args.run_order,
        "cache_context": (
            f"The {second} ran second on the same filesystem; caches were not flushed."
        ),
        "cli": cli,
        "wrapper": wrapped,
        "wrapper_minus_cli_wall_seconds": extra,
        "acceptance_rule": "wrapper <= CLI + max(5 percent of CLI, 60 seconds)",
        "allowed_extra_seconds": allowed_extra,
        "acceptance_bound_passed": passed,
        "resource_scope": (
            "Per-command child resource usage recorded by Python; external "
            "CPU, memory, affinity, and thread limits are operator supplied."
        ),
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not passed:
        raise RuntimeError(
            f"wrapper wall overhead {extra:.3f}s exceeds {allowed_extra:.3f}s"
        )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
