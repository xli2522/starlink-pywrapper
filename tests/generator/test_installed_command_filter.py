from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


HELPERS = Path(__file__).resolve().parents[2] / "helperscripts"
sys.path.insert(0, str(HELPERS))
SPEC = importlib.util.spec_from_file_location(
    "generate_2025a_test", HELPERS / "generate_2025a.py"
)
assert SPEC and SPEC.loader
generate_2025a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_2025a)


def test_command_executable_path_resolves_supported_variable_forms(tmp_path):
    installation = tmp_path / "star"

    assert generate_2025a._command_executable_path(
        "$KAPPA_DIR/stats", installation, "KAPPA", "KAPPA_DIR"
    ) == installation / "bin" / "kappa" / "stats"
    assert generate_2025a._command_executable_path(
        "${KAPPA_DIR}/fitsmod edit=write",
        installation,
        "KAPPA",
        "KAPPA_DIR",
    ) == installation / "bin" / "kappa" / "fitsmod"
    assert generate_2025a._command_executable_path(
        "${STARLINK_DIR}/bin/convert/fits2ndf",
        installation,
        "Figaro",
        "FIG_DIR",
    ) == installation / "bin" / "convert" / "fits2ndf"


def test_audited_uninstalled_addition_is_omitted(tmp_path):
    command_paths = {
        "mem2d": "$KAPPA_DIR/mem2d",
        "stats": "$KAPPA_DIR/stats",
    }
    module_info = {"mem2d": object(), "stats": object()}
    stats = tmp_path / "bin" / "kappa" / "stats"
    stats.parent.mkdir(parents=True)
    stats.touch(mode=0o755)

    paths, info = generate_2025a._filter_uninstalled_commands(
        command_paths,
        module_info,
        tmp_path,
        "KAPPA",
        "KAPPA_DIR",
        {"stats"},
    )

    assert paths == {"stats": "$KAPPA_DIR/stats"}
    assert set(info) == {"stats"}


def test_missing_existing_or_unreviewed_command_fails(tmp_path):
    with pytest.raises(RuntimeError, match="Existing public command"):
        generate_2025a._filter_uninstalled_commands(
            {"stats": "$KAPPA_DIR/stats"},
            {"stats": object()},
            tmp_path,
            "KAPPA",
            "KAPPA_DIR",
            {"stats"},
        )

    with pytest.raises(RuntimeError, match="Generated command"):
        generate_2025a._filter_uninstalled_commands(
            {"newtask": "$KAPPA_DIR/newtask"},
            {"newtask": object()},
            tmp_path,
            "KAPPA",
            "KAPPA_DIR",
            set(),
        )
