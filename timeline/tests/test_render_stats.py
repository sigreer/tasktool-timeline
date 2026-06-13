"""Rendering of per-item effort stats onto cards and phase bands."""

import datetime as dt

from timeline import model, render
from timeline.stats import ItemStats
from timeline.tests.helpers import phase, slice_, x

GEN = dt.datetime(2026, 6, 6, 12, 0)


def _items():
    p = model._item("P20", "phase", None,
                    phase("P20", status="done", started="2026-05-29",
                          closed="2026-05-30", title="Marketing library"))
    s = model._item("P20.S1", "slice", "P20",
                    slice_("S1", status="done", closed="2026-05-29",
                           title="Component inventory"))
    xi = model._item("X1", "x", None,
                     x("X1", status="done", closed="2026-05-29", title="Cross item"))
    return [p, s, xi]


def test_no_stats_renders_identically():
    base = render.render_html("fixture", _items(), generated=GEN).html
    none = render.render_html("fixture", _items(), generated=GEN, stats=None).html
    empty = render.render_html("fixture", _items(), generated=GEN, stats={}).html
    assert base == none == empty
    assert 'class="mag"' not in base
    assert 'class="pb-stats"' not in base


def test_slice_card_shows_commit_and_line_badge():
    stats = {"P20.S1": ItemStats(commits=47, added=2910, removed=300, files=28)}
    h = render.render_html("fixture", _items(), generated=GEN, stats=stats).html
    assert 'class="mag"' in h
    assert "47 commits" in h            # always-visible badge
    assert "3.2k" in h                  # humanized total lines (2910+300=3210)
    # full breakdown present for the detail panel
    assert "stat-line" in h
    assert "2,910" in h and "300" in h and "28 files" in h


def test_phase_finish_band_shows_rollup():
    stats = {"P20": ItemStats(commits=120, added=18000, removed=4000, files=210)}
    h = render.render_html("fixture", _items(), generated=GEN, stats=stats).html
    assert 'class="pb-stats"' in h
    assert "120 commits" in h
    assert "22k lines" in h             # 18000 + 4000 = 22000 -> 22k


def test_cross_cutting_card_gets_stats_when_shown():
    stats = {"X1": ItemStats(commits=9, added=400, removed=50, files=12)}
    h = render.render_html("fixture", _items(), generated=GEN, stats=stats,
                           show_x=True).html
    assert "9 commits" in h


def test_stats_for_absent_item_are_silently_skipped():
    # stats may reference keys not in the visible set; render must not choke.
    stats = {"P99": ItemStats(commits=5, added=10, removed=2, files=1)}
    h = render.render_html("fixture", _items(), generated=GEN, stats=stats).html
    assert h.startswith("<!DOCTYPE html>")
    assert 'class="mag"' not in h
