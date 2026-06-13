#!/usr/bin/env python3
"""Live timeline server: serves a tasktool project's work-history timeline as a
self-contained HTML page, regenerated on demand at most once per interval.

Design goals (per the X29 brief): minimal resource use, always-fresh when
viewed. The server holds no background work — it regenerates the HTML lazily on
the first request after the cache goes stale (default: 1 hour). Between
regenerations it serves the cached bytes instantly. A `<meta http-equiv=refresh>`
tag is injected so an open browser tab reloads itself periodically and therefore
picks up each hourly regeneration without manual action.

    python3 server.py --repo ~/Dev/sigreer/multistore --port 8787

Stdlib only. The `timeline` package (same repo) does the real work.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make `timeline` importable
from timeline import extract, model, render  # noqa: E402


def build_html(repo: str, show_x: bool, overrides: str | None) -> tuple[str, list[str]]:
    """Run the full extract -> model -> render pipeline. Returns (html, warnings).

    Mirrors timeline.timeline.main but returns the HTML instead of writing it,
    so the server can hold it in memory. Kept deliberately thin so the rendering
    logic stays solely in the (tested) `timeline` package."""
    root = extract.repo_root(repo)
    warnings: list[str] = []
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

    ov_path = Path(overrides) if overrides else root / "docs" / "timeline-overrides.json"
    if ov_path.exists():
        warnings += model.apply_overrides(items, json.loads(ov_path.read_text()))
    elif overrides:
        raise SystemExit(f"overrides file not found: {ov_path}")

    project = live.get("project") or root.name
    result = render.render_html(project, items, generated=dt.datetime.now(), show_x=show_x)
    if result.unplaced:
        warnings.append(f"{len(result.unplaced)} item(s) omitted (no resolvable dates): "
                        + ", ".join(sorted(result.unplaced)))
    return result.html, warnings


def inject_autorefresh(html: str, seconds: int) -> str:
    """Insert a meta-refresh so an open tab reloads itself periodically."""
    tag = f'<meta http-equiv="refresh" content="{seconds}">'
    marker = '<meta charset="utf-8">'
    if marker in html:
        return html.replace(marker, marker + tag, 1)
    return html.replace("<head>", "<head>" + tag, 1)


ERROR_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60"><title>timeline — error</title>
<style>body{{font-family:system-ui,sans-serif;margin:40px;color:#333}}
pre{{background:#fafafa;border:1px solid #e5e5e5;padding:16px;overflow:auto}}</style>
</head><body><h1>Timeline generation failed</h1>
<p>The server could not build the timeline. It will retry on the next request
(auto-retry in 60s).</p><pre>{detail}</pre></body></html>"""


class Cache:
    """Thread-safe lazily-regenerated HTML cache."""

    def __init__(self, repo, show_x, overrides, interval, refresh):
        self.repo = repo
        self.show_x = show_x
        self.overrides = overrides
        self.interval = interval          # seconds between regenerations
        self.refresh = refresh            # browser meta-refresh seconds
        self._lock = threading.Lock()
        self._html: bytes | None = None
        self._built_at: float = 0.0       # monotonic
        self._built_wall: dt.datetime | None = None
        self._warnings: list[str] = []
        self._error: str | None = None

    def _stale(self, now: float) -> bool:
        return self._html is None or (now - self._built_at) >= self.interval

    def get(self) -> tuple[bytes, bool]:
        """Return (html_bytes, ok). Regenerates if stale, else serves cache."""
        now = time.monotonic()
        with self._lock:
            if not self._stale(now):
                return self._html, self._error is None
            try:
                html, warnings = build_html(self.repo, self.show_x, self.overrides)
                html = inject_autorefresh(html, self.refresh)
                self._html = html.encode("utf-8")
                self._built_at = now
                self._built_wall = dt.datetime.now()
                self._warnings = warnings
                self._error = None
                stamp = self._built_wall.strftime("%Y-%m-%d %H:%M:%S")
                msg = f"[{stamp}] regenerated timeline for {self.repo}"
                if warnings:
                    msg += " (warnings: " + "; ".join(warnings) + ")"
                print(msg, file=sys.stderr, flush=True)
                return self._html, True
            except Exception:
                detail = traceback.format_exc()
                self._error = detail
                print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] ERROR building timeline:\n"
                      f"{detail}", file=sys.stderr, flush=True)
                if self._html is not None:
                    # Serve last-good rather than an error page when we have one.
                    return self._html, False
                page = ERROR_PAGE.format(detail=detail).encode("utf-8")
                self._html = page
                self._built_at = now
                return page, False


def make_handler(cache: Cache):
    class Handler(BaseHTTPRequestHandler):
        server_version = "tasktool-timeline/1.0"

        def _send(self, status, body: bytes, ctype="text/html; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                body, ok = cache.get()
                self._send(200 if ok else 503, body)
            elif path == "/healthz":
                self._send(200, b"ok", "text/plain; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        do_HEAD = do_GET

        def log_message(self, fmt, *args):  # quieter access log
            return

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="target tasktool project repo")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--interval", type=int, default=3600,
                    help="min seconds between regenerations (default: 3600 = 1h)")
    ap.add_argument("--refresh", type=int, default=900,
                    help="browser auto-refresh seconds (default: 900 = 15m)")
    ap.add_argument("--show-x", action="store_true",
                    help="start with cross-cutting items visible")
    ap.add_argument("--overrides", default=None,
                    help="overrides JSON (default: <repo>/docs/timeline-overrides.json)")
    args = ap.parse_args(argv)

    cache = Cache(args.repo, args.show_x, args.overrides, args.interval, args.refresh)
    # Warm the cache once at startup so the first visitor gets an instant page
    # and any config error surfaces in the logs immediately.
    cache.get()

    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(cache))
    url = f"http://{args.host}:{args.port}/"
    print(f"tasktool-timeline serving {args.repo}\n"
          f"  -> {url}\n"
          f"  regenerate every {args.interval}s, browser refresh every {args.refresh}s",
          file=sys.stderr, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", file=sys.stderr)
        httpd.shutdown()


if __name__ == "__main__":
    main()
