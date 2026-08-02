from __future__ import annotations

from collections import OrderedDict
import importlib.util
from pathlib import Path
import sys


HELPERS = Path(__file__).resolve().parents[2] / "helperscripts"
sys.path.insert(0, str(HELPERS))

GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_functions_ifd_merge_test", HELPERS / "generate_functions.py"
)
assert GENERATOR_SPEC and GENERATOR_SPEC.loader
generate_functions = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(generate_functions)

CURRENT_SPEC = importlib.util.spec_from_file_location(
    "generate_2025a_ifd_merge_test", HELPERS / "generate_2025a.py"
)
assert CURRENT_SPEC and CURRENT_SPEC.loader
generate_2025a = importlib.util.module_from_spec(CURRENT_SPEC)
CURRENT_SPEC.loader.exec_module(generate_2025a)


def parameter(*, list_: bool, readwrite: str):
    return generate_functions.parinfo(
        "ubnd",
        None,
        "Help prompt",
        "!",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        list_,
        readwrite,
    )


def merge(fields, fallback, source_vectors=None):
    command = generate_functions.commandinfo(
        "polplot",
        "Plots a vector map.",
        {"ubnd": fallback},
        None,
    )
    result = generate_2025a._merge_ifd_metadata(
        generate_functions,
        {"polplot": command},
        {"polplot": OrderedDict((("ubnd", fields),))},
        "polpack",
        source_vectors,
    )
    return result["polplot"].pardict["ubnd"]


def test_omitted_ifd_size_and_access_preserve_current_help_metadata():
    result = merge(
        {"type": "_REAL", "prompt": "Interface prompt"},
        parameter(list_=True, readwrite="read"),
    )

    assert result.type_ == "_REAL"
    assert result.prompt == "Interface prompt"
    assert result.default == "!"
    assert result.list_ is True
    assert result.access == "read"
    assert result.readwrite == "read"


def test_explicit_ifd_size_and_access_override_help_metadata():
    result = merge(
        {"type": "_REAL", "size": "1", "access": "WRITE"},
        parameter(list_=True, readwrite="read"),
        {"polplot": {"ubnd"}},
    )

    assert result.list_ is False
    assert result.access == "WRITE"
    assert result.readwrite == "write"


def test_source_vector_declaration_fills_missing_ifd_and_help_shape():
    result = merge(
        {"type": "_REAL"},
        parameter(list_=False, readwrite="read"),
        {"polplot": {"ubnd"}},
    )

    assert result.list_ is True


def test_source_vector_declaration_updates_legacy_ifl_metadata():
    fallback = parameter(list_=False, readwrite="read")._replace(type_="_CHAR")
    command = generate_functions.commandinfo(
        "ircam2ndf",
        "Converts IRCAM data.",
        {"obs": fallback._replace(name="obs")},
        None,
    )

    result = generate_2025a._merge_ifd_metadata(
        generate_functions,
        {"ircam2ndf": command},
        {},
        "convert",
        {"ircam2ndf": {"obs"}},
    )

    assert result["ircam2ndf"].pardict["obs"].list_ is True


def test_ifd_vector_without_help_metadata_remains_supported():
    result = generate_2025a._parinfo(
        generate_functions,
        "polpack",
        "polplot",
        "ubnd",
        {"type": "_REAL", "size": "*"},
    )

    assert result.list_ is True
    assert result.access == "UPDATE"
    assert result.readwrite == "update"
