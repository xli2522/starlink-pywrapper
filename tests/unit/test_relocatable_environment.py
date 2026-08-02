from __future__ import annotations

from pathlib import Path
import stat
import tempfile

from starlink._environment import capture_starlink_environment


def test_profile_receives_validated_starlink_dir_before_it_is_sourced():
    with tempfile.TemporaryDirectory() as temp:
        installation = Path(temp) / "relocated star"
        (installation / "etc").mkdir(parents=True)
        (installation / "bin" / "kappa").mkdir(parents=True)
        (installation / "etc" / "profile").write_text(
            'export PROFILE_INPUT_STARLINK_DIR="$STARLINK_DIR"\n'
            'export KAPPA_DIR="$STARLINK_DIR/bin/kappa"\n'
            'export LD_LIBRARY_PATH="$STARLINK_DIR/lib"\n',
            encoding="utf-8",
        )
        parget = installation / "bin" / "kappa" / "parget"
        parget.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        parget.chmod(parget.stat().st_mode | stat.S_IXUSR)

        captured = capture_starlink_environment(
            installation,
            extra_profile_environment={"STARLINK_DIR": "/wrong/value"},
        )

    expected = str(installation.resolve())
    assert captured["PROFILE_INPUT_STARLINK_DIR"] == expected
    assert captured["STARLINK_DIR"] == expected
    assert captured["KAPPA_DIR"] == expected + "/bin/kappa"
    assert captured["LD_LIBRARY_PATH"] == expected + "/lib"
