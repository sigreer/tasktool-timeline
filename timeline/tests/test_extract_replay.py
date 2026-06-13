import datetime as dt

from timeline import extract
from timeline.tests.helpers import doc, make_repo, phase, slice_, x


def test_replay_records_transitions_with_commit_times(tmp_path):
    s_ready = slice_("S1", status="ready", created="2026-06-01")
    s_prog = slice_("S1", status="in_progress", created="2026-06-01")
    s_done = slice_("S1", status="done", created="2026-06-01", closed="2026-06-02")
    repo = make_repo(tmp_path, [
        ("2026-06-01T10:00:00 +0000", doc(phases=[phase("P1", slices=[s_ready])])),
        ("2026-06-01T15:30:00 +0000", doc(phases=[phase("P1", slices=[s_prog])])),
        ("2026-06-02T09:45:00 +0000", doc(phases=[phase("P1", slices=[s_done])])),
    ])
    histories, warnings = extract.replay(repo)
    assert warnings == []
    ts = [(t.old, t.new) for t in histories["P1.S1"].transitions]
    assert ts == [(None, "ready"), ("ready", "in_progress"), ("in_progress", "done")]
    done = histories["P1.S1"].transitions[-1]
    expected = int(dt.datetime(2026, 6, 2, 9, 45,
                               tzinfo=dt.timezone.utc).timestamp())
    assert done.ts == expected


def test_replay_suppresses_import_artifacts(tmp_path):
    # P0 arrives already done in the first commit: no usable transition.
    imported = phase("P0", status="done", closed="2026-05-01")
    repo = make_repo(tmp_path, [
        ("2026-06-01T10:00:00 +0000", doc(phases=[imported])),
    ])
    histories, _ = extract.replay(repo)
    assert "P0" not in histories


def test_replay_skips_unparseable_revision(tmp_path):
    repo = make_repo(tmp_path, [
        ("2026-06-01T10:00:00 +0000", doc(phases=[phase("P1", status="ready")])),
    ])
    # Hand-commit a broken revision, then a good one.
    import subprocess, os, json
    (repo / "docs" / "tasklist.json").write_text("{ broken")
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-06-01T11:00:00 +0000",
           "GIT_COMMITTER_DATE": "2026-06-01T11:00:00 +0000"}
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "broken"], cwd=repo, check=True,
                   capture_output=True, env=env)
    good = doc(phases=[phase("P1", status="done", closed="2026-06-01")])
    (repo / "docs" / "tasklist.json").write_text(json.dumps(good))
    env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "2026-06-01T12:00:00 +0000"
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "good"], cwd=repo, check=True,
                   capture_output=True, env=env)

    histories, warnings = extract.replay(repo)
    assert len(warnings) == 1 and "skipped unparseable" in warnings[0]
    assert [t.new for t in histories["P1"].transitions] == ["ready", "done"]


def test_replay_tracks_cross_items(tmp_path):
    repo = make_repo(tmp_path, [
        ("2026-06-01T10:00:00 +0000", doc(cross=[x("X1", status="ready")])),
        ("2026-06-03T16:20:00 +0000",
         doc(cross=[x("X1", status="done", closed="2026-06-03")])),
    ])
    histories, _ = extract.replay(repo)
    assert [t.new for t in histories["X1"].transitions] == ["ready", "done"]
