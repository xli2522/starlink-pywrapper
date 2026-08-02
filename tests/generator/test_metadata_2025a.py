from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest


HELPER = Path(__file__).resolve().parents[2] / "helperscripts" / "metadata_2025a.py"
SPEC = importlib.util.spec_from_file_location("metadata_2025a_test", HELPER)
assert SPEC and SPEC.loader
metadata_2025a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metadata_2025a)


class Parameter:
    def __init__(self, type_):
        self.type_ = type_


class Command:
    def __init__(self, parameters):
        self.pardict = parameters


def test_untyped_shell_helper_is_excluded_but_ifd_action_is_retained():
    commands = {
        "shell_helper": Command({"arg": Parameter(None)}),
        "typed": Command({"in": Parameter("NDF")}),
        "current_action": Command({}),
        "script_without_adam_parameters": Command(None),
    }
    result = metadata_2025a.discard_untyped_shell_helpers(
        commands, {"current_action": {}}
    )
    assert set(result) == {
        "typed",
        "current_action",
        "script_without_adam_parameters",
    }


def test_existing_callable_is_added_for_compatibility():
    class Generator:
        @staticmethod
        def commandinfo(name, description, parameters, longdescription):
            return (name, description, parameters, longdescription)

    result = metadata_2025a.add_existing_callables(
        Generator,
        {},
        {"legacy_alias": "Legacy summary."},
        "kappa",
    )
    assert result["legacy_alias"] == (
        "legacy_alias",
        "Legacy summary.",
        {},
        None,
    )


@pytest.mark.parametrize(
    ("command", "parameter", "expected"),
    (
        ("configecho", "ndf", "NDF"),
        ("erase", "object", "UNIV"),
        ("wcsshow", "object", "LITERAL"),
    ),
)
def test_audited_kappa_type_overrides(command, parameter, expected):
    assert metadata_2025a.parameter_type(
        "kappa", command, parameter, {}
    ) == expected


def test_unrecognized_missing_ifd_type_fails_with_parameter_identity():
    with pytest.raises(
        RuntimeError, match=r"kappa\.unknown\.mystery"
    ):
        metadata_2025a.parameter_type(
            "kappa", "unknown", "mystery", {}
        )


def test_vector_parameters_are_read_from_pinned_application_prologues(tmp_path):
    (tmp_path / "polplot.f").write_text(
        "*     UBND(2) = _REAL (Read)\n"
        "*     PIXELREF(2) = REAL (Read)\n"
        "*     VSCALE = _REAL (Read)\n",
        encoding="utf-8",
    )
    library = tmp_path / "libsmurf"
    library.mkdir()
    (library / "smurf_makemap.c").write_text(
        "/* application */\n"
        "*     PIXSIZE( 2 ) = _REAL (Read)\n",
        encoding="utf-8",
    )
    (tmp_path / "echmerge.f").write_text(
        "*     output(i) = weight*input(i)\n",
        encoding="utf-8",
    )

    polpack = metadata_2025a.load_source_vector_parameters(
        tmp_path, "polpack"
    )
    smurf = metadata_2025a.load_source_vector_parameters(tmp_path, "smurf")

    assert polpack["polplot"] == {"pixelref", "ubnd"}
    assert "vscale" not in polpack["polplot"]
    assert smurf["makemap"] == {"pixsize"}
    assert "echmerge" not in polpack
