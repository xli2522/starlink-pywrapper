Changelog
=========

0.4.0.dev1
-----------------------------------

* Generate the existing wrapper modules from pinned Starlink 2025A interface
  and help metadata and target Errata Patch 1.
* Require CPython 3.12 and use `pyproject.toml` as the package metadata
  source.
* Use one portable command runtime with argument arrays, captured diagnostics,
  isolated ADAM state, process-group cleanup, and timeout handling.
* Retrieve output parameters through Starlink `parget` by default while
  retaining an optional legacy Python HDS compatibility reader.
* Preserve the established calling conventions, result tuples,
  `returnstdout`, `change_starpath`, `starcomm`,
  `set_HDS_version`, ORAC-DR, Picard, and FLUXES entry points.
* Regenerate deterministic module signatures and help for the existing package
  set, including the explicit FIGARO `exam` compatibility error.
* Add fast unit and generator coverage, live Starlink smoke tests, and an
  opt-in paired CLI/wrapper POL-2 Tutorial 1 reduction.
* Modernize packaging, distribution payload checks, and isolated-wheel
  installation checks.
