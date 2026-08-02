from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

from starlink._environment import (
    StarlinkEnvironmentError,
    capture_starlink_environment,
    configure_session_environment,
)


class EnvironmentTests(unittest.TestCase):
    def make_installation(self, root: Path, profile: str) -> Path:
        installation = root / "Star link ; $unicode-星"
        (installation / "etc").mkdir(parents=True)
        (installation / "bin" / "kappa").mkdir(parents=True)
        (installation / "etc" / "profile").write_text(profile, encoding="utf-8")
        parget = installation / "bin" / "kappa" / "parget"
        parget.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        parget.chmod(parget.stat().st_mode | stat.S_IXUSR)
        return installation

    def test_profile_is_captured_without_mutating_or_leaking_parent_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installation = self.make_installation(
                root,
                'export STARLINK_DIR="$STARLINK_PROFILE_TEST_ROOT"\n'
                'export PROFILE_MARKER="captured value"\n',
            )
            before = os.environ.copy()
            os.environ["UNRELATED_WRAPPER_TEST_SECRET"] = "must-not-leak"
            try:
                child = capture_starlink_environment(
                    installation,
                    extra_profile_environment={
                        "STARLINK_PROFILE_TEST_ROOT": str(installation)
                    },
                )
            finally:
                os.environ.clear()
                os.environ.update(before)

            self.assertEqual(child["PROFILE_MARKER"], "captured value")
            self.assertEqual(child["STARLINK_DIR"], str(installation.resolve()))
            self.assertNotIn("UNRELATED_WRAPPER_TEST_SECRET", child)
            self.assertNotIn("STARLINK_PROFILE", child)
            self.assertEqual(
                child["PATH"].split(os.pathsep)[0],
                str(Path(sys.executable).absolute().parent),
            )

    def test_rejects_missing_profile_and_missing_parget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installation = root / "star"
            installation.mkdir()
            with self.assertRaisesRegex(StarlinkEnvironmentError, "etc/profile"):
                capture_starlink_environment(installation)

            (installation / "etc").mkdir()
            (installation / "etc" / "profile").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(StarlinkEnvironmentError, "parget"):
                capture_starlink_environment(installation)

    def test_profile_path_and_fixed_environment_cannot_be_overridden(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installation = self.make_installation(
                root,
                'export PROFILE_MARKER="trusted profile"\n',
            )
            untrusted = root / "untrusted-profile"
            untrusted.write_text(
                'export PROFILE_MARKER="wrong profile"\n', encoding="utf-8"
            )

            child = capture_starlink_environment(
                installation,
                extra_profile_environment={
                    "PATH": "/untrusted/bin",
                    "STARLINK_DIR": "/untrusted/star",
                    "STARLINK_PROFILE": str(untrusted),
                },
            )

            self.assertEqual(child["PROFILE_MARKER"], "trusted profile")
            self.assertEqual(
                child["STARLINK_DIR"], str(installation.resolve())
            )
            self.assertNotIn("/untrusted/bin", child["PATH"])

    def test_rejects_shell_startup_environment_injection(self):
        with tempfile.TemporaryDirectory() as temp:
            installation = self.make_installation(Path(temp), "")
            for key in ("BASH_ENV", "LD_PRELOAD", "BASH_FUNC_demo%%"):
                with self.subTest(key=key):
                    with self.assertRaisesRegex(
                        StarlinkEnvironmentError, "shell startup"
                    ):
                        capture_starlink_environment(
                            installation,
                            extra_profile_environment={key: "/tmp/untrusted"},
                        )

    def test_session_environment_preserves_short_symlink_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            physical = root / ("physical-" + "x" * 80)
            (physical / "adam").mkdir(parents=True)
            (physical / "star-temp").mkdir()
            alias = root / "p2-short"
            alias.symlink_to(physical, target_is_directory=True)

            child = configure_session_environment(
                {"STARLINK_DIR": "/path/to/starlink"},
                alias / "adam",
                alias / "star-temp",
            )

            self.assertEqual(child["ADAM_USER"], str(alias / "adam"))
            self.assertEqual(child["AGI_USER"], str(alias / "adam"))
            self.assertEqual(child["STAR_TEMP"], str(alias / "star-temp"))
            self.assertEqual(
                Path(child["ADAM_USER"]).resolve(), physical / "adam"
            )


if __name__ == "__main__":
    unittest.main()
