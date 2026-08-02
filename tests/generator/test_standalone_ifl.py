from __future__ import annotations

import importlib.util
from pathlib import Path


GENERATOR = (
    Path(__file__).resolve().parents[2] / "helperscripts" / "generate_functions.py"
)
SPEC = importlib.util.spec_from_file_location("standalone_ifl_generator", GENERATOR)
assert SPEC and SPEC.loader
generate_functions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_functions)


def test_ifl_parser_can_supply_metadata_without_a_master_help_entry():
    metadata = generate_functions._ifl_parser(
        [
            "interface demo\n",
            "parameter values\n",
            "  type '_REAL'\n",
            "  size 4\n",
            "  access READ\n",
            "  prompt 'Input values'\n",
            "endparameter\n",
            "endinterface\n",
        ],
        None,
        comname="demo",
    )

    assert metadata["values"].type_ == "_REAL"
    assert metadata["values"].list_ is True
    assert metadata["values"].readwrite == "read"
