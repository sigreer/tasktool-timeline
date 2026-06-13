import json

from timeline import extract
from timeline.tests.helpers import doc, phase, x

PHASE_MD = """# P3 — Old phase

status: done
closed: 2026-05-04

## Slices

- **S1** [done] — closed 2026-05-04 — something

## Full phase JSON (for tasktool unarchive)

```json
{}
```
"""

CROSS_MD = """# X7 — Old cross item

status: done

## Full cross-cutting JSON (for tasktool unarchive)

```json
{}
```
"""

LEGACY_MD = """# P1 — Legacy phase ✅ `DONE 2026-04-29`

## S1 — Old slice ✅ `DONE 2026-04-29`
"""

BROKEN_MD = """# P9 — Broken

## Full phase JSON (for tasktool unarchive)

```json
{ this is not json
```
"""


def _write_archives(tmp_path, files):
    arch = tmp_path / "docs" / "archived-tasks"
    arch.mkdir(parents=True)
    for name, text in files.items():
        (arch / name).write_text(text)
    return tmp_path


def test_reads_phase_and_cross_blocks(tmp_path):
    p3 = doc(phases=[phase("P3", status="done", closed="2026-05-04")])
    x7 = x("X7", status="done", closed="2026-05-05")
    _write_archives(tmp_path, {
        "P3-old.md": PHASE_MD.format(json.dumps(p3, indent=2)),
        "X7-old.md": CROSS_MD.format(json.dumps(x7, indent=2)),
        "P1-legacy.md": LEGACY_MD,
    })
    project_docs, x_objects, warnings = extract.read_archives(tmp_path)
    assert [d["phases"][0]["id"] for d in project_docs] == ["P3"]
    assert [o["id"] for o in x_objects] == ["X7"]
    assert warnings == []  # legacy file silently ignored — it has no JSON block


def test_unparseable_block_warns_not_fatal(tmp_path):
    _write_archives(tmp_path, {"P9-broken.md": BROKEN_MD})
    project_docs, x_objects, warnings = extract.read_archives(tmp_path)
    assert project_docs == [] and x_objects == []
    assert len(warnings) == 1 and "P9-broken.md" in warnings[0]


def test_no_archive_dir_is_fine(tmp_path):
    project_docs, x_objects, warnings = extract.read_archives(tmp_path)
    assert (project_docs, x_objects, warnings) == ([], [], [])
