"""Layout-pass tests: reading order, collision resolution, prominence.

Positions are asserted via the data-ta (top, first-to-last reading order)
attribute every positioned element carries, parsed out of the emitted HTML.
"""

import datetime as dt
import re

from timeline import model, render
from timeline.tests.helpers import phase, slice_

GEN = dt.datetime(2026, 6, 6, 12, 0)


def _phase(pid, **kw):
    return model._item(pid, "phase", None, phase(pid, **kw))


def _slice(pid, sid, **kw):
    return model._item(f"{pid}.{sid}", "slice", pid, slice_(sid, **kw))


def _tops(html, cls, attr="data-ta"):
    """-> {key: top} for positioned divs of a css class."""
    pat = re.compile(r'<div class="' + cls
                     + r'[^"]*" data-key="([^"]+)"[^>]*'
                     + attr + r'="(-?\d+)"')
    return {m.group(1): int(m.group(2)) for m in pat.finditer(html)}


def _sided_tops(html, attr="data-ta"):
    """-> [(side, key, top)] for slice cards."""
    pat = re.compile(r'<div class="slice-card (left|right)" '
                     r'data-key="([^"]+)"[^>]*' + attr + r'="(-?\d+)"')
    return [(m.group(1), m.group(2), int(m.group(3)))
            for m in pat.finditer(html)]


def test_phase_node_strictly_before_child_cards_and_ring_after():
    # started == first slice close: the common same-timestamp case the
    # human flagged ("often the case").
    p = _phase("P1", status="done", started="2026-06-01", closed="2026-06-01")
    s1 = _slice("P1", "S1", status="done", closed="2026-06-01")
    s2 = _slice("P1", "S2", status="done", closed="2026-06-01")
    h = render.render_html("t", [p, s1, s2], generated=GEN).html
    node = _tops(h, "phase-node")["P1"]
    cards = _tops(h, "slice-card")
    ring = _tops(h, "phase-ring")["P1"]
    assert node < min(cards.values())
    assert ring > max(cards.values())


def test_derived_start_node_precedes_cards():
    # multistore P11 shape: no started/created on the phase, slices carry
    # only closes. The node must still land before its first slice card.
    p = _phase("P11", status="done", closed="2026-06-03")
    ss = [_slice("P11", f"S{i}", status="done", closed=f"2026-06-0{i}")
          for i in (1, 2, 3)]
    h = render.render_html("t", [p] + ss, generated=GEN).html
    node = _tops(h, "phase-node")["P11"]
    cards = _tops(h, "slice-card")
    assert len(cards) == 3
    assert node < min(cards.values())


def test_minimum_vertical_separation_per_side():
    # Six slices closing the same minute must fan out, never stack.
    p = _phase("P1", status="done", started="2026-06-01T09:00",
               closed="2026-06-01T10:00")
    ss = [_slice("P1", f"S{i}", status="done", closed="2026-06-01T09:30")
          for i in range(1, 7)]
    h = render.render_html("t", [p] + ss, generated=GEN).html
    by_side = {"left": [], "right": []}
    for side, _key, top in _sided_tops(h):
        by_side[side].append(top)
    assert sum(len(v) for v in by_side.values()) == 6
    for tops in by_side.values():
        tops.sort()
        assert all(b - a >= 28 for a, b in zip(tops, tops[1:]))


def test_open_label_clear_of_cards():
    # A slice closing right at generation time competes with the open
    # phase's "in progress" label for the same y; they must not collide.
    p1 = _phase("P1", status="done", started="2026-06-05",
                closed="2026-06-06")
    s1 = _slice("P1", "S1", status="done", closed="2026-06-06T11:59")
    p2 = _phase("P2", status="ready", started="2026-06-05")
    h = render.render_html("t", [p1, s1, p2], generated=GEN).html
    label = _tops(h, "open-label")["P2"]
    for side, _key, top in _sided_tops(h):
        if side == "right":
            assert abs(label - top) >= 20


def test_phase_prominence_markup():
    p = _phase("P1", status="done", started="2026-06-01", closed="2026-06-02",
               title="Big unit of work")
    s = _slice("P1", "S1", status="done", closed="2026-06-01")
    h = render.render_html("t", [p, s], generated=GEN).html
    assert 'class="phase-band start"' in h    # full-width band at phase start
    assert 'class="phase-band finish"' in h   # full-width band at phase finish
    # Start and finish bands share the .pb-num/.pb-title font so prominence does
    # not swap with reading direction; start/end identity is carried by emoji
    # markers instead (see test_render_defects).
    assert re.search(r"\.pb-num\{[^}]*font-weight:700", h)
    assert re.search(r"\.pb-num\{[^}]*font-size:24px", h)
    assert re.search(r"\.pb-title\{[^}]*font-weight:700", h)
    assert re.search(r"\.pb-title\{[^}]*font-size:14px", h)
