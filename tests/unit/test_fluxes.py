from __future__ import annotations

from collections import namedtuple
import datetime
from unittest import mock

import pytest

from starlink import fluxes


Result = namedtuple(
    "fluxes_result",
    "flu apass now ofl pos hpbw f_centre f_width f_total f_beam",
)


def returned_result():
    return Result("y", "n", "n", "n", "n", 1, 2, 3, 4, 5)


@pytest.mark.parametrize(
    ("value", "expected_date", "expected_time"),
    (
        (datetime.date(2025, 1, 2), '"02 01 25"', '"00 00 00"'),
        (datetime.datetime(2025, 1, 2, 3, 4, 5), '"02 01 25"', '"03 04 05"'),
        ("2025-01-02", '"02 01 25"', '"00 00 00"'),
        ("2025-01-02T03:04:05.250", '"02 01 25"', '"03 04 05"'),
    ),
)
def test_fluxes_accepts_documented_date_values(
    value, expected_date, expected_time
):
    with mock.patch(
        "starlink.fluxes.wrapper.starcomm", return_value=returned_result()
    ) as call:
        result = fluxes.get_flux("URANUS", value)

    assert result.f_total == 4
    assert call.call_args.kwargs["date"] == expected_date
    assert call.call_args.kwargs["time"] == expected_time


def test_fluxes_reports_invalid_string_clearly():
    with pytest.raises(ValueError, match="Could not parse"):
        fluxes.get_flux("URANUS", "not-a-date")


def test_fluxes_rejects_unsupported_date_type():
    with pytest.raises(TypeError, match="date must be"):
        fluxes.get_flux("URANUS", object())
