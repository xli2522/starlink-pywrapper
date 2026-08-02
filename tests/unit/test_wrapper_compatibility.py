from __future__ import annotations

from pathlib import Path
import stat
from unittest import mock

import pytest

from starlink import wrapper


def configured_environment(root: Path) -> dict[str, str]:
    return {
        "STARLINK_DIR": str(root),
        "ADAM_USER": str(root / "adam"),
        "KAPPA_DIR": str(root / "bin/kappa"),
    }


def fake_process(returncode=0, pid=1234):
    process = mock.Mock()
    process.pid = pid
    process.returncode = returncode
    process.communicate.return_value = (None, None)
    return process


def test_set_hds_version_updates_only_configured_child_environment(tmp_path):
    child = configured_environment(tmp_path)
    with mock.patch.object(wrapper, "env", child):
        wrapper.set_HDS_version(5)
    assert child["HDS_VERSION"] == "5"

    with mock.patch.object(wrapper, "env", None):
        with pytest.raises(wrapper.StarlinkEnvironmentError):
            wrapper.set_HDS_version(4)


def test_structural_installation_warns_for_release_mismatch(tmp_path, caplog):
    root = tmp_path / "star"
    (root / "etc").mkdir(parents=True)
    (root / "bin/kappa").mkdir(parents=True)
    (root / "manifests").mkdir()
    (root / "etc/profile").write_text(
        'export KAPPA_DIR="$STARLINK_DIR/bin/kappa"\n', encoding="utf-8"
    )
    parget = root / "bin/kappa/parget"
    parget.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    parget.chmod(parget.stat().st_mode | stat.S_IXUSR)
    (root / "manifests/starlink.version").write_text(
        "2024A\nexample\n", encoding="utf-8"
    )
    old_env = wrapper.env
    old_starpath = wrapper.starpath
    try:
        with caplog.at_level("WARNING", logger="starlink._runtime"):
            wrapper.change_starpath(root)
        assert wrapper.starpath == str(root.resolve())
        assert "generated for Starlink 2025A" in caplog.text
        assert "reports 2024A" in caplog.text
    finally:
        wrapper.env = old_env
        wrapper.starpath = old_starpath


def test_picard_expands_text_list_without_backticks(tmp_path):
    root = tmp_path / "star"
    data = tmp_path / "data"
    data.mkdir()
    first = data / "first file.sdf"
    second = data / "second.sdf"
    first.touch()
    second.touch()
    listing = data / "inputs.lis"
    listing.write_text("first file.sdf\nsecond.sdf\n", encoding="utf-8")
    process = fake_process()

    with mock.patch.object(wrapper, "env", configured_environment(root)), mock.patch(
        "starlink.wrapper.subprocess.Popen", return_value=process
    ) as popen:
        result = wrapper.picard("REDUCE", listing, dataout=tmp_path)

    argv = popen.call_args.args[0]
    assert argv[-3:] == ["REDUCE", str(first), str(second)]
    assert all("`" not in value for value in argv)
    assert popen.call_args.kwargs["shell"] is False
    assert result.status == 0
    assert result.pid == process.pid


def test_oracdr_writes_validated_file_list_and_uses_literal_options(tmp_path):
    root = tmp_path / "star"
    raw = tmp_path / "raw"
    raw.mkdir()
    first = raw / "a.sdf"
    first.touch()
    process = fake_process()

    def inspect_popen(argv, **kwargs):
        files_arg = next(value for value in argv if value.startswith("-files="))
        content = Path(files_arg.split("=", 1)[1]).read_text(encoding="utf-8")
        assert content == str(first) + "\n"
        assert "-calib=GAIN=2" in argv
        assert "-calib GAIN=2" not in argv
        assert kwargs["shell"] is False
        return process

    with mock.patch.object(wrapper, "env", configured_environment(root)), mock.patch(
        "starlink.wrapper.subprocess.Popen", side_effect=inspect_popen
    ):
        result = wrapper.oracdr(
            "SCUBA2_850",
            rawfiles=[first.name],
            datain=raw,
            dataout=tmp_path,
            calib="GAIN=2",
        )

    assert result.status == 0


def test_orac_and_picard_reject_missing_inputs(tmp_path):
    root = tmp_path / "star"
    with mock.patch.object(wrapper, "env", configured_environment(root)):
        with pytest.raises(FileNotFoundError):
            wrapper.picard("REDUCE", [tmp_path / "missing.sdf"], dataout=tmp_path)
        with pytest.raises(FileNotFoundError):
            wrapper.oracdr(
                "ACSIS",
                rawfiles=["missing.sdf"],
                datain=tmp_path,
                dataout=tmp_path,
            )


