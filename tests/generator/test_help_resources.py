from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest


REPO = Path(__file__).resolve().parents[2]
HELPERS = REPO / "helperscripts"
sys.path.insert(0, str(HELPERS))

from help_resources import (  # noqa: E402
    _select_source,
    generate_package_help,
)
from html_to_rst import html_to_rst  # noqa: E402


PINNED_COMMIT = "899c03fc4af3b6feb26756b904e5a597343191ed"
PINNED_RELEASE = "2025A plus Errata Patch 1"


def test_prohtml_converter_preserves_help_structure() -> None:
    result = html_to_rst(
        "<H1>STATS</H1><H3>Purpose</H3>Compute statistics<P>"
        "<UL><LI>mean<LI>sigma</UL><H3>Usage</H3>"
        "<PRE>stats image</PRE>"
    )

    assert "STATS\n#####" in result
    assert "Purpose\n~~~~~~~" in result
    assert "+ mean" in result
    assert "+ sigma" in result
    assert "::\n\n    stats image" in result


def test_ambiguous_source_requires_an_explicit_override(tmp_path: Path) -> None:
    source = tmp_path / "applications" / "demo"
    first = source / "one" / "task.f"
    second = source / "two" / "task.f"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    index = {"task": [first, second]}

    with pytest.raises(RuntimeError, match="Ambiguous help source"):
        _select_source(source, "demo", "task", index)


def test_ccdhelp_override_selects_current_root_source(tmp_path: Path) -> None:
    source = tmp_path / "applications" / "ccdpack"
    current = source / "ccdhelp.f"
    duplicate = source / "help" / "ccdhelp.f"
    current.parent.mkdir(parents=True)
    duplicate.parent.mkdir(parents=True)
    current.write_text("current", encoding="utf-8")
    duplicate.write_text("duplicate", encoding="utf-8")

    selected = _select_source(
        source,
        "ccdpack",
        "ccdhelp",
        {"ccdhelp": [current, duplicate]},
    )

    assert selected == current


def test_figaro_table_uses_authoritative_package_help(tmp_path: Path) -> None:
    source = tmp_path / "applications" / "figaro"
    internal = source / "main" / "table.f"
    command = source / "figaro2" / "table.f"

    selected = _select_source(
        source, "figaro", "table", {"table": [internal, command]}
    )

    assert selected is None


def test_checked_in_help_manifest_matches_resources() -> None:
    manifest_path = REPO / "manifests" / "help_manifest_2025a.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert document["schema_version"] == 1
    assert document["starlink_release"] == PINNED_RELEASE
    assert document["starlink_source_commit"] == PINNED_COMMIT
    records = document["resources"]
    assert document["resource_count"] == len(records)

    recorded = {record["path"] for record in records}
    actual = {
        path.relative_to(REPO).as_posix()
        for path in (REPO / "starlink").glob("*_help/*.rst")
    }
    assert recorded == actual

    for record in records:
        path = REPO / record["path"]
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == record["sha256"]
        text = content.decode("utf-8")
        assert f".. Starlink source commit: {PINNED_COMMIT}" in text
        assert f".. Starlink source file: {record['source']}" in text
        lines = text.splitlines()
        assert all(line == line.rstrip() for line in lines)
        assert not any(
            line.startswith(("<<<<<<< ", "=======", ">>>>>>> "))
            for line in lines
        )


def test_package_generation_replaces_stale_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_repo = tmp_path / "source"
    source_root = source_repo / "applications" / "demo"
    source_root.mkdir(parents=True)
    source = source_root / "task.f"
    source.write_text("source", encoding="utf-8")

    baseline = tmp_path / "baseline"
    baseline_help = baseline / "demo_help"
    baseline_help.mkdir(parents=True)
    (baseline_help / "task.rst").write_text("old", encoding="utf-8")

    output = tmp_path / "output"
    output_help = output / "demo_help"
    output_help.mkdir(parents=True)
    (output_help / "stale.rst").write_text("stale", encoding="utf-8")

    def fake_prohtml(_installation, _source, destination, _adam_user):
        destination.write_text(
            "<H1>TASK</H1><H3>Purpose</H3>Current help<P>",
            encoding="utf-8",
        )

    monkeypatch.setattr("help_resources._run_prohtml", fake_prohtml)
    records = generate_package_help(
        source_repo=source_repo,
        source_root=source_root,
        installation=tmp_path / "installation",
        output=output,
        baseline=baseline,
        package="demo",
        command_paths={"task": "$DEMO_DIR/task"},
        release=PINNED_RELEASE,
        commit=PINNED_COMMIT,
    )

    assert [path.name for path in output_help.iterdir()] == ["task.rst"]
    assert "Current help" in (output_help / "task.rst").read_text(encoding="utf-8")
    assert records[0]["source"] == "applications/demo/task.f"


def test_invalid_source_prologue_falls_back_to_package_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_repo = tmp_path / "source"
    source_root = source_repo / "applications" / "demo"
    source_root.mkdir(parents=True)
    (source_root / "task.f").write_text("legacy source", encoding="utf-8")
    (source_root / "demo.hlp").write_text(
        "1 TASK\n\n TASK - Current package help\n\n"
        "2 Description\n This remains available in 2025A.\n"
        "2 Parameters\n3 INPUT\n Input dataset.\n",
        encoding="latin-1",
    )

    baseline_help = tmp_path / "baseline" / "demo_help"
    baseline_help.mkdir(parents=True)
    (baseline_help / "task.rst").write_text("old", encoding="utf-8")

    def invalid_prohtml(_installation, _source, destination, _adam_user):
        destination.write_text("", encoding="utf-8")
        raise RuntimeError("invalid source prologue")

    monkeypatch.setattr("help_resources._run_prohtml", invalid_prohtml)
    output = tmp_path / "output"
    records = generate_package_help(
        source_repo=source_repo,
        source_root=source_root,
        installation=tmp_path / "installation",
        output=output,
        baseline=tmp_path / "baseline",
        package="demo",
        command_paths={"task": "$DEMO_DIR/task"},
        release=PINNED_RELEASE,
        commit=PINNED_COMMIT,
    )

    text = (output / "demo_help" / "task.rst").read_text(encoding="utf-8")
    assert "Source format: Starlink package help fallback" in text
    assert "TASK\n####" in text
    assert "Description\n-----------" in text
    assert "This remains available in 2025A." in text
    assert "Current package help\n\nDescription" in text
    assert records[0]["source"] == "applications/demo/demo.hlp"
