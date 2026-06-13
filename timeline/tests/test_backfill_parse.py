from timeline import backfill

LEGACY = """# P1 — Stabilise baseline ✅ `DONE 2026-04-29`

Archived from the legacy `docs/TASKLIST.md`. Closed 2026-04-29.

## S1 — Baseline upgrade & validation ✅ `DONE 2026-04-29`

- ✅ **T1** Upgrade and pin the stack.

## S2 — Second slice ✅ `DONE 2026-04-30`
"""


def test_parse_legacy_archive():
    parsed = backfill.parse_legacy(LEGACY)
    assert parsed.phase_id == "P1"
    assert parsed.closed == "2026-04-29"
    assert [(s.sid, s.title, s.closed) for s in parsed.slices] == [
        ("S1", "Baseline upgrade & validation", "2026-04-29"),
        ("S2", "Second slice", "2026-04-30"),
    ]


def test_parse_legacy_returns_none_without_done_heading():
    assert backfill.parse_legacy("# Notes\n\nNothing here.") is None


def test_parse_legacy_without_backticks():
    parsed = backfill.parse_legacy(
        "# P3 — Editor-grade CMS + shared packages ✅ DONE 2026-05-04\n")
    assert parsed.phase_id == "P3"
    assert parsed.closed == "2026-05-04"


def test_mine_first_mentions():
    subjects = [
        (100, "*DOCS*: P2.S3 close — resolve schema"),
        (200, "feat p2-s4 add importer"),
        (300, "P2: wrap up phase"),
        (400, "P3.S1 start"),
    ]
    first = backfill.first_mentions(subjects)
    assert first["P2.S3"] == 100
    assert first["P2.S4"] == 200
    assert first["P2"] == 100      # phase inherits its earliest item mention
    assert first["P3.S1"] == 400
    assert first["P3"] == 400
