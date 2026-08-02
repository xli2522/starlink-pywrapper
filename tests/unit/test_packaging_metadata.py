"""Regression checks for the modernized package metadata."""

from __future__ import annotations

from pathlib import Path
import runpy
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def metadata() -> dict:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_project_metadata_has_one_authoritative_source() -> None:
    project = metadata()["project"]
    setup_source = (PROJECT_ROOT / "setup.py").read_text(encoding="utf-8")

    assert project["name"] == "starlink-pywrapper"
    assert project["version"] == "0.4.0.dev1"
    assert project["requires-python"] == ">=3.12,<3.13"
    assert project["dependencies"] == ["starlink-pyhds"]
    assert not (PROJECT_ROOT / "requirements.txt").exists()
    assert "version=" not in setup_source
    assert "install_requires" not in setup_source
    assert "license=" not in setup_source


def test_package_version_matches_project_metadata() -> None:
    version_namespace = runpy.run_path(PROJECT_ROOT / "starlink" / "_version.py")

    assert version_namespace["__version__"] == metadata()["project"]["version"]


def test_license_is_declared_and_included_in_source_archives() -> None:
    project = metadata()["project"]
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    manifest = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert project["license"] == "GPL-3.0-or-later"
    assert project["license-files"] == ["LICENSE"]
    assert "License ::" not in project["classifiers"]
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 29 June 2007" in license_text
    assert "include LICENSE" in manifest.splitlines()


def test_project_urls_distinguish_the_fork_and_upstream_projects() -> None:
    urls = metadata()["project"]["urls"]

    assert urls["Homepage"].startswith("https://github.com/")
    assert urls["Upstream Repository"] == (
        "https://github.com/Starlink/starlink-pywrapper"
    )
    assert urls["Starlink Homepage"] == (
        "https://starlink.eao.hawaii.edu/starlink/"
    )
