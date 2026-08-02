from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import tempfile
from unittest import mock

import pytest

from starlink import wrapper
from starlink._runtime import _read_result, _run_command
from starlink._results import _ResultBackendTimeoutError


def test_executable_not_found_is_structured_error():
    with tempfile.TemporaryDirectory() as temp:
        with pytest.raises(wrapper.StarlinkCommandError) as caught:
            _run_command(
                [str(Path(temp) / "missing executable")],
                env={"PATH": "/usr/bin:/bin"},
                cwd=temp,
                timeout=1,
                adam_dir=temp,
            )
    error = caught.value
    assert error.returncode is None
    assert "Unable to start" in str(error)
    assert error.stderr


def test_timeout_terminates_process_group_and_preserves_output():
    process = mock.Mock()
    process.pid = 12345
    process.returncode = -15
    process.communicate.side_effect = [
        subprocess.TimeoutExpired(["fake"], 0.1),
        (b"partial stdout", b"partial stderr"),
    ]
    with mock.patch(
        "starlink._runtime.subprocess.Popen", return_value=process
    ), mock.patch(
        "starlink._runtime._terminate_process_group"
    ) as terminate:
        with pytest.raises(wrapper.StarlinkTimeoutError) as caught:
            _run_command(
                ["fake"],
                env={"PATH": "/usr/bin:/bin"},
                cwd="/tmp",
                timeout=0.1,
                adam_dir="/tmp/adam",
            )

    terminate.assert_called_once_with(process)
    assert caught.value.stdout == "partial stdout"
    assert caught.value.stderr == "partial stderr"
    assert caught.value.returncode == -15


def test_keyboard_interrupt_terminates_process_group():
    process = mock.Mock()
    process.pid = 12345
    process.communicate.side_effect = [KeyboardInterrupt(), (b"", b"")]
    with mock.patch(
        "starlink._runtime.subprocess.Popen", return_value=process
    ), mock.patch(
        "starlink._runtime._terminate_process_group"
    ) as terminate:
        with pytest.raises(KeyboardInterrupt):
            _run_command(
                ["fake"],
                env={"PATH": "/usr/bin:/bin"},
                cwd="/tmp",
                timeout=None,
                adam_dir="/tmp/adam",
            )

    terminate.assert_called_once_with(process)
    assert process.communicate.call_count == 2


def test_result_retrieval_timeout_is_a_structured_starlink_timeout():
    backend_timeout = _ResultBackendTimeoutError(
        ["/opt/star/bin/kappa/parget", "parname=mean", "applic=stats"],
        0.25,
        b"partial stdout",
        b"partial stderr",
    )
    with mock.patch(
        "starlink._runtime.PargetBackend.read",
        side_effect=backend_timeout,
    ):
        with pytest.raises(wrapper.StarlinkTimeoutError) as caught:
            _read_result(
                "stats",
                (),
                {
                    "KAPPA_DIR": "/opt/star/bin/kappa",
                    "ADAM_USER": "/tmp/adam",
                },
                timeout=0.25,
                cwd="/tmp/work",
            )

    error = caught.value
    assert error.stdout == "partial stdout"
    assert error.stderr == "partial stderr"
    assert error.adam_dir == "/tmp/adam"
    assert error.cwd == "/tmp/work"


@pytest.mark.parametrize("reader_fails", [False, True])
def test_application_parameter_file_is_removed_after_call(reader_fails: bool):
    with tempfile.TemporaryDirectory() as temp:
        adam = Path(temp)
        parameter_file = adam / "fake.sdf"
        completed = subprocess.CompletedProcess(["fake"], 0, b"ok", b"")

        def run(*args, **kwargs):
            parameter_file.write_bytes(b"new parameter state")
            return completed

        def read(*args, **kwargs):
            if reader_fails:
                raise RuntimeError("result failure")
            return "result"

        with mock.patch.object(
            wrapper,
            "env",
            {"STARLINK_DIR": temp, "ADAM_USER": temp},
        ), mock.patch.object(wrapper, "adamdir", temp), mock.patch(
            "starlink.wrapper._run_command", side_effect=run
        ), mock.patch(
            "starlink.wrapper._read_result", side_effect=read
        ):
            if reader_fails:
                with pytest.raises(RuntimeError, match="result failure"):
                    wrapper.starcomm("/bin/true", "fake")
            else:
                assert wrapper.starcomm("/bin/true", "fake") == "result"

        assert not parameter_file.exists()


def test_one_hundred_calls_replace_parameter_state_without_stale_values(
    tmp_path: Path,
):
    adam = tmp_path / "adam"
    adam.mkdir()
    parameter_file = adam / "fake.sdf"
    completed = subprocess.CompletedProcess(["fake"], 0, b"", b"")
    sequence = iter(range(100))

    def run(*args, **kwargs):
        del args, kwargs
        parameter_file.write_text(str(next(sequence)), encoding="ascii")
        return completed

    def read(*args, **kwargs):
        del args, kwargs
        return int(parameter_file.read_text(encoding="ascii"))

    with mock.patch.object(
        wrapper,
        "env",
        {"STARLINK_DIR": str(tmp_path), "ADAM_USER": str(adam)},
    ), mock.patch.object(wrapper, "adamdir", str(adam)), mock.patch(
        "starlink.wrapper._run_command", side_effect=run
    ), mock.patch(
        "starlink.wrapper._read_result", side_effect=read
    ):
        values = [wrapper.starcomm("/bin/true", "fake") for _ in range(100)]

    assert values == list(range(100))
    assert not parameter_file.exists()


def test_debug_log_records_argv_without_environment_secrets(caplog):
    completed = subprocess.CompletedProcess(
        ["/opt/star/bin/kappa/stats"], 0, b"", b""
    )
    secret = "must-not-appear-in-debug-output"
    with mock.patch.object(
        wrapper,
        "env",
        {
            "STARLINK_DIR": "/opt/star",
            "ADAM_USER": "/tmp/adam",
            "PRIVATE_TOKEN": secret,
        },
    ), mock.patch.object(wrapper, "adamdir", "/tmp/adam"), mock.patch(
        "starlink.wrapper._run_command", return_value=completed
    ), mock.patch(
        "starlink.wrapper._read_result", return_value="result"
    ), caplog.at_level(logging.DEBUG, logger="starlink._runtime"):
        wrapper.starcomm(
            "/opt/star/bin/kappa/stats",
            "stats",
            "input.sdf",
        )

    log_text = caplog.text
    assert "/opt/star/bin/kappa/stats" in log_text
    assert "input.sdf" in log_text
    assert secret not in log_text
