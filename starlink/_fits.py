"""FITS-header extraction without a mandatory Python HDS binding."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def get_ndf_fitshdr(datafile: os.PathLike[str] | str):
    """Return an Astropy FITS header using Starlink KAPPA ``fitslist``.

    ``fitslist`` is part of the selected Starlink installation and therefore
    understands the installation's HDS version.  The temporary logfile is
    private to this call and is removed on every exit path.
    """

    from astropy.io import fits

    from . import wrapper

    source = Path(datafile).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="starlink-fitslist-") as temp:
        logfile = Path(temp, "header.lis")
        wrapper.starcomm(
            "$KAPPA_DIR/fitslist",
            "fitslist",
            str(source),
            logfile=str(logfile),
            _starlink_parameters=(),
        )
        if not logfile.is_file():
            raise RuntimeError(
                f"KAPPA fitslist did not create its requested logfile: {logfile}"
            )
        cards = logfile.read_text(encoding="ascii", errors="replace")
    return fits.Header.fromstring(cards, sep="\n")


def get_ndf_fitshdr_legacy(datafile: os.PathLike[str] | str):
    """Return an Astropy FITS header through an installed legacy HDS binding."""

    from astropy.io import fits

    try:
        from starlink import hds
    except (ImportError, ModuleNotFoundError) as exc:
        raise ImportError(
            "Legacy FITS-header access requires a compatible starlink.hds "
            "module installed separately"
        ) from exc

    hdsobj = hds.open(os.fspath(datafile), "READ")
    fitscomp = hdsobj.find("MORE").find("FITS")
    fitsheader = fitscomp.get()
    text = "\n".join(
        item.decode("ascii", "replace") if isinstance(item, bytes) else item
        for item in fitsheader
    )
    return fits.Header.fromstring(text, sep="\n")
