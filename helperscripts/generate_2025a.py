#!/usr/bin/env python3
"""Generate only the existing wrapper packages from pinned Starlink metadata."""

from __future__ import annotations

import argparse
from collections import OrderedDict
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import sys

from ifd_metadata import load_ifd_tree
from metadata_2025a import (
    add_ifd_actions,
    add_existing_callables,
    baseline_signatures,
    discard_untyped_shell_helpers,
    existing_descriptions,
    load_source_vector_parameters,
    parameter_type,
    standalone_ifl_metadata,
)



PINNED_STARLINK_COMMIT = "899c03fc4af3b6feb26756b904e5a597343191ed"
PINNED_STARLINK_RELEASE = "2025A plus Errata Patch 1"

PACKAGES = OrderedDict(
    (
        ("ATOOLS", ("atools.star-hlp", "ATOOLS_DIR")),
        ("CCDPACK", ("ccdpack.hlp", "CCDPACK_DIR")),
        ("CONVERT", ("convert_master.hlp", "CONVERT_DIR")),
        ("CUPID", ("cupid.star-hlp", "CUPID_DIR")),
        ("Figaro", ("figaro.hlp", "FIG_DIR")),
        ("KAPPA", ("kappa_master.hlp", "KAPPA_DIR")),
        ("POLPACK", ("polpack_master.hlp", "POLPACK_DIR")),
        ("SMURF", ("smurf_master.hlp", "SMURF_DIR")),
    )
)

KNOWN_UNINSTALLED_COMMANDS = {
    ("KAPPA", "mem2d"): "$KAPPA_DIR/mem2d",
}


def _load_legacy_generator(repo: Path):
    path = repo / "helperscripts" / "generate_functions.py"
    spec = importlib.util.spec_from_file_location("starlink_generator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load generator helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _command_executable_path(
    command: str,
    installation: Path,
    package_name: str,
    environment_name: str,
) -> Path:
    """Resolve the executable token in one validated generated command."""

    tokens = shlex.split(command)
    if not tokens:
        raise RuntimeError(f"Empty command mapping for {package_name}")
    executable = tokens[0]
    roots = (
        (f"${environment_name}", installation / "bin" / package_name.lower()),
        (
            f"${{{environment_name}}}",
            installation / "bin" / package_name.lower(),
        ),
        ("$STARLINK_DIR", installation),
        ("${STARLINK_DIR}", installation),
    )
    for prefix, root in roots:
        if executable.startswith(prefix + "/"):
            return root / executable[len(prefix) + 1 :]
    raise RuntimeError(
        f"Cannot resolve generated executable for {package_name}: {command}"
    )


def _filter_uninstalled_commands(
    command_paths,
    module_info,
    installation: Path,
    package_name: str,
    environment_name: str,
    baseline_names,
):
    """Reject missing public commands and omit audited unavailable additions."""

    retained_paths = dict(command_paths)
    retained_info = dict(module_info)
    for name, command in command_paths.items():
        if command.startswith("__REMOVED__:"):
            continue
        executable = _command_executable_path(
            command, installation, package_name, environment_name
        )
        if executable.is_file() and os.access(executable, os.X_OK):
            continue
        if name in baseline_names:
            raise RuntimeError(
                f"Existing public command is not executable in the pinned "
                f"installation: {package_name}.{name}: {executable}"
            )
        expected = KNOWN_UNINSTALLED_COMMANDS.get((package_name, name))
        if expected != command:
            raise RuntimeError(
                f"Generated command is not executable in the pinned "
                f"installation: {package_name}.{name}: {executable}"
            )
        retained_paths.pop(name)
        retained_info.pop(name, None)
    return retained_paths, retained_info


def _verify_source(source: Path) -> None:
    completed = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    actual = completed.stdout.strip()
    if actual != PINNED_STARLINK_COMMIT:
        raise RuntimeError(
            f"Starlink source must be pinned to {PINNED_STARLINK_COMMIT}, "
            f"not {actual}"
        )


def _parinfo(
    generator,
    package_name: str,
    command_name: str,
    name: str,
    fields: dict[str, str],
    fallback=None,
    source_is_vector: bool = False,
):
    def value(field: str, attribute: str | None = None):
        if field in fields:
            return fields[field]
        if fallback is None:
            return None
        return getattr(fallback, attribute or field)

    size = fields.get("size")
    if size is None:
        is_list = source_is_vector or bool(
            fallback is not None and fallback.list_
        )
    else:
        is_list = size.strip() not in {"", "1"}
    access = value("access")
    if not access and fallback is not None:
        access = fallback.readwrite
    access = access or "UPDATE"
    return generator.parinfo(
        name,
        parameter_type(package_name, command_name, name, fields),
        value("prompt"),
        value("default"),
        value("position"),
        value("range", "range_"),
        value("in", "in_"),
        access,
        value("association"),
        value("ppath"),
        value("vpath"),
        is_list,
        access.lower(),
    )


def _merge_ifd_metadata(
    generator,
    module_info,
    ifd_actions,
    package_name: str,
    source_vectors=None,
):
    source_vectors = source_vectors or {}
    merged = {}
    for name, info in module_info.items():
        if name in ifd_actions:
            help_parameters = info.pardict or {}
            parameters = OrderedDict(
                (
                    parameter_name,
                    _parinfo(
                        generator,
                        package_name,
                        name,
                        parameter_name,
                        fields,
                        help_parameters.get(parameter_name),
                        parameter_name in source_vectors.get(name, set()),
                    ),
                )
                for parameter_name, fields in ifd_actions[name].items()
            )
            info = generator.commandinfo(
                info.name, info.description, parameters, info.longdescription
            )
        elif info.pardict:
            missing = [
                parameter.name
                for parameter in info.pardict.values()
                if not parameter.type_
            ]
            if missing:
                raise RuntimeError(
                    f"No typed 2025A interface metadata for {name}: "
                    f"{', '.join(missing)}"
                )
            vector_parameters = source_vectors.get(name, set())
            if vector_parameters:
                parameters = OrderedDict(
                    (
                        parameter_name,
                        parameter._replace(list_=True)
                        if parameter_name in vector_parameters
                        else parameter,
                    )
                    for parameter_name, parameter in info.pardict.items()
                )
                info = generator.commandinfo(
                    info.name,
                    info.description,
                    parameters,
                    info.longdescription,
                )
        merged[name] = info
    return merged


def generate(source: Path, installation: Path, output: Path, repo: Path) -> None:
    _verify_source(source)
    generator = _load_legacy_generator(repo)
    generator.moduleline = (
        "Runs commands from the Starlink {} package.\n\n"
        "Autogenerated from pinned Starlink interface and help metadata by "
        "starlink-pywrapper/helperscripts/generate_2025a.py.\n\n"
        f"Starlink version: {PINNED_STARLINK_RELEASE}\n"
        f"Source commit: {PINNED_STARLINK_COMMIT}"
    )

    output.mkdir(parents=True, exist_ok=True)
    previous = Path.cwd()
    try:
        os.chdir(output)
        for package, (help_name, environment_name) in PACKAGES.items():
            package_name = package.lower()
            source_root = source / "applications" / package_name
            help_path = source_root / help_name
            script_path = (
                installation / "bin" / package_name / f"{package_name}.sh"
            )
            if not help_path.is_file():
                raise FileNotFoundError(help_path)
            if not script_path.is_file():
                raise FileNotFoundError(script_path)

            descriptions = existing_descriptions(repo, package_name)
            signature_overrides = baseline_signatures(repo, package_name)
            ifd_actions = load_ifd_tree(source_root)
            source_vectors = load_source_vector_parameters(
                source_root, package_name
            )
            module_info = generator.get_module_info(
                help_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines(True),
                str(source_root),
                create_longhelp=False,
            )
            if package_name in module_info:
                module_info.pop(package_name)
            for help_command in (
                package_name + "_help",
                package_name[:3] + "help",
            ):
                module_info.pop(help_command, None)

            if ifd_actions:
                module_info = add_ifd_actions(
                    generator, module_info, ifd_actions, descriptions, package_name
                )
            elif not module_info:
                module_info = standalone_ifl_metadata(
                    generator, source_root, descriptions, package_name
                )
            module_info = add_existing_callables(
                generator, module_info, descriptions, package_name
            )
            module_info = discard_untyped_shell_helpers(
                module_info, ifd_actions
            )

            command_paths = generator.get_command_paths(
                script_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines(True),
                module_info.keys(),
                package,
            )
            module_info = {
                name: info for name, info in module_info.items()
                if name in command_paths
            }
            module_info = _merge_ifd_metadata(
                generator,
                module_info,
                ifd_actions,
                package_name,
                source_vectors,
            )

            removed_commands = {
                ("Figaro", "exam"): (
                    "echo 'The EXAM command has been removed.  "
                    "Please use HDSTRACE instead.'",
                    "Starlink 2025A removed FIGARO EXAM; use HDSTRACE instead.",
                ),
            }
            for name in list(command_paths):
                command = command_paths[name]
                if not command.startswith("echo "):
                    continue
                known = removed_commands.get((package, name))
                if known is not None:
                    expected, message = known
                    if command != expected:
                        raise RuntimeError(
                            f"Unexpected removal mapping for {package}.{name}: "
                            f"{command}"
                        )
                    command_paths[name] = "__REMOVED__:" + message
                elif name in descriptions:
                    raise RuntimeError(
                        f"Existing public command was removed by Starlink 2025A: "
                        f"{package}.{name}: {command}"
                    )
                else:
                    command_paths.pop(name)
                    module_info.pop(name, None)
            expected_prefix = "$" + environment_name + "/"
            for name, command in command_paths.items():
                if (
                    not command.startswith(expected_prefix)
                    and not command.startswith("${" + environment_name + "}/")
                    and not command.startswith("__REMOVED__:")
                    and not command.startswith("${STARLINK_DIR}/")
                ):
                    raise RuntimeError(
                        f"Unexpected command mapping for {package}.{name}: {command}"
                    )
            command_paths, module_info = _filter_uninstalled_commands(
                command_paths,
                module_info,
                installation,
                package,
                environment_name,
                signature_overrides,
            )

            docs = generator.make_docstrings(
                module_info,
                generator.sunnames.get(package_name),
                kstyle="numpy",
            )
            names = sorted(command_paths)
            generator.create_module(
                package, names, docs, command_paths, module_info,
                signature_overrides=signature_overrides
            )
    finally:
        os.chdir(previous)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    generate(
        args.source.resolve(),
        args.installation.resolve(),
        args.output.resolve(),
        repo,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
