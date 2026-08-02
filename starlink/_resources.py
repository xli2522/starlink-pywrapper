"""Small importlib.resources compatibility helpers."""

from __future__ import annotations

from importlib.resources import files
import os


def resource_filename(package: str, relative_name: str) -> str:
    """Return the installed path for one package resource.

    Wheels are installed as ordinary directories by supported Python package
    installers, so this preserves the path-based behavior expected by
    ``starhelp`` without depending on deprecated ``pkg_resources``.
    """

    return os.fspath(files(package).joinpath(relative_name))
