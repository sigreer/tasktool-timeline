"""Render TimelineItem records to a single self-contained HTML page."""

from __future__ import annotations

import bisect
import datetime as dt
import html as _html
import re

PALETTE = ["#7c5cff", "#10ac84", "#ff9f43", "#4cc2ff",
           "#ee5253", "#f368e0", "#01a3a4", "#feca57"]
SLATE = "#8395a7"
PX_PER_HOUR = 3.0
MIN_GAP_PX = 34     # bursts expand to at least this much per adjacent pair
MAX_GAP_PX = 140    # quiet stretches compress to at most this much
QUIET_RUN_DAYS = 3      # a run of >= this many idle days collapses to one segment


def _done_slices(phase_key, items):
    return [i for i in items
            if i.kind == "slice" and i.parent == phase_key and i.status == "done"]


def visible_items(items):
    """Apply the spec's display rules; preserves input order."""
    out = []
    for it in items:
        if it.excluded:
            continue
        if it.kind == "phase":
            if it.status == "cancelled" and not _done_slices(it.key, items):
                continue
            out.append(it)
        elif it.kind == "slice":
            if it.status != "done" or it.closed.when is None:
                continue
            parent = next((p for p in items if p.key == it.parent), None)
            if parent and parent.excluded:
                continue
            out.append(it)
        else:  # x
            if it.status == "done" and it.closed.when is not None:
                out.append(it)
    return out


def phase_span(phase, items):
    """-> (start|None, end|None, close_only). end None means the phase is open.

    close_only is True when no resolvable start exists. When the phase has no
    `started`, the earliest slice activity (start OR close) is used: a slice
    closing proves the phase was active by then, and legacy phases often have
    slice closes but no slice starts (multistore P11)."""
    start = phase.started.when
    if start is None:
        slice_dates = [d for s in items
                       if s.kind == "slice" and s.parent == phase.key
                       for d in (s.started.when, s.closed.when)
                       if d is not None]
        start = min(slice_dates) if slice_dates else None
    if start is None:
        start = phase.created.when
    end = _eff_end(phase.closed)
    return start, end, start is None


class TimeScale:
    """Piecewise-linear time->y mapping: proportional between anchor events,
    clamped per adjacent pair to [MIN_GAP_PX, MAX_GAP_PX]."""

    def __init__(self, timestamps, px_per_hour=PX_PER_HOUR,
                 min_gap=MIN_GAP_PX, max_gap=MAX_GAP_PX):
        self._anchors = sorted(set(timestamps))
        self._ys = []
        y = 0.0
        for i, t in enumerate(self._anchors):
            if i:
                hours = (t - self._anchors[i - 1]).total_seconds() / 3600.0
                y += min(max(hours * px_per_hour, min_gap), max_gap)
            self._ys.append(y)

    def y(self, when):
        i = bisect.bisect_left(self._anchors, when)
        if i < len(self._anchors) and self._anchors[i] == when:
            return self._ys[i]
        if i == 0:
            return self._ys[0] if self._ys else 0.0
        if i == len(self._anchors):
            return self._ys[-1]
        a0, a1 = self._anchors[i - 1], self._anchors[i]
        frac = (when - a0).total_seconds() / (a1 - a0).total_seconds()
        return self._ys[i - 1] + frac * (self._ys[i] - self._ys[i - 1])

    @property
    def height(self):
        return (self._ys[-1] if self._ys else 0.0) + 80.0


def assign_lanes(spans):
    """Greedy interval lane assignment for phase strands.

    spans: iterable of (key, start, end) with start/end datetimes (end may be
    None for an open phase — treat as datetime.max for packing).
    -> ({key: lane}, lane_count)
    """
    assignment, lane_ends = {}, []
    inf = dt.datetime.max
    ordered = sorted(spans, key=lambda s: (s[1], s[2] or inf))
    for key, start, end in ordered:
        end = end or inf
        for lane, lane_end in enumerate(lane_ends):
            if start >= lane_end:
                lane_ends[lane] = end
                assignment[key] = lane
                break
        else:
            lane_ends.append(end)
            assignment[key] = len(lane_ends) - 1
    return assignment, len(lane_ends)


def classify_days(active_dates):
    """Walk the inclusive calendar range over the active-day set and classify
    each day. Returns an ordered list of:
      ("day", date, is_active)                  -- a date marker (pill + divider)
      ("quiet", run_start, run_end, n_days)     -- a collapsed run of >= QUIET_RUN_DAYS idle days
    Idle runs only occur strictly between active days (the range is framed by the
    first and last active day), so there is never a leading/trailing idle run.
    """
    if not active_dates:
        return []
    days = sorted(active_dates)
    lo, hi, active = days[0], days[-1], set(days)
    out, run = [], []
    one = dt.timedelta(days=1)
    d = lo
    while d <= hi:
        if d in active:
            if run:
                if len(run) >= QUIET_RUN_DAYS:
                    out.append(("quiet", run[0], run[-1], len(run)))
                else:
                    out.extend(("day", r, False) for r in run)
                run = []
            out.append(("day", d, True))
        else:
            run.append(d)
        d += one
    return out


from dataclasses import dataclass as _dataclass


@_dataclass
class RenderResult:
    html: str
    unplaced: list


PAD_TOP = 40        # px of breathing room above the first element
PAD_BOTTOM = 60
TRACK_PAD = 12      # extra px between adjacent occupants of the same track
# Half-height a phase band reserves on every track. The band is full-width, so a
# node/ring must keep cards on BOTH sides clear of it; this is half the CSS
# .phase-band height (54px) so neighbouring elements never slide under the band.
PHASE_BAND_HALF = 27
# Centre-track half-height a date pill reserves. Larger than the pill's real
# half (~8px) so the collision sweep pushes a pill that lands on a phase band
# clear of it by >= 1.5x the pill height; still below the natural per-day gap so
# interior date pills keep their uniform rhythm. See test_short_idle_runs_*.
DATE_PILL_HALF = 22
_RANK = {"date": -1, "node": 0, "card": 1, "open": 1, "ring": 2}  # tie-break at equal y
_SEQ_RE = re.compile(r"^P(\d+)(?:\.S(\d+)([a-z]*))?$")


def _seq_key(key):
    """Stable secondary order for elements resolving to the same instant: group
    by parent phase number, then slice sequence (numeric, suffix-aware). Without
    this, equal-instant cards fall back to lexicographic key order, which sorts
    'P10' before 'P2' and 'S10' before 'S2'. Phase-level anchors sort before
    their own slices; cross-cutting (X) items sort after all phases by number."""
    m = _SEQ_RE.match(key)
    if m:
        seq = int(m.group(2)) if m.group(2) else -1
        return (0, int(m.group(1)), seq, m.group(3) or "")
    mx = re.match(r"^X(\d+)", key)
    if mx:
        return (1, int(mx.group(1)), 0, "")
    return (2, 0, 0, key)


class _El:
    """One positioned point element (node, ring, card, open-label).

    Strands, bands and gap segments are ranges derived from these after
    layout. `tracks` lists the vertical columns the element occupies as
    (track, half-height) pairs: "L"/"R" are the card/label columns either
    side of the spine, "C" is the spine itself.
    """
    __slots__ = ("key", "kind", "when", "tracks", "phase", "item", "side", "ys")

    def __init__(self, key, kind, when, tracks, phase=None, item=None, side=""):
        self.key, self.kind, self.when = key, kind, when
        self.tracks = tracks
        self.phase = phase      # owning phase key (ordering constraints)
        self.item = item
        self.side = side
        self.ys = {}            # direction -> resolved y centre

    def half(self):
        return max(h for _, h in self.tracks)


def layout(els, scale, direction="asc"):
    """Assign collision-free y centres for one reading direction.

    Sequential order beats strict time-proportionality: per phase, the two
    anchors (start node, close ring) are forced to opposite ends of the phase
    block, and which one sits on top follows the reading order. In ``asc``
    (oldest-first, top->bottom = old->new) the start node is forced strictly
    above every other element of the phase and the close ring strictly below.
    In ``desc`` (newest-first) the reading order inverts, so the close ring is
    forced to the top and the start node to the bottom. A monotone sweep then
    nudges elements down until every track keeps a minimum vertical
    separation. Returns the content bottom (max y + half).
    """
    maxy = max((scale.y(e.when) for e in els), default=0.0)
    for e in els:
        ty = scale.y(e.when)
        e.ys[direction] = (maxy - ty) if direction == "desc" else ty

    groups = {}
    for e in els:
        if e.phase:
            groups.setdefault(e.phase, []).append(e)
    for group in groups.values():
        node = next((e for e in group if e.kind == "node"), None)
        ring = next((e for e in group if e.kind == "ring"), None)
        rest = [e for e in group if e.kind not in ("node", "ring")]
        # asc reads top->bottom oldest->newest: start node on top, close ring
        # below. desc (newest-first) inverts the reading order: close ring on
        # top, start node below. Force the top anchor strictly above the
        # phase's other elements and the bottom anchor strictly below.
        top_el, bottom_el = (node, ring) if direction == "asc" else (ring, node)
        if top_el:
            others = [e.ys[direction] for e in rest] \
                + ([bottom_el.ys[direction]] if bottom_el else [])
            if others and top_el.ys[direction] >= min(others):
                top_el.ys[direction] = min(others) - 1
        if bottom_el:
            others = [e.ys[direction] for e in rest] \
                + ([top_el.ys[direction]] if top_el else [])
            if others and bottom_el.ys[direction] <= max(others):
                bottom_el.ys[direction] = max(others) + 1

    bottom = {}
    for e in sorted(els, key=lambda e: (e.ys[direction], _RANK[e.kind], _seq_key(e.key))):
        y = e.ys[direction]
        for t, h in e.tracks:
            if t in bottom:
                y = max(y, bottom[t] + TRACK_PAD + h)
        e.ys[direction] = y
        for t, h in e.tracks:
            bottom[t] = y + h
    return max((e.ys[direction] + e.half() for e in els), default=0.0)


def _color(phase_key):
    try:
        return PALETTE[int(phase_key.lstrip("PX")) % len(PALETTE)]
    except ValueError:
        return SLATE


def _fmt(dv):
    if dv.when is None:
        return "—"
    if dv.precision == "minute":
        return dv.when.strftime("%-d %b %Y, %H:%M")
    return dv.when.strftime("%-d %b %Y")


def _eff_end(dv):
    """Interval-effective instant for a date value used as an END/close boundary.

    Day-precision dates resolve to 00:00, which is correct for a start but pins a
    close to the *start* of its day — before same-day minute activity, inverting
    legacy intervals. As an end boundary a day-precision value resolves to
    end-of-day (23:59:59) instead. Minute precision and None pass through. This is
    an internal sort/interval/duration value only; never surface it in a label.
    """
    if dv is None or dv.when is None:
        return None
    if dv.precision == "day":
        return dv.when.replace(hour=23, minute=59, second=59)
    return dv.when


def render_html(project, items, *, generated, show_x=False):
    vis = visible_items(items)
    phases = [i for i in vis if i.kind == "phase"]
    slices = [i for i in vis if i.kind == "slice"]
    xs = [i for i in vis if i.kind == "x"]

    spans, unplaced = {}, []
    for p in phases:
        start, end, close_only = phase_span(p, items)
        if start is None and end is None:
            unplaced.append(p.key)
            continue
        spans[p.key] = (start or end, end, close_only)
    placeable_phases = [p for p in phases if p.key in spans]

    anchors = []
    for start, end, _ in spans.values():
        anchors.append(start)
        anchors.append(end or generated)
    anchors += [_eff_end(s.closed) for s in slices if s.parent in spans]
    anchors += [_eff_end(i.closed) for i in xs]
    if not anchors:
        anchors = [generated]
    scale = TimeScale(anchors)
    span_text = (f"{min(anchors).strftime('%-d %b %Y')} – {max(anchors).strftime('%-d %b %Y')}"
                 if len(anchors) > 1 else "")

    lane_of, lane_count = assign_lanes(
        [(k, s, e) for k, (s, e, _) in spans.items()])
    overlapping = _overlap_keys(spans)
    strand_off = lambda lane: (lane - (lane_count - 1) / 2) * 12

    # --- Build point elements, then resolve positions with the layout pass.
    els = []
    for p in placeable_phases:
        start, end, close_only = spans[p.key]
        # Reserve the band's full half-height on every track (it is full-width),
        # so neither cards (L/R) nor date pills (C) slide under the band; the
        # date pill's own enlarged C reservation then keeps it clear by >= 1.5x
        # its height.
        band_tracks = (("C", PHASE_BAND_HALF), ("L", PHASE_BAND_HALF),
                       ("R", PHASE_BAND_HALF))
        if not close_only:
            els.append(_El(p.key, "node", start,
                           band_tracks, phase=p.key, item=p))
        if end is not None:
            els.append(_El(p.key, "ring", end,
                           band_tracks, phase=p.key, item=p))
        else:
            els.append(_El(p.key, "open", generated,
                           (("R", 9),), phase=p.key, item=p))

    counters = {}
    for s in sorted(slices, key=lambda i: _eff_end(i.closed)):
        if s.parent not in spans:
            unplaced.append(s.key)
            continue
        n = counters[s.parent] = counters.get(s.parent, -1) + 1
        if s.parent in overlapping:
            side = "left" if lane_of[s.parent] % 2 == 0 else "right"
        else:
            side = "left" if n % 2 == 0 else "right"
        els.append(_El(s.key, "card", _eff_end(s.closed),
                       (("L" if side == "left" else "R", 14),),
                       phase=s.parent, item=s, side=side))

    # X-items reserve layout space even while hidden, so toggling them on
    # never overlaps existing content.
    for n, i in enumerate(sorted(xs, key=lambda i: _eff_end(i.closed))):
        side = "left" if n % 2 == 0 else "right"
        els.append(_El(i.key, "card", _eff_end(i.closed),
                       (("L" if side == "left" else "R", 14),),
                       item=i, side=side))

    # Active days = every embedded point event's local date, including ALL X
    # closes regardless of --show-x (X data is always embedded; visibility is a
    # client-side CSS toggle). F1 invariant: an X-only day is active, so it always
    # gets a pill and is never folded into a quiet run.
    active_dates = set()
    for start, end, close_only in spans.values():
        if not close_only:
            active_dates.add(start.date())
        if end is not None:
            active_dates.add(end.date())
    for s in slices:
        if s.parent in spans:
            active_dates.add(_eff_end(s.closed).date())
    for i in xs:
        active_dates.add(_eff_end(i.closed).date())

    day_entries = classify_days(active_dates)

    # Every rendered day-marker anchors at the SAME time-of-day (noon) so that
    # consecutive rendered days are a uniform 24h apart on the scale and clamp to
    # an identical per-day gap, regardless of how many short idle days separate
    # active days. (Anchoring active days at their first real event instead would
    # make per-day gaps wobble with each day's fractional-day activity offset.)
    date_marker = {}   # date -> _El (rendering + per-day scale anchor)
    for entry in day_entries:
        if entry[0] != "day":
            continue
        d = entry[1]
        anchor = dt.datetime.combine(d, dt.time(12, 0))
        m = _El(f"date-{d.isoformat()}", "date", anchor, (("C", DATE_PILL_HALF),))
        date_marker[d] = m
        els.append(m)

    # Every rendered day-marker (active days AND short idle days, but NOT days
    # folded inside a collapsed quiet run) becomes a scale anchor, so each
    # consecutive rendered day gets at least MIN_GAP_PX of separation. Without
    # this, idle-day noon instants interpolate between two close real anchors
    # and collapse to ~zero vertical gap. Quiet-run days are intentionally
    # absent from date_marker, so their interior days never become anchors and
    # the run still compresses to its single segment.
    anchors += [m.when for m in date_marker.values()]
    scale = TimeScale(anchors)

    # Both reading orders are laid out up front; the in-page toggle swaps
    # positions via the data attributes. Default = newest at top ("desc").
    bottom_a = layout(els, scale, "asc")
    bottom_d = layout(els, scale, "desc")
    height_a = int(bottom_a + PAD_TOP + PAD_BOTTOM)
    height_d = int(bottom_d + PAD_TOP + PAD_BOTTOM)
    tops = lambda e: (f"{e.ys['asc'] + PAD_TOP:.0f}",
                      f"{e.ys['desc'] + PAD_TOP:.0f}")

    parts = []
    # A single full-height dotted base spine down the centre, painted BELOW the
    # colored strands (which overpaint it solid wherever a phase is active). This
    # guarantees a line is ALWAYS present between nodes — idle stretches show the
    # dotted base. It spans the full content extent in each direction so it is
    # never absent. Known limitation: with multiple parallel lanes the strands
    # shift off-centre, leaving the centred dotted base visible alongside them;
    # per the spec, visibility-while-overlapped does not matter — only absence.
    if els:
        spine_top_a = min(e.ys["asc"] - e.half() for e in els) + PAD_TOP
        spine_bot_a = max(e.ys["asc"] + e.half() for e in els) + PAD_TOP
        spine_top_d = min(e.ys["desc"] - e.half() for e in els) + PAD_TOP
        spine_bot_d = max(e.ys["desc"] + e.half() for e in els) + PAD_TOP
        parts.append(
            f'<div class="base-spine" data-key="base-spine" '
            f'style="top:{spine_top_d:.0f}px;height:{spine_bot_d - spine_top_d:.0f}px" '
            f'data-ta="{spine_top_a:.0f}" data-ha="{spine_bot_a - spine_top_a:.0f}" '
            f'data-td="{spine_top_d:.0f}" data-hd="{spine_bot_d - spine_top_d:.0f}"></div>')

    # Strands + bands next: they paint behind nodes and cards, over the spine.
    by_phase = {}
    for e in els:
        if e.phase:
            by_phase.setdefault(e.phase, []).append(e)
    for p in placeable_phases:
        start, end, close_only = spans[p.key]
        if close_only:
            continue
        color = _color(p.key)
        off = strand_off(lane_of[p.key])
        ysa = [e.ys["asc"] for e in by_phase[p.key]]
        ysd = [e.ys["desc"] for e in by_phase[p.key]]
        ya, ha = min(ysa) + PAD_TOP, max(ysa) - min(ysa)
        yd, hd = min(ysd) + PAD_TOP, max(ysd) - min(ysd)
        parts.append(
            f'<div class="strand" data-key="{_html.escape(p.key)}" '
            f'style="top:{yd:.0f}px;height:{hd:.0f}px;'
            f'margin-left:{off:.0f}px;background:{color}" '
            f'data-ta="{ya:.0f}" data-ha="{ha:.0f}" '
            f'data-td="{yd:.0f}" data-hd="{hd:.0f}"></div>')

    # Date pills + divider hairlines (one per "day" entry).
    for entry in day_entries:
        if entry[0] != "day":
            continue
        d = entry[1]
        m = date_marker[d]
        ta, td = tops(m)
        label = d.strftime("%-d %b %Y")
        parts.append(
            f'<div class="day-divider" data-key="div-{d.isoformat()}" '
            f'style="top:{td}px" data-ta="{ta}" data-td="{td}"></div>'
            f'<div class="date-pill" data-key="pill-{d.isoformat()}" '
            f'style="top:{td}px" data-ta="{ta}" data-td="{td}">{label}</div>')

    # Quiet runs: dotted segment spanning the idle stretch, positioned by mapping
    # the run INTERVAL through the same TimeScale used for everything else (same
    # mechanism that anchors idle-day pills via noon). Endpoints: run_start at
    # 00:00 and the day after run_end at 00:00 (end-of-run exclusive) so the
    # segment covers the full idle stretch. A scale-mapped interval has
    # non-negative height by construction, so 3+ day runs always render.
    maxy = max((scale.y(e.when) for e in els), default=0.0)
    for entry in day_entries:
        if entry[0] != "quiet":
            continue
        run_start, run_end, ndays = entry[1], entry[2], entry[3]
        t0 = dt.datetime.combine(run_start, dt.time(0, 0))
        t1 = dt.datetime.combine(run_end + dt.timedelta(days=1), dt.time(0, 0))
        y0, y1 = scale.y(t0), scale.y(t1)
        # asc: y grows with time, so the earlier endpoint is the top.
        ga0, ga1 = min(y0, y1) + PAD_TOP, max(y0, y1) + PAD_TOP
        # desc: same transform layout() applies (maxy - y), which flips order.
        d0, d1 = maxy - y0, maxy - y1
        gd0, gd1 = min(d0, d1) + PAD_TOP, max(d0, d1) + PAD_TOP
        parts.append(
            f'<div class="gap" data-key="quiet-{run_start.isoformat()}" '
            f'style="top:{gd0:.0f}px;height:{gd1 - gd0:.0f}px" '
            f'data-ta="{ga0:.0f}" data-ha="{ga1 - ga0:.0f}" '
            f'data-td="{gd0:.0f}" data-hd="{gd1 - gd0:.0f}"></div>'
            f'<div class="gap-label" data-key="quiet-{run_start.isoformat()}" '
            f'style="top:{(gd0 + gd1) / 2:.0f}px" '
            f'data-ta="{(ga0 + ga1) / 2:.0f}" data-td="{(gd0 + gd1) / 2:.0f}">'
            f'{ndays} quiet day{"s" if ndays != 1 else ""}</div>')

    # Point elements (date markers are rendered above, not here).
    for e in els:
        if e.kind == "date":
            continue
        ta, td = tops(e)
        if e.kind == "node":
            parts.append(_node_html(e.item, ta, td,
                                    strand_off(lane_of[e.key]),
                                    _color(e.key)))
        elif e.kind == "ring":
            parts.append(_ring_html(e.item, ta, td,
                                    strand_off(lane_of[e.key])))
        elif e.kind == "open":
            parts.append(
                f'<div class="open-label" data-key="{_html.escape(e.key)}" '
                f'style="top:{td}px;color:{_color(e.key)}" '
                f'data-ta="{ta}" data-td="{td}">'
                f'\U0001F3CE️ {_html.escape(e.key)} in progress…</div>')
        else:  # card
            if e.phase:
                color, off = _color(e.phase), strand_off(lane_of[e.phase])
                css = "slice-card"
            else:
                color, off, css = SLATE, 0, "slice-card x-node"
            parts.append(_card(e.item, ta, td, e.side, color, off, css=css))

    legend = "".join(
        f'<span class="chip"><i style="background:{_color(p.key)}"></i>'
        f'{_html.escape(p.key)}</span>' for p in placeable_phases)
    done_slices = len(slices)
    body_class = "show-x" if show_x else ""
    html_out = _SHELL.format(
        project=_html.escape(project), legend=legend, span=span_text,
        n_phases=sum(1 for p in placeable_phases if p.status == "done"),
        n_slices=done_slices,
        height=height_d, height_asc=height_a, height_desc=height_d,
        generated=generated.strftime("%-d %b %Y %H:%M"),
        body_class=body_class, checked="checked" if show_x else "",
        content="\n".join(parts))
    return RenderResult(html_out, unplaced)


def _overlap_keys(spans):
    keys = list(spans)
    out = set()
    inf = dt.datetime.max
    for i, a in enumerate(keys):
        s0, e0, _ = spans[a]
        for b in keys[i + 1:]:
            s1, e1, _ = spans[b]
            if s0 < (e1 or inf) and s1 < (e0 or inf):
                out.update((a, b))
    return out


def _band(p, td, pos, color, cls, icon, status=""):
    """Full-width phase band: icon + phase number on the left, title + icon on
    the right. Used for both phase start (node) and phase finish (ring) so each
    consumes the full row width symmetrically."""
    key = _html.escape(p.key)
    num = f'{icon} <b>{key}</b>' + (f' {status}' if status else "")
    return (f'<div class="phase-band {cls}" data-key="{key}" '
            f'style="top:{td}px;color:#fff;background:{color}" {pos}>'
            f'<span class="pb-num">{num}</span>'
            f'<span class="pb-title">{_html.escape(p.label())} {icon}</span></div>')


def _node_html(p, ta, td, off, color):
    key = _html.escape(p.key)
    pos = f'data-ta="{ta}" data-td="{td}"'
    return (_band(p, td, pos, color, "start", "\U0001F3CE️") +
            f'<div class="phase-node" data-key="{key}" '
            f'style="top:{td}px;margin-left:{off:.0f}px;background:{color}" '
            f'{pos}></div>')


def _ring_html(p, ta, td, off):
    ring = "#9aa0a6" if p.status == "cancelled" else _color(p.key)
    status = "cancelled" if p.status == "cancelled" else "complete"
    key = _html.escape(p.key)
    pos = f'data-ta="{ta}" data-td="{td}"'
    return (_band(p, td, pos, ring, "finish", "\U0001F3C1", status) +
            f'<div class="phase-ring" data-key="{key}" '
            f'style="top:{td}px;margin-left:{off:.0f}px;border-color:{ring}" '
            f'{pos}></div>')


def _duration_text(started, closed):
    start_eff = started.when            # starts stay at 00:00 for day precision
    close_eff = _eff_end(closed)        # ends resolve to end-of-day
    if start_eff is None or close_eff is None:
        return ""
    delta = close_eff - start_eff
    total = int(delta.total_seconds())
    if total <= 0:
        return ""
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if started.precision == "day" or closed.precision == "day":
        d = max(days, 1)
        return f" · {d} day{'s' if d != 1 else ''}"
    if days:
        return f" · {days}d {hours}h"
    return f" · {hours}h {minutes:02d}m"


def _card(item, ta, td, side, color, off, css):
    started_clause = (f'started {_fmt(item.started)} · '
                      if item.started.when else "")
    detail = (f'<div class="detail">{_html.escape(item.key)} · '
              f'{_html.escape(item.title)}<br>'
              f'{started_clause}closed {_fmt(item.closed)}'
              f'{_duration_text(item.started, item.closed)}</div>')
    dot_css = "dot x-node" if "x-node" in css else "dot"
    conn_css = "connector x-node" if "x-node" in css else "connector"
    key = _html.escape(item.key)
    pos = f'data-ta="{ta}" data-td="{td}"'
    return (f'<div class="{conn_css} {side}" data-key="{key}" '
            f'style="top:{td}px;background:{color}" {pos}></div>'
            f'<div class="{css} {side}" data-key="{key}" '
            f'title="{_html.escape(item.label())}" '
            f'onclick="this.classList.toggle(\'open\')" '
            f'style="top:{td}px;border-color:{color};background:{color}" '
            f'{pos}>'
            f'<b>{key}</b> {_html.escape(item.label())}{detail}</div>'
            f'<div class="{dot_css} {side}-dot" data-key="{key}" '
            f'style="top:{td}px;margin-left:{off:.0f}px;background:{color}" '
            f'{pos}></div>')


_SHELL = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{project} — timeline</title>
<style>
body{{font-family:system-ui,sans-serif;background:#fafafa;color:#333;margin:0}}
header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #e5e5e5;
  padding:14px 28px;z-index:10}}
header h1{{font-size:18px;margin:0 0 4px}}
header .meta{{font-size:12px;color:#888}}
.chip{{font-size:11px;margin-right:10px;color:#555}}
.chip i{{display:inline-block;width:9px;height:9px;border-radius:50%;
  margin-right:4px}}
#wrap{{position:relative;max-width:980px;margin:30px auto;height:{height}px}}
.base-spine{{position:absolute;left:50%;border-left:2px dotted #c4c4cc;
  transform:translateX(-50%);z-index:0}}
.strand{{position:absolute;left:50%;width:4px;border-radius:2px;
  transform:translateX(-50%);z-index:1}}
.phase-band{{position:absolute;left:0;right:0;height:54px;display:flex;
  align-items:center;justify-content:space-between;padding:0 22px;
  box-sizing:border-box;transform:translateY(-50%);border-radius:8px;z-index:0}}
.pb-num{{font-size:24px;font-weight:700;white-space:nowrap;z-index:1}}
.pb-title{{font-size:14px;font-weight:700;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;max-width:44%;text-align:right;z-index:1}}
.phase-node{{position:absolute;left:50%;width:20px;height:20px;
  border-radius:50%;border:3px solid #fff;transform:translate(-50%,-50%);
  box-shadow:0 0 0 2px currentColor;z-index:3}}
.phase-ring{{position:absolute;left:50%;width:14px;height:14px;
  border-radius:50%;background:#fff;border:3px solid;
  transform:translate(-50%,-50%);z-index:3}}
.open-label{{position:absolute;left:50%;margin-left:26px;font-size:11px;
  font-style:italic;transform:translateY(-50%)}}
.dim{{color:#999;font-weight:400;font-size:11px}}
.gap{{position:absolute;left:50%;border-left:3px dotted #aaa;
  transform:translateX(-50%)}}
.gap-label{{position:absolute;left:50%;margin-left:14px;font-size:10px;
  color:#999;font-style:italic;transform:translateY(-50%)}}
.day-divider{{position:absolute;left:0;right:0;height:1px;background:#ececef;
  transform:translateY(-50%);z-index:0}}
.date-pill{{position:absolute;left:50%;transform:translate(-50%,-50%);
  background:#fff;border:1px solid #d9d2f5;color:#6d28d9;font-size:10px;
  font-weight:700;padding:2px 8px;border-radius:11px;white-space:nowrap;z-index:4}}
.slice-card{{position:absolute;max-width:38%;font-size:12px;cursor:pointer;
  border:1px solid;border-radius:6px;padding:6px 10px;color:#fff;
  transform:translateY(-50%);z-index:2;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.slice-card:hover,.slice-card.open{{white-space:normal;overflow:visible;
  text-overflow:clip;z-index:6;background:#fff!important;color:#333}}
.slice-card.left{{right:50%;margin-right:48px;text-align:right}}
.slice-card.right{{left:50%;margin-left:48px}}
.connector{{position:absolute;height:2px;width:48px;
  transform:translateY(-50%);z-index:1}}
.connector.left{{right:50%}}
.connector.right{{left:50%}}
.dot{{position:absolute;left:50%;width:11px;height:11px;border-radius:50%;
  transform:translate(-50%,-50%);z-index:3}}
.detail{{display:none;margin-top:6px;padding-top:6px;
  border-top:1px solid rgba(0,0,0,.1);font-size:11px;color:#666}}
.slice-card.open .detail{{display:block}}
.x-node{{display:none}}
body.show-x .x-node{{display:block}}
body.show-x .dot.x-node{{display:block}}
label.xtoggle{{font-size:12px;color:#555;float:right;cursor:pointer}}
</style></head>
<body class="{body_class}">
<header><h1>{project} — work timeline</h1>
<div class="meta">{span} · {n_phases} phases · {n_slices} slices completed ·
generated {generated}
<label class="xtoggle"><input type="checkbox" id="showX" {checked}
onchange="document.body.classList.toggle('show-x',this.checked)">
show cross-cutting items</label>
<label class="xtoggle"><input type="checkbox" id="dirNewest" checked
onchange="setDir(this.checked)">
newest first</label></div>
<div>{legend}</div></header>
<div id="wrap">
{content}
</div>
<script>
function setDir(newest){{
  document.getElementById('wrap').style.height=
    (newest?{height_desc}:{height_asc})+'px';
  var els=document.querySelectorAll('#wrap [data-ta]');
  for(var i=0;i<els.length;i++){{
    var e=els[i];
    e.style.top=(newest?e.getAttribute('data-td')
                       :e.getAttribute('data-ta'))+'px';
    var hh=newest?e.getAttribute('data-hd'):e.getAttribute('data-ha');
    if(hh!==null)e.style.height=hh+'px';
  }}
}}
</script>
</body></html>
"""
