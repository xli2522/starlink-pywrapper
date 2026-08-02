# Copyright (C) 2013-2014 Science and Technology Facilities Council.
# Copyright (C) 2015-2018 East Asian Observatory
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


"""Public interface for running external Starlink applications.

Generated package modules call :func:`starcomm`. This module also preserves
the historical ORAC-DR, Picard, environment-selection, and argument helper
entry points from starlink-pywrapper 0.3. Process management and result
retrieval live in private modules so there is only one execution path.
"""

from __future__ import annotations

from collections import namedtuple
import glob
import logging
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from typing import Iterable


logger = logging.getLogger(__name__)
default_starpath = None

# Return type and field order are part of the 0.3 compatibility surface.
oracoutput = namedtuple(
    "oracoutput", "runlog outdir datafiles imagefiles logfiles status pid"
)


class StarError(Exception):
    """Historical generic Starlink exception retained for compatibility."""

    def __init__(self, command, arg, stderr):
        message = f"Starlink error occurred during:\n {command} {arg}\n"
        message += str(stderr)
        super().__init__(message)


def subprocess_setup():
    """Restore the signal defaults expected by non-Python child programs."""

    signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def _make_argument_list(*args, **kwargs):
    """Serialize ordinary Python arguments using the historical call shape."""

    output = [str(value) for value in args]
    for key, value in kwargs.items():
        if key.endswith("_"):
            key = key[:-1]
        output.append(f"{key}={value}")
    return output


# Imported after ``_make_argument_list`` so the runtime can register the
# preserved serializer when it initializes this module.
from . import _runtime as _runtime  # noqa: E402
from ._environment import StarlinkEnvironmentError  # noqa: E402

StarlinkCommandError = _runtime.StarlinkCommandError
StarlinkTimeoutError = _runtime.StarlinkTimeoutError
StarlinkApplicationUnavailableError = _runtime.StarlinkApplicationUnavailableError
_run_command = _runtime._run_command
_read_result = _runtime._read_result
set_result_backend = _runtime.set_result_backend
get_result_backend = _runtime.get_result_backend


def setup_starlink_environ(starpath, adamdir, noprompt=True):
    """Create a child-process environment for a Starlink installation.

    Parameters
    ----------
    starpath : path-like
        Root directory of an existing Starlink installation.
    adamdir : path-like
        Absolute directory used for the child applications' ADAM state.
    noprompt : bool, optional
        Disable interactive Starlink parameter prompting when true.

    Returns
    -------
    dict
        Environment variables captured from the installation's validated
        ``etc/profile`` and supplemented with isolated ADAM and temporary state.

    The parent Python environment is not modified.
    """

    return _runtime.setup_starlink_environ(starpath, adamdir, noprompt)


def change_starpath(starlinkdir):
    """Select the Starlink installation used by subsequent wrapper calls.

    This preserves the historical ``change_starpath`` entry point and updates
    the module-level ``starpath`` and ``env`` values. The supplied directory is
    validated and its official ``etc/profile`` is loaded. The wrapper does not
    search for, install, or modify Starlink.
    """

    return _runtime.change_starpath(starlinkdir)


def starcomm(command, commandname, *args, **kwargs):
    """Execute a Starlink application using the preserved 0.3 call shape.

    Parameters
    ----------
    command : str
        Executable path or trusted generated command template, for example
        ``"$KAPPA_DIR/stats"``.
    commandname : str
        Starlink application name used when retrieving output parameters.
    *args
        Positional Starlink parameters.
    **kwargs
        Keyword Starlink parameters. Names reserved by Python retain the
        historical trailing underscore convention, such as ``in_`` for ``IN``.

    Wrapper options
    ---------------
    returnstdout : bool, optional
        Return captured standard output alongside the application result.
    _starlink_timeout : float, optional
        Maximum number of seconds shared by application execution and result
        retrieval.
    _starlink_return_stderr : bool, optional
        Return captured standard error alongside the application result.
    _starlink_cwd : path-like, optional
        Working directory for the child process.

    Returns
    -------
    namedtuple or tuple
        Generated parameter metadata is used with Starlink's ``parget`` command
        to construct the historical namedtuple-like result. Requested standard
        output or error strings are appended in a tuple.

    Raises
    ------
    StarlinkEnvironmentError
        If no usable Starlink installation has been selected.
    StarlinkCommandError
        If the application cannot start or exits unsuccessfully.
    StarlinkTimeoutError
        If execution or result retrieval exceeds the requested timeout.

    Examples
    --------
    >>> result = starcomm("$KAPPA_DIR/stats", "stats", ndf="myndf.sdf")
    >>> result = starcomm("$KAPPA_DIR/stats", "stats", in_="myndf.sdf")
    """

    return _runtime.starcomm(command, commandname, *args, **kwargs)

# Populated by ``initialize``: these names remain observable for 0.3 callers.
starpath = None
env = None
adamdir = None
_runtime.initialize(globals())


def set_HDS_version(version):
    """Set ``HDS_VERSION`` in the environment used by child applications.

    The default remains the value selected by the Starlink installation. This
    function changes only the wrapper's isolated child environment and does not
    modify the parent process environment.
    """

    if not isinstance(env, dict):
        raise StarlinkEnvironmentError(
            "No Starlink installation is configured; call change_starpath() first"
        )
    env["HDS_VERSION"] = str(version)


JCMTINST = ["ACSIS", "SCUBA2_850", "SCUBA2_450", "SCUBA", "JCMTDAS"]
UKIRTINST = [
    "CGS4", "CLASSICCAM", "GMOS", "INGRID", "IRCAM2", "IRCAM", "IRIS2",
    "ISAAC", "MICHELLE", "NACO", "OCGS4", "SOFI", "SPEX", "START",
    "UFTI", "UFTI_OLD",
]
ORACDR_DATA_IN_PATHS = {
    "ACSIS": "/jcmtdata/raw/acsis/spectra",
    "SCUBA2": "/jcmtdata/raw/scuba2/ok",
}


def _configured_environment() -> dict[str, str]:
    if not isinstance(env, dict):
        raise StarlinkEnvironmentError(
            "No Starlink installation is configured; call change_starpath() first"
        )
    return env.copy()


def oracdr_envsetup(
    instrument,
    utdate=None,
    ORAC_DIR=None,
    ORAC_DATA_IN=None,
    ORAC_DATA_OUT=None,
    ORAC_CAL_ROOT=None,
    ORAC_DATA_CAL=None,
    ORAC_PERL5LIB=None,
):
    """Return an ORAC-DR environment based on the selected Starlink.

    The configured wrapper environment is copied before ORAC-DR paths are
    added, so this helper does not mutate the environment used by ordinary
    Starlink application calls.
    """

    oracenv = _configured_environment()
    utdate = str(utdate) if utdate is not None else time.strftime("%Y%m%d")
    instrument = str(instrument).upper()
    oracenv["ORAC_INSTRUMENT"] = instrument

    if ORAC_DATA_IN is None:
        if "SCUBA2" in instrument or "SCUBA-2" in instrument:
            ORAC_DATA_IN = os.path.join(ORACDR_DATA_IN_PATHS["SCUBA2"], utdate)
        elif instrument in ORACDR_DATA_IN_PATHS:
            ORAC_DATA_IN = os.path.join(ORACDR_DATA_IN_PATHS[instrument], utdate)
        elif instrument in JCMTINST:
            ORAC_DATA_IN = os.path.join("/jcmtdata/raw", instrument.lower(), utdate)
        elif instrument in UKIRTINST:
            ORAC_DATA_IN = os.path.join("/ukirtdata/raw", instrument.lower(), utdate)
        else:
            ORAC_DATA_IN = "/"

    root = Path(oracenv["STARLINK_DIR"])
    orac_dir = Path(ORAC_DIR).expanduser() if ORAC_DIR else root / "bin/oracdr/src"
    cal_root = (
        Path(ORAC_CAL_ROOT).expanduser()
        if ORAC_CAL_ROOT
        else orac_dir.parent / "cal"
    )
    data_cal = (
        Path(ORAC_DATA_CAL).expanduser()
        if ORAC_DATA_CAL
        else cal_root / ("scuba2" if "SCUBA2" in instrument else instrument.lower())
    )
    oracenv.update(
        {
            "ORAC_DATA_IN": str(Path(ORAC_DATA_IN).expanduser().resolve()),
            "ORAC_DATA_OUT": str(
                Path(ORAC_DATA_OUT or os.getcwd()).expanduser().resolve()
            ),
            "ORAC_DIR": str(orac_dir.resolve()),
            "ORAC_PERL5LIB": str(
                Path(ORAC_PERL5LIB).expanduser().resolve()
                if ORAC_PERL5LIB
                else (orac_dir / "lib/perl5").resolve()
            ),
            "ORAC_CAL_ROOT": str(cal_root.resolve()),
            "ORAC_DATA_CAL": str(data_cal.resolve()),
            "ORAC_LOOP": "flag -skip",
            "STAR_LOGIN": "1",
        }
    )
    return oracenv


def _existing_directory(value, name):
    path = Path(value or os.getcwd()).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"{name} directory does not exist: {path}")
    return path


def _collect_outputs(outputdir: Path, prefix: str, pid: int):
    hidden_log = outputdir / f".{prefix}_{pid}.log"
    output_log = outputdir / f"{prefix}_{pid}.log"
    runlog = None
    if hidden_log.is_file():
        hidden_log.replace(output_log)
        runlog = str(output_log)
    datafiles = sorted(
        str(path)
        for pattern in ("*.sdf", "*.fits", "*.fit", "*.FIT", "*.FITS")
        for path in outputdir.glob(pattern)
        if not path.is_symlink()
    )
    images = sorted(str(path) for path in outputdir.glob("*.png"))
    logs = sorted(str(path) for path in outputdir.glob("log.*"))
    return runlog, datafiles, images, logs


def _run_orac(argv, child_env, outputdir: Path, prefix: str):
    logger.info("Running ORAC command array: %r", argv)
    try:
        process = subprocess.Popen(argv, env=child_env, shell=False)
    except OSError as exc:
        raise StarlinkCommandError(
            argv,
            None,
            "",
            str(exc),
            cwd=outputdir,
            adam_dir=child_env.get("ADAM_USER", ""),
            message=f"Unable to start {prefix}",
        ) from exc
    process.communicate()
    runlog, datafiles, images, logs = _collect_outputs(
        outputdir, prefix, process.pid
    )
    return oracoutput(
        runlog,
        str(outputdir),
        datafiles,
        images,
        logs,
        process.returncode,
        process.pid,
    )


def _read_path_list(list_file: Path) -> list[Path]:
    if not list_file.is_file():
        raise FileNotFoundError(f"Input file list does not exist: {list_file}")
    result = []
    for line in list_file.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = list_file.parent / path
        result.append(path.resolve())
    return result


def _validated_input_paths(values: Iterable[os.PathLike[str] | str], base: Path):
    result = []
    for value in values:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Input data file does not exist: {path}")
        result.append(path)
    if not result:
        raise ValueError("No input data files were supplied")
    return result


def oracdr(
    instrument,
    loop="file",
    dataout=None,
    datain=None,
    recipe=None,
    recpars=None,
    onegroup=False,
    rawfiles=None,
    utdate=None,
    obslist=None,
    headeroverride=None,
    calib=None,
    verbose=False,
    debug=False,
    warn=False,
):
    """Run ORAC-DR on a batch of files.

    Parameters
    ----------
    instrument : str
        Instrument name.
    loop : {"file", "list"}, optional
        Select raw filenames or observation numbers plus a UT date.
    dataout, datain : path-like, optional
        Output and input directories. Both default to the current directory.
    recipe : str, optional
        Recipe name; when omitted, ORAC-DR uses the recipe in the headers.
    recpars : str, optional
        Recipe-parameter filename or literal parameter value.
    onegroup : bool, optional
        Force all observations into one processing group.
    rawfiles : path-like or iterable of path-like, optional
        Input file list for ``loop="file"``. A path to a text list is expanded;
        other relative paths are interpreted beneath ``datain``.
    utdate : int, optional
        Observation date in ``YYYYMMDD`` form for ``loop="list"``.
    obslist : iterable of int, optional
        Observation numbers for ``loop="list"``.
    headeroverride, calib : str, optional
        Header and calibration overrides passed to ORAC-DR.
    verbose, debug, warn : bool, optional
        Enable the corresponding ORAC-DR diagnostic options.

    Returns
    -------
    oracoutput
        Named tuple containing ``runlog``, ``outdir``, ``datafiles``,
        ``imagefiles``, ``logfiles``, ``status``, and ``pid``.

    Notes
    -----
    A non-zero ORAC-DR exit status is returned in ``status`` rather than raised;
    callers should inspect it when failure is significant.
    """

    if loop not in {"file", "list"}:
        raise ValueError('loop must be "file" or "list"')
    if loop == "list" and (utdate is None or not obslist):
        raise ValueError('loop="list" requires both utdate and obslist')
    if loop == "file" and rawfiles is None:
        raise ValueError('loop="file" requires rawfiles')

    parent = _existing_directory(dataout, "ORAC_DATA_OUT")
    input_dir = _existing_directory(datain, "ORAC_DATA_IN")
    outputdir = Path(tempfile.mkdtemp(prefix="ORACworking-", dir=parent))
    oracenv = oracdr_envsetup(
        instrument,
        utdate=utdate,
        ORAC_DATA_IN=str(input_dir),
        ORAC_DATA_OUT=str(outputdir),
    )
    temporary_list = None
    try:
        root = Path(oracenv["STARLINK_DIR"])
        argv = [
            str(root / "Perl/bin/perl"),
            str(Path(oracenv["ORAC_DIR"]) / "bin/oracdr"),
            "-log=sf",
            "-nodisplay",
            "-batch",
            f"-loop={loop}",
        ]
        if loop == "list":
            listed = obslist if isinstance(obslist, str) else ",".join(
                str(int(value)) for value in obslist
            )
            argv.extend((f"-ut={utdate}", f"-list={listed}"))
        else:
            if isinstance(rawfiles, (str, os.PathLike)):
                candidate = Path(rawfiles).expanduser().resolve()
                paths = _read_path_list(candidate)
            else:
                paths = _validated_input_paths(rawfiles, input_dir)
            paths = _validated_input_paths(paths, input_dir)
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="orac-input-",
                suffix=".lis",
                dir=outputdir,
                delete=False,
            )
            temporary_list = Path(handle.name)
            with handle:
                handle.write("\n".join(str(path) for path in paths) + "\n")
            argv.append(f"-files={temporary_list}")

        options = (
            (recpars, "recpars"),
            (headeroverride, "headeroverride"),
            (calib, "calib"),
        )
        argv.extend(f"-{name}={value}" for value, name in options if value is not None)
        if onegroup:
            argv.append("-onegroup")
        if verbose:
            argv.append("-verbose")
        if warn:
            argv.append("-warn")
        if debug:
            argv.append("-debug")
        if recipe:
            argv.append(str(recipe))
        return _run_orac(argv, oracenv, outputdir, "oracdr")
    finally:
        if temporary_list is not None:
            temporary_list.unlink(missing_ok=True)


def picard(
    recipe,
    files,
    dataout=None,
    recpars=None,
    oracdir=None,
    verbose=False,
    debug=False,
    warn=False,
):
    """Run a Picard recipe on a group of files.

    Parameters
    ----------
    recipe : str
        Recipe name.
    files : path-like or iterable of path-like
        Input paths, or a text file containing one input path per line. Relative
        entries in a text list are resolved relative to that list file.
    dataout : path-like, optional
        Parent directory for the temporary Picard output directory.
    recpars : str, optional
        Value passed to Picard's ``--recpars`` option.
    oracdir : path-like, optional
        Custom ORAC-DR source tree; the selected Starlink installation is used
        by default.
    verbose, debug, warn : bool, optional
        Enable the corresponding Picard diagnostic options.

    Returns
    -------
    oracoutput
        Named tuple containing ``runlog``, ``outdir``, ``datafiles``,
        ``imagefiles``, ``logfiles``, ``status``, and ``pid``.

    Input paths are validated and passed as literal argument-array elements;
    no shell or backtick expansion is used.
    """

    parent = _existing_directory(dataout, "ORAC_DATA_OUT")
    outputdir = Path(tempfile.mkdtemp(prefix="PICARDworking-", dir=parent))
    picardenv = _configured_environment()
    root = Path(picardenv["STARLINK_DIR"])
    orac_dir = Path(oracdir).expanduser().resolve() if oracdir else root / "bin/oracdr/src"
    picardenv.update(
        {
            "ORAC_DIR": str(orac_dir),
            "ORAC_PERL5LIB": str(orac_dir / "lib/perl5"),
            "ORAC_DATA_OUT": str(outputdir),
            "STAR_LOGIN": "1",
        }
    )
    if isinstance(files, (str, os.PathLike)):
        input_paths = _read_path_list(Path(files).expanduser().resolve())
    else:
        input_paths = _validated_input_paths(files, Path.cwd())
    input_paths = _validated_input_paths(input_paths, Path.cwd())

    argv = [
        str(root / "Perl/bin/perl"),
        str(orac_dir / "bin/picard"),
        "-log=sf",
        "-nodisplay",
    ]
    if recpars is not None:
        argv.append(f"-recpars={recpars}")
    if verbose:
        argv.append("-verbose")
    if warn:
        argv.append("-warn")
    if debug:
        argv.append("-debug")
    argv.extend((str(recipe), *(str(path) for path in input_paths)))
    return _run_orac(argv, picardenv, outputdir, "picard")


# Preserve the old in-tree discovery fallback without constructing a parallel
# environment dictionary.  Installed packages normally use STARLINK_DIR or an
# explicit change_starpath() call.
if starpath is None and default_starpath:
    change_starpath(default_starpath)
elif starpath is None:
    candidate = (Path(__file__).resolve().parent / "../../bin/smurf/makemap").resolve()
    if candidate.is_file():
        change_starpath(candidate.parents[2])
