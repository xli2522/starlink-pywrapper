#!/usr/bin/env python3
"""Sample the size of a Linux process tree until a status file changes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time


def process_parents() -> dict[int, int]:
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            closing = stat.rfind(")")
            fields = stat[closing + 2 :].split()
            parents[int(entry.name)] = int(fields[1])
        except (FileNotFoundError, PermissionError, ValueError, IndexError):
            continue
    return parents


def descendants(root: int, parents: dict[int, int]) -> set[int]:
    result = {root}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in result and pid not in result:
                result.add(pid)
                changed = True
    return result


def resident_memory_kib(processes: set[int]) -> int:
    """Return the sampled aggregate resident memory for a process tree."""

    page_kib = os.sysconf("SC_PAGE_SIZE") // 1024
    total = 0
    for pid in processes:
        try:
            fields = Path(f"/proc/{pid}/statm").read_text(
                encoding="utf-8"
            ).split()
            total += int(fields[1]) * page_kib
        except (
            FileNotFoundError,
            PermissionError,
            ProcessLookupError,
            ValueError,
            IndexError,
        ):
            continue
    return total


def load_summary(
    samples: list[tuple[float, float, float]],
) -> dict[str, object]:
    """Summarize host load averages sampled alongside the process tree."""

    labels = ("one_minute", "five_minutes", "fifteen_minutes")
    result: dict[str, object] = {"sample_count": len(samples)}
    for index, label in enumerate(labels):
        values = [sample[index] for sample in samples]
        result[label] = {
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
            "mean": sum(values) / len(values) if values else None,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root_pid", type=int)
    parser.add_argument("status_file", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--interval", type=float, default=0.1)
    args = parser.parse_args()

    started = time.time()
    samples = 0
    maximum = 0
    maximum_descendants = 0
    maximum_tree_rss_kib = 0
    load_samples: list[tuple[float, float, float]] = []
    while True:
        parents = process_parents()
        tree = descendants(args.root_pid, parents)
        if args.root_pid in parents or Path(f"/proc/{args.root_pid}").exists():
            maximum = max(maximum, len(tree))
            maximum_descendants = max(maximum_descendants, len(tree) - 1)
            maximum_tree_rss_kib = max(
                maximum_tree_rss_kib,
                resident_memory_kib(tree),
            )
            load_samples.append(os.getloadavg())
            samples += 1
        try:
            status = args.status_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            status = "missing"
        if status != "running":
            break
        time.sleep(args.interval)

    report = {
        "schema_version": 1,
        "root_pid": args.root_pid,
        "sampling_interval_seconds": args.interval,
        "samples": samples,
        "maximum_processes_including_worker": maximum,
        "maximum_descendants": maximum_descendants,
        "maximum_tree_rss_kib": maximum_tree_rss_kib,
        "machine_load": load_summary(load_samples),
        "started_unix": started,
        "finished_unix": time.time(),
        "final_status": status,
        "monitor_pid": os.getpid(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
