# tasktool-timeline

A self-contained HTML **work-history timeline generator** for [tasktool] projects —
repos that track their work in `docs/tasklist.json`. It reads the live tracker, the
archived-task JSON blocks, and the git history of `docs/tasklist.json`, then renders a
single self-contained HTML page: phases, slices and cross-cutting (`X`) items on a
proportional time axis with duration cards, lanes, quiet-gap compression, and per-item
effort stats (commits, lines, files).

## Project Task List

[`docs/tasklist.json`](docs/tasklist.json) is the canonical tracker for this repo's
phases, slices, tasks, and cross-cutting items. Use `tasktool` for all mutations from the
authoritative `master` checkout; do not hand-edit the JSON except through the documented
emergency path. The pre-commit hook validates the tracker on every commit.

Useful commands:

```bash
tasktool list --open
tasktool brief <id>
tasktool show <id>
tasktool set <id> --status in_progress
tasktool close <slice-id>
tasktool archive-phase <phase-id>
tasktool validate
```

**Numbering & status discipline.** Every unit of work has a stable ID (`P{n}.S{n}[.T{n}]`,
letter suffix `S{n}a` for follow-ups, `X{n}` for cross-cutting). IDs are assigned at birth
and **never renumbered**. Within a nested context the short form (`S1`, `T3`) suffices;
fully-qualified IDs are only for cross-scope references. Full rules and gating concepts
live in the `superstar:tasklist-discipline` skill.

(This project is dogfood: a tasktool project whose own timeline you can render with
`./generate.sh .` — the same data model it visualises governs its own work tracking.)

## Planning & implementation discipline

**Always use the `superstar:*` skills for planning and implementation work — not direct
authoring.** Specs, plans, and the act of executing those plans go through the skill
harness so the brainstorm → spec → plan → execute → verify chain stays consistent.

- **Before any creative / feature / behavioural work:** `superstar:brainstorming`.
- **Writing a spec or implementation plan:** `superstar:writing-plans` (artefact under
  [`docs/specs/`](docs/specs/) or [`docs/plans/`](docs/plans/), naming convention
  `YYYY-MM-DD-<id>-<slug>(-design).md`).
- **Executing a plan in this session:** `superstar:subagent-driven-development`
  (parallelisable tasks) or `superstar:executing-plans` (review-checkpointed).
- **Debugging a defect:** `superstar:systematic-debugging` before proposing a fix.
- **TDD work:** `superstar:test-driven-development`.
- **Claiming "done":** `superstar:verification-before-completion` — evidence (command
  output) before assertions.
- **Review:** `superstar:requesting-internal-review`, `superstar:receiving-internal-review`,
  and `superstar:external-review` (chains land under [`docs/reviewer/`](docs/reviewer/)).
- **Closing a development branch:** `superstar:finishing-a-development-branch`.

Doc tree: [`docs/specs/`](docs/specs/), [`docs/plans/`](docs/plans/),
[`docs/handoffs/`](docs/handoffs/), [`docs/reviewer/`](docs/reviewer/),
[`docs/archived-tasks/`](docs/archived-tasks/).

## Purpose & audience

This is a **companion tool to the tasktool / `docs/tasklist.json` half of the superstar
skill.** Its job is to turn the machine-readable task tracker into a glanceable visual
narrative of how a project progressed over time.

The primary audience is **non-technical associates / stakeholders** who want to see
progress on:

- `../../multistore` — the multistore ecommerce project (primary driver; ~1,800 commits,
  the main test corpus).
- `../superstar` — the superstar skills repo itself (secondary).

Everything else flows from that goal: stats exist so a non-technical reader can gauge
scale of effort; the live server + meta-refresh exist so an associate can keep a tab open
and see it stay current; machine-generated churn is filtered out so the numbers reflect
*authored* effort rather than lockfile noise.

**Core tenet:** a read-only visualiser layered on top of tasktool's data model. It never
mutates the target repo. When the tasktool schema or conventions change, this tool
follows. New features should serve the "help an associate understand progress at a glance"
goal.

## Architecture

Python 3 stdlib + `git` only — **zero third-party dependencies** (`requires-python >=
3.10`). The real work lives in the `timeline/` package as a four-stage pipeline:

```
extract → model → render        (+ stats, computed alongside)
```

| File | Role |
|------|------|
| `timeline/extract.py` | Reads tracker data from a repo: live `docs/tasklist.json`, archived-task JSON blocks (`## Full phase JSON` / `## Full cross-cutting JSON` fenced blocks in `docs/archived-tasks/`), and a git **replay** of `docs/tasklist.json` history for transition timing. Detects shallow clones. |
| `timeline/model.py` | The **only** module that knows the `docs/tasklist.json` schema. Normalizes everything into `TimelineItem` records (key, kind=phase\|slice\|x, dates with precision/source). Owns date resolution: tracker fields are authoritative; git replay upgrades precision / fills nulls; `docs/timeline-overrides.json` can override dates/titles/exclusions. `TimelineItem` is the seam between stages. |
| `timeline/render.py` | Renders `TimelineItem`s to a single self-contained HTML page (largest module). Owns the proportional time axis, lane packing, quiet-gap compression (`QUIET_RUN_DAYS`, `MIN_GAP_PX`/`MAX_GAP_PX`, `PX_PER_HOUR`), the colour palette, and display rules (`visible_items`). |
| `timeline/stats.py` | Per-item effort stats from a single `git log --numstat` pass. Attributes commits to items by matching tasktool keys (`P25`, `P25.S2`, `X72`, branch-slug `p25-s1`) in commit **subjects**; phases roll up their slices de-duplicated. Excludes machine-generated noise (lockfiles, `node_modules`/`dist`/build output, minified bundles, snapshots, the tracker's own bookkeeping) and binaries/merges from line counts. Read-only. |
| `timeline/timeline.py` | CLI entry point (`--repo`, `-o`, `--show-x`, `--overrides`, `--no-stats`). Thin orchestration over the pipeline. |
| `timeline/backfill.py` | **Run-once** migration helper: rewrites pre-tasktool archive markdown into the canonical `## Full phase JSON` blocks the generator reads. Dry-run by default, `--write` applies. Never invoked by the generator or server. |

Top-level entry points:

| File | Role |
|------|------|
| `server.py` | Live HTTP server. Lazily regenerates the page **at most once per `--interval`** (default 3600s), serving cached bytes between regenerations; injects a `<meta http-equiv=refresh>` (default `--refresh` 900s) so open tabs self-reload; serves last-good HTML on regeneration failure; `GET /healthz` → `ok`. `build_html()` mirrors `timeline.main` but returns HTML in memory — keep rendering logic in the package, not here. |
| `generate.sh` | One-off static HTML: `./generate.sh <repo> [output.html] [-- extra timeline.py args]`. |
| `systemd/` | User service unit to keep the live server running (multistore, hourly). |

## Working in this repo

### Run it

```bash
# one-off static file
./generate.sh ../../multistore /tmp/multistore.html        # multistore
./generate.sh ../superstar    /tmp/superstar.html          # superstar

# or directly
PYTHONPATH=. python3 timeline/timeline.py --repo ../../multistore -o out.html

# live server
python3 server.py --repo ../../multistore --port 8787      # http://127.0.0.1:8787/
```

To see real output, generate against `../../multistore` or `../superstar` and open the
HTML, or check any timeline HTML already committed in those repos.

### Tests

```bash
PYTHONPATH=. python3 -m pytest timeline/tests -q     # ~146 tests, <1s
```

The suite is comprehensive (extract, model, merge, overrides, render layout/lanes/scale/
stats, CLI, backfill). **Add tests for any new feature or fix** — it's TDD-friendly and
the suite is fast. Generated `*.html` is gitignored except `timeline/tests/**/*.html`
fixtures.

### Conventions

- **Stdlib + git only.** Do not add third-party runtime dependencies — it's a deliberate
  design constraint that keeps the tool trivially deployable.
- **Read-only on target repos.** The generator and server must never write to the repo
  being visualised. Only `backfill.py` writes, and only with `--write`, only to its own
  repo's archive files.
- **`model.py` is the schema boundary.** Schema knowledge stays there; `TimelineItem` is
  the contract the other stages consume.
- **Fail loud on bad config.** Overrides with unknown keys / malformed values raise rather
  than silently no-op.

[tasktool]: tasktool is the task tracker that ships inside the **superstar** skills repo
(`sigreer/superstar`) — the CLI lives at `tools/tasktool/` and its conventions are defined
by the `superstar:tasklist-discipline` skill. Locally that's `../superstar`. There is no
standalone tasktool repository.
