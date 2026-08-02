from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from starlink import wrapper


class ArgumentTests(unittest.TestCase):
    def test_legacy_argument_serialization_is_preserved(self):
        result = wrapper._make_argument_list(
            "^mylist",
            in_="qudata/*",
            null="!",
            enabled=True,
            values=[1, 2],
        )
        self.assertEqual(
            result,
            ["^mylist", "in=qudata/*", "null=!", "enabled=True", "values=[1, 2]"],
        )


class RunnerTests(unittest.TestCase):
    def make_executable(self, root: Path, body: str) -> Path:
        executable = root / "fake star command"
        executable.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        return executable

    def test_command_captures_mixed_non_utf8_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            command = self.make_executable(
                root,
                "printf 'ok\\377out\\n'\nprintf 'bad\\376err\\n' >&2\nexit 7\n",
            )
            with mock.patch.object(
                wrapper,
                "env",
                {"STARLINK_DIR": str(root), "ADAM_USER": str(root / "adam")},
            ), mock.patch.object(wrapper, "adamdir", str(root / "adam")):
                (root / "adam").mkdir()
                with self.assertRaises(wrapper.StarlinkCommandError) as caught:
                    wrapper.starcomm(str(command), "fake")

            error = caught.exception
            self.assertEqual(error.returncode, 7)
            self.assertIn("\ufffd", error.stdout)
            self.assertIn("\ufffd", error.stderr)
            self.assertEqual(error.argv[0], str(command))

    def test_wrapper_only_options_do_not_reach_application_arguments(self):
        completed = mock.Mock(returncode=0, stdout=b"", stderr=b"diagnostic")
        with mock.patch.object(wrapper, "env", {
            "STARLINK_DIR": "/opt/star",
            "ADAM_USER": "/tmp/adam",
        }), mock.patch.object(wrapper, "adamdir", "/tmp/adam"), mock.patch(
            "starlink.wrapper._run_command", return_value=completed
        ) as run, mock.patch(
            "starlink.wrapper._read_result", return_value="result"
        ):
            value = wrapper.starcomm(
                "/opt/star/bin/kappa/stats",
                "stats",
                in_="input.sdf",
                returnstdout=True,
                _starlink_timeout=3,
                _starlink_return_stderr=True,
                _starlink_cwd="/tmp/work",
                _starlink_parameters=(("mean", "_DOUBLE", False, "WRITE"),),
            )

        self.assertEqual(value, ("result", "", "diagnostic"))
        argv = run.call_args.args[0]
        self.assertEqual(
            argv, ["/opt/star/bin/kappa/stats", "in=input.sdf"]
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertEqual(run.call_args.kwargs["cwd"], "/tmp/work")

    def test_whitespace_is_quoted_for_subpar_without_using_a_shell(self):
        completed = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(wrapper, "env", {
            "STARLINK_DIR": "/opt/star",
            "ADAM_USER": "/tmp/adam",
        }), mock.patch.object(wrapper, "adamdir", "/tmp/adam"), mock.patch(
            "starlink.wrapper._run_command", return_value=completed
        ) as run, mock.patch(
            "starlink.wrapper._read_result", return_value="result"
        ):
            value = wrapper.starcomm(
                "/opt/star/bin/kappa/cadd",
                "cadd",
                "/data/input sample.sdf",
                2.5,
                out="/data/output map.sdf",
                tests=[1, 2],
                group="DATA,VARIANCE,QUALITY",
            )

        self.assertEqual(value, "result")
        self.assertEqual(
            run.call_args.args[0],
            [
                "/opt/star/bin/kappa/cadd",
                '"/data/input sample.sdf"',
                "2.5",
                'out="/data/output map.sdf"',
                "tests=[1,2]",
                'group="DATA,VARIANCE,QUALITY"',
            ],
        )

    def test_adam_directory_is_absolute_and_survives_chdir(self):
        self.assertTrue(os.path.isabs(wrapper.adamdir))
        self.assertTrue(Path(wrapper.adamdir).name.startswith("starlink-adam-"))
        original = os.getcwd()
        with tempfile.TemporaryDirectory() as temp:
            os.chdir(temp)
            try:
                self.assertTrue(Path(wrapper.adamdir).is_absolute())
                self.assertTrue(Path(wrapper.adamdir).is_dir())
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
