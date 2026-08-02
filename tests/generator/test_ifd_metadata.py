from __future__ import annotations

from pathlib import Path
import tempfile

from helperscripts.ifd_metadata import parse_ifd_actions


def test_parses_ordered_action_parameters_and_current_types():
    content = """
action stats {
  parameter ndf {
    position 1
    type NDF
    access READ
    prompt {Data structure to analyse}
  }
  parameter maxpos {
    size *
    type _INT64
    access WRITE
    vpath INTERNAL
  }
}
"""
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp, "kappa.ifd.in")
        path.write_text(content, encoding="utf-8")
        actions = parse_ifd_actions(path)

    assert list(actions) == ["stats"]
    assert list(actions["stats"]) == ["ndf", "maxpos"]
    assert actions["stats"]["ndf"]["prompt"] == "Data structure to analyse"
    assert actions["stats"]["maxpos"]["size"] == "*"
    assert actions["stats"]["maxpos"]["type"] == "_INT64"
