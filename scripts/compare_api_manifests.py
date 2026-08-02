#!/usr/bin/env python3
"""Create a deterministic, machine-readable API-manifest comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in items}


def _compare_named_items(
    before_items: list[dict[str, Any]],
    after_items: list[dict[str, Any]],
) -> dict[str, Any]:
    before = _index(before_items)
    after = _index(after_items)
    shared = sorted(before.keys() & after.keys())
    changed = []
    for name in shared:
        fields = sorted(
            field
            for field in before[name].keys() | after[name].keys()
            if before[name].get(field) != after[name].get(field)
        )
        if fields:
            changed.append(
                {
                    "name": name,
                    "changed_fields": fields,
                    "before": before[name],
                    "after": after[name],
                }
            )
    return {
        "added": [after[name] for name in sorted(after.keys() - before.keys())],
        "removed": [before[name] for name in sorted(before.keys() - after.keys())],
        "changed": changed,
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_modules = before["modules"]
    after_modules = after["modules"]
    modules: dict[str, Any] = {}
    summary = {
        "modules_added": 0,
        "modules_removed": 0,
        "callables_added": 0,
        "callables_removed": 0,
        "callables_changed": 0,
        "signatures_changed": 0,
        "result_types_added": 0,
        "result_types_removed": 0,
        "result_types_changed": 0,
    }

    for name in sorted(before_modules.keys() | after_modules.keys()):
        if name not in before_modules:
            summary["modules_added"] += 1
            module = {
                "status": "added",
                "callables": {
                    "added": after_modules[name]["public_callables"],
                    "removed": [],
                    "changed": [],
                },
                "result_types": {
                    "added": after_modules[name]["public_result_types"],
                    "removed": [],
                    "changed": [],
                },
            }
        elif name not in after_modules:
            summary["modules_removed"] += 1
            module = {
                "status": "removed",
                "callables": {
                    "added": [],
                    "removed": before_modules[name]["public_callables"],
                    "changed": [],
                },
                "result_types": {
                    "added": [],
                    "removed": before_modules[name]["public_result_types"],
                    "changed": [],
                },
            }
        else:
            callable_changes = _compare_named_items(
                before_modules[name]["public_callables"],
                after_modules[name]["public_callables"],
            )
            result_changes = _compare_named_items(
                before_modules[name]["public_result_types"],
                after_modules[name]["public_result_types"],
            )
            module = {
                "status": (
                    "changed"
                    if any(callable_changes.values()) or any(result_changes.values())
                    else "unchanged"
                ),
                "callables": callable_changes,
                "result_types": result_changes,
            }

        summary["callables_added"] += len(module["callables"]["added"])
        summary["callables_removed"] += len(module["callables"]["removed"])
        summary["callables_changed"] += len(module["callables"]["changed"])
        summary["signatures_changed"] += sum(
            "signature" in item["changed_fields"]
            for item in module["callables"]["changed"]
        )
        summary["result_types_added"] += len(module["result_types"]["added"])
        summary["result_types_removed"] += len(module["result_types"]["removed"])
        summary["result_types_changed"] += len(module["result_types"]["changed"])
        modules[name] = module

    return {
        "schema_version": 1,
        "baseline_source": before["source"],
        "candidate_source": after["source"],
        "summary": summary,
        "modules": modules,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(
        json.loads(args.before.read_text(encoding="utf-8")),
        json.loads(args.after.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
