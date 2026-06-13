import datetime as dt

from timeline import extract, model
from timeline.tests.helpers import phase, slice_


def _ts(*args):
    return int(dt.datetime(*args).timestamp())


def _hist(*transitions):
    h = extract.KeyHistory()
    h.transitions = [extract.Transition(ts, old, new) for ts, old, new in transitions]
    return h


def test_replay_upgrades_same_day_field_to_minute():
    it = model._item("P1.S1", "slice", "P1",
                     slice_("S1", status="done", closed="2026-06-02"))
    h = _hist((_ts(2026, 6, 2, 9, 45), "in_progress", "done"))
    model.apply_replay(it, h)
    assert it.closed.when == dt.datetime(2026, 6, 2, 9, 45)
    assert it.closed.precision == "minute" and it.closed.source == "replay"


def test_replay_does_not_override_conflicting_field_date():
    # Field says 06-03, replay observed the transition on 06-02: field wins.
    it = model._item("P1.S1", "slice", "P1",
                     slice_("S1", status="done", closed="2026-06-03"))
    model.apply_replay(it, _hist((_ts(2026, 6, 2, 9, 45), "in_progress", "done")))
    assert it.closed.when == dt.datetime(2026, 6, 3)
    assert it.closed.precision == "day" and it.closed.source == "field"


def test_replay_fills_null_started():
    it = model._item("P1.S1", "slice", "P1", slice_("S1", status="done"))
    model.apply_replay(it, _hist((_ts(2026, 6, 1, 8, 0), "ready", "in_progress"),
                                 (_ts(2026, 6, 2, 9, 0), "in_progress", "done")))
    assert it.started.when == dt.datetime(2026, 6, 1, 8, 0)
    assert it.started.source == "replay"


def test_replay_never_invents_phase_closed():
    it = model._item("P1", "phase", None, phase("P1", status="ready"))
    model.apply_replay(it, _hist((_ts(2026, 6, 2, 9, 0), "ready", "done")))
    assert it.closed.when is None  # phase closed comes from the field or not at all


def test_replay_fills_slice_closed_when_field_null():
    it = model._item("P1.S1", "slice", "P1", slice_("S1", status="done"))
    model.apply_replay(it, _hist((_ts(2026, 6, 2, 9, 0), "in_progress", "done")))
    assert it.closed.when == dt.datetime.fromtimestamp(_ts(2026, 6, 2, 9, 0))
    assert it.closed.source == "replay"


def test_replay_closed_picks_last_terminal_transition_after_reopen():
    # cancelled -> reopened -> done: closed must be the final terminal
    # transition (the done), not the earlier cancellation.
    it = model._item("P1.S1", "slice", "P1", slice_("S1", status="done"))
    t3 = _ts(2026, 6, 4, 11, 30)
    model.apply_replay(it, _hist(
        (_ts(2026, 6, 1, 9, 0), "ready", "cancelled"),
        (_ts(2026, 6, 2, 10, 0), "cancelled", "in_progress"),
        (t3, "in_progress", "done")))
    assert it.closed.when == dt.datetime.fromtimestamp(t3)
    assert it.closed.source == "replay"
