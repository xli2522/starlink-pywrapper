from __future__ import annotations

from pathlib import Path
import tempfile
from types import ModuleType
import unittest

import pytest
from unittest import mock

from starlink import utilities


class FitsHeaderUtilityTests(unittest.TestCase):
    def test_default_reader_uses_fitslist_and_private_logfile(self):
        seen = {}

        def fake_starcomm(command, command_name, datafile, **kwargs):
            seen["command"] = command
            seen["command_name"] = command_name
            seen["datafile"] = datafile
            seen["kwargs"] = kwargs
            Path(kwargs["logfile"]).write_text(
                "SIMPLE  =                    T\n"
                "OBJECT  = '3C 273'\n"
                "END\n",
                encoding="ascii",
            )

        with tempfile.TemporaryDirectory() as temp, mock.patch(
            "starlink.wrapper.starcomm", side_effect=fake_starcomm
        ):
            source = Path(temp, "input.sdf")
            source.touch()
            header = utilities.get_ndf_fitshdr(source)
            logfile = Path(seen["kwargs"]["logfile"])

        self.assertEqual(seen["command"], "$KAPPA_DIR/fitslist")
        self.assertEqual(seen["command_name"], "fitslist")
        self.assertEqual(seen["datafile"], str(source.resolve()))
        self.assertEqual(seen["kwargs"]["_starlink_parameters"], ())
        self.assertEqual(header["OBJECT"], "3C 273")
        self.assertFalse(logfile.exists())

    def test_legacy_reader_reports_missing_binding_clearly(self):
        with mock.patch.dict("sys.modules", {"starlink.hds": None}):
            with self.assertRaisesRegex(ImportError, "starlink.hds"):
                utilities.get_ndf_fitshdr_legacy("input.sdf")


if __name__ == "__main__":
    unittest.main()

def test_resource_filename_supports_generated_module_anchor():
    from starlink._resources import resource_filename

    filename = resource_filename("starlink.kappa", "kappa_help/stats.rst")
    assert Path(filename).is_file()


def test_function_summary_and_starhelp_paths(tmp_path):
    from starlink import utilities

    module = ModuleType("demo")
    exec("def alpha():\n    '''Alpha summary.'''\n", module.__dict__)
    assert "Alpha summary" in utilities.get_module_function_summary(module)
    assert utilities.get_module_function_summary(ModuleType("empty")) == ""

    with mock.patch("starlink.utilities.pydoc.pager") as pager:
        utilities.starhelp(module)
    pager.assert_called_once()

    def generated():
        return None

    generated.__module__ = "starlink.kappa"
    help_file = tmp_path / "generated.rst"
    help_file.write_text("Generated help", encoding="utf-8")
    with mock.patch(
        "starlink.utilities.resource_filename", return_value=str(help_file)
    ), mock.patch("starlink.utilities.pydoc.pager") as pager:
        utilities.starhelp(generated)
    pager.assert_called_once_with("Generated help")

    with mock.patch(
        "starlink.utilities.resource_filename",
        return_value=str(tmp_path / "missing.rst"),
    ):
        with pytest.raises(FileNotFoundError):
            utilities.starhelp(generated)

    with pytest.raises(TypeError, match="module or function"):
        utilities.starhelp(42)
