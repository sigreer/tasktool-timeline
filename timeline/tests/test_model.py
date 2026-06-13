import datetime as dt

import pytest

from timeline import model
from timeline.tests.helpers import doc, phase, slice_, x


def test_parse_tracker_date_day():
    when, precision = model.parse_tracker_date("2026-05-20")
    assert when == dt.datetime(2026, 5, 20)
    assert precision == "day"


def test_parse_tracker_date_minute():
    when, precision = model.parse_tracker_date("2026-05-20T14:30:00")
    assert when == dt.datetime(2026, 5, 20, 14, 30)
    assert precision == "minute"


def test_parse_tracker_date_absent_and_epoch():
    assert model.parse_tracker_date(None) == (None, "day")
    assert model.parse_tracker_date("") == (None, "day")
    assert model.parse_tracker_date("1970-01-01") == (None, "day")


def test_items_from_project_walks_phases_slices_cross():
    d = doc(
        phases=[phase("P1", status="done", closed="2026-05-01",
                      slices=[slice_("S1", status="done", closed="2026-05-01")])],
        cross=[x("X1", status="done", closed="2026-05-02")],
    )
    items = {i.key: i for i in model.items_from_project(d)}
    assert set(items) == {"P1", "P1.S1", "X1"}
    assert items["P1"].kind == "phase" and items["P1"].parent is None
    assert items["P1.S1"].kind == "slice" and items["P1.S1"].parent == "P1"
    assert items["X1"].kind == "x"
    assert items["P1.S1"].closed.when == dt.datetime(2026, 5, 1)
    assert items["P1.S1"].closed.source == "field"


def test_item_from_cross():
    it = model.item_from_cross(x("X9", status="done", closed="2026-05-03"))
    assert (it.key, it.kind, it.status) == ("X9", "x", "done")


def test_collect_dedup_first_wins():
    live = doc(phases=[phase("P2", status="ready", created="2026-06-01")])
    arch = doc(phases=[phase("P2", status="done", closed="2026-05-30")])
    items = model.collect(live, [arch], [])
    p2 = [i for i in items if i.key == "P2"]
    assert len(p2) == 1 and p2[0].status == "ready"  # live wins


def test_label_prefers_display_title():
    it = model.item_from_cross(x("X9", title="raw jargon title"))
    assert it.label() == "raw jargon title"
    it.display_title = "Friendly name"
    assert it.label() == "Friendly name"
