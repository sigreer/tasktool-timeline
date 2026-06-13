import datetime as dt

import pytest

from timeline import model
from timeline.tests.helpers import phase, slice_, x


def _items():
    return [
        model._item("P14", "phase", None,
                    phase("P14", status="done", started="2026-05-24",
                          closed="2026-05-24")),
        model._item("P21.S2", "slice", "P21",
                    slice_("S2", status="done", closed="2026-06-02")),
        model._item("X12", "x", None, x("X12", status="done", closed="2026-06-01")),
    ]


def test_override_date_wins_over_field():
    items = _items()
    model.apply_overrides(items, {"items": {"P14": {"started": "2026-05-20"}}})
    p14 = items[0]
    assert p14.started.when == dt.datetime(2026, 5, 20)
    assert p14.started.source == "override"


def test_override_display_title_and_exclude():
    items = _items()
    model.apply_overrides(items, {"items": {
        "P21.S2": {"display_title": "Quiet-launch controls"},
        "X12": {"exclude": True},
    }})
    assert items[1].label() == "Quiet-launch controls"
    assert items[2].excluded is True


def test_unknown_override_key_is_fatal():
    with pytest.raises(SystemExit):
        model.apply_overrides(_items(), {"items": {"P14": {"startd": "2026-05-20"}}})


def test_unknown_item_id_warns_not_fatal():
    warnings = model.apply_overrides(_items(), {"items": {"P99": {"exclude": True}}})
    assert len(warnings) == 1 and "P99" in warnings[0]


def test_no_overrides_is_noop():
    assert model.apply_overrides(_items(), {}) == []


def test_non_string_date_value_is_fatal():
    with pytest.raises(SystemExit):
        model.apply_overrides(_items(), {"items": {"P14": {"started": 20260520}}})


def test_null_date_value_is_fatal():
    with pytest.raises(SystemExit):
        model.apply_overrides(_items(), {"items": {"P14": {"started": None}}})


def test_unparseable_date_value_is_fatal():
    with pytest.raises(SystemExit):
        model.apply_overrides(_items(), {"items": {"P14": {"started": "not-a-date"}}})


def test_non_bool_exclude_is_fatal():
    with pytest.raises(SystemExit):
        model.apply_overrides(_items(), {"items": {"X12": {"exclude": "false"}}})


def test_exclude_false_is_noop():
    items = _items()
    model.apply_overrides(items, {"items": {"X12": {"exclude": False}}})
    assert items[2].excluded is False


def test_non_string_display_title_is_fatal():
    with pytest.raises(SystemExit):
        model.apply_overrides(_items(), {"items": {"P21.S2": {"display_title": 123}}})
