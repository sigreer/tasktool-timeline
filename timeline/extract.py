"""Read tracker data out of a repo: live file, archive JSON blocks, git replay."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

TRACKER = "docs/tasklist.json"

_PHASE_BLOCK_RE = re.compile(
    r"^## Full phase JSON.*?^```json\n(.*?)^```", re.S | re.M)
_CROSS_BLOCK_RE = re.compile(
    r"^## Full cross-cutting JSON.*?^```json\n(.*?)^```", re.S | re.M)


def git(repo, *args, check=True):
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise SystemExit(f"timeline: git {' '.join(args)} failed: "
                         f"{proc.stderr.strip()}")
    return proc.stdout


def repo_root(path):
    return Path(git(path, "rev-parse", "--show-toplevel").strip())


def read_live(repo):
    p = Path(repo) / TRACKER
    if not p.exists():
        raise SystemExit(f"timeline: {p} not found — not a tasktool project")
    return json.loads(p.read_text())


def read_archives(repo):
    """-> (project_docs, x_objects, warnings).

    Reads both '## Full phase JSON' blocks (a project-shaped object whose
    `phases` array holds the archived phase) and '## Full cross-cutting JSON'
    blocks (a single item object). Files with neither block (pure-legacy
    markdown) are ignored — they are backfill.py's input, not ours.
    """
    project_docs, x_objects, warnings = [], [], []
    arch = Path(repo) / "docs" / "archived-tasks"
    files = sorted(arch.glob("*.md")) if arch.is_dir() else []
    for f in files:
        text = f.read_text()
        pm = _PHASE_BLOCK_RE.search(text)
        cm = _CROSS_BLOCK_RE.search(text)
        try:
            if pm:
                project_docs.append(json.loads(pm.group(1)))
            elif cm:
                x_objects.append(json.loads(cm.group(1)))
        except json.JSONDecodeError as e:
            warnings.append(f"{f.name}: unparseable JSON block: {e}")
    return project_docs, x_objects, warnings


@dataclass
class Transition:
    ts: int          # unix commit timestamp
    old: str | None
    new: str


@dataclass
class KeyHistory:
    transitions: list = field(default_factory=list)


def _statuses(doc):
    cur = {}
    for p in doc.get("phases", []):
        cur[p["id"]] = p.get("status", "?")
        for s in p.get("slices", []):
            cur[f"{p['id']}.{s['id']}"] = s.get("status", "?")
    for c in doc.get("cross_cutting", []):
        cur[c["id"]] = c.get("status", "?")
    return cur


def replay(repo):
    """Walk every commit touching docs/tasklist.json oldest->newest and record
    per-item status transitions with commit timestamps.

    Deliberately status-only: date *fields* are read once from the final file
    and stay authoritative for the date — replay supplies transition timing
    (see the spec's "Git replay" section).

    Import-artifact suppression: an item whose first observation is already
    terminal (done/cancelled) arrived via a migration commit — that observation
    carries no real timing and is dropped entirely.
    """
    out = git(repo, "log", "--reverse", "--format=%H %ct", "--", TRACKER)
    commits = [line.split() for line in out.splitlines() if line]
    prev, histories, warnings = {}, {}, []
    for sha, ts in commits:
        ts = int(ts)
        proc = subprocess.run(
            ["git", "-C", str(repo), "show", f"{sha}:{TRACKER}"],
            capture_output=True, text=True)
        if proc.returncode != 0:
            continue  # file absent at this revision
        try:
            doc = json.loads(proc.stdout)
        except json.JSONDecodeError:
            warnings.append(f"replay: skipped unparseable revision {sha[:8]}")
            continue
        cur = _statuses(doc)
        for key, status in cur.items():
            old = prev.get(key)
            if old == status:
                continue
            if old is None and status in ("done", "cancelled"):
                continue  # import artifact
            histories.setdefault(key, KeyHistory()).transitions.append(
                Transition(ts, old, status))
        prev = cur
    return histories, warnings


def is_shallow(repo):
    return git(repo, "rev-parse", "--is-shallow-repository").strip() == "true"
