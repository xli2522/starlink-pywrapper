# Copyright (C) 2016 East Asian Observatory
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Convenience helpers for generated Starlink modules."""

from __future__ import annotations

from inspect import getmembers, isfunction
import os
import pydoc
from types import FunctionType, ModuleType

from ._fits import (
    get_ndf_fitshdr as _get_ndf_fitshdr,
    get_ndf_fitshdr_legacy,
)
from ._resources import resource_filename


def get_ndf_fitshdr(datafile):
    """Return an Astropy FITS header from an NDF through KAPPA ``fitslist``.

    The selected Starlink installation reads the NDF, so both HDS-v4 and
    HDS-v5 files supported by that installation can be handled without a
    mandatory Python HDS binding. Astropy is imported only when this function
    is called. Use :func:`get_ndf_fitshdr_legacy` to request the old direct
    Python-HDS path explicitly.
    """

    return _get_ndf_fitshdr(datafile)


def get_module_function_summary(module):
    """Return a sorted one-line summary of documented module functions."""

    summaries = {}
    for name, function in getmembers(module, isfunction):
        lines = (function.__doc__ or "").strip().splitlines()
        summaries[name] = lines[0] if lines else "(no summary available)"
    if not summaries:
        return ""
    width = max(map(len, summaries))
    return "\n".join(
        f"{name:<{width + 1}}: {summaries[name]}" for name in sorted(summaries)
    )


def starhelp(myobj):
    """Display generated long help for a wrapper module or function."""

    if isinstance(myobj, ModuleType):
        document = get_module_function_summary(myobj)
    elif isinstance(myobj, FunctionType):
        parts = myobj.__module__.split(".")
        if len(parts) < 2:
            raise ValueError(f"Cannot determine Starlink module for {myobj!r}")
        relative = os.path.join(parts[1] + "_help", myobj.__name__ + ".rst")
        filename = resource_filename(myobj.__module__, relative)
        if not os.path.isfile(filename):
            raise FileNotFoundError(f"starhelp resource does not exist: {filename}")
        with open(filename, encoding="utf-8") as handle:
            document = handle.read()
    else:
        raise TypeError(
            f"starhelp requires a Starlink module or function, not {myobj!r}"
        )
    pydoc.pager(document)
