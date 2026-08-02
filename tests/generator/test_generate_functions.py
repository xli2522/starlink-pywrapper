from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


GENERATOR = (
    Path(__file__).resolve().parents[2] / "helperscripts" / "generate_functions.py"
)
SPEC = importlib.util.spec_from_file_location("generate_functions", GENERATOR)
assert SPEC and SPEC.loader
generate_functions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_functions)


class GeneratorTests(unittest.TestCase):
    def parameter(self, name, type_, access, *, list_=False, position=None):
        return generate_functions.parinfo(
            name,
            type_,
            "prompt",
            None,
            position,
            None,
            None,
            access,
            None,
            None,
            None,
            list_,
            access.lower(),
        )

    def test_unknown_type_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "_COMPLEX"):
            generate_functions._get_python_type("_COMPLEX")

    def test_module_contains_ordered_private_result_metadata(self):
        parameters = {
            "in": self.parameter("in", "NDF", "READ", position="1"),
            "mean": self.parameter("mean", "_DOUBLE", "WRITE"),
            "maxpos": self.parameter(
                "maxpos", "_INT64", "WRITE", list_=True
            ),
        }
        info = generate_functions.commandinfo(
            "class", "Description", parameters, None
        )
        module_dict = {"class": info}
        docs = generate_functions.make_docstrings(module_dict)

        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                generate_functions.create_module(
                    "KAPPA",
                    ["class"],
                    docs,
                    {"class": "$KAPPA_DIR/class"},
                    module_dict,
                )
                first = Path("kappa.py").read_text(encoding="utf-8")
                generate_functions.create_module(
                    "KAPPA",
                    ["class"],
                    docs,
                    {"class": "$KAPPA_DIR/class"},
                    module_dict,
                )
                second = Path("kappa.py").read_text(encoding="utf-8")
            finally:
                os.chdir(previous)

        self.assertEqual(first, second)
        self.assertIn("'class': (", first)
        self.assertLess(first.index("('in', 'NDF'"), first.index("('mean', '_DOUBLE'"))
        self.assertIn("('maxpos', '_INT64', True, 'WRITE')", first)
        self.assertIn("def class_(", first)
        self.assertIn("'class',", first)
        self.assertIn(
            "_starlink_parameters=__starlink_parameters['class']", first
        )


if __name__ == "__main__":
    unittest.main()
