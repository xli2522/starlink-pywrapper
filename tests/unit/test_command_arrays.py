from __future__ import annotations

from unittest import mock

from starlink import wrapper


def test_trusted_multi_token_command_is_passed_as_an_argument_array():
    completed = mock.Mock(returncode=0, stdout=b"", stderr=b"")
    with mock.patch.object(
        wrapper,
        "env",
        {
            "STARLINK_DIR": "/opt/star",
            "ADAM_USER": "/tmp/adam",
        },
    ), mock.patch.object(wrapper, "adamdir", "/tmp/adam"), mock.patch(
        "starlink.wrapper._run_command", return_value=completed
    ) as run, mock.patch(
        "starlink.wrapper._read_result", return_value="result"
    ):
        wrapper.starcomm(
            "${STARLINK_DIR}/bin/starperl ${STARLINK_DIR}/bin/tool.pl",
            "tool",
            in_="input.sdf",
        )

    assert run.call_args.args[0] == [
        "/opt/star/bin/starperl",
        "/opt/star/bin/tool.pl",
        "in=input.sdf",
    ]


def test_multi_token_command_preserves_special_installation_path():
    completed = mock.Mock(returncode=0, stdout=b"", stderr=b"")
    starlink_dir = "/opt/Star link/$literal"
    with mock.patch.object(
        wrapper,
        "env",
        {
            "STARLINK_DIR": starlink_dir,
            "ADAM_USER": "/tmp/adam",
            "literal": "must-not-expand",
        },
    ), mock.patch.object(wrapper, "adamdir", "/tmp/adam"), mock.patch(
        "starlink.wrapper._run_command", return_value=completed
    ) as run, mock.patch(
        "starlink.wrapper._read_result", return_value="result"
    ):
        wrapper.starcomm(
            "${STARLINK_DIR}/bin/starperl ${STARLINK_DIR}/bin/tool.pl",
            "tool",
        )

    assert run.call_args.args[0] == [
        starlink_dir + "/bin/starperl",
        starlink_dir + "/bin/tool.pl",
    ]
