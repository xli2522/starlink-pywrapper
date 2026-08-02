"""Validated child-process environments for current Starlink installations."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping


class StarlinkEnvironmentError(RuntimeError):
    """Raised when a Starlink installation cannot provide a safe environment."""


GENERATED_STARLINK_RELEASE = "2025A"


_HOST_ENV_ALLOWLIST = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "TMPDIR",
    "USER",
)

_CAPTURE_SCRIPT = 'source "$STARLINK_PROFILE" >/dev/null && env -0'
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_FIXED_PROFILE_KEYS = {"PATH", "STARLINK_DIR", "STARLINK_PROFILE"}
_UNSAFE_PROFILE_KEYS = {
    "BASHOPTS",
    "BASH_ENV",
    "CDPATH",
    "ENV",
    "GLOBIGNORE",
    "IFS",
    "LD_AUDIT",
    "LD_PRELOAD",
    "SHELLOPTS",
}


def _parse_nul_environment(payload: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for record in payload.split(b"\0"):
        if not record or b"=" not in record:
            continue
        key, value = record.split(b"=", 1)
        result[key.decode("utf-8", "surrogateescape")] = value.decode(
            "utf-8", "surrogateescape"
        )
    return result


def _validated_profile_overrides(
    values: Mapping[str, str] | None,
) -> dict[str, str]:
    """Return diagnostic profile inputs that cannot alter shell startup."""

    result: dict[str, str] = {}
    for raw_key, raw_value in (values or {}).items():
        key = str(raw_key)
        value = str(raw_value)
        if key.startswith("BASH_FUNC_"):
            raise StarlinkEnvironmentError(
                f"Profile environment variable {key!r} may alter shell startup"
            )
        if not _ENVIRONMENT_NAME.fullmatch(key):
            raise StarlinkEnvironmentError(
                f"Invalid profile environment variable name: {key!r}"
            )
        if "\0" in value:
            raise StarlinkEnvironmentError(
                f"Profile environment variable {key!r} contains a NUL byte"
            )
        if key in _FIXED_PROFILE_KEYS:
            # These values are selected from the validated installation below.
            continue
        if key in _UNSAFE_PROFILE_KEYS:
            raise StarlinkEnvironmentError(
                f"Profile environment variable {key!r} may alter shell startup"
            )
        result[key] = value
    return result


def validate_starlink_installation(starlink_dir: os.PathLike[str] | str) -> Path:
    """Return a resolved root after checking the files needed by the wrapper."""

    root = Path(starlink_dir).expanduser().resolve()
    if not root.is_dir():
        raise StarlinkEnvironmentError(
            f"Starlink installation directory does not exist: {root}"
        )

    profile = root / "etc" / "profile"
    if not profile.is_file():
        raise StarlinkEnvironmentError(
            f"Starlink installation is missing etc/profile: {profile}"
        )

    parget = root / "bin" / "kappa" / "parget"
    if not parget.is_file():
        raise StarlinkEnvironmentError(
            f"Starlink installation is missing the required parget executable: "
            f"{parget}"
        )
    if not os.access(parget, os.X_OK):
        raise StarlinkEnvironmentError(
            f"Starlink parget is not executable: {parget}"
        )
    return root


def read_starlink_release(starlink_dir: os.PathLike[str] | str) -> str | None:
    """Read a release label when the installation provides its manifest."""

    root = validate_starlink_installation(starlink_dir)
    manifest = root / "manifests" / "starlink.version"
    if not manifest.is_file():
        return None
    try:
        first_line = manifest.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError, UnicodeError) as exc:
        raise StarlinkEnvironmentError(
            f"Unable to read Starlink release manifest: {manifest}"
        ) from exc
    return first_line or None


def capture_starlink_environment(
    starlink_dir: os.PathLike[str] | str,
    *,
    extra_profile_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Source the trusted Starlink profile and return its child environment.

    The profile path is passed through the environment to a fixed shell
    program.  It is never interpolated into shell text, so whitespace,
    non-ASCII characters, and shell metacharacters in the installation path
    cannot extend the command.
    """

    root = validate_starlink_installation(starlink_dir)
    profile = root / "etc" / "profile"

    profile_overrides = _validated_profile_overrides(extra_profile_environment)
    profile_env = {
        key: value for key, value in os.environ.items() if key in _HOST_ENV_ALLOWLIST
    }
    profile_env.update(profile_overrides)
    profile_env["PATH"] = "/usr/bin:/bin"
    profile_env["STARLINK_PROFILE"] = str(profile)
    # The official relocatable profile selects all package and library paths
    # from STARLINK_DIR while it is being sourced.
    profile_env["STARLINK_DIR"] = str(root)

    try:
        completed = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", _CAPTURE_SCRIPT],
            env=profile_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise StarlinkEnvironmentError(
            f"Unable to start the fixed shell used for {profile}: {exc}"
        ) from exc

    if completed.returncode:
        stderr = completed.stderr.decode("utf-8", "replace")
        raise StarlinkEnvironmentError(
            f"Starlink profile failed with status {completed.returncode}: "
            f"{profile}\n{stderr}"
        )

    child = _parse_nul_environment(completed.stdout)
    # Starlink's Python scripts use ``#!/usr/bin/env python3``.  Prefer the
    # interpreter running this wrapper (including its virtual environment)
    # without leaking the caller's arbitrary PATH into child processes.
    python_bin = str(Path(sys.executable).absolute().parent)
    child_path = child.get("PATH", "/usr/bin:/bin")
    child["PATH"] = os.pathsep.join(
        [python_bin] + [
            entry for entry in child_path.split(os.pathsep)
            if entry and entry != python_bin
        ]
    )
    child.pop("STARLINK_PROFILE", None)
    for key in profile_overrides:
        child.pop(key, None)
    child["STARLINK_DIR"] = str(root)
    return child


def configure_session_environment(
    captured: Mapping[str, str],
    adam_dir: os.PathLike[str] | str,
    temp_dir: os.PathLike[str] | str,
    *,
    noprompt: bool = True,
) -> dict[str, str]:
    """Add isolated wrapper-session state to a captured Starlink environment."""

    result = dict(captured)
    # Do not resolve symlinks here.  Starlink/HDS has a 132-character path
    # limit, so callers may intentionally provide a short absolute alias for
    # owned scratch storage at a longer physical location.
    adam_path = Path(adam_dir).expanduser().absolute()
    temp_path = Path(temp_dir).expanduser().absolute()
    result["ADAM_USER"] = str(adam_path)
    result["AGI_USER"] = result["ADAM_USER"]
    result["STAR_TEMP"] = str(temp_path)
    result["MSG_SZOUT"] = "0"
    result["ADAM_EXIT"] = "1"
    if noprompt:
        result["ADAM_NOPROMPT"] = "1"
        result["STARUTIL_NOPROMPT"] = "1"
    return result
