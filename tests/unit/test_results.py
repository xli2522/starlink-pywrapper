from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from starlink._results import (
    LegacyHdsBackend,
    ParameterSpec,
    PargetBackend,
    ResultBackendError,
    _ResultBackendTimeoutError,
    convert_parget_value,
)


class ConvertPargetValueTests(unittest.TestCase):
    def test_converts_supported_scalars(self):
        self.assertEqual(convert_parget_value("42\n", "_INTEGER", False), 42)
        self.assertEqual(convert_parget_value("9223372036854775807", "_INT64", False),
                         9223372036854775807)
        self.assertAlmostEqual(
            convert_parget_value("1.25D+02", "_DOUBLE", False), 125.0
        )
        self.assertIs(convert_parget_value("FALSE", "_LOGICAL", False), False)
        self.assertEqual(convert_parget_value("'DATA'", "_CHAR", False), "DATA")
        self.assertEqual(
            convert_parget_value("/tmp/example.sdf", "NDF", False),
            "/tmp/example.sdf",
        )

    def test_converts_vectors_without_eval(self):
        self.assertEqual(
            convert_parget_value("[779,525]", "_INT64", True), [779, 525]
        )
        self.assertEqual(
            convert_parget_value("['a,b','c']", "_CHAR", True), ["a,b", "c"]
        )

    def test_converts_multiline_character_vector(self):
        self.assertEqual(
            convert_parget_value(
                "'Data grid indices; first pixel at (1,1)',\n"
                "'Pixel coordinates; first pixel at (0.5,0.5)'",
                "_CHAR",
                True,
            ),
            [
                "Data grid indices; first pixel at (1,1)",
                "Pixel coordinates; first pixel at (0.5,0.5)",
            ],
        )

    def test_undecodable_character_bytes_are_replaced_deterministically(self):
        response = subprocess.CompletedProcess(
            [], 0, b"'bad\xffvalue'\n", b""
        )
        backend = PargetBackend(run=lambda *args, **kwargs: response)
        result = backend.read(
            "demo",
            (ParameterSpec("text", "_CHAR", False, "WRITE"),),
            {"KAPPA_DIR": "/opt/star/bin/kappa"},
        )
        self.assertEqual(result.text, "bad\ufffdvalue")

    def test_unknown_type_fails_loudly(self):
        with self.assertRaises(ResultBackendError):
            convert_parget_value("value", "_COMPLEX", False)


class PargetBackendTests(unittest.TestCase):
    def test_builds_namedtuple_in_metadata_order_and_omits_absent_value(self):
        specs = (
            ParameterSpec("mean", "_DOUBLE", False, "WRITE"),
            ParameterSpec("maxpos", "_INT64", True, "WRITE"),
            ParameterSpec("class", "_CHAR", False, "WRITE"),
            ParameterSpec("median", "_DOUBLE", False, "WRITE"),
        )
        responses = {
            "mean": subprocess.CompletedProcess([], 0, b"12.5\n", b""),
            "maxpos": subprocess.CompletedProcess([], 0, b"[779,525]\n", b""),
            "class": subprocess.CompletedProcess([], 0, b"'DATA'\n", b""),
            "median": subprocess.CompletedProcess(
                [], 1, b"", b"PARGET: Parameter MEDIAN is undefined\n"
            ),
        }

        def fake_run(argv, **kwargs):
            return responses[argv[1].split("=", 1)[1].lower()]

        backend = PargetBackend(run=fake_run)
        result = backend.read(
            "stats",
            specs,
            {"KAPPA_DIR": "/opt/star/bin/kappa", "ADAM_USER": "/tmp/adam"},
            timeout=5,
            cwd="/tmp",
        )

        self.assertEqual(result._fields, ("mean", "maxpos", "class_"))
        self.assertEqual(result.mean, 12.5)
        self.assertEqual(result.maxpos, [779, 525])
        self.assertEqual(result.class_, "DATA")
        first_argv = backend.invocations[0]
        self.assertEqual(first_argv[0], "/opt/star/bin/kappa/parget")
        self.assertIn("applic=stats", first_argv)
        self.assertIn("vector=yes", first_argv)

    def test_unexpected_parget_failure_is_not_treated_as_absent(self):
        response = subprocess.CompletedProcess(
            [], 2, b"", b"parget: corrupt parameter file\n"
        )
        backend = PargetBackend(run=lambda *args, **kwargs: response)
        with self.assertRaises(ResultBackendError) as caught:
            backend.read(
                "stats",
                (ParameterSpec("mean", "_DOUBLE", False, "WRITE"),),
                {"KAPPA_DIR": "/opt/star/bin/kappa"},
            )
        self.assertIn("corrupt parameter file", str(caught.exception))



    def test_patch1_missing_component_diagnostic_is_absent(self):
        response = subprocess.CompletedProcess(
            [],
            1,
            b"",
            (
                b"There is no 'clip' component in the HDS structure\n"
                b"There is no Parameter clip in file /tmp/adam/stats.\n"
            ),
        )
        backend = PargetBackend(run=lambda *args, **kwargs: response)
        result = backend.read(
            "stats",
            (ParameterSpec("clip", "_REAL", True, "READ"),),
            {"KAPPA_DIR": "/opt/star/bin/kappa"},
        )
        self.assertEqual(result._fields, ())

    def test_timeout_budget_is_shared_across_all_parget_calls(self):
        response = subprocess.CompletedProcess([], 0, b"1\n", b"")
        timeouts = []

        def fake_run(*args, **kwargs):
            timeouts.append(kwargs["timeout"])
            return response

        backend = PargetBackend(run=fake_run)
        specs = (
            ParameterSpec("first", "_INTEGER", False, "WRITE"),
            ParameterSpec("second", "_INTEGER", False, "WRITE"),
        )
        with mock.patch(
            "starlink._results.time.monotonic",
            side_effect=(100.0, 101.0, 104.0),
        ):
            backend.read(
                "demo",
                specs,
                {"KAPPA_DIR": "/opt/star/bin/kappa"},
                timeout=5.0,
            )

        self.assertEqual(timeouts, [4.0, 1.0])

    def test_subprocess_timeout_preserves_result_retrieval_details(self):
        def fake_run(argv, **kwargs):
            raise subprocess.TimeoutExpired(
                argv,
                kwargs["timeout"],
                output=b"partial output",
                stderr=b"partial error",
            )

        backend = PargetBackend(run=fake_run)
        with self.assertRaises(_ResultBackendTimeoutError) as caught:
            backend.read(
                "stats",
                (ParameterSpec("mean", "_DOUBLE", False, "WRITE"),),
                {"KAPPA_DIR": "/opt/star/bin/kappa"},
                timeout=0.5,
            )

        self.assertEqual(caught.exception.stdout, b"partial output")
        self.assertEqual(caught.exception.stderr, b"partial error")


class LegacyBackendTests(unittest.TestCase):
    def test_import_is_lazy(self):
        importer = mock.Mock()
        importer.return_value.get_adam_hds_values.return_value = "legacy-result"
        backend = LegacyHdsBackend(import_module=importer)
        self.assertFalse(importer.called)
        result = backend.read("stats", (), {"ADAM_USER": "/tmp/adam"})
        importer.assert_called_once_with("starlink.hdsutils")
        self.assertEqual(result, "legacy-result")


if __name__ == "__main__":
    unittest.main()
