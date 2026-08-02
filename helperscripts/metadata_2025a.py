"""Build current wrapper metadata from pinned Starlink interface sources."""

from __future__ import annotations

import ast
import json
from keyword import iskeyword
from pathlib import Path
import re


PARAMETER_TYPE_OVERRIDES = {
    # The pinned KAPPA help declares these types, but the corresponding IFD
    # entries omit both TYPE and PTYPE.
    ("kappa", "configecho", "ndf"): "NDF",
    ("kappa", "erase", "object"): "UNIV",
    ("kappa", "wcsshow", "object"): "LITERAL",
}

_SOURCE_VECTOR_PARAMETER = re.compile(
    r"(?im)^[ \t]*(?:[*!]|/\*)[ \t]*"
    r"([A-Za-z][A-Za-z0-9_]*)[ \t]*\([^\r\n)]*\)[ \t]*=[ \t]*"
    r"(?:_[A-Za-z0-9]+|NDF|FILENAME|TRN|DEVICE|GRAPHICS|HDSOBJECT|"
    r"UNIV|UNIVERSAL|IRCAM|DOUBLE|REAL|INTEGER|LOGICAL|CHAR|"
    r"CHARACTER|ERROR|LITERAL)\b"
)


def load_source_vector_parameters(
    source_root: Path, package_name: str
) -> dict[str, set[str]]:
    """Return vector parameters declared in maintained application sources.

    Current Starlink IFD files sometimes omit ``size`` for parameters that
    applications read or write as arrays.  The application prologues retain
    declarations such as ``UBND(2) = _REAL`` and are pinned with the rest of
    the source tree.
    """

    result: dict[str, set[str]] = {}
    prefix = package_name.lower() + "_"
    for path in sorted(Path(source_root).rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {
            ".c",
            ".f",
            ".f77",
            ".f90",
            ".for",
        }:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        parameters = {
            match.group(1).lower()
            for match in _SOURCE_VECTOR_PARAMETER.finditer(text)
        }
        if not parameters:
            continue
        action = path.stem.lower()
        if action.startswith(prefix):
            action = action[len(prefix) :]
        result.setdefault(action, set()).update(parameters)
    return result


def parameter_type(
    package_name: str,
    command_name: str,
    parameter_name: str,
    fields: dict[str, str],
) -> str:
    """Return a typed 2025A parameter or fail with its exact identity."""

    value = fields.get("type") or fields.get("ptype")
    if value:
        return value
    key = (
        package_name.lower(),
        command_name.lower(),
        parameter_name.lower(),
    )
    try:
        return PARAMETER_TYPE_OVERRIDES[key]
    except KeyError as exc:
        raise RuntimeError(
            "No typed 2025A interface metadata for "
            f"{package_name}.{command_name}.{parameter_name}"
        ) from exc


def baseline_signatures(repo: Path, package_name: str) -> dict[str, str]:
    """Return exact frozen signatures for existing generated callables."""

    path = repo / "manifests" / "api_manifest_baseline.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    module = manifest["modules"].get(package_name, {})
    result = {}
    for item in module.get("public_callables", []):
        if item.get("kind") != "function" or not item.get("signature"):
            continue
        name = item["name"]
        if name.endswith("_") and iskeyword(name[:-1]):
            name = name[:-1]
        result[name] = item["signature"][1:-1]
    return result


def existing_descriptions(repo: Path, package_name: str) -> dict[str, str]:
    """Return stable first-line descriptions from the checked-in wrapper."""

    path = repo / "starlink" / f"{package_name}.py"
    if not path.is_file():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines = (ast.get_docstring(node) or "").strip().splitlines()
            if lines:
                result[node.name[:-1] if node.name.endswith("_") and iskeyword(node.name[:-1]) else node.name] = lines[0]
    return result


def _description(
    descriptions: dict[str, str], package_name: str, command_name: str
) -> str:
    return descriptions.get(
        command_name,
        f"Runs the Starlink {package_name.upper()} {command_name} application.",
    )


def add_existing_callables(
    generator,
    module_info,
    descriptions: dict[str, str],
    package_name: str,
):
    """Keep every existing callable represented during regeneration."""

    result = dict(module_info)
    for name in sorted(descriptions):
        result.setdefault(
            name,
            generator.commandinfo(
                name,
                _description(descriptions, package_name, name),
                {},
                None,
            ),
        )
    return result


def add_ifd_actions(
    generator,
    module_info,
    ifd_actions,
    descriptions: dict[str, str],
    package_name: str,
):
    """Add actions absent from the small package-level source HLP file."""

    result = dict(module_info)
    for name in sorted(ifd_actions):
        result.setdefault(
            name,
            generator.commandinfo(
                name,
                _description(descriptions, package_name, name),
                {},
                None,
            ),
        )
    return result


def standalone_ifl_metadata(
    generator,
    source_root: Path,
    descriptions: dict[str, str],
    package_name: str,
):
    """Load one-command legacy IFL files when the master HLP is an include."""

    result = {}
    excluded = {
        f"{package_name}_mon",
        f"{package_name}help",
        f"{package_name[:3]}help",
    }
    for path in sorted(source_root.glob("*.ifl")):
        name = path.stem.lower()
        if name in excluded or name.endswith("_mon"):
            continue
        parameters = generator._ifl_parser(
            path.read_text(encoding="utf-8", errors="replace").splitlines(True),
            None,
            comname=name,
        )
        if not parameters:
            continue
        result[name] = generator.commandinfo(
            name,
            _description(descriptions, package_name, name),
            parameters,
            None,
        )
    return result


def discard_untyped_shell_helpers(module_info, ifd_actions):
    """Exclude non-ADAM help topics that have no typed interface metadata."""

    return {
        name: info
        for name, info in module_info.items()
        if (
            name in ifd_actions
            or not info.pardict
            or all(parameter.type_ for parameter in info.pardict.values())
        )
    }
