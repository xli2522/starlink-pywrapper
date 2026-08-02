"""Starlink application result adapters.

The default adapter asks the installed Starlink ``parget`` command for values
described by generator metadata.  The old HDS reader remains available as an
explicit, lazily imported compatibility backend.
"""

from __future__ import annotations

import csv
from collections import namedtuple
from dataclasses import dataclass
import importlib
from keyword import iskeyword
import os
import subprocess
import time
from typing import Callable, Iterable, Mapping, Sequence


class ResultBackendError(RuntimeError):
    """Raised when an application result cannot be retrieved safely."""


class _ResultBackendTimeoutError(ResultBackendError):
    """Internal timeout detail translated by the public command runner."""

    def __init__(
        self,
        argv: Sequence[str],
        timeout: float,
        stdout: bytes | str | None = None,
        stderr: bytes | str | None = None,
    ) -> None:
        self.argv = tuple(argv)
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"Timed out after {timeout} seconds while retrieving "
            f"{' '.join(argv)}"
        )


@dataclass(frozen=True)
class ParameterSpec:
    """Generator-provided information needed to retrieve one ADAM parameter."""

    name: str
    starlink_type: str
    is_vector: bool = False
    access: str | None = None

    @classmethod
    def coerce(cls, value: "ParameterSpec | Sequence[object]") -> "ParameterSpec":
        if isinstance(value, cls):
            return value
        try:
            name, starlink_type, is_vector, access = value
        except (TypeError, ValueError) as exc:
            raise ResultBackendError(
                f"Invalid generated parameter metadata: {value!r}"
            ) from exc
        return cls(str(name), str(starlink_type), bool(is_vector), str(access))


_INTEGER_TYPES = {
    "_BYTE",
    "_UBYTE",
    "_WORD",
    "_UWORD",
    "_INTEGER",
    "_INT64",
}
_FLOAT_TYPES = {"_REAL", "_DOUBLE", "DOUBLE", "ERROR"}
_STRING_TYPES = {"_CHAR", "LITERAL", "FILENAME", "NDF", "TRN", "DEVICE", "GRAPHICS", "HDSOBJECT", "UNIV", "UNIVERSAL", "IRCAM"}
_LOGICAL_TYPES = {"_LOGICAL"}


def _strip_matching_quotes(value: str) -> str:
    value = value.strip()
    value = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _split_vector(value: str) -> list[str]:
    value = value.strip()
    value = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if not value.strip():
        return []
    return next(
        csv.reader(
            [value],
            delimiter=",",
            quotechar="'",
            skipinitialspace=True,
        )
    )


def _convert_scalar(value: str, starlink_type: str) -> object:
    normalized_type = starlink_type.strip().strip("'\"").upper()
    stripped = value.strip()
    if normalized_type in _INTEGER_TYPES:
        return int(stripped)
    if normalized_type in _FLOAT_TYPES:
        return float(stripped.replace("D", "E").replace("d", "e"))
    if normalized_type in _LOGICAL_TYPES:
        logical = stripped.strip(".").upper()
        if logical in {"TRUE", "T", "YES", "Y", "1"}:
            return True
        if logical in {"FALSE", "F", "NO", "N", "0"}:
            return False
        raise ResultBackendError(
            f"Cannot convert {value!r} to Starlink logical"
        )
    if normalized_type in _STRING_TYPES:
        return _strip_matching_quotes(stripped)
    raise ResultBackendError(
        f"Unsupported generated Starlink parameter type: {starlink_type!r}"
    )


def convert_parget_value(
    value: str, starlink_type: str, is_vector: bool
) -> object:
    """Convert canonical ``parget`` text using generator metadata only."""

    if is_vector:
        return [_convert_scalar(item, starlink_type) for item in _split_vector(value)]
    return _convert_scalar(value, starlink_type)


def _field_name(name: str) -> str:
    result = name.lower()
    if iskeyword(result):
        result += "_"
    return result


def _looks_absent(stdout: str, stderr: str) -> bool:
    message = f"{stdout}\n{stderr}".lower()
    return any(
        marker in message
        for marker in (
            "is undefined",
            "undefined parameter",
            "parameter is null",
            "null parameter",
            "has no value",
            "not active",
            "there is no parameter",
        )
    )


class PargetBackend:
    """Read represented ADAM values through Starlink's own ``parget``."""

    name = "parget"

    def __init__(self, run: Callable[..., subprocess.CompletedProcess[bytes]] | None = None):
        self._run = run or subprocess.run
        self.invocations: list[list[str]] = []

    def read(
        self,
        command_name: str,
        parameters: Iterable[ParameterSpec | Sequence[object]],
        env: Mapping[str, str],
        *,
        timeout: float | None = None,
        cwd: os.PathLike[str] | str | None = None,
    ) -> object:
        try:
            parget = os.path.join(env["KAPPA_DIR"], "parget")
        except KeyError as exc:
            raise ResultBackendError(
                "The captured Starlink environment does not define KAPPA_DIR"
            ) from exc

        values: list[object] = []
        fields: list[str] = []
        deadline = None if timeout is None else time.monotonic() + timeout
        for raw_spec in parameters:
            spec = ParameterSpec.coerce(raw_spec)
            argv = [
                parget,
                f"parname={spec.name}",
                f"applic={command_name}",
                "vector=yes",
            ]
            self.invocations.append(argv)
            current_timeout = timeout
            if deadline is not None:
                current_timeout = max(0.0, deadline - time.monotonic())
                if current_timeout == 0.0:
                    raise _ResultBackendTimeoutError(
                        argv, timeout or 0.0
                    )
            try:
                completed = self._run(
                    argv,
                    env=dict(env),
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=current_timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise _ResultBackendTimeoutError(
                    argv,
                    current_timeout or 0.0,
                    exc.stdout,
                    exc.stderr,
                ) from exc
            except OSError as exc:
                raise ResultBackendError(
                    f"Unable to retrieve {command_name}.{spec.name} with parget: "
                    f"{exc}"
                ) from exc

            stdout = completed.stdout.decode("utf-8", "replace")
            stderr = completed.stderr.decode("utf-8", "replace")
            if completed.returncode:
                if _looks_absent(stdout, stderr):
                    continue
                raise ResultBackendError(
                    f"parget failed for {command_name}.{spec.name} with status "
                    f"{completed.returncode}:\n{stdout}{stderr}"
                )

            fields.append(_field_name(spec.name))
            values.append(
                convert_parget_value(stdout.rstrip("\r\n"), spec.starlink_type,
                                     spec.is_vector)
            )

        result_type = namedtuple(command_name, fields)

        class StarResults(result_type):
            __slots__ = ()

            def __repr__(self) -> str:
                from .hdsutils import _hdstrace_print

                return _hdstrace_print(self)

        return StarResults(*values)


class LegacyHdsBackend:
    """Compatibility adapter for a separately installed legacy HDS reader."""

    name = "legacy_hds"

    def __init__(self, import_module: Callable[[str], object] = importlib.import_module):
        self._import_module = import_module

    def read(
        self,
        command_name: str,
        parameters: Iterable[ParameterSpec | Sequence[object]],
        env: Mapping[str, str],
        **_: object,
    ) -> object:
        del parameters
        try:
            hdsutils = self._import_module("starlink.hdsutils")
            return hdsutils.get_adam_hds_values(
                command_name, os.fspath(env["ADAM_USER"])
            )
        except (ImportError, ModuleNotFoundError) as exc:
            raise ResultBackendError(
                "The legacy HDS backend was requested, but a compatible "
                "starlink.hds module is not installed"
            ) from exc
