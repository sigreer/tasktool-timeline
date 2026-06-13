#!/usr/bin/env python3
"""Generate a self-contained HTML timeline of a tasktool project's history.

Human-facing utility. Never referenced by skills or hooks; adds no agent
context. Usage:

    python3 tools/timeline/timeline.py --repo ~/Dev/proj -o timeline.html
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # support `python3 tools/timeline/timeline.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/
    from timeline import extract, model, render
else:
    from . import extract, model, render


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".", help="target repo (default: cwd)")
    ap.add_argument("-o", "--output", default="timeline.html")
    ap.add_argument("--show-x", action="store_true",
                    help="start with cross-cutting items visible")
    ap.add_argument("--overrides", default=None,
                    help="overrides JSON (default: <repo>/docs/timeline-overrides.json)")
    args = ap.parse_args(argv)

    root = extract.repo_root(args.repo)
    warnings = []
    if extract.is_shallow(root):
        warnings.append("shallow clone: replay limited; some items stay day-precision")

    live = extract.read_live(root)
    project_docs, x_objects, w = extract.read_archives(root)
    warnings += w
    histories, w = extract.replay(root)
    warnings += w

    items = model.collect(live, project_docs, x_objects)
    for it in items:
        h = histories.get(it.key)
        if h:
            model.apply_replay(it, h)

    ov_path = Path(args.overrides) if args.overrides \
        else root / "docs" / "timeline-overrides.json"
    if ov_path.exists():
        warnings += model.apply_overrides(items, json.loads(ov_path.read_text()))
    elif args.overrides:
        raise SystemExit(f"timeline: overrides file not found: {ov_path}")

    project = live.get("project") or root.name
    result = render.render_html(project, items,
                                generated=dt.datetime.now(), show_x=args.show_x)
    Path(args.output).write_text(result.html)

    for warning in warnings:
        print(f"timeline: {warning}", file=sys.stderr)
    if result.unplaced:
        print(f"timeline: {len(result.unplaced)} item(s) had no resolvable "
              f"dates and were omitted: {', '.join(sorted(result.unplaced))}",
              file=sys.stderr)
    print(f"timeline: wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
