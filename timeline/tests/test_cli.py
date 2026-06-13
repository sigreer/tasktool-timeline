import json
import time

import pytest

from timeline import timeline
from timeline.tests.helpers import doc, make_repo, phase, slice_, x


@pytest.fixture
def utc_tz(monkeypatch):
    # model._merge_date only upgrades a field to minute precision when the
    # replay commit's *local* calendar date matches the field date, so
    # test_end_to_end is TZ-dependent (fails at e.g. UTC+8, where the
    # 16:30 UTC commit falls on the next local day). Pin UTC, then restore.
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _project_repo(tmp_path):
    s_done = slice_("S1", status="done", created="2026-06-01", closed="2026-06-02",
                    title="Build the widget")
    snapshots = [
        ("2026-06-01T10:00:00 +0000",
         doc(phases=[phase("P1", status="ready", created="2026-06-01",
                           slices=[slice_("S1", status="ready",
                                          created="2026-06-01",
                                          title="Build the widget")])])),
        ("2026-06-02T16:30:00 +0000",
         doc(phases=[phase("P1", status="done", created="2026-06-01",
                           started="2026-06-01", closed="2026-06-02",
                           slices=[s_done])],
             cross=[x("X1", status="done", closed="2026-06-02",
                      title="Cross thing")])),
    ]
    return make_repo(tmp_path, snapshots)


def test_end_to_end(tmp_path, capsys, utc_tz):
    repo = _project_repo(tmp_path)
    out = tmp_path / "t.html"
    timeline.main(["--repo", str(repo), "-o", str(out)])
    h = out.read_text()
    assert "Build the widget" in h and "Cross thing" in h
    # Replay upgraded the same-day close to minute precision. Rendered times
    # are local wall clock, so compute the expectation from the commit epoch.
    import datetime as dt
    ts = int(dt.datetime(2026, 6, 2, 16, 30, tzinfo=dt.timezone.utc).timestamp())
    assert dt.datetime.fromtimestamp(ts).strftime("%H:%M") in h


def test_overrides_applied(tmp_path):
    repo = _project_repo(tmp_path)
    (repo / "docs" / "timeline-overrides.json").write_text(json.dumps(
        {"items": {"P1.S1": {"display_title": "Friendly widget"}}}))
    out = tmp_path / "t.html"
    timeline.main(["--repo", str(repo), "-o", str(out)])
    assert "Friendly widget" in out.read_text()


def test_missing_tracker_is_fatal(tmp_path):
    import subprocess
    bare = tmp_path / "bare"
    bare.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=bare, check=True)
    with pytest.raises(SystemExit):
        timeline.main(["--repo", str(bare), "-o", str(tmp_path / "x.html")])


def test_direct_script_invocation(tmp_path):
    # The acceptance commands run the file directly from the repo root —
    # cover the script-mode sys.path shim, not just the package import.
    import subprocess, sys
    from pathlib import Path
    repo = _project_repo(tmp_path)
    out = tmp_path / "direct.html"
    script = Path(__file__).resolve().parents[1] / "timeline.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--repo", str(repo), "-o", str(out)],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parents[3])
    assert proc.returncode == 0, proc.stderr
    assert "Build the widget" in out.read_text()


def test_unplaced_summary_on_stderr(tmp_path, capsys):
    repo = _project_repo(tmp_path)
    live = json.loads((repo / "docs" / "tasklist.json").read_text())
    live["phases"].append(phase("P9", status="ready"))  # no dates at all
    (repo / "docs" / "tasklist.json").write_text(json.dumps(live))
    timeline.main(["--repo", str(repo), "-o", str(tmp_path / "t.html")])
    assert "P9" in capsys.readouterr().err
