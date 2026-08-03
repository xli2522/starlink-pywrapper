starlink-pywrapper
==================

Python interfaces to applications in an external 'Starlink Software Collection'.

Scope
-----

'starlink-pywrapper` launches Starlink applications and presents their parameters
and results through Python. It does not reimplement, modify, or patch Starlink
algorithms. A working Starlink installation must be installed separately.

The generated modules cover the project's existing KAPPA, CONVERT, ATOOLS,
CCDPACK, CUPID, FIGARO, POLPACK, and SMURF interfaces. The package also retains
its FLUXES, ORAC-DR, Picard, and utility helpers.

Version `0.4.0.dev1` is generated from pinned Starlink 2025A interface and
help metadata and targets **Starlink 2025A plus Errata Patch 1**.

Supported configurations
------------------------

The latest version has been tested with CPython 3.12 on:

* Ubuntu 24.04 under WSL2; and
* native Ubuntu 22.04.

Both tested configurations use Starlink 2025A plus Errata Patch 1. The package
supports Linux and requires CPython 3.12. Ordinary calls may use another
structurally valid Starlink installation, but the wrapper warns when its
reported release differs from the generated 2025A target.

Installation
------------

Install Starlink separately from the
`Starlink website <https://starlink.eao.hawaii.edu/starlink/>`_.

From a source checkout, install the wrapper with::

    python -m pip install .

Astropy is optional and is needed only for helpers that return an Astropy FITS
header::

    python -m pip install ".[fits]"

The default result reader uses Starlink's own `parget` application and does not
require a Python HDS binding. Existing applications that explicitly require the
historical reader can request the optional legacy dependency::

    python -m pip install ".[hds]"

The legacy 'starlink-pyhds` package has its own build and platform
constraints; it is not required for normal wrapper calls.

Selecting Starlink
------------------

Set `STARLINK_DIR` before starting Python::

    export STARLINK_DIR=/path/to/starlink

or select an installation explicitly::

    from starlink import wrapper

    wrapper.change_starpath("/path/to/starlink")

The supplied directory must contain a usable Starlink `etc/profile` and
KAPPA `parget`. The profile is captured for child processes without modifying
the parent Python environment.

Calling Starlink applications
-----------------------------

Import a generated module and call an application with ordinary Python
arguments and keywords::

    from starlink import kappa, wrapper

    wrapper.change_starpath("/path/to/starlink")
    result = kappa.stats("/path/to/input.sdf")
    print(result.mean)

Generated functions return Starlink output parameters as namedtuple-like
Python objects, so callers do not need to invoke parget themselves.
**By default, the wrapper uses the selected Starlink installation's parget
executable internally to retrieve these values. The historical direct-HDS
reader remains available as an optional compatibility mode.** <-(major
implementation change from previous versions; same user experience)
Names that are Python keywords retain the historical trailing underscore, for
example `in_`.

Use `returnstdout=True` when the application's terminal output is also
needed::

    result, stdout = kappa.stats(
        "/path/to/input.sdf",
        returnstdout=True,
    )

Normal Python introspection exposes generated signatures and short help::

    help(kappa.stats)

Long generated help can be displayed with::

    from starlink.utilities import starhelp

    starhelp(kappa.stats)

Errors and timeouts
-------------------

Application start failures and unsuccessful exits raise
`StarlinkCommandError`. Timeouts raise `StarlinkTimeoutError`. These
exceptions retain the argument vector, return code, stdout, stderr, working
directory, and ADAM directory when available::

    try:
        kappa.stats(
            "/path/to/input.sdf",
            _starlink_timeout=60,
            _starlink_cwd="/path/to/work",
        )
    except wrapper.StarlinkTimeoutError as error:
        print(error.argv)
        print(error.stderr)

Each Python process uses isolated absolute ADAM and temporary directories.
Application parameter state is removed after calls, and child process groups
are terminated on timeout or interruption.

Additional helpers
------------------

'starlink.utilities.get_ndf_fitshdr` returns an Astropy FITS header by
asking the selected Starlink installation to read the NDF. 'starlink.fluxes`
accepts `date`, `datetime`, or supported ISO-format date strings.

'starlink.wrapper.oracdr` and 'starlink.wrapper.picard` preserve their
existing result tuple and calling style. Input list files and Python path lists
are validated and passed as literal subprocess arguments; no user-controlled
shell expansion is used.

Limitations
-----------

The package does not install Starlink, provide a Python NDF/HDS object model,
or change Starlink scientific behavior.

See `doc/details.rst` for the complete usage contract.
