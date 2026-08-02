from __future__ import annotations

from starlink.hdsutils import _hds_arrays_structures


class PrimitiveCell:
    struc = None
    shape = ()
    type = "_INTEGER"

    def __init__(self, name: str, value: int):
        self.name = name
        self._value = value

    def get(self):
        return self._value


class StructuredArray:
    shape = (2,)

    def cell(self, index):
        return PrimitiveCell("VALUE", index[0] + 1)


def test_legacy_hds_structured_array_uses_current_recursive_helper():
    result = _hds_arrays_structures(StructuredArray())

    assert result.shape == (2,)
    assert result.tolist() == [{"value": 1}, {"value": 2}]
