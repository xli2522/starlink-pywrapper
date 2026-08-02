from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
from unittest import mock

import pytest

from starlink import wrapper
from starlink import _runtime
from starlink._results import ResultBackendError


def child_env(root: Path):
    return {
        "STARLINK_DIR": str(root),
        "ADAM_USER": str(root / "adam"),
        "KAPPA_DIR": str(root / "bin/kappa"),
    }


def test_runtime_configuration_and_result_backend_edges(tmp_path):
    with mock.patch(
        "starlink._runtime.capture_starlink_environment",
        return_value={"STARLINK_DIR": str(tmp_path)},
    ), mock.patch(
        "starlink._runtime.configure_session_environment",
        return_value={"STARLINK_DIR": str(tmp_path), "ADAM_USER": str(tmp_path)},
    ) as configure:
        result = wrapper.setup_starlink_environ(tmp_path, tmp_path / "adam", False)
    assert result["STARLINK_DIR"] == str(tmp_path)
    assert configure.call_args.kwargs["noprompt"] is False

    original = wrapper.get_result_backend()
    try:
        wrapper.set_result_backend(" LEGACY_HDS ")
        assert wrapper.get_result_backend() == "legacy_hds"
        with pytest.raises(ValueError, match="result backend"):
            wrapper.set_result_backend("unknown")
    finally:
        wrapper.set_result_backend(original)

    assert _runtime._decode(None) == ""
    assert _runtime._decode("text") == "text"
    assert _runtime._quote_subpar_argument('"already quoted"') == '"already quoted"'
    assert _runtime._quote_subpar_argument("items=[1, 2]") == "items=[1,2]"
    with pytest.raises(ResultBackendError, match="Unknown result"):
        _runtime._read_result("demo", (), {}, backend="missing")


def test_runtime_session_directories_do_not_resolve_short_alias(tmp_path):
    physical = tmp_path / ("physical-" + "x" * 80)
    physical.mkdir()
    alias = tmp_path / "p2-short"
    alias.symlink_to(physical, target_is_directory=True)
    adam = alias / "starlink-adam-test"
    star_temp = alias / "starlink-temp-test"
    adam.mkdir()
    star_temp.mkdir()

    fake_adam = mock.Mock(spec=tempfile.TemporaryDirectory)
    fake_adam.name = str(adam)
    fake_temp = mock.Mock(spec=tempfile.TemporaryDirectory)
    fake_temp.name = str(star_temp)
    with mock.patch.object(_runtime, "_adam_directory", fake_adam), mock.patch.object(
        _runtime, "_star_temp_directory", fake_temp
    ):
        actual_adam, actual_temp = _runtime._ensure_session_directories()

    assert actual_adam == str(adam)
    assert actual_temp == str(star_temp)


def test_legacy_result_and_xwindow_dispatch(tmp_path):
    with mock.patch(
        "starlink._runtime.LegacyHdsBackend.read", return_value="legacy"
    ):
        assert _runtime._read_result(
            "demo", (), {"ADAM_USER": str(tmp_path)}, backend="legacy_hds"
        ) == "legacy"

    with mock.patch("starlink._runtime._run_command") as run:
        _runtime._maybe_create_xwindow(
            {"device": "plot/GWM"},
            {"STARLINK_DIR": "/path/to/starlink"},
            cwd=tmp_path,
            timeout=4,
            adam_dir=str(tmp_path),
        )
        _runtime._maybe_create_xwindow(
            {"device": object()},
            {"STARLINK_DIR": "/path/to/starlink"},
            cwd=None,
            timeout=None,
            adam_dir=str(tmp_path),
        )
    assert run.call_args.args[0] == [
        "/path/to/starlink/bin/xmake", "plot"
    ]


def test_starcomm_validation_and_stderr_only(tmp_path):
    completed = subprocess.CompletedProcess(["true"], 0, b"out", b"err")
    with mock.patch.object(wrapper, "env", None):
        with pytest.raises(wrapper.StarlinkEnvironmentError):
            wrapper.starcomm("/bin/true", "true")

    environment = child_env(tmp_path)
    (tmp_path / "adam").mkdir()
    with mock.patch.object(wrapper, "env", environment), mock.patch.object(
        wrapper, "adamdir", str(tmp_path / "adam")
    ):
        with pytest.raises(ValueError, match="non-negative"):
            wrapper.starcomm("/bin/true", "true", _starlink_timeout=-1)
        with pytest.raises(TypeError, match="metadata"):
            wrapper.starcomm(
                "/bin/true", "true", _starlink_parameters=object()
            )
        with pytest.raises(ValueError, match="cannot be empty"):
            wrapper.starcomm("", "true")
        with mock.patch(
            "starlink.wrapper._run_command", return_value=completed
        ), mock.patch("starlink.wrapper._read_result", return_value="result"):
            value = wrapper.starcomm(
                "/bin/true", "true", _starlink_return_stderr=True
            )
    assert value == ("result", "err")


def test_wrapper_legacy_error_signal_and_environment_branches(tmp_path):
    assert "demo arg" in str(wrapper.StarError("demo", "arg", "stderr"))
    with mock.patch("starlink.wrapper.signal.signal") as set_signal:
        wrapper.subprocess_setup()
    assert set_signal.call_count == 2

    root = tmp_path / "star"
    with mock.patch.object(wrapper, "env", child_env(root)):
        scuba = wrapper.oracdr_envsetup("SCUBA2_850", utdate=20250102)
        acsis = wrapper.oracdr_envsetup("ACSIS", utdate=20250102)
        ukirt = wrapper.oracdr_envsetup("UFTI", utdate=20250102)
        other = wrapper.oracdr_envsetup("OTHER", utdate=20250102)
        custom = wrapper.oracdr_envsetup(
            "ACSIS",
            ORAC_DIR=tmp_path / "orac",
            ORAC_DATA_IN=tmp_path,
            ORAC_DATA_OUT=tmp_path,
            ORAC_CAL_ROOT=tmp_path / "cal",
            ORAC_DATA_CAL=tmp_path / "data-cal",
            ORAC_PERL5LIB=tmp_path / "perl",
        )
    assert scuba["ORAC_DATA_IN"].endswith("/20250102")
    assert acsis["ORAC_DATA_IN"].endswith("/20250102")
    assert ukirt["ORAC_DATA_IN"].endswith("/ufti/20250102")
    assert other["ORAC_DATA_IN"] == "/"
    assert custom["ORAC_PERL5LIB"] == str((tmp_path / "perl").resolve())


def test_orac_validation_list_mode_options_and_output_inventory(tmp_path):
    for kwargs in (
        {"loop": "bad", "rawfiles": ["x"]},
        {"loop": "list", "utdate": None, "obslist": None},
        {"loop": "file", "rawfiles": None},
    ):
        with pytest.raises(ValueError):
            wrapper.oracdr("ACSIS", dataout=tmp_path, datain=tmp_path, **kwargs)

    root = tmp_path / "star"
    process = mock.Mock(pid=55, returncode=0)
    process.communicate.return_value = (None, None)

    def create_outputs(argv, **kwargs):
        out = Path(kwargs["env"]["ORAC_DATA_OUT"])
        (out / ".oracdr_55.log").write_text("log", encoding="utf-8")
        (out / "product.sdf").touch()
        (out / "preview.png").touch()
        (out / "log.group").touch()
        assert "-list=1,2" in argv
        assert "-onegroup" in argv
        assert "-verbose" in argv
        assert "-warn" in argv
        assert "-debug" in argv
        assert argv[-1] == "REDUCE"
        return process

    with mock.patch.object(wrapper, "env", child_env(root)), mock.patch(
        "starlink.wrapper.subprocess.Popen", side_effect=create_outputs
    ):
        result = wrapper.oracdr(
            "ACSIS",
            loop="list",
            utdate=20250102,
            obslist=[1, 2],
            dataout=tmp_path,
            datain=tmp_path,
            recipe="REDUCE",
            onegroup=True,
            verbose=True,
            warn=True,
            debug=True,
        )
    assert result.runlog.endswith("oracdr_55.log")
    assert result.datafiles[0].endswith("product.sdf")
    assert result.imagefiles[0].endswith("preview.png")
    assert result.logfiles[0].endswith("log.group")


def test_orac_start_failure_is_structured(tmp_path):
    with mock.patch(
        "starlink.wrapper.subprocess.Popen", side_effect=OSError("missing")
    ):
        with pytest.raises(wrapper.StarlinkCommandError) as caught:
            wrapper._run_orac(
                ["/missing"], child_env(tmp_path), tmp_path, "picard"
            )
    assert caught.value.returncode is None
    assert "Unable to start picard" in str(caught.value)


