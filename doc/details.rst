Detailed guide
==============

Purpose and public modules
--------------------------

``starlink-pywrapper`` is a Python interface to external Starlink
applications. It prepares a child environment, launches an installed
application, and converts its output parameters into Python values. Scientific
processing remains entirely within Starlink.

Generated interfaces are provided for :mod:`starlink.atools`,
:mod:`starlink.ccdpack`, :mod:`starlink.convert`,
:mod:`starlink.cupid`, :mod:`starlink.figaro`,
:mod:`starlink.kappa`, :mod:`starlink.polpack`, and
:mod:`starlink.smurf`. The package also preserves
:mod:`starlink.fluxes`, :mod:`starlink.picard`,
:mod:`starlink.utilities`, and the ORAC-DR and Picard helpers in
:mod:`starlink.wrapper`.

The generated interface provenance is available as
``starlink.__starlink_source_version__``. For this candidate it identifies
Starlink 2025A, Errata Patch 1, and the pinned Starlink source metadata.

Installation
------------

The package supports CPython 3.12 on Linux. Install an official Starlink
distribution separately, then install this source checkout::

    python -m pip install .

For development and tests, use::

    python -m pip install -e ".[test]"

Install the optional FITS helper dependency with::

    python -m pip install ".[fits]"

The default result reader does not require ``starlink-pyhds``. The
`hds` extra exists only for applications that explicitly select the
historical compatibility reader::

    python -m pip install ".[hds]"

Starlink selection and child environments
-----------------------------------------

If `STARLINK_DIR` is set when :mod:`starlink.wrapper` is imported,
the wrapper attempts to select it. An installation can also be chosen at any
time::

    from starlink import wrapper

    wrapper.change_starpath("/path/to/starlink")

Selection validates the directory, `etc/profile`, and executable KAPPA
`parget`. The trusted profile is sourced by a fixed non-interactive shell.
Its values are copied into the wrapper's child environment; unrelated parent
variables are not copied into the captured Starlink profile and the parent
Python environment is not modified.

Paths containing spaces and non-ASCII characters are supported. A
structurally valid installation from a release other than the generated 2025A
target can be used for ordinary calls, with a warning. Release validation is
stricter and is documented separately.

The selected path is available as `wrapper.starpath`. The child
environment is available as `wrapper.env` for compatibility, but callers
should normally use :func:`starlink.wrapper.change_starpath` instead of
modifying it.

Generated calls and results
---------------------------

Generated functions follow the established positional and keyword calling
style::

    from starlink import kappa

    result = kappa.stats("/path/to/input.sdf")
    print(result.mean)
    print(result.numpix)

A parameter whose Starlink name is reserved by Python uses a trailing
underscore, such as `in_`. The generated signature and short description
are available through `help()`.

The default result backend invokes the selected installation's KAPPA
`parget` executable using generated parameter metadata. It preserves
declared result order and converts scalar, vector, logical, integer, and
floating-point values to Python types. Missing optional values are represented
without reusing stale state from an earlier call.

The historical Python HDS reader is available only by explicit request::

    from starlink import wrapper

    wrapper.set_result_backend("legacy_hds")

Restore the default with::

    wrapper.set_result_backend("parget")

The legacy backend is loaded lazily. If its optional dependency is unavailable,
the wrapper raises a clear result-backend error rather than preventing the
package from importing.

Differences from standalone Starlink
------------------------------------

The wrapper runs the installed Starlink applications rather than replacing
their scientific behavior, but it adapts their command-line interface for
non-interactive Python programs.

Output parameters
~~~~~~~~~~~~~~~~~

Generated functions return Starlink output parameters as namedtuple-like
Python objects. Callers can therefore access values directly instead of
invoking KAPPA ``parget`` themselves::

    from starlink import kappa

    result = kappa.stats('/path/to/input.sdf')
    print(result.mean)
    print(result.sigma)

The default result reader does use the selected Starlink installation's
``parget`` executable internally. This differs from the historical wrapper,
which read ADAM parameter files through the optional Python HDS binding, but
the returned Python interface remains the same. See `Generated calls and
results`_ for the optional legacy reader.

Arguments and shell quoting
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parameters are supplied as ordinary Python positional and keyword arguments.
Python booleans and sequences are converted to Starlink parameter values, and
a Starlink parameter whose name is reserved by Python uses a trailing
underscore, such as ``in_``. Callers should not add shell escapes or backtick
expressions: application commands are launched with argument arrays and no
user-controlled shell expansion is performed.

Non-interactive operation
~~~~~~~~~~~~~~~~~~~~~~~~~

The wrapper configures Starlink for non-interactive execution. It does not
support missing-value prompts, graphics-cursor input, or other interactions
that require a terminal or GUI response. Supply all parameters needed by the
selected non-interactive mode.

Commands that primarily print information can still be called, but their
namedtuple-like result may contain no useful fields. For example, KAPPA
``fitslist`` can be used with ``returnstdout=True``. For scripting, prefer
:func:`starlink.kappa.fitsval` for one FITS keyword or
:func:`starlink.utilities.get_ndf_fitshdr` for an entire FITS header. The
latter requires the optional FITS dependency.

Environment and temporary state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Starlink setup script does not need to be sourced in the user's shell.
Selecting an installation captures its trusted profile for child processes
without modifying the parent Python environment. Each Python process uses
isolated absolute ADAM and temporary directories, allowing independent
processes to run concurrently. Owned temporary state and child processes are
cleaned on normal completion and handled on errors, timeouts, and interrupts.

Standard output, errors, and timeouts
-------------------------------------

Set `returnstdout=True` to receive `(result, stdout)`. The
``starcomm`` compatibility entry point also accepts
`_starlink_return_stderr=True` when stderr must be returned.

Generated calls accept these wrapper controls:

`_starlink_timeout`
    Maximum seconds shared by application execution and output-parameter
    retrieval.

`_starlink_cwd`
    Working directory for the child application.

`_starlink_result_backend`
    Result backend for this call only.

Application failures raise :class:`starlink.wrapper.StarlinkCommandError`.
Timeouts raise :class:`starlink.wrapper.StarlinkTimeoutError`. Diagnostic
attributes include `argv`, `returncode`, ``stdout``,
``stderr``, `cwd`, and `adam_dir` when available.

Commands run with argument arrays and ``shell=False``. Timeout, error,
keyboard-interrupt, and interpreter-exit paths terminate owned child processes
and clean isolated temporary state.

Help and FITS headers
---------------------

Use :func:`starlink.utilities.starhelp` with a generated module for a
command summary, or with a generated function for packaged long help::

    from starlink import kappa
    from starlink.utilities import starhelp

    starhelp(kappa)
    starhelp(kappa.ndftrace)

:func:`starlink.utilities.get_ndf_fitshdr` asks the selected Starlink
installation to read an NDF and returns an `astropy.io.fits.Header`. This
path supports the HDS formats understood by that Starlink installation and
does not require the legacy Python HDS binding. Astropy is imported only when
the helper is called.

The explicit `get_ndf_fitshdr_legacy` helper retains the old direct
Python-HDS behavior for compatible installations.

FLUXES
------

The hand-written FLUXES helper accepts a Python `date`, `datetime`,
or supported ISO-format string::

    import datetime
    from starlink import fluxes

    result = fluxes.get_flux(
        "URANUS",
        datetime.date(2025, 1, 2),
        filter_=850,
    )
    print(result.f_total)

Invalid date strings raise `ValueError`; unsupported date objects raise
`TypeError`.

ORAC-DR and Picard
------------------

ORAC-DR accepts a Python sequence of files or a text list. Relative paths in a
Python sequence are resolved beneath `datain`; relative entries in a text
list are resolved relative to the list file::

    from starlink import wrapper

    output = wrapper.oracdr(
        "SCUBA2_850",
        rawfiles=["observation-1.sdf", "observation-2.sdf"],
        datain="/path/to/raw",
        dataout="/path/to/output",
        recipe="REDUCE_SCAN",
    )

Picard accepts a Python sequence or a text list in the same way::

    output = wrapper.picard(
        "SCUBA2_MAPSTATS",
        ["/path/to/map-1.sdf", "/path/to/map-2.sdf"],
        dataout="/path/to/output",
    )

Both return the preserved `oracoutput` tuple containing the log, output
directory, discovered products, status, and process identifier. A completed
ORAC-DR or Picard process reports a non-zero exit in `status`, so callers
should inspect it when failure is significant. Input files are validated
before launch. Backticks and user-controlled shell parsing are not used.

Compatibility helpers and limitations
-------------------------------------

:func:`starlink.wrapper.set_HDS_version` changes `HDS_VERSION` only
in the wrapper's child environment. It does not modify Starlink or the
parent process.

The removed FIGARO `exam` application remains represented by an explicit
compatibility function that raises
:class:`starlink.wrapper.StarlinkApplicationUnavailableError` and directs
callers to `HDSTRACE`.

Interactive prompting and GUI-driven cursor operations are not supported.
Callers must supply the parameters needed for non-interactive execution. This
project does not provide a new NDF/HDS object model or substitute Python
implementations for Starlink applications.
