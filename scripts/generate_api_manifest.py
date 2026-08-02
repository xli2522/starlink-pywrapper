#!/usr/bin/env python3
"""Generate a deterministic public-API manifest from a starlink source tree.

The legacy distribution cannot always be imported on the audit interpreter,
so this tool deliberately uses the Python AST rather than importing modules.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any


GENERATED_VERSION_RE = re.compile(
    r"Starlink version:\s*(?P<release>[^\n]+)\s*\n"
    r"(?P<commit>[0-9a-f]+)\s+\((?P<generated_at>[^)]+)\)",
    re.IGNORECASE,
)
PINNED_GENERATED_VERSION_RE = re.compile(
    r"Starlink version:\s*(?P<release>[^\n]+)\s*\n"
    r"Source commit:\s*(?P<commit>[0-9a-f]+)",
    re.IGNORECASE,
)



def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_signature(arguments: ast.arguments) -> str:
    """Return an inspect-like signature for an AST arguments node."""
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults: list[ast.expr | None] = [
        *([None] * (len(positional) - len(arguments.defaults))),
        *arguments.defaults,
    ]
    pieces: list[str] = []

    for index, (argument, default) in enumerate(zip(positional, defaults)):
        text = argument.arg
        if argument.annotation is not None:
            text += f": {ast.unparse(argument.annotation)}"
        if default is not None:
            text += f" = {ast.unparse(default)}"
        pieces.append(text)
        if arguments.posonlyargs and index + 1 == len(arguments.posonlyargs):
            pieces.append("/")

    if arguments.vararg is not None:
        text = f"*{arguments.vararg.arg}"
        if arguments.vararg.annotation is not None:
            text += f": {ast.unparse(arguments.vararg.annotation)}"
        pieces.append(text)
    elif arguments.kwonlyargs:
        pieces.append("*")

    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        text = argument.arg
        if argument.annotation is not None:
            text += f": {ast.unparse(argument.annotation)}"
        if default is not None:
            text += f" = {ast.unparse(default)}"
        pieces.append(text)

    if arguments.kwarg is not None:
        text = f"**{arguments.kwarg.arg}"
        if arguments.kwarg.annotation is not None:
            text += f": {ast.unparse(arguments.kwarg.annotation)}"
        pieces.append(text)

    return f"({', '.join(pieces)})"


def namedtuple_fields(call: ast.Call) -> list[str] | None:
    function = call.func
    is_namedtuple = (
        isinstance(function, ast.Name)
        and function.id == "namedtuple"
        or isinstance(function, ast.Attribute)
        and function.attr == "namedtuple"
    )
    if not is_namedtuple or len(call.args) < 2:
        return None
    fields = call.args[1]
    if isinstance(fields, ast.Constant) and isinstance(fields.value, str):
        return fields.value.replace(",", " ").split()
    if isinstance(fields, (ast.List, ast.Tuple)):
        values: list[str] = []
        for element in fields.elts:
            if not isinstance(element, ast.Constant) or not isinstance(
                element.value, str
            ):
                return None
            values.append(element.value)
        return values
    return None


def generated_version(module_doc: str | None) -> dict[str, str] | None:
    if not module_doc:
        return None
    match = GENERATED_VERSION_RE.search(module_doc)
    if match:
        return match.groupdict()
    match = PINNED_GENERATED_VERSION_RE.search(module_doc)
    if match:
        result = match.groupdict()
        result["generated_at"] = "deterministic"
        return result
    return None


def parse_module(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    callables: list[dict[str, Any]] = []
    result_types: list[dict[str, Any]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            callables.append(
                {
                    "kind": "async_function"
                    if isinstance(node, ast.AsyncFunctionDef)
                    else "function",
                    "name": node.name,
                    "signature": format_signature(node.args),
                    "doc_summary": (
                        (ast.get_docstring(node) or "").strip().splitlines() or [""]
                    )[0],
                }
            )
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            callables.append(
                {
                    "kind": "class",
                    "name": node.name,
                    "signature": None,
                    "doc_summary": (
                        (ast.get_docstring(node) or "").strip().splitlines() or [""]
                    )[0],
                }
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            fields = namedtuple_fields(value)
            if fields is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    result_types.append({"name": target.id, "fields": fields})

    return {
        "file": path.name,
        "sha256": sha256(path),
        "generated_starlink": generated_version(ast.get_docstring(tree)),
        "public_callables": sorted(callables, key=lambda item: item["name"]),
        "public_result_types": sorted(result_types, key=lambda item: item["name"]),
    }


def build_manifest(
    source_root: Path,
    *,
    source_label: str,
    package_version: str,
    artifact_path: Path | None,
) -> dict[str, Any]:
    package_root = source_root / "starlink"
    if not package_root.is_dir():
        raise FileNotFoundError(f"Missing starlink package under {source_root}")

    modules = {
        path.stem: parse_module(path)
        for path in sorted(package_root.glob("*.py"))
        if path.name != "__init__.py"
    }
    generated_versions = sorted(
        {
            json.dumps(module["generated_starlink"], sort_keys=True)
            for module in modules.values()
            if module["generated_starlink"] is not None
        }
    )

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "source": {
            "label": source_label,
            "package_version": package_version,
            "artifact": str(artifact_path) if artifact_path else None,
            "artifact_sha256": sha256(artifact_path) if artifact_path else None,
        },
        "package": "starlink",
        "namespace_initialization": "pkgutil.extend_path",
        "modules": modules,
        "generated_starlink_versions": [
            json.loads(item) for item in generated_versions
        ],
        "wrapper_contract": {
            "environment_entry_points": [
                "STARLINK_DIR",
                "starlink.wrapper.change_starpath",
                "starlink.wrapper.set_HDS_version",
            ],
            "special_keywords": ["returnstdout"],
            "reserved_parameter_rule": "append '_' to Python reserved words",
            "result_behavior": (
                "Starlink application calls return namedtuple-like ADAM parameter "
                "results; returnstdout=True returns (result, stdout)."
            ),
        },
    }
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest(
        args.source_root.resolve(),
        source_label=args.source_label,
        package_version=args.package_version,
        artifact_path=args.artifact.resolve() if args.artifact else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
