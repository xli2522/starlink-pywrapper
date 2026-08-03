Known issues and non-interactive caveats
========================================

These notes describe differences between interactive Starlink use and the
wrapper's non-interactive execution mode. The wrapper does not alter the
underlying Starlink applications or their parameter systems.

Output-only applications
------------------------

``kappa.fitslist`` writes the FITS header primarily to standard output and
does not declare useful output parameters for the wrapper's namedtuple-like
result. Use ``returnstdout=True`` when that textual listing is wanted.
For programmatic access, prefer :func:`starlink.kappa.fitsval` for one
keyword or :func:`starlink.utilities.get_ndf_fitshdr` for an entire
header. Reading the complete header is normally more efficient than making
many separate ``fitsval`` calls.

Parameters that may otherwise prompt
------------------------------------

The wrapper disables Starlink parameter prompting. A Starlink application
therefore fails instead of asking interactively when it cannot obtain a
required value.

``cupid.findclumps`` exposes ``rms`` as a keyword. Starlink can derive a
dynamic RMS default from an available variance component, but scripts should
pass ``rms=...`` explicitly when the input does not provide a suitable
default.

``atools.astmask`` exposes ``val`` as a keyword, and its generated
2025A help describes ``BAD`` as the suggested value. For predictable
non-interactive behavior, pass ``val='BAD'`` or another intended
numeric value explicitly.

WSL filesystem location
-----------------------

When using Starlink 2025A under WSL2, launch Starlink applications from a
working directory on the WSL Linux filesystem, such as beneath
``/home/user``. When the process working directory is on a mounted Windows
filesystem such as ``/mnt/c``, KAPPA applications produce their expected
results but could exit with a segmentation fault in Starlink's bundled HDF5
shutdown code.

Start Python from a Linux-filesystem directory or pass a suitable
``_starlink_cwd`` to an individual generated call. The wrapper reports a
non-zero Starlink exit as :class:`starlink.wrapper.StarlinkCommandError`; it
does not suppress or reinterpret this external failure.

Resolved stale output state
---------------------------

Older releases of the wrapper could return an optional ``kappa.stats`` value,
such as ``median``, from a previous call in the same ADAM directory.
Version 0.4 removes the application's parameter file before every call,
removes it again afterward, and omits optional values that were not produced
by the current invocation. Results from an earlier call are therefore not
reused.
