"""Shared fixture builders for timeline tests."""

import json
import os
import subprocess


def doc(phases=None, cross=None):
    return {
        "schema_version": 1,
        "project": "fixture",
        "north_star": "",
        "last_reviewed": None,
        "phases": phases or [],
        "cross_cutting": cross or [],
        "archived_phases": [],
        "archived_cross_cutting": [],
    }


def phase(pid, status="ready", created=None, started=None, closed=None,
          slices=None, title=None):
    return {
        "id": pid, "status": status, "created": created, "started": started,
        "closed": closed, "title": title or f"Phase {pid}",
        "slices": slices or [], "notes": "",
    }


def slice_(sid, status="ready", created=None, started=None, closed=None, title=None):
    return {
        "id": sid, "status": status, "created": created, "started": started,
        "closed": closed, "title": title or f"Slice {sid}",
        "tasks": [], "refs": [], "notes": "",
    }


def x(xid, status="ready", created=None, started=None, closed=None, title=None):
    return {
        "id": xid, "status": status, "created": created, "started": started,
        "closed": closed, "title": title or f"Cross {xid}", "notes": "",
    }


def make_repo(tmp_path, snapshots):
    """Create a git repo with one commit of docs/tasklist.json per snapshot.

    snapshots: list of (iso_datetime_with_offset, doc_dict),
               e.g. ("2026-06-01T10:00:00 +0000", doc(...)).
    Returns the repo path.
    """
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    run = lambda *a, **kw: subprocess.run(a, cwd=repo, check=True,
                                          capture_output=True, **kw)
    run("git", "init", "-q")
    run("git", "config", "user.email", "test@test")
    run("git", "config", "user.name", "test")
    for iso, d in snapshots:
        (repo / "docs" / "tasklist.json").write_text(json.dumps(d, indent=2))
        env = {**os.environ, "GIT_AUTHOR_DATE": iso, "GIT_COMMITTER_DATE": iso}
        run("git", "add", "-A")
        subprocess.run(["git", "commit", "-q", "-m", "snap"], cwd=repo,
                       check=True, capture_output=True, env=env)
    return repo
