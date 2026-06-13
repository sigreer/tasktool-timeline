import datetime as dt

from timeline import model, render
from timeline.tests.helpers import phase, slice_, x


def _phase(pid, **kw):
    return model._item(pid, "phase", None, phase(pid, **kw))


def _slice(pid, sid, **kw):
    return model._item(f"{pid}.{sid}", "slice", pid, slice_(sid, **kw))


def _x(xid, **kw):
    return model._item(xid, "x", None, x(xid, **kw))


def test_cancelled_phase_without_done_slice_omitted():
    items = [_phase("P5", status="cancelled", closed="2026-05-24"),
             _slice("P5", "S1", status="cancelled")]
    assert render.visible_items(items) == []


def test_cancelled_phase_with_done_slice_kept_cancelled_slices_dropped():
    items = [_phase("P16", status="cancelled", closed="2026-05-24"),
             _slice("P16", "S1", status="done", closed="2026-05-23"),
             _slice("P16", "S2", status="cancelled")]
    keys = [i.key for i in render.visible_items(items)]
    assert keys == ["P16", "P16.S1"]


def test_only_done_dated_slices_and_x_items_visible():
    items = [_phase("P1", status="ready", created="2026-06-01"),
             _slice("P1", "S1", status="in_progress"),
             _slice("P1", "S2", status="done", closed="2026-06-02"),
             _x("X1", status="done", closed="2026-06-03"),
             _x("X2", status="ready"),
             _x("X3", status="done")]  # done but dateless -> not placeable
    keys = [i.key for i in render.visible_items(items)]
    assert keys == ["P1", "P1.S2", "X1"]


def test_excluded_items_dropped():
    it = _x("X1", status="done", closed="2026-06-03")
    it.excluded = True
    assert render.visible_items([it]) == []


def test_excluded_phase_suppresses_its_slices():
    p = _phase("P3", status="done", closed="2026-06-05")
    p.excluded = True
    s = _slice("P3", "S1", status="done", closed="2026-06-04")
    keys = [i.key for i in render.visible_items([p, s])]
    assert keys == []  # both dropped


def test_phase_span_prefers_started_then_slice_then_created():
    p = _phase("P2", status="done", created="2026-06-01", closed="2026-06-05")
    s = _slice("P2", "S1", status="done", started="2026-06-02", closed="2026-06-04")
    start, end, close_only = render.phase_span(p, [p, s])
    assert start == dt.datetime(2026, 6, 2)   # earliest slice start
    assert end == dt.datetime(2026, 6, 5, 23, 59, 59)  # day-precision close -> end-of-day
    assert close_only is False


def test_close_only_phase():
    p = _phase("P1", status="done", closed="2026-04-29")
    start, end, close_only = render.phase_span(p, [p])
    assert (start is None
            and end == dt.datetime(2026, 4, 29, 23, 59, 59)  # day-precision close -> end-of-day
            and close_only is True)


def test_phase_span_falls_back_to_slice_closes():
    # multistore P11: phase has no started/created, slices have only closes.
    # The span must start at the earliest slice activity, not mid-phase.
    p = _phase("P11", status="done", closed="2026-05-19")
    s1 = _slice("P11", "S1", status="done", closed="2026-05-15")
    s2 = _slice("P11", "S5", status="done", started="2026-05-19T10:37",
                closed="2026-05-19T11:22")
    start, end, close_only = render.phase_span(p, [p, s1, s2])
    assert start == dt.datetime(2026, 5, 15)   # earliest slice close wins
    assert end == dt.datetime(2026, 5, 19, 23, 59, 59)  # day-precision close -> end-of-day
    assert close_only is False


def test_duration_positive_for_same_day_minute_start_day_close():
    started = model.DateValue(dt.datetime(2026, 5, 19, 23, 41, 0), "minute", "replay")
    closed = model.DateValue(dt.datetime(2026, 5, 19, 0, 0, 0), "day", "field")
    text = render._duration_text(started, closed)
    assert text.strip() != ""   # day/minute mixed -> "· 1 day", never empty
    assert "-" not in text       # never a negative/inverted duration


def test_duration_minute_pair_unchanged():
    started = model.DateValue(dt.datetime(2026, 5, 21, 17, 21, 0), "minute", "replay")
    closed = model.DateValue(dt.datetime(2026, 5, 21, 18, 15, 0), "minute", "replay")
    assert render._duration_text(started, closed) == " · 0h 54m"
