Installation and complete validation walkthrough
================================================

This walkthrough starts with a Linux account that does not already contain
Starlink or ``starlink-pywrapper``. It installs the Starlink 2025A binary
distribution and Errata Patch 1, installs the wrapper from this fork's
``master`` branch, and runs all three validation levels:

* the portable pytest suite;
* small live Starlink smoke tests; and
* the full JCMT POL-2 Tutorial 1 CLI-versus-wrapper reduction.

The commands target the two configurations on which this wrapper has been
validated: native Ubuntu 22.04 and Ubuntu 24.04 under WSL2, both on x86-64
Linux with CPython 3.12. Use the Starlink archive built for the installed
Ubuntu release.

The example paths use ``$HOME`` and contain no project-specific usernames.
Change them if necessary, but keep the Starlink installation, Git checkout,
and external POL-2 workspace in three separate directories.

What the commands install
-------------------------

Starlink and the wrapper are separate projects:

* ``$HOME/software/star-2025A`` contains the external Starlink installation.
* ``$HOME/src/starlink-pywrapper`` contains the source checkout.
* ``$HOME/.venvs/starlink-pywrapper`` contains the Python environment.
* ``$HOME/starlink-pywrapper-validation`` contains the downloaded tutorial
  archive, verified raw data, reduction products, and outcome reports.

The wrapper never modifies or patches Starlink. The commands in this tutorial
apply the official Starlink patch before the wrapper is installed.

Prerequisites
-------------

Install basic tools and the GNU Fortran runtime required by the Ubuntu
Starlink binaries::

    sudo apt-get update
    sudo apt-get install -y ca-certificates curl git libgfortran5

Administrative installation is only needed for these operating-system
packages. Starlink itself, the wrapper, and the validation workspace can all
be installed under an ordinary user account.

The wrapper requires Python 3.12. Confirm the interpreter before continuing::

    python3.12 --version

Expected output begins with::

    Python 3.12.

Ubuntu 24.04 provides Python 3.12 and its virtual-environment module through
the normal package manager if they are not already installed::

    sudo apt-get install -y python3.12 python3.12-venv

Ubuntu 22.04 does not provide Python 3.12 in its default package set. Use a
Python 3.12 interpreter supplied by the system administrator or a trusted
environment manager. For example, an existing Conda installation can create
the tested interpreter with::

    conda create --name starlink-pywrapper python=3.12 -y
    conda activate starlink-pywrapper
    python --version

If ``python3.12`` is available directly, create an isolated environment with::

    mkdir -p "$HOME/.venvs"
    python3.12 -m venv "$HOME/.venvs/starlink-pywrapper"
    source "$HOME/.venvs/starlink-pywrapper/bin/activate"
    python --version

The remainder of the tutorial assumes that ``python`` refers to this Python
3.12 environment.

Install Starlink 2025A plus Errata Patch 1
------------------------------------------

The official download and errata pages are:

* `Starlink 2025A download and installation
  <https://starlink.eao.hawaii.edu/starlink/2025ADownload>`_;
* `Starlink 2025A Errata
  <https://starlink.eao.hawaii.edu/starlink/2025AErrata>`_.

The following block selects the official Ubuntu 22 or Ubuntu 24 archive from
``/etc/os-release``. It refuses unsupported Ubuntu releases and refuses to
overwrite an existing ``star-2025A`` directory. The base-archive MD5 values
are published on the official download page. The Patch 1 SHA-256 values pin
the official patch archives used for this wrapper's validation.

Run from a Bash shell::

    set -euo pipefail

    download_dir="$HOME/downloads/starlink-2025A"
    install_parent="$HOME/software"
    mkdir -p "$download_dir" "$install_parent"

    . /etc/os-release
    case "$VERSION_ID" in
        22.04)
            platform=Ubuntu22
            archive_md5=b19b86218b82bae0beffaa6003b26306
            patch_sha256=c45720c72bad497724a1b7a2a3b2abf6fac1591fd81b28d7a0aaa838c94852fb
            ;;
        24.04)
            platform=Ubuntu24
            archive_md5=a8fe4af85cfa98ccf17313aa347cb7f3
            patch_sha256=a67378011521cf79a98d487491e6d7e8b2b9c00270afadde0373e518c2cba3f2
            ;;
        *)
            echo "This walkthrough has no validated Starlink archive for Ubuntu $VERSION_ID" >&2
            exit 2
            ;;
    esac

    archive="starlink-2025A-Linux-${platform}.tar.gz"
    patch="starlink-2025A-Linux-${platform}_patch1.tar.gz"
    release_url=https://ftp.eao.hawaii.edu/starlink/2025A
    patch_url="$release_url/patch1"

    test ! -e "$install_parent/star-2025A" || {
        echo "Refusing to overwrite $install_parent/star-2025A" >&2
        exit 2
    }

    curl --fail --location --continue-at - \
        --output "$download_dir/$archive" \
        "$release_url/$archive"
    printf '%s  %s\n' "$archive_md5" "$download_dir/$archive" | md5sum --check -

    curl --fail --location --continue-at - \
        --output "$download_dir/$patch" \
        "$patch_url/$patch"
    printf '%s  %s\n' "$patch_sha256" "$download_dir/$patch" | sha256sum --check -

    tar -xzf "$download_dir/$archive" -C "$install_parent"
    tar -xzf "$download_dir/$patch" -C "$install_parent"

The base archive is about 1.4 GB. A successful checksum stage ends with output
similar to the following; the leading directory varies::

    <download-directory>/starlink-2025A-Linux-Ubuntu24.tar.gz: OK
    <download-directory>/starlink-2025A-Linux-Ubuntu24_patch1.tar.gz: OK

Do not bypass a failed checksum. Recheck the selected operating-system build
and the official download and errata pages instead.

The patch archive contains paths beginning with ``star-2025A``. It must be
extracted from the directory that contains the installation, as shown above.
It is not a separate Starlink installation.

On WSL2, keep Starlink on the Linux filesystem, such as beneath ``$HOME``.
Installing it beneath ``/mnt/c`` introduces Windows filesystem semantics and
is not the configuration validated by this project.

Verify the Starlink installation
--------------------------------

First verify the release manifest and the Patch 1 marker used by the strict
POL-2 preflight::

    starlink_dir="$HOME/software/star-2025A"

    test "$(sed -n '1p' "$starlink_dir/manifests/starlink.version")" = 2025A
    printf '%s  %s\n' \
        91b6a51f982af54847a3761768f5ccdbf130aa295b4a9bf9a353ecf628d525c1 \
        "$starlink_dir/include/star/hds_types.h" | sha256sum --check -

Expected output::

    <starlink-directory>/include/star/hds_types.h: OK

Starlink's official profile changes library and command paths. Source it only
inside a child shell for this direct Starlink check, so those changes do not
leak into the Python environment::

    (
        export STARLINK_DIR="$starlink_dir"
        set +u
        source "$STARLINK_DIR/etc/profile"

        if ldd "$STARLINK_DIR/bin/kappa/stats" | grep -q 'not found'; then
            echo "Starlink has unresolved shared-library dependencies:" >&2
            ldd "$STARLINK_DIR/bin/kappa/stats" | grep 'not found' >&2
            exit 1
        fi

        "$STARLINK_DIR/bin/starversion"
        "$STARLINK_DIR/bin/kappa/stats" \
            "$STARLINK_DIR/examples/sc7/object2d.sdf"
    )

The validated installation reports the following version and sample
statistics. Formatting and insignificant final digits can vary::

    2025A @ 899c03fc4af3b6feb26756b904e5a597343191ed (2025-05-06T04:10:05)

       Pixel statistics for the NDF structure
       .../examples/sc7/object2d

          Pixel mean             : 8.02819
          Minimum pixel value    : -1094
          Maximum pixel value    : 777.667
          Total number of pixels : 537600
          Number of pixels used  : 537600 (100.0%)

If ``ldd`` reports ``libgfortran.so.5 => not found``, install the Ubuntu
``libgfortran5`` package before continuing. Other missing libraries usually
indicate that the Starlink profile was not sourced for the direct check or
that the archive does not match the host operating system.

Install the wrapper from the public fork
----------------------------------------

Return to the Python 3.12 environment, then make a fresh checkout of the
public fork's ``master`` branch::

    mkdir -p "$HOME/src"
    git clone --branch master --single-branch \
        https://github.com/xli2522/starlink-pywrapper.git \
        "$HOME/src/starlink-pywrapper"
    cd "$HOME/src/starlink-pywrapper"

    python -m pip install --upgrade pip
    python -m pip install -e '.[test]'
    python -m pip check

    python -c 'import sys, starlink; print(sys.version.split()[0]); print(starlink.__version__)'

The important final lines are::

    No broken requirements found.
    3.12.<patch-level>
    0.4.0.dev1

The editable installation is intentional for a source checkout: the tests and
full runner use files from the checkout. End users who only need wrapper calls
can instead use ``python -m pip install .`` from the checkout.

Run one wrapper call
--------------------

The wrapper can discover Starlink from ``STARLINK_DIR`` without sourcing the
Starlink profile into the parent Python shell::

    export STARLINK_DIR="$HOME/software/star-2025A"

    python - <<'PY'
    import os
    from pathlib import Path

    from starlink import kappa

    sample = Path(os.environ["STARLINK_DIR"]) / "examples/sc7/object2d.sdf"
    statistics = kappa.stats(str(sample), _starlink_timeout=60)
    trace = kappa.ndftrace(str(sample), _starlink_timeout=60)

    print(f"Pixels: {statistics.numpix}")
    print(f"Mean: {statistics.mean:.6f}")
    print(f"Dimensions: {trace.dims}")
    PY

Expected output::

    Pixels: 537600
    Mean: 8.028186
    Dimensions: [1024, 525]

Run the portable pytest suite
-----------------------------

The normal suite does not need Starlink and does not download tutorial data.
Clear the opt-in smoke variables so the live tests are reported as skipped::

    cd "$HOME/src/starlink-pywrapper"
    unset STARLINK_TEST_DIR STARLINK_SMOKE_NDF
    python -m pytest -q

For the documented ``master`` revision, the expected summary is::

    130 passed, 12 skipped, 3 subtests passed in <time>

Test counts can increase as coverage is added. The acceptance condition is no
failures or errors; the skips include tests that require an explicitly
selected live Starlink installation or optional compatibility dependency.

Run the live Starlink smoke tests
---------------------------------

The smoke suite uses the small immutable NDF shipped in Starlink and completes
in seconds. It does not download POL-2 data::

    STARLINK_TEST_DIR="$STARLINK_DIR" \
        python -m pytest -q -m starlink_smoke

Expected summary::

    ..........                                                               [100%]
    10 passed, 132 deselected in <time>

These tests execute real KAPPA applications through both direct command arrays
and the public wrapper. They check scalar and vector results, an output NDF,
input immutability, paths containing spaces, isolated processes, structured
failure and recovery, and generated executable targets.

Run the full POL-2 reduction validation
---------------------------------------

This is an expensive developer and release test, not an ordinary installation
test. The first run downloads the official 1,964,931,434-byte tutorial archive
and stages 116 verified raw files. Allow at least 10 GB of free space in the
external workspace. Runtime depends strongly on the machine and the selected
``SMURF_THREADS`` value.

The following strict command records the exact clean Git commit and fails the
shell command if any validation stage is incomplete. It runs both workflows;
``--order wrapper-first`` only selects which one runs first::

    cd "$HOME/src/starlink-pywrapper"
    validation_root="$HOME/starlink-pywrapper-validation"
    candidate="$(git rev-parse HEAD)"

    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    SMURF_THREADS=4 \
        python scripts/run_optional_pol2_tutorial.py \
            "$validation_root" \
            "$STARLINK_DIR" \
            --order wrapper-first \
            --expected-commit "$candidate" \
            --release-gate \
            --strict

Choose ``SMURF_THREADS`` according to local resource policy. The portable
runner defaults it to one and contains no host-specific CPU affinity, memory
limit, scheduler, hostname, or filesystem path. External schedulers and
resource controls may wrap this command without changing the test.

An abridged successful first-run transcript is shown below. Paths, commit IDs,
timestamps, download progress, and timings are intentionally replaced or
omitted; scientific pass criteria are not::

    Downloading official POL-2 archive: https://ftp.eao.hawaii.edu/...
    Downloaded 0.25 GiB
    ...

    == unit and generator tests ==
    ...
    129 passed, 3 subtests passed in <time>

    == Starlink smoke tests ==
    ..........                                                               [100%]
    10 passed, 132 deselected in <time>

    == paired POL-2 Tutorial 1 validation ==
    Verifying 116 raw inputs against the frozen SHA-256 manifest...
    ...

    OPTIONAL POL-2 VALIDATION: PASSED
    Outcome report: <validation-workspace>/reports/pol2-wrapper-first-<commit>-<timestamp>-optional-validation.json

The outcome report must contain ``"outcome": "passed"``. The corresponding
fresh run directory must contain ``POL2_PAIR_COMPLETE``. A validated run also
records that all 116 raw inputs matched the frozen manifest, both workflows
completed, semantic NDF and FITS catalogue comparisons passed, the raw hashes
were unchanged, and owned scratch state was cleaned.

Inspect the outcome::

    latest_report="$(find "$validation_root/reports" -maxdepth 1 -type f \
        -name '*-optional-validation.json' -printf '%T@ %p\n' \
        | sort -nr | head -1 | cut -d' ' -f2-)"

    python - "$latest_report" <<'PY'
    import json
    import sys
    from pathlib import Path

    report_path = Path(sys.argv[1])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    print("Outcome:", report["outcome"])
    print("Expected commit:", report["expected_commit"])
    print("Actual commit:", report["actual_commit"])
    print("Run root:", report["run_root"])
    print("Archive reused:", report["data"]["archive_reused"])
    print("Data reused:", report["data"]["data_reused"])
    print("Verified raw inputs:", report["data"]["raw_verification"]["file_count"])
    for step in report["steps"]:
        print(step["name"], "status=", step["returncode"])
    PY

Expected first-run values are::

    Outcome: passed
    Expected commit: <40-character commit>
    Actual commit: <the same 40-character commit>
    Run root: <validation-workspace>/runs/pol2-wrapper-first-...
    Archive reused: False
    Data reused: False
    Verified raw inputs: 116
    unit and generator tests status= 0
    Starlink smoke tests status= 0
    paired POL-2 Tutorial 1 validation status= 0

Reuse an existing verified download
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The runner automatically reuses the following exact archive if it is already
present and passes size and SHA-256 verification::

    $validation_root/downloads/JCMT_POL-2_tutorial1_2017_raw_only.tar.gz

Its required SHA-256 is
``8071bbb929a9224b34c9b104c7bc3f484f32781c64a3ee0e19854a8079e2086b``.
To reuse a download from another location, copy it to that exact destination
before starting the runner::

    mkdir -p "$validation_root/downloads"
    cp --reflink=auto --preserve=mode,timestamps \
        /path/to/JCMT_POL-2_tutorial1_2017_raw_only.tar.gz \
        "$validation_root/downloads/"

    printf '%s  %s\n' \
        8071bbb929a9224b34c9b104c7bc3f484f32781c64a3ee0e19854a8079e2086b \
        "$validation_root/downloads/JCMT_POL-2_tutorial1_2017_raw_only.tar.gz" \
        | sha256sum --check -

A subsequent successful run reports ``Archive reused: True``. If the existing
read-only ``tutorial/raw`` tree also passes the frozen 116-file manifest, it
reports ``Data reused: True``. Reduction products are never reused: each run
gets fresh CLI and wrapper output directories.

Understanding failures and cleanup
----------------------------------

The normal full runner is non-fatal by default, but this walkthrough uses
``--strict``. Therefore ``OPTIONAL POL-2 VALIDATION: INCOMPLETE`` is a failed
validation even if an operator later reruns without ``--strict``. Read the JSON
report's ``error`` and ``steps`` entries before retrying.

Common early failures are:

* the shell is using a Python version other than 3.12;
* test dependencies were not installed from ``.[test]``;
* the wrong Ubuntu Starlink archive was selected;
* Errata Patch 1 was not extracted from Starlink's parent directory;
* ``libgfortran5`` is unavailable;
* the Git checkout is dirty while ``--release-gate`` is enabled; or
* the external workspace is inside the Git checkout.

The runner preserves reports and scientific products for review. It removes
only scratch directories and short path aliases that it created. It never
deletes the Starlink installation, Git checkout, downloaded raw observations,
or completed run directory. On success, there should be no residual
``run_optional_pol2_tutorial.py``, ``run_paired_validation.py``, ``pol2map``,
``calcqu``, or ``makemap`` processes from the run.

For detailed descriptions of each comparison and the non-fatal form of the
runner, see :doc:`../validation`.
