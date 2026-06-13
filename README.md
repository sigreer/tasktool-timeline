# tasktool-timeline

A self-contained HTML **work-history timeline generator** for [tasktool] projects
(repos with a `docs/tasklist.json`). It reads the live tracker, the archived-task
JSON blocks, and the git history of `docs/tasklist.json`, then renders a single
self-contained HTML page — phases, slices and cross-cutting items laid out on a
proportional time axis with duration cards, lanes, and quiet-gap compression.

Originally built as **X29** inside the `superstar` skills repo; extracted here as a
standalone project. Python 3 stdlib + `git` only — **zero third-party dependencies**.

```
timeline/        the package (extract → model → render → CLI), with its test suite
server.py        live HTTP server: lazily regenerates the page at most once/interval
generate.sh      one-off static HTML generation
systemd/         user service unit to keep the live server running
```

## Quick start

### One-off static file

```bash
./generate.sh ~/Dev/sigreer/multistore multistore.html
# open multistore.html in a browser
```

Or directly:

```bash
PYTHONPATH=. python3 timeline/timeline.py --repo ~/Dev/sigreer/multistore -o out.html
```

Flags: `--show-x` (start with cross-cutting items visible),
`--overrides <file>` (defaults to `<repo>/docs/timeline-overrides.json`).

### Live server (recommended)

```bash
python3 server.py --repo ~/Dev/sigreer/multistore --port 8787
# browse http://127.0.0.1:8787/
```

The server is deliberately lazy and low-footprint:

- It regenerates the timeline **on demand, at most once per `--interval`** (default
  3600s = 1 hour). Between regenerations it serves the cached HTML instantly, so an
  idle server does essentially no work.
- The served page carries a `<meta http-equiv="refresh">` (default `--refresh` 900s
  = 15 min) so an **open browser tab reloads itself** and picks up each hourly
  regeneration with no manual action.
- If a regeneration fails it keeps serving the last good page (or an auto-retrying
  error page if it has never succeeded), so a transient bad tracker state never
  takes the page down.

`GET /healthz` returns `ok` for liveness checks.

## Run it as a background service (multistore, hourly)

A systemd **user** service keeps the live server up whenever your session/system is
running, regenerating the multistore timeline hourly on view:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/tasktool-timeline-multistore.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tasktool-timeline-multistore.service

# then browse:
xdg-open http://127.0.0.1:8787/

# logs / status:
systemctl --user status tasktool-timeline-multistore.service
journalctl --user -u tasktool-timeline-multistore.service -f
```

To survive logout (run even when you're not logged in): `loginctl enable-linger $USER`.

The unit caps memory at 256M and runs niced; the process idles between requests.

## backfill.py

`timeline/backfill.py` is a **run-once** migration helper that rewrites pre-tasktool
archive markdown into the canonical `## Full phase JSON` blocks the generator reads.
Dry-run (prints a unified diff) by default; `--write` applies. It is never invoked by
the generator or the server.

```bash
PYTHONPATH=. python3 timeline/backfill.py --repo <repo>          # dry-run diff
PYTHONPATH=. python3 timeline/backfill.py --repo <repo> --write  # apply
```

## Tests

```bash
PYTHONPATH=. python3 -m pytest timeline/tests -q   # 110 tests
```

## How dates are resolved (summary)

- Tracker `created`/`started`/`closed` **fields** are the authoritative dates.
- Git **replay** of `docs/tasklist.json` supplies transition *timing*: a field date
  on a day with a matching replay transition is upgraded to minute precision; a null
  field is filled from replay (except a phase's `closed`, never invented).
- `docs/timeline-overrides.json` can override dates / titles / exclude items; unknown
  keys and malformed values fail loud.

[tasktool]: https://github.com/sigreer (the superstar fork's task tracker)
