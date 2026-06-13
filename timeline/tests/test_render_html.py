import datetime as dt

from timeline import model, render
from timeline.tests.helpers import phase, slice_, x

GEN = dt.datetime(2026, 6, 6, 12, 0)


def _items():
    p20 = model._item("P20", "phase", None,
                      phase("P20", status="done", started="2026-05-29",
                            closed="2026-05-30", title="Marketing library"))
    s1 = model._item("P20.S1", "slice", "P20",
                     slice_("S1", status="done", closed="2026-05-29",
                            title="Component inventory"))
    p1 = model._item("P1", "phase", None,
                     phase("P1", status="done", closed="2026-04-29",
                           title="Legacy close-only"))
    x1 = model._item("X1", "x", None,
                     x("X1", status="done", closed="2026-05-29",
                       title="Cross item"))
    open_p = model._item("P23", "phase", None,
                         phase("P23", status="ready", started="2026-06-05",
                               title="Open phase"))
    return [p1, p20, s1, x1, open_p]


def test_render_produces_selfcontained_html():
    result = render.render_html("fixture", _items(), generated=GEN)
    h = result.html
    assert h.startswith("<!DOCTYPE html>")
    for needle in ("Marketing library", "Component inventory", "Cross item",
                   "phase-node", "slice-card", "x-node", "showX",
                   "Legacy close-only", "Open phase"):
        assert needle in h
    # Self-contained: no external fetches.
    assert "http://" not in h and "https://" not in h and "src=" not in h


def test_day_precision_shows_no_time_minute_shows_time():
    items = _items()
    items[2].closed = model.DateValue(dt.datetime(2026, 5, 29, 10, 14),
                                      "minute", "replay")
    h = render.render_html("fixture", items, generated=GEN).html
    assert "10:14" in h
    h2 = render.render_html("fixture", _items(), generated=GEN).html
    assert "00:00" not in h2  # day precision never fakes a midnight time


def test_show_x_flag_sets_initial_body_class():
    off = render.render_html("fixture", _items(), generated=GEN).html
    on = render.render_html("fixture", _items(), generated=GEN, show_x=True).html
    assert '<body class="">' in off
    assert '<body class="show-x">' in on


def test_unplaced_items_reported_not_rendered():
    dateless = model._item("P99", "phase", None, phase("P99", status="ready"))
    result = render.render_html("fixture", _items() + [dateless], generated=GEN)
    assert "P99" in result.unplaced
    assert "P99" not in result.html


def test_x_dot_hidden_with_card():
    h = render.render_html("fixture", _items(), generated=GEN).html
    assert 'class="dot x-node' in h  # the X dot toggles with the card


def test_detail_includes_duration():
    items = _items()
    items[2].started = model.DateValue(dt.datetime(2026, 5, 29, 8, 0),
                                       "minute", "replay")
    items[2].closed = model.DateValue(dt.datetime(2026, 5, 29, 10, 14),
                                      "minute", "replay")
    h = render.render_html("fixture", items, generated=GEN).html
    assert "2h 14m" in h


def test_header_shows_date_span():
    h = render.render_html("fixture", _items(), generated=GEN).html
    assert "29 Apr 2026" in h and "6 Jun 2026" in h


def test_html_escapes_titles():
    bad = model._item("X5", "x", None,
                      x("X5", status="done", closed="2026-05-29",
                        title="<script>alert(1)</script>"))
    h = render.render_html("fixture", _items() + [bad], generated=GEN).html
    assert "<script>alert(1)</script>" not in h
    assert "&lt;script&gt;" in h


def test_card_title_attribute_carries_full_title():
    h = render.render_html("fixture", _items(), generated=GEN).html
    assert 'title="Component inventory"' in h
    assert 'title="Cross item"' in h


def test_card_title_attribute_escapes_malicious_titles():
    bad = model._item("X6", "x", None,
                      x("X6", status="done", closed="2026-05-29",
                        title='"x" onmouseover="alert(1)"'))
    h = render.render_html("fixture", _items() + [bad], generated=GEN).html
    assert 'onmouseover="alert(1)"' not in h
    assert "&quot;x&quot; onmouseover=&quot;alert(1)&quot;" in h


def test_card_truncation_css_present():
    h = render.render_html("fixture", _items(), generated=GEN).html
    assert "white-space:nowrap" in h
    assert "overflow:hidden" in h
    assert "text-overflow:ellipsis" in h


def test_card_hover_and_open_untruncate():
    h = render.render_html("fixture", _items(), generated=GEN).html
    assert ".slice-card:hover,.slice-card.open{" in h
    assert "white-space:normal" in h


def test_unknown_start_omits_started_clause():
    # Phase with no started/created (multistore P11): the node still renders
    # (span derived from slice closes) but never shows a dangling "started —".
    p = model._item("P11", "phase", None,
                    phase("P11", status="done", closed="2026-05-19",
                          title="Toolkit convergence"))
    s = model._item("P11.S1", "slice", "P11",
                    slice_("S1", status="done", closed="2026-05-15"))
    h = render.render_html("fixture", [p, s], generated=GEN).html
    assert "Toolkit convergence" in h
    assert "started —" not in h


def test_cancelled_phase_without_done_slices_absent_from_html():
    p = model._item("P16", "phase", None,
                    phase("P16", status="cancelled", closed="2026-05-24",
                          title="Variant separation"))
    s = model._item("P16.S4", "slice", "P16",
                    slice_("S4", status="cancelled", closed="2026-05-24"))
    h = render.render_html("fixture", _items() + [p, s], generated=GEN).html
    assert "P16" not in h and "Variant separation" not in h


def test_cancelled_phase_with_done_slices_rendered_as_cancelled():
    # Spec: cancelled phases show when they have >=1 done slice, rendered
    # with the grey "cancelled" close treatment and only their done slices.
    p = model._item("P16", "phase", None,
                    phase("P16", status="cancelled", closed="2026-05-24",
                          title="Variant separation"))
    s_done = model._item("P16.S1", "slice", "P16",
                         slice_("S1", status="done", started="2026-05-23",
                                closed="2026-05-23", title="Done bit"))
    s_canc = model._item("P16.S4", "slice", "P16",
                         slice_("S4", status="cancelled", closed="2026-05-24",
                                title="Cancelled bit"))
    h = render.render_html("fixture", _items() + [p, s_done, s_canc],
                           generated=GEN).html
    assert "Variant separation" in h and "cancelled" in h
    assert "Done bit" in h
    assert "Cancelled bit" not in h


import re


def test_date_pills_and_dividers_render_with_quiet_run():
    items = [
        model._item("P1", "phase", None,
                    phase("P1", status="done", started="2026-05-19", closed="2026-06-05")),
        model._item("P1.S1", "slice", "P1",
                    slice_("S1", status="done", closed="2026-05-19", title="First slice")),
        model._item("P1.S2", "slice", "P1",
                    slice_("S2", status="done", closed="2026-06-05", title="Later slice")),
    ]
    html = render.render_html("fixture", items, generated=GEN).html
    assert 'class="date-pill' in html and 'class="day-divider' in html
    # active days 19 May and 5 Jun get pills; the 20 May..4 Jun run collapses
    assert re.search(r'class="date-pill[^>]*>19 May 2026<', html)
    assert re.search(r'class="date-pill[^>]*>5 Jun 2026<', html)
    assert "quiet day" in html


def test_x_only_day_gets_pill_even_when_hidden():
    items = [
        model._item("P1", "phase", None,
                    phase("P1", status="done", started="2026-05-19", closed="2026-05-19")),
        model._item("P1.S1", "slice", "P1",
                    slice_("S1", status="done", closed="2026-05-19")),
        model._item("X1", "x", None,
                    x("X1", status="done", closed="2026-05-25", title="Cross item")),
    ]
    html = render.render_html("fixture", items, generated=GEN, show_x=False).html
    # X-only day 25 May is active -> a date pill, even though X cards are CSS-hidden
    assert re.search(r'class="date-pill[^>]*>25 May 2026<', html)


def test_card_face_has_no_date_but_detail_does():
    items = [
        model._item("P1", "phase", None,
                    phase("P1", status="done", started="2026-05-19", closed="2026-05-19")),
        model._item("P1.S1", "slice", "P1",
                    slice_("S1", status="done", closed="2026-05-19", title="Foo slice")),
    ]
    html = render.render_html("fixture", items, generated=GEN).html
    card = re.search(r'<div class="slice-card[^>]*data-key="P1\.S1".*?</div>\s*</div>',
                     html, re.S).group(0)
    face, _, detail = card.partition('<div class="detail"')
    assert "19 May 2026" not in face        # date stripped from the visible face
    assert "19 May 2026" in detail          # still in the click-to-expand popout
    assert "closed" in detail               # datetime + duration retained


def test_phase_node_and_ring_faces_have_no_inline_date():
    items = [model._item("P1", "phase", None,
                         phase("P1", status="done", started="2026-05-19", closed="2026-05-20"))]
    html = render.render_html("fixture", items, generated=GEN).html
    start = re.search(r'<div class="phase-band start"[^>]*>(.*?)</div>',
                      html, re.S).group(1)
    assert "May" not in start               # start band carries no date
    finish = re.search(r'<div class="phase-band finish"[^>]*>(.*?)</div>',
                       html, re.S).group(1)
    assert "May" not in finish and "complete" in finish
