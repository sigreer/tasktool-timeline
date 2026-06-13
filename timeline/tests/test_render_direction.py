"""Direction toggle: default newest-at-top, in-page switch to oldest-first.

Every positioned element carries data-ta (first-to-last top) and data-td
(last-to-first top). The emitted inline style uses the data-td value — the
default reading order — and the toggle's inline script swaps tops.
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


def _tops(html, cls, attr):
    pat = re.compile(r'<div class="' + cls
                     + r'[^"]*" data-key="([^"]+)"[^>]*'
                     + attr + r'="(-?\d+)"')
    return {m.group(1): int(m.group(2)) for m in pat.finditer(html)}


def _two_phases():
    p1 = _phase("P1", status="done", started="2026-06-01", closed="2026-06-02")
    s1 = _slice("P1", "S1", status="done", closed="2026-06-01")
    p2 = _phase("P2", status="done", started="2026-06-04", closed="2026-06-05")
    s2 = _slice("P2", "S1", status="done", closed="2026-06-04")
    return [p1, s1, p2, s2]


def test_default_reading_order_is_newest_at_top():
    h = render.render_html("t", _two_phases(), generated=GEN).html
    td = _tops(h, "phase-ring", "data-td")
    ta = _tops(h, "phase-ring", "data-ta")
    assert td["P2"] < td["P1"]      # newer phase above in the default order
    assert ta["P1"] < ta["P2"]      # toggled order is oldest-first
    # The emitted inline top is the default (newest-first) value.
    m = re.search(r'<div class="phase-ring" data-key="P2" '
                  r'style="top:(\d+)px', h)
    assert m and int(m.group(1)) == td["P2"]


def test_phase_anchors_bracket_children_following_reading_order():
    # The start node and close ring bracket each phase's child cards, and
    # which anchor is on top follows the reading order. asc (oldest-first):
    # start node above the cards, close ring below. desc (newest-first): the
    # reading order inverts, so the close ring is above the cards and the
    # start node below (see test_start_node_and_close_ring_swap_ends_*).
    items = _two_phases()
    h = render.render_html("t", items, generated=GEN).html
    # asc: node above card above ring.
    na, ca, ra = (_tops(h, c, "data-ta") for c in
                  ("phase-node", "slice-card", "phase-ring"))
    for pk in ("P1", "P2"):
        kid = ca[f"{pk}.S1"]
        assert na[pk] < kid < ra[pk]
    # desc: ring above card above node (anchors swapped).
    nd, cd, rd = (_tops(h, c, "data-td") for c in
                  ("phase-node", "slice-card", "phase-ring"))
    for pk in ("P1", "P2"):
        kid = cd[f"{pk}.S1"]
        assert rd[pk] < kid < nd[pk]


def test_direction_toggle_markup_and_script():
    h = render.render_html("t", _two_phases(), generated=GEN).html
    assert 'id="dirNewest"' in h
    assert re.search(r'<input type="checkbox" id="dirNewest" checked', h)
    assert "function setDir" in h
    # Still self-contained: the script is inline, no external fetches.
    assert "http://" not in h and "https://" not in h and "src=" not in h


def test_range_elements_carry_both_heights():
    items = _two_phases()
    h = render.render_html("t", items, generated=GEN).html
    m = re.search(r'<div class="strand" data-key="P1"[^>]*data-ta="(-?\d+)" '
                  r'data-ha="(\d+)" data-td="(-?\d+)" data-hd="(\d+)"', h)
    assert m, "strand must carry per-direction top and height"
    # The strand spans the full node..ring extent in both directions. Which
    # anchor is the top end swaps with reading order, so compare against
    # min/max rather than assuming node==top, ring==bottom.
    for top_attr, h_attr in (("data-ta", "data-ha"), ("data-td", "data-hd")):
        nodes = _tops(h, "phase-node", top_attr)
        rings = _tops(h, "phase-ring", top_attr)
        sm = re.search(r'<div class="strand" data-key="P1"[^>]*'
                       + top_attr + r'="(-?\d+)"[^>]*'
                       + h_attr + r'="(\d+)"', h)
        top, height = int(sm.group(1)), int(sm.group(2))
        assert top == min(nodes["P1"], rings["P1"])
        assert top + height == max(nodes["P1"], rings["P1"])


def test_open_phase_anchor_follows_reading_order():
    # An open phase has a start node and an "in progress" (open) label at the
    # generation instant but no close ring. The start/end anchors still bracket
    # the children following reading order: asc (oldest-first) puts the start
    # node on top and the open label at the bottom; desc (newest-first) inverts
    # it so the open label reads at the top and the start node at the bottom.
    p = _phase("P9", status="ready", started="2026-06-05")
    s = _slice("P9", "S1", status="done", closed="2026-06-05")
    h = render.render_html("t", [p, s], generated=GEN).html
    na, ca, oa = (_tops(h, c, "data-ta") for c in
                  ("phase-node", "slice-card", "open-label"))
    assert na["P9"] < ca["P9.S1"] < oa["P9"]
    nd, cd, od = (_tops(h, c, "data-td") for c in
                  ("phase-node", "slice-card", "open-label"))
    assert od["P9"] < cd["P9.S1"] < nd["P9"]


def test_start_node_and_close_ring_swap_ends_with_direction():
    # The phase start (node, 🏎️) and close (ring, 🏁) anchor opposite ends of
    # the phase block, and which end is *top* must follow the reading order:
    #   asc  (oldest-first, top->bottom = old->new): start node above ring.
    #   desc (newest-first): reading order inverts, so the close ring is the
    #        topmost reading point and the start node the bottommost.
    # The force-ordering pass must invert with direction (X29 visual defect:
    # in newest-first the emojis appeared "the wrong way round" because the
    # start node stayed pinned to the top).
    items = _two_phases()
    h = render.render_html("t", items, generated=GEN).html
    nodes_a = _tops(h, "phase-node", "data-ta")
    rings_a = _tops(h, "phase-ring", "data-ta")
    nodes_d = _tops(h, "phase-node", "data-td")
    rings_d = _tops(h, "phase-ring", "data-td")
    for pk in ("P1", "P2"):
        assert nodes_a[pk] < rings_a[pk], f"asc: start node above close ring ({pk})"
        assert rings_d[pk] < nodes_d[pk], f"desc: close ring above start node ({pk})"
    # The strand still spans the full phase extent (min..max) in both
    # directions regardless of which anchor is on top.
    for top_attr, h_attr in (("data-ta", "data-ha"), ("data-td", "data-hd")):
        nodes = _tops(h, "phase-node", top_attr)
        rings = _tops(h, "phase-ring", top_attr)
        sm = re.search(r'<div class="strand" data-key="P1"[^>]*'
                       + top_attr + r'="(-?\d+)"[^>]*'
                       + h_attr + r'="(\d+)"', h)
        top, height = int(sm.group(1)), int(sm.group(2))
        assert top == min(nodes["P1"], rings["P1"])
        assert top + height == max(nodes["P1"], rings["P1"])


def test_date_pills_carry_both_direction_tops():
    items = [
        model._item("P1", "phase", None,
                    phase("P1", status="done", started="2026-06-01", closed="2026-06-02")),
        model._item("P1.S1", "slice", "P1", slice_("S1", status="done", closed="2026-06-01")),
    ]
    html = render.render_html("fixture", items, generated=GEN).html
    asc = _tops(html, "date-pill", "data-ta")
    desc = _tops(html, "date-pill", "data-td")
    assert asc and desc and set(asc) == set(desc)   # every pill has both tops
