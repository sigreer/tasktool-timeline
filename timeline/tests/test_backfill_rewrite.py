import datetime as dt
import json

from timeline import backfill
from timeline.tests.helpers import doc, phase

ARCHIVE_TEMPLATE = """# P1 — Stabilise baseline

status: done
closed: 2026-04-29

## Slices


## Full phase JSON (for tasktool unarchive)

```json
{}
```
"""

LEGACY = """# P1 — Stabilise baseline ✅ `DONE 2026-04-29`

## S1 — Baseline upgrade ✅ `DONE 2026-04-29`
"""


def _setup(tmp_path):
    arch = tmp_path / "docs" / "archived-tasks"
    arch.mkdir(parents=True)
    empty = doc(phases=[phase("P1", status="done", closed="2026-04-29",
                              created="1970-01-01")])
    (arch / "P1-tasktool.md").write_text(
        ARCHIVE_TEMPLATE.format(json.dumps(empty, indent=2)))
    (arch / "P1-legacy.md").write_text(LEGACY)
    return tmp_path


def test_plan_rewrites_fills_slices_and_started(tmp_path):
    root = _setup(tmp_path)
    mentions = {"P1": int(dt.datetime(2026, 4, 25, 9, 0).timestamp())}
    changes = backfill.plan_rewrites(root, mentions)
    assert len(changes) == 1
    path, new_text = changes[0]
    assert path.name == "P1-tasktool.md"
    block = json.loads(backfill._json_block(new_text))
    p1 = block["phases"][0]
    assert p1["started"] == "2026-04-25"
    assert [(s["id"], s["status"], s["closed"]) for s in p1["slices"]] == [
        ("S1", "done", "2026-04-29")]
    assert p1["closed"] == "2026-04-29"  # existing values never overwritten


def test_existing_slices_not_touched(tmp_path):
    root = _setup(tmp_path)
    arch = root / "docs" / "archived-tasks" / "P1-tasktool.md"
    filled = doc(phases=[phase("P1", status="done", closed="2026-04-29",
                               slices=[{"id": "S1", "status": "done",
                                        "closed": "2026-04-29",
                                        "title": "already here"}])])
    arch.write_text(ARCHIVE_TEMPLATE.format(json.dumps(filled, indent=2)))
    changes = backfill.plan_rewrites(root, {"P1": 1000})
    if changes:  # only the started fill may remain
        block = json.loads(backfill._json_block(changes[0][1]))
        assert block["phases"][0]["slices"][0]["title"] == "already here"


def test_started_clamped_to_previous_phase_close(tmp_path):
    # Mined mention predates the previous phase's close: sequential-era
    # cross-check clamps the start to the previous close.
    root = _setup(tmp_path)
    arch = root / "docs" / "archived-tasks"
    p0 = doc(phases=[phase("P0", status="done", closed="2026-04-27")])
    (arch / "P0-tasktool.md").write_text(
        ARCHIVE_TEMPLATE.replace("P1", "P0").format(json.dumps(p0, indent=2)))
    early = int(dt.datetime(2026, 4, 20, 9, 0).timestamp())
    changes = backfill.plan_rewrites(root, {"P1": early})
    target = next(c for c in changes if c[0].name == "P1-tasktool.md")
    block = json.loads(backfill._json_block(target[1]))
    assert block["phases"][0]["started"] == "2026-04-27"  # clamped, not 04-20


def test_started_kept_when_after_previous_close(tmp_path):
    root = _setup(tmp_path)
    arch = root / "docs" / "archived-tasks"
    p0 = doc(phases=[phase("P0", status="done", closed="2026-04-20")])
    (arch / "P0-tasktool.md").write_text(
        ARCHIVE_TEMPLATE.replace("P1", "P0").format(json.dumps(p0, indent=2)))
    mined = int(dt.datetime(2026, 4, 25, 9, 0).timestamp())
    changes = backfill.plan_rewrites(root, {"P1": mined})
    target = next(c for c in changes if c[0].name == "P1-tasktool.md")
    block = json.loads(backfill._json_block(target[1]))
    assert block["phases"][0]["started"] == "2026-04-25"  # mined date kept


def test_no_fill_when_clamp_passes_own_close(tmp_path):
    # Parallel-era phases: the previous phase closed AFTER this phase did, so
    # the clamp would push the start past this phase's own close. Skip the
    # fill instead of writing started > closed.
    root = _setup(tmp_path)
    arch = root / "docs" / "archived-tasks"
    p0 = doc(phases=[phase("P0", status="done", closed="2026-05-10")])
    (arch / "P0-tasktool.md").write_text(
        ARCHIVE_TEMPLATE.replace("P1", "P0").format(json.dumps(p0, indent=2)))
    early = int(dt.datetime(2026, 4, 20, 9, 0).timestamp())
    changes = backfill.plan_rewrites(root, {"P1": early})
    target = next(c for c in changes if c[0].name == "P1-tasktool.md")
    block = json.loads(backfill._json_block(target[1]))
    p1 = block["phases"][0]
    assert p1["started"] is None          # not filled with 2026-05-10
    assert p1["closed"] == "2026-04-29"   # untouched


def test_no_fill_when_mined_date_after_own_close(tmp_path):
    # Retroactively-recorded phase: the raw mined mention postdates the
    # phase's own close. No clamp involved; the fill is simply skipped.
    root = _setup(tmp_path)
    late = int(dt.datetime(2026, 5, 15, 9, 0).timestamp())
    changes = backfill.plan_rewrites(root, {"P1": late})
    assert len(changes) == 1  # slices fill still happens
    block = json.loads(backfill._json_block(changes[0][1]))
    p1 = block["phases"][0]
    assert p1["started"] is None
    assert p1["closed"] == "2026-04-29"


def test_non_ascii_kept_literal_in_rewrite(tmp_path):
    root = _setup(tmp_path)
    arch = root / "docs" / "archived-tasks" / "P1-tasktool.md"
    d = doc(phases=[phase("P1", status="done", closed="2026-04-29",
                          title="Stabilise — baseline ✅")])
    arch.write_text(ARCHIVE_TEMPLATE.format(
        json.dumps(d, indent=2, ensure_ascii=False)))
    mined = int(dt.datetime(2026, 4, 25, 9, 0).timestamp())
    changes = backfill.plan_rewrites(root, {"P1": mined})
    assert len(changes) == 1
    raw = backfill._json_block(changes[0][1])
    assert "Stabilise — baseline ✅" in raw
    assert "\\u2014" not in raw and "\\u2705" not in raw


def test_diff_output_and_write(tmp_path, capsys):
    root = _setup(tmp_path)
    backfill.run(root, mentions={"P1": 1000}, write=False)
    assert "P1-tasktool.md" in capsys.readouterr().out
    before = (root / "docs" / "archived-tasks" / "P1-tasktool.md").read_text()
    backfill.run(root, mentions={"P1": 1000}, write=True)
    after = (root / "docs" / "archived-tasks" / "P1-tasktool.md").read_text()
    assert before != after and '"S1"' in after
