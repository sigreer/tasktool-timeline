import datetime as dt

from timeline import render


def test_proportional_between_guards():
    t0 = dt.datetime(2026, 6, 1, 12, 0)
    # 20h apart at 3 px/h = 60px: inside [34, 140] so exactly proportional.
    scale = render.TimeScale([t0, t0 + dt.timedelta(hours=20)])
    assert scale.y(t0) == 0
    assert scale.y(t0 + dt.timedelta(hours=20)) == 60


def test_min_gap_expands_bursts():
    t0 = dt.datetime(2026, 6, 5, 11, 0)
    # 5 minutes apart -> 0.25px proportional -> clamped to MIN_GAP_PX.
    scale = render.TimeScale([t0, t0 + dt.timedelta(minutes=5)])
    assert scale.y(t0 + dt.timedelta(minutes=5)) == render.MIN_GAP_PX


def test_max_gap_compresses_quiet_stretches():
    t0 = dt.datetime(2026, 5, 30)
    # 10 days -> 720px proportional -> clamped to MAX_GAP_PX.
    scale = render.TimeScale([t0, t0 + dt.timedelta(days=10)])
    assert scale.y(t0 + dt.timedelta(days=10)) == render.MAX_GAP_PX


def test_interpolates_between_anchors():
    t0 = dt.datetime(2026, 6, 1)
    t1 = t0 + dt.timedelta(hours=20)
    scale = render.TimeScale([t0, t1])
    assert scale.y(t0 + dt.timedelta(hours=10)) == 30  # halfway


def test_monotonic_and_height():
    t0 = dt.datetime(2026, 6, 1)
    ts = [t0, t0 + dt.timedelta(minutes=1), t0 + dt.timedelta(days=30)]
    scale = render.TimeScale(ts)
    ys = [scale.y(t) for t in ts]
    assert ys == sorted(ys)
    assert scale.height > ys[-1]
