#!/usr/bin/env python3
"""Compare paired POLPACK FITS catalogues semantically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from astropy.io import fits
import numpy as np


CATALOGUES = (
    "starlink_cat.FIT",
    "starlink_cat_none.FIT",
    "starlink_cat_as.FIT",
    "starlink_cat_mas.FIT",
)
VOLATILE_HEADER_KEYS = {
    "",
    "CHECKSUM",
    "DATASUM",
    "DATE",
    "HISTORY",
    "COMMENT",
}


def table_hdu(hdulist: fits.HDUList) -> fits.BinTableHDU:
    for hdu in hdulist:
        if isinstance(hdu, fits.BinTableHDU):
            return hdu
    raise RuntimeError("FITS catalogue contains no binary table")


def semantic_header(header: fits.Header) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for card in header.cards:
        if card.keyword in VOLATILE_HEADER_KEYS:
            continue
        result[card.keyword] = card.value
    return result


def schema(hdu: fits.BinTableHDU) -> list[dict[str, Any]]:
    return [
        {
            "name": column.name,
            "format": column.format,
            "unit": column.unit,
            "dim": column.dim,
            "null": column.null,
        }
        for column in hdu.columns
    ]


def compare_column(left: Any, right: Any) -> dict[str, Any]:
    left_masked = np.ma.asarray(left)
    right_masked = np.ma.asarray(right)
    left_mask = np.ma.getmaskarray(left_masked)
    right_mask = np.ma.getmaskarray(right_masked)
    masks_equal = np.array_equal(left_mask, right_mask)
    left_data = np.asarray(left_masked.data)
    right_data = np.asarray(right_masked.data)
    record: dict[str, Any] = {
        "shape_equal": left_data.shape == right_data.shape,
        "mask_equal": masks_equal,
        "dtype_left": str(left_data.dtype),
        "dtype_right": str(right_data.dtype),
    }
    if left_data.shape != right_data.shape:
        record["equal"] = False
        return record

    kind = left_data.dtype.kind
    if kind in "iufc" and right_data.dtype.kind in "iufc":
        left_float = left_data.astype(np.complex128 if kind == "c" else np.float64)
        right_float = right_data.astype(
            np.complex128 if right_data.dtype.kind == "c" else np.float64
        )
        finite_equal = np.array_equal(
            np.isfinite(left_float), np.isfinite(right_float)
        )
        exact = np.array_equal(left_float, right_float, equal_nan=True)
        valid = ~left_mask & ~right_mask
        valid &= np.isfinite(left_float) & np.isfinite(right_float)
        if np.any(valid):
            difference = np.abs(left_float[valid] - right_float[valid])
            denominator = np.maximum(
                np.maximum(np.abs(left_float[valid]), np.abs(right_float[valid])),
                np.finfo(np.float64).tiny,
            )
            max_absolute = float(np.max(difference))
            max_relative = float(np.max(difference / denominator))
        else:
            max_absolute = 0.0
            max_relative = 0.0
        roundoff_equal = bool(
            np.allclose(
                left_float,
                right_float,
                rtol=1e-12,
                atol=1e-12,
                equal_nan=True,
            )
        )
        record.update(
            {
                "finite_mask_equal": finite_equal,
                "exact": exact,
                "roundoff_equal": roundoff_equal,
                "max_absolute_difference": max_absolute,
                "max_relative_difference": max_relative,
                "equal": masks_equal and finite_equal and roundoff_equal,
            }
        )
    else:
        exact = np.array_equal(left_data, right_data)
        record.update({"exact": exact, "equal": masks_equal and exact})
    return record


def compare_catalogue(cli_path: Path, wrapper_path: Path) -> dict[str, Any]:
    with fits.open(cli_path, memmap=True) as cli_hdus, fits.open(
        wrapper_path, memmap=True
    ) as wrapper_hdus:
        cli_table = table_hdu(cli_hdus)
        wrapper_table = table_hdu(wrapper_hdus)
        cli_schema = schema(cli_table)
        wrapper_schema = schema(wrapper_table)
        cli_names = list(cli_table.columns.names)
        wrapper_names = list(wrapper_table.columns.names)
        columns: dict[str, Any] = {}
        if cli_names == wrapper_names:
            for name in cli_names:
                columns[name] = compare_column(
                    cli_table.data[name], wrapper_table.data[name]
                )
        headers_equal = (
            semantic_header(cli_hdus[0].header)
            == semantic_header(wrapper_hdus[0].header)
            and semantic_header(cli_table.header)
            == semantic_header(wrapper_table.header)
        )
        row_count_cli = len(cli_table.data)
        row_count_wrapper = len(wrapper_table.data)
        all_columns_equal = (
            cli_names == wrapper_names
            and all(record["equal"] for record in columns.values())
        )
        return {
            "cli_path": str(cli_path),
            "wrapper_path": str(wrapper_path),
            "row_count_cli": row_count_cli,
            "row_count_wrapper": row_count_wrapper,
            "row_count_equal": row_count_cli == row_count_wrapper,
            "schema_equal": cli_schema == wrapper_schema,
            "cli_schema": cli_schema,
            "wrapper_schema": wrapper_schema,
            "semantic_headers_equal": headers_equal,
            "cli_primary_header": semantic_header(cli_hdus[0].header),
            "wrapper_primary_header": semantic_header(wrapper_hdus[0].header),
            "cli_table_header": semantic_header(cli_table.header),
            "wrapper_table_header": semantic_header(wrapper_table.header),
            "columns": columns,
            "all_columns_equal": all_columns_equal,
            "equivalent": (
                row_count_cli == row_count_wrapper
                and cli_schema == wrapper_schema
                and headers_equal
                and all_columns_equal
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
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

    records: dict[str, Any] = {}
    for relative in CATALOGUES:
        cli_path = cli_dir / relative
        wrapper_path = wrapper_dir / relative
        if not cli_path.is_file() or not wrapper_path.is_file():
            raise RuntimeError(f"paired catalogue is missing: {relative}")
        records[relative] = compare_catalogue(cli_path, wrapper_path)

    equivalent = all(record["equivalent"] for record in records.values())
    report = {
        "schema_version": 1,
        "cli_dir": str(cli_dir),
        "wrapper_dir": str(wrapper_dir),
        "catalogues": records,
        "all_semantically_equivalent": equivalent,
        "numeric_tolerance": {"rtol": 1e-12, "atol": 1e-12},
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    if not equivalent:
        raise RuntimeError("one or more paired POLPACK catalogues differ")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
