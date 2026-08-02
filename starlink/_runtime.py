"""Modern internal execution path, installed into :mod:`starlink.wrapper`.

Keeping this implementation in a separate module limits changes to the old
ORAC-DR and Picard helpers while their public entry points remain in
``wrapper.py``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import signal
import shlex
import subprocess
import tempfile
import time
from typing import Iterable, Mapping, MutableMapping, Sequence

from ._environment import (
    GENERATED_STARLINK_RELEASE,
    StarlinkEnvironmentError,
    capture_starlink_environment,
    configure_session_environment,
    read_starlink_release,
)
from ._results import (
    LegacyHdsBackend,
    PargetBackend,
    ResultBackendError,
    _ResultBackendTimeoutError,
)


logger = logging.getLogger(__name__)
_wrapper_globals: MutableMapping[str, object] | None = None
_adam_directory: tempfile.TemporaryDirectory[str] | None = None
_star_temp_directory: tempfile.TemporaryDirectory[str] | None = None
_default_result_backend = "parget"
_ENVIRONMENT_REFERENCE = re.compile(
    r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|"
    r"(?P<plain>[A-Za-z_][A-Za-z0-9_]*))"
)


class StarlinkApplicationUnavailableError(RuntimeError):
    """An upstream Starlink release removed a preserved wrapper entry point."""


class StarlinkCommandError(RuntimeError):
    """A failed Starlink child process with complete captured diagnostics."""

    def __init__(
        self,
        argv: Sequence[str],
        returncode: int | None,
        stdout: str,
        stderr: str,
        *,
        cwd: os.PathLike[str] | str | None,
        adam_dir: os.PathLike[str] | str,
        message: str | None = None,
    ) -> None:
        self.argv = tuple(os.fspath(item) for item in argv)
        self.command = self.argv[0] if self.argv else ""
        self.arguments = self.argv[1:]
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.cwd = os.fspath(cwd) if cwd is not None else os.getcwd()
        self.adam_dir = os.fspath(adam_dir)
        summary = message or (
            f"Starlink command failed with status {returncode}: "
            f"{' '.join(self.argv)}"
        )
        super().__init__(f"{summary}\nstdout:\n{stdout}\nstderr:\n{stderr}")


class StarlinkTimeoutError(StarlinkCommandError, TimeoutError):
    """A Starlink command exceeded its caller-supplied timeout."""


def _ensure_session_directories() -> tuple[str, str]:
    global _adam_directory, _star_temp_directory
    if _adam_directory is None:
        _adam_directory = tempfile.TemporaryDirectory(prefix="starlink-adam-")
    if _star_temp_directory is None:
        _star_temp_directory = tempfile.TemporaryDirectory(prefix="starlink-temp-")
    return (
        str(Path(_adam_directory.name).expanduser().absolute()),
        str(Path(_star_temp_directory.name).expanduser().absolute()),
    )


def setup_starlink_environ(
    starpath: os.PathLike[str] | str,
    adamdir: os.PathLike[str] | str,
    noprompt: bool = True,
) -> dict[str, str]:
    """Capture a current Starlink profile and add isolated ADAM state."""

    _, temp_dir = _ensure_session_directories()
    captured = capture_starlink_environment(starpath)
    return configure_session_environment(
        captured, adamdir, temp_dir, noprompt=noprompt
    )


def change_starpath(starlinkdir: os.PathLike[str] | str) -> None:
    """Select and validate a Starlink installation for subsequent calls."""

    if _wrapper_globals is None:
        raise RuntimeError("starlink.wrapper modernization was not initialized")
    adam_dir, temp_dir = _ensure_session_directories()
    captured = capture_starlink_environment(starlinkdir)
    configured = configure_session_environment(captured, adam_dir, temp_dir)
    _wrapper_globals["starpath"] = configured["STARLINK_DIR"]
    _wrapper_globals["env"] = configured
    release = read_starlink_release(configured["STARLINK_DIR"])
    if release is not None and release != GENERATED_STARLINK_RELEASE:
        logger.warning(
            "This wrapper was generated for Starlink %s, but %s reports %s; "
            "ordinary calls remain enabled, while strict validation will reject "
            "this mismatch",
            GENERATED_STARLINK_RELEASE,
            configured["STARLINK_DIR"],
            release,
        )


def set_result_backend(name: str) -> None:
    """Select ``parget`` (default) or the optional ``legacy_hds`` adapter."""

    global _default_result_backend
    normalized = str(name).strip().lower()
    if normalized not in {"parget", "legacy_hds"}:
        raise ValueError(
            "result backend must be 'parget' or 'legacy_hds', "
            f"not {name!r}"
        )
    _default_result_backend = normalized


def get_result_backend() -> str:
    """Return the process-wide default result backend name."""

    return _default_result_backend


def _decode(payload: bytes | str | None) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    return payload.decode("utf-8", "replace")


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
        else:
            process.kill()
        process.wait()


def _run_command(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: os.PathLike[str] | str | None,
    timeout: float | None,
    adam_dir: os.PathLike[str] | str,
) -> subprocess.CompletedProcess[bytes]:
    """Run one application as an isolated process group."""

    try:
        process = subprocess.Popen(
            list(argv),
            env=dict(env),
            cwd=cwd,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        raise StarlinkCommandError(
            argv,
            None,
            "",
            str(exc),
            cwd=cwd,
            adam_dir=adam_dir,
            message=f"Unable to start Starlink executable {argv[0]!r}",
        ) from exc

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        stdout, stderr = process.communicate()
        raise StarlinkTimeoutError(
            argv,
            process.returncode,
            _decode(stdout),
            _decode(stderr),
            cwd=cwd,
            adam_dir=adam_dir,
            message=f"Starlink command timed out after {timeout} seconds",
        ) from exc
    except KeyboardInterrupt:
        _terminate_process_group(process)
        process.communicate()
        raise

    completed = subprocess.CompletedProcess(
        list(argv), process.returncode, stdout, stderr
    )
    if completed.returncode:
        raise StarlinkCommandError(
            argv,
            completed.returncode,
            _decode(stdout),
            _decode(stderr),
            cwd=cwd,
            adam_dir=adam_dir,
        )
    return completed


def _expand_command(command: str, env: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group("braced") or match.group("plain")
        return env.get(key, match.group(0))

    return _ENVIRONMENT_REFERENCE.sub(replace, command)


def _quote_subpar_argument(argument: str) -> str:
    """Preserve whitespace when Starlink SUBPAR reparses an argv element."""

    if "=" in argument:
        key, value = argument.split("=", 1)
        prefix = key + "="
    else:
        value = argument
        prefix = ""
    if value.startswith("[") and value.endswith("]"):
        value = value.replace(", ", ",")
        if not any(character.isspace() for character in value):
            return prefix + value
    if not any(character.isspace() for character in value) and "," not in value:
        return argument
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        return argument
    return prefix + '"' + value.replace('"', '""') + '"'


def _remove_parameter_file(adam_dir: str, command_name: str) -> None:
    parameter_file = Path(adam_dir, command_name + ".sdf")
    try:
        parameter_file.unlink()
    except FileNotFoundError:
        pass


def _read_result(
    command_name: str,
    parameters: Iterable[Sequence[object]],
    env: Mapping[str, str],
    *,
    backend: str | None = None,
    timeout: float | None = None,
    cwd: os.PathLike[str] | str | None = None,
) -> object:
    selected = (backend or _default_result_backend).strip().lower()
    if selected == "parget":
        try:
            return PargetBackend().read(
                command_name, parameters, env, timeout=timeout, cwd=cwd
            )
        except _ResultBackendTimeoutError as exc:
            raise StarlinkTimeoutError(
                exc.argv,
                None,
                _decode(exc.stdout),
                _decode(exc.stderr),
                cwd=cwd,
                adam_dir=env.get("ADAM_USER", ""),
                message=(
                    "Starlink result retrieval timed out after "
                    f"{exc.timeout} seconds"
                ),
            ) from exc
    if selected == "legacy_hds":
        return LegacyHdsBackend().read(command_name, parameters, env)
    raise ResultBackendError(f"Unknown result backend: {selected!r}")


def _maybe_create_xwindow(
    kwargs: Mapping[str, object],
    env: Mapping[str, str],
    *,
    cwd: os.PathLike[str] | str | None,
    timeout: float | None,
    adam_dir: str,
) -> None:
    device = kwargs.get("device")
    if not isinstance(device, str):
        return
    names = {
        "xw": "xwindows",
        "x2w": "xwindows2",
        "x3w": "xwindows3",
        "x4w": "xwindows4",
        "xwindows": "xwindows",
        "x2windows": "xwindows2",
        "x3windows": "xwindows3",
        "x4windows": "xwindows4",
    }
    if device.endswith("/GWM"):
        window_name = device.split("/GWM", 1)[0]
    else:
        window_name = names.get(device)
    if window_name:
        _run_command(
            [os.path.join(env["STARLINK_DIR"], "bin", "xmake"), window_name],
            env=env,
            cwd=cwd,
            timeout=timeout,
            adam_dir=adam_dir,
        )


def starcomm(command: str, commandname: str, *args: object, **kwargs: object) -> object:
    """Execute one Starlink application while preserving the legacy call shape."""

    if _wrapper_globals is None:
        raise RuntimeError("starlink.wrapper modernization was not initialized")
    current_env = _wrapper_globals.get("env")
    if not isinstance(current_env, dict):
        raise StarlinkEnvironmentError(
            "No Starlink installation is configured; set STARLINK_DIR before "
            "importing or call starlink.wrapper.change_starpath('/path/to/star')"
        )
    adam_dir = os.fspath(_wrapper_globals["adamdir"])

    normalized = {str(key).lower(): value for key, value in kwargs.items()}
    return_stdout = bool(normalized.pop("returnstdout", False))
    return_stderr = bool(normalized.pop("_starlink_return_stderr", False))
    timeout_value = normalized.pop("_starlink_timeout", None)
    timeout = float(timeout_value) if timeout_value is not None else None
    if timeout is not None and timeout < 0:
        raise ValueError("_starlink_timeout must be non-negative")
    cwd = normalized.pop("_starlink_cwd", None)
    backend = normalized.pop("_starlink_result_backend", None)
    metadata = normalized.pop("_starlink_parameters", ())
    if not isinstance(metadata, Iterable):
        raise TypeError("_starlink_parameters must be iterable generator metadata")

    argument_builder = _wrapper_globals["_legacy_make_argument_list"]
    argument_list = [
        _quote_subpar_argument(argument)
        for argument in argument_builder(*args, **normalized)
    ]
    executable = _expand_command(command, current_env)
    if os.path.exists(executable):
        command_argv = [executable]
    else:
        # Split the trusted generated command template before expansion so an
        # installation path containing whitespace remains within each argv
        # element.  Expansion is single-pass, so dollar signs inside the
        # resolved installation path are not interpreted a second time.
        command_argv = [
            _expand_command(part, current_env) for part in shlex.split(command)
        ]
    if not command_argv:
        raise ValueError("Starlink command cannot be empty")
    argv = command_argv + argument_list
    _remove_parameter_file(adam_dir, commandname)

    started = time.monotonic()
    try:
        _maybe_create_xwindow(
            normalized,
            current_env,
            cwd=cwd,
            timeout=timeout,
            adam_dir=adam_dir,
        )
        runner = _wrapper_globals["_run_command"]
        completed = runner(
            argv,
            env=current_env,
            cwd=cwd,
            timeout=timeout,
            adam_dir=adam_dir,
        )
        elapsed = time.monotonic() - started
        remaining = None if timeout is None else max(0.0, timeout - elapsed)
        reader = _wrapper_globals["_read_result"]
        result = reader(
            commandname,
            metadata,
            current_env,
            backend=backend,
            timeout=remaining,
            cwd=cwd,
        )
        stdout = _decode(completed.stdout)
        stderr = _decode(completed.stderr)
        logger.debug("Starlink command %r completed successfully", argv)
        if return_stdout and return_stderr:
            return result, stdout, stderr
        if return_stdout:
            return result, stdout
        if return_stderr:
            return result, stderr
        return result
    finally:
        _remove_parameter_file(adam_dir, commandname)


def initialize(wrapper_globals: MutableMapping[str, object]) -> None:
    """Install this execution path while leaving old helper APIs in place."""

    global _wrapper_globals
    _wrapper_globals = wrapper_globals
    adam_dir, _ = _ensure_session_directories()
    wrapper_globals["_legacy_make_argument_list"] = wrapper_globals[
        "_make_argument_list"
    ]
    wrapper_globals["adamdir"] = adam_dir
    wrapper_globals["env"] = None
    wrapper_globals["starpath"] = None

    configured = os.environ.get("STARLINK_DIR")
    if configured:
        try:
            change_starpath(configured)
        except StarlinkEnvironmentError as exc:
            logger.warning("Could not configure STARLINK_DIR %r: %s", configured, exc)
