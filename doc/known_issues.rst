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

Resolved stale output state
---------------------------

Older releases of the wrapper could return an optional ``kappa.stats`` value,
such as ``median``, from a previous call in the same ADAM directory.
Version 0.4 removes the application's parameter file before every call,
removes it again afterward, and omits optional values that were not produced
by the current invocation. Results from an earlier call are therefore not
reused.
