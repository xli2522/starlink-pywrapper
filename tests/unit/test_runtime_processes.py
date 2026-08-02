from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
from unittest import mock

import pytest

from starlink._runtime import (
    StarlinkCommandError,
    StarlinkTimeoutError,
    _read_result,
    _run_command,
)
from starlink._results import _ResultBackendTimeoutError


def test_executable_not_found_is_structured_error():
    with tempfile.TemporaryDirectory() as temp:
        with pytest.raises(StarlinkCommandError) as caught:
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


def test_command_uses_an_argument_array_without_a_shell():
    process = mock.Mock()
    process.returncode = 0
    process.communicate.return_value = (b"output", b"")

    with mock.patch(
        "starlink._runtime.subprocess.Popen", return_value=process
    ) as popen:
        completed = _run_command(
            ["/opt/Star link/bin/tool", "input=a file.sdf"],
            env={"PATH": "/usr/bin:/bin"},
            cwd="/tmp",
            timeout=5,
            adam_dir="/tmp/adam",
        )

    assert completed.stdout == b"output"
    assert popen.call_args.args[0] == [
        "/opt/Star link/bin/tool",
        "input=a file.sdf",
    ]
    assert popen.call_args.kwargs["shell"] is False


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
        with pytest.raises(StarlinkTimeoutError) as caught:
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
        with pytest.raises(StarlinkTimeoutError) as caught:
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
