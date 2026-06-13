import datetime as dt

from timeline import model, render

D = lambda day, hour=0: dt.datetime(2026, 6, day, hour)


def test_sequential_phases_share_lane_zero():
    spans = [("P1", D(1), D(3)), ("P2", D(4), D(6))]
    lanes, n = render.assign_lanes(spans)
    assert lanes == {"P1": 0, "P2": 0} and n == 1


def test_two_overlapping_phases_get_two_lanes():
    spans = [("P1", D(1), D(5)), ("P2", D(3), D(8))]
    lanes, n = render.assign_lanes(spans)
    assert n == 2 and lanes["P1"] != lanes["P2"]


def test_three_way_overlap_gets_three_lanes():
    spans = [("P14", D(1), D(9)), ("P16", D(4), D(6)), ("P17", D(5), D(7))]
    lanes, n = render.assign_lanes(spans)
    assert n == 3 and len(set(lanes.values())) == 3


def test_lane_frees_after_phase_closes():
    spans = [("P1", D(1), D(3)), ("P2", D(2), D(8)), ("P3", D(4), D(6))]
    lanes, n = render.assign_lanes(spans)
    assert n == 2 and lanes["P3"] == lanes["P1"]


def test_day_precision_close_is_end_of_day_not_inverted():
    closed = model.DateValue(dt.datetime(2026, 5, 19, 0, 0, 0), "day", "field")
    assert render._eff_end(closed) == dt.datetime(2026, 5, 19, 23, 59, 59)
    started = dt.datetime(2026, 5, 19, 23, 41, 0)   # P4-shaped minute start
    assert render._eff_end(closed) > started        # interval no longer inverted


def test_two_same_day_phases_get_distinct_lanes():
    end = render._eff_end(model.DateValue(dt.datetime(2026, 5, 19, 0, 0), "day", "field"))
    spans = {
        "P3": (dt.datetime(2026, 5, 19, 0, 0), end, False),
        "P4": (dt.datetime(2026, 5, 19, 0, 0), end, False),
    }
    lane_of, count = render.assign_lanes([(k, s, e) for k, (s, e, _) in spans.items()])
    assert count == 2 and lane_of["P3"] != lane_of["P4"]
    assert "P3" in render._overlap_keys(spans) and "P4" in render._overlap_keys(spans)


from datetime import date


def test_classify_days_active_short_idle_and_quiet_run():
    active = {date(2026, 5, 19), date(2026, 5, 21), date(2026, 6, 5)}
    out = render.classify_days(active)
    # 19th active; 20th is a 1-day idle -> own day marker; 21st active;
    # 22 May..4 Jun is a 14-day idle run (>=3) -> single quiet; 5 Jun active.
    assert [e[0] for e in out] == ["day", "day", "day", "quiet", "day"]
    assert out[0] == ("day", date(2026, 5, 19), True)
    assert out[1] == ("day", date(2026, 5, 20), False)   # short idle pill
    assert out[2] == ("day", date(2026, 5, 21), True)
    assert out[3][0] == "quiet" and out[3][3] == 14       # 14 quiet days
    assert out[4] == ("day", date(2026, 6, 5), True)


def test_classify_days_two_day_idle_not_collapsed():
    active = {date(2026, 5, 19), date(2026, 5, 22)}       # 20,21 idle = 2 days < 3
    out = render.classify_days(active)
    assert [e[0] for e in out] == ["day", "day", "day", "day"]
    assert out[1][2] is False and out[2][2] is False      # both idle pills


def test_classify_days_three_day_idle_collapses():
    active = {date(2026, 5, 19), date(2026, 5, 23)}       # 20,21,22 idle = 3 days
    out = render.classify_days(active)
    assert [e[0] for e in out] == ["day", "quiet", "day"]
    assert out[1][3] == 3
