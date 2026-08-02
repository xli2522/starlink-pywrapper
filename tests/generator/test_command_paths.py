from __future__ import annotations

import importlib.util
from pathlib import Path


GENERATOR = (
    Path(__file__).resolve().parents[2] / "helperscripts" / "generate_functions.py"
)
SPEC = importlib.util.spec_from_file_location("command_path_generator", GENERATOR)
assert SPEC and SPEC.loader
generate_functions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_functions)


def test_ifd2star_function_header_allows_whitespace_before_parentheses():
    result = generate_functions.get_command_paths(
        [
            'stats () { $KAPPA_DIR/stats ${1+"$@"}; }\n',
            'kap_stats () { $KAPPA_DIR/stats ${1+"$@"}; }\n',
        ],
        ["stats"],
        "KAPPA",
    )
    assert result == {"stats": "$KAPPA_DIR/stats"}


def test_python_script_prefix_is_removed_without_lstrip_corruption():
    result = generate_functions.get_command_paths(
        ['matchbeam () { python3 $SMURF_DIR/matchbeam.py ${1+"$@"}; }\n'],
        ["matchbeam"],
        "SMURF",
    )
    assert result == {"matchbeam": "$SMURF_DIR/matchbeam.py"}


def test_last_shell_definition_wins_and_aliases_become_argument_arrays():
    result = generate_functions.get_command_paths(
        [
            'fitsin () { $KAPPA_DIR/fitsin ${1+"$@"}; }\n',
            'fitsin () { echo removed ${1+"$@"}; }\n',
            'fitswrite () { fitsmod edit=write ${1+"$@"}; }\n',
        ],
        ["fitsin", "fitswrite"],
        "KAPPA",
    )
    assert result == {
        "fitsin": "echo removed",
        "fitswrite": "${KAPPA_DIR}/fitsmod edit=write",
    }
