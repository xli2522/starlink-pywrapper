from __future__ import annotations

from pathlib import Path
import tempfile

from helperscripts.ifd_metadata import parse_ifd_actions


def test_ifd_parser_preserves_ptype_for_graphics_devices():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "demo.ifd"
        path.write_text(
            "action gdset {\n"
            "  parameter device {\n"
            "    ptype DEVICE\n"
            "    access READ\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        actions = parse_ifd_actions(path)
    assert actions["gdset"]["device"]["ptype"] == "DEVICE"
