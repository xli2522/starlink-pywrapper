#!/usr/bin/env python3
"""Compare CLI and wrapper NDF products with Starlink itself."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from starlink import kappa, wrapper


TOP_LEVEL_PRODUCTS = (
    "iauto.sdf",
    "iext.sdf",
    "qext.sdf",
    "uext.sdf",
    "astmask.sdf",
    "pcamask.sdf",
)
SOURCE_REGION_PRODUCTS = {"iauto.sdf", "iext.sdf", "qext.sdf", "uext.sdf"}


def result_dict(result: object) -> dict[str, Any]:
    return {
        key: value
        for key, value in result._asdict().items()  # type: ignore[attr-defined]
    }


def selected_metadata(result: object) -> dict[str, Any]:
    values = result_dict(result)
    names = (
        "ndim",
        "dims",
        "lbound",
        "ubound",
        "type",
        "units",
        "label",
        "title",
        "fdomain",
        "extname",
        "exttype",
        "variance",
        "quality",
        "badbits",
    )
    return {name: values.get(name) for name in names}


def selected_stats(result: object) -> dict[str, Any]:
    values = result_dict(result)
    names = (
        "minimum",
        "maximum",
        "mean",
        "sigma",
        "total",
        "numpix",
        "numgood",
        "numbad",
        "minpos",
        "maxpos",
        "mincoord",
        "maxcoord",
    )
    return {name: values.get(name) for name in names}


def values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, float) and isinstance(right, float):
        return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
    return left == right


def central_section(path: Path, trace: object) -> str | None:
    dims = list(getattr(trace, "dims", ()))
    lower = list(getattr(trace, "lbound", ()))
    upper = list(getattr(trace, "ubound", ()))
    if len(dims) != 2 or len(lower) != 2 or len(upper) != 2:
        return None
    sections: list[str] = []
    for low, high in zip(lower, upper):
        span = high - low + 1
        section_low = int(low + span // 4)
        section_high = int(high - span // 4)
        sections.append(f"{section_low}:{section_high}")
    return f"{path}({','.join(sections)})"


def product_inventory(root: Path) -> dict[str, Path]:
    inventory = {
        relative: root / relative
        for relative in TOP_LEVEL_PRODUCTS
        if (root / relative).is_file()
    }
    for directory in ("maps", "qudata"):
        for path in sorted((root / directory).glob("*.sdf")):
            inventory[str(path.relative_to(root))] = path
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cli_dir", type=Path)
    parser.add_argument("wrapper_dir", type=Path)
    parser.add_argument("starlink_dir", type=Path)
    parser.add_argument("report_dir", type=Path)
    args = parser.parse_args()

    cli_dir = args.cli_dir.resolve(strict=True)
    python_dir = args.wrapper_dir.resolve(strict=True)
    report_dir = args.report_dir.resolve()
    if report_dir.exists():
        raise RuntimeError(f"report directory must not exist: {report_dir}")
    report_dir.mkdir(parents=True)
    ndf_reports = report_dir / "ndfcompare"
    ndf_reports.mkdir()
    wrapper.change_starpath(args.starlink_dir.resolve(strict=True))

    cli_products = product_inventory(cli_dir)
    python_products = product_inventory(python_dir)
    if set(cli_products) != set(python_products):
        missing_cli = sorted(set(python_products) - set(cli_products))
        missing_wrapper = sorted(set(cli_products) - set(python_products))
        raise RuntimeError(
            f"NDF inventories differ; missing CLI={missing_cli}, "
            f"missing wrapper={missing_wrapper}"
        )
    for required in TOP_LEVEL_PRODUCTS:
        if required not in cli_products:
            raise RuntimeError(f"required paired NDF is missing: {required}")

    records: list[dict[str, Any]] = []
    all_similar = True
    for relative in sorted(cli_products):
        cli_path = cli_products[relative]
        python_path = python_products[relative]
        report_path = ndf_reports / (relative.replace("/", "__") + ".txt")
        comparison = kappa.ndfcompare(
            str(cli_path),
            str(python_path),
            report=str(report_path),
            accdat="0",
            accvar="0",
            accpos=0.0,
            nbad="0",
            _starlink_timeout=300,
        )
        cli_trace = kappa.ndftrace(str(cli_path), _starlink_timeout=120)
        python_trace = kappa.ndftrace(str(python_path), _starlink_timeout=120)
        cli_stats = kappa.stats(str(cli_path), _starlink_timeout=120)
        python_stats = kappa.stats(str(python_path), _starlink_timeout=120)

        cli_metadata = selected_metadata(cli_trace)
        python_metadata = selected_metadata(python_trace)
        cli_statistics = selected_stats(cli_stats)
        python_statistics = selected_stats(python_stats)
        metadata_equal = cli_metadata == python_metadata
        statistics_equal = all(
            values_equal(cli_statistics[key], python_statistics[key])
            for key in cli_statistics
        )
        similar = bool(comparison.similar)
        all_similar = (
            all_similar and similar and metadata_equal and statistics_equal
        )
        record: dict[str, Any] = {
            "relative_path": relative,
            "ndfcompare_similar": similar,
            "ndfcompare_report": str(report_path),
            "metadata_equal": metadata_equal,
            "statistics_equal": statistics_equal,
            "cli_metadata": cli_metadata,
            "wrapper_metadata": python_metadata,
            "cli_statistics": cli_statistics,
            "wrapper_statistics": python_statistics,
        }

        if relative in SOURCE_REGION_PRODUCTS:
            cli_section = central_section(cli_path, cli_trace)
            python_section = central_section(python_path, python_trace)
            if cli_section and python_section:
                cli_source = selected_stats(
                    kappa.stats(cli_section, _starlink_timeout=120)
                )
                python_source = selected_stats(
                    kappa.stats(python_section, _starlink_timeout=120)
                )
                source_equal = all(
                    values_equal(cli_source[key], python_source[key])
                    for key in cli_source
                )
                all_similar = all_similar and source_equal
                record["central_source_region"] = {
                    "cli_section": cli_section,
                    "wrapper_section": python_section,
                    "equal": source_equal,
                    "cli_statistics": cli_source,
                    "wrapper_statistics": python_source,
                }
        records.append(record)

    output = {
        "schema_version": 1,
        "starlink_dir": wrapper.starpath,
        "cli_dir": str(cli_dir),
        "wrapper_dir": str(python_dir),
        "paired_ndf_count": len(records),
        "all_semantically_equivalent": all_similar,
        "tolerance": {
            "ndfcompare_accdat": "0",
            "ndfcompare_accvar": "0",
            "ndfcompare_accpos": 0.0,
            "ndfcompare_nbad": "0",
            "summary_float_rel_tol": 1e-12,
            "summary_float_abs_tol": 1e-12,
        },
        "products": records,
    }
    (report_dir / "ndf_comparison.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not all_similar:
        raise RuntimeError("one or more paired NDF products differ")
    print(report_dir / "ndf_comparison.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
