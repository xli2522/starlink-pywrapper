Validation
==========

The source checkout provides three validation levels. The first is portable
and does not require Starlink. The other two execute an existing Starlink
installation and are opt-in.

Install the test dependencies from the checkout first::

    python -m pip install -e '.[test]'

Normal pytest runs never install Starlink, download tutorial data, or place
scientific products in the repository.

Fast pytest suite
-----------------

Run the complete fast suite with::

    python -m pytest -q

For a focused development run, use::

    python -m pytest -q tests/unit tests/generator

These tests exercise environment discovery, command construction, result
conversion, error and timeout handling, process cleanup, compatibility
helpers, safe archive handling, deterministic generation, and fake paired
POL-2 orchestration. They use temporary files and fake applications rather
than a Starlink installation.

Optional Starlink smoke tests
-----------------------------

The smoke tests make small live calls against an existing Starlink
installation. They do not install or modify Starlink and do not download
tutorial data::

    STARLINK_TEST_DIR=/path/to/starlink \
      python -m pytest -q -m starlink_smoke

By default they use ``examples/sc7/object2d.sdf`` from the selected
installation. A different immutable sample can be selected with
``STARLINK_SMOKE_NDF``, although tests that assert the packaged example's
reference statistics then require a scientifically equivalent fixture.

The smoke suite checks the default result reader, typed scalar and vector
outputs, an output-producing KAPPA call, preservation of the input NDF,
structured failure and recovery, generated executable targets, and explicit
compatibility behavior.

Full POL-2 Tutorial 1 validation
--------------------------------

The full runner is a developer and release-validation tool. It executes the
same frozen POL-2 Tutorial 1 reduction twice: once with direct Starlink
command arrays and once through the public Python wrapper. It then compares
the resulting products semantically.

The runner requires:

* a source checkout with the test dependencies installed;
* an existing Starlink 2025A installation with Errata Patch 1;
* network access for the first data download; and
* a writable workspace outside, and disjoint from, the Git checkout.

It never installs Starlink. Run the optional, non-fatal form with::

    python scripts/run_optional_pol2_tutorial.py \
      /path/to/external/pol2-validation \
      /path/to/starlink \
      --order cli-first

The second argument can be ``auto`` to discover Starlink through
``STARLINK_DIR`` or KAPPA ``parget`` on ``PATH``. Discovery still
requires the installation to pass the Starlink 2025A Patch 1 preflight.

The paired workflows always run in separate fresh directories. The
``--order`` option accepts ``cli-first`` or ``wrapper-first`` and
changes only which workflow runs first; both workflows run in either case.

Data acquisition and safety
~~~~~~~~~~~~~~~~~~~~~~~~~~~

On the first run, the tool obtains the official archive directly from:

`official JCMT POL-2 Tutorial 1 archive
<https://ftp.eao.hawaii.edu/jcmt/usersmeetings/JCMT_POL-2_tutorial1_2017_raw_only.tar.gz>`_

The frozen archive fixture is 1,964,931,434 bytes with SHA-256
``8071bbb929a9224b34c9b104c7bc3f484f32781c64a3ee0e19854a8079e2086b``.
The extractor rejects absolute paths, traversal, links, devices, unexpected
roots, and unexpected member counts. Recognized AppleDouble and
``__MACOSX`` metadata are ignored only after path and type validation.

Before either reduction starts, all 116 selected raw files must match the
frozen manifest in
``tests/integration/pol2/tutorial1_raw_sha256.txt``. The published raw
tree is read-only, and hashes are checked again after both workflows. The
archive and verified data are reused on later runs, but every reduction gets
a new output directory.

The workspace contains the archive, verified raw data, reports, and generated
products. It can require substantial disk space and is intentionally kept
outside Git for operator-controlled inspection and cleanup.

Scientific and operational checks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The runner performs:

* unit and generator tests;
* the live Starlink smoke suite;
* the direct CLI and public-wrapper POL-2 reductions;
* exact NDF comparison plus metadata and summary-statistic comparison;
* semantic FITS catalogue comparison;
* unchanged-raw-input verification;
* structured wrapper failure and recovery checks; and
* a performance check requiring wrapper time to be no more than direct CLI
  time plus the greater of five percent or 60 seconds.

NDF evidence includes dimensions, bounds, data and variance comparisons,
quality state, units, labels, titles, WCS domain, bad-pixel accounting, and
selected full-image and source-region statistics. Scientific processing is
performed entirely by the selected Starlink installation.

Thread and resource limits
~~~~~~~~~~~~~~~~~~~~~~~~~~

The portable runner does not contain hostnames, schedulers, CPU topology, or
machine-specific resource limits. BLAS-related thread variables default to
one, and ``SMURF_THREADS`` defaults to one unless supplied by the
operator. For example::

    SMURF_THREADS=4 \
      python scripts/run_optional_pol2_tutorial.py \
        /path/to/external/pol2-validation \
        /path/to/starlink

CPU affinity, memory limits, and job scheduling remain the operator's
responsibility and can be applied with the facilities appropriate to the
machine.

Outcomes and strict release gating
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, an incomplete full validation writes a report and prints
``INCOMPLETE (non-fatal)`` but returns a successful process status. This
makes the expensive external validation optional. Always inspect the reported
``outcome`` rather than assuming that process status alone means the
reduction passed.

Use ``--strict`` when an incomplete result must return a failure status.
For an exact release candidate, also require a clean checkout at a specified
commit::

    candidate=$(git rev-parse HEAD)

    python scripts/run_optional_pol2_tutorial.py \
      /path/to/external/pol2-validation \
      /path/to/starlink \
      --order wrapper-first \
      --expected-commit $candidate \
      --release-gate \
      --strict

``--release-gate`` requires the full 40-character commit, verifies that
``HEAD`` matches it, and rejects a dirty checkout. Successful paired
validation creates ``POL2_PAIR_COMPLETE`` beneath the fresh run root and
writes a JSON outcome report beneath ``reports`` in the external
workspace. Run products and reports are preserved; owned short-path aliases
and temporary scratch state are cleaned automatically.

The ``pol2_tutorial`` pytest marker validates evidence produced by the
paired runner. It is invoked automatically during the full workflow and is not
a substitute for running that workflow.
