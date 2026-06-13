"""Tests for per-item work-magnitude stats (timeline.stats)."""

import os
import subprocess

import pytest

from timeline import model, stats
from timeline.tests.helpers import doc, phase, slice_, x


# --- key extraction / normalization -----------------------------------------

@pytest.mark.parametrize("subject, expected", [
    ("P25.S2: close slice", {"P25.S2"}),
    ("*MERGE* P25.S2 chrome and homepage quickfix batch", {"P25.S2"}),
    ("*DOCS* X74: cancel — compat-shim", {"X74"}),
    ("X72: add maintenance-scanner plan", {"X72"}),
    ("*DOCS* P25: add parallel manager handoff", {"P25"}),
    ("Merge branch 'worktree-p25-s1-first-pass'", {"P25.S1"}),
    ("*DOCS*: backfill P1-P12 archive stubs", {"P1", "P12"}),
    ("P25.S2 and P25.S6 joint fix", {"P25.S2", "P25.S6"}),
    ("Bump Superstar to 6.10.2", set()),
    ("fix typo in readme", set()),
])
def test_extract_keys(subject, expected):
    assert stats.extract_keys(subject) == expected


def test_slice_ref_does_not_also_count_as_bare_phase():
    # "P25.S2" must attribute to the slice only — the phase picks it up on rollup.
    assert stats.extract_keys("P25.S2: work") == {"P25.S2"}


# --- noise path filtering ----------------------------------------------------

@pytest.mark.parametrize("path", [
    "package-lock.json",
    "apps/web/pnpm-lock.yaml",
    "yarn.lock",
    "node_modules/foo/index.js",
    "apps/web/dist/bundle.js",
    ".next/static/chunk.js",
    "assets/app.min.js",
    "styles/site.min.css",
    "bundle.js.map",
    "docs/tasklist.json",
    "docs/archived-tasks/P1.md",
    "components/__snapshots__/x.snap",
])
def test_noise_paths_excluded(path):
    assert stats.is_noise_path(path) is True


@pytest.mark.parametrize("path", [
    "src/index.ts",
    "docs/specs/2026-06-01-P25-spec.md",
    "apps/web/components/Cart.tsx",
    "server.py",
])
def test_real_paths_kept(path):
    assert stats.is_noise_path(path) is False


# --- end-to-end against a real git fixture -----------------------------------

def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(a, cwd=repo, check=True, capture_output=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")
    return repo, run


def _commit(repo, run, subject, files):
    for name, lines in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(f"line {i}" for i in range(lines)) + "\n")
    run("git", "add", "-A")
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-06-01T10:00:00 +0000",
           "GIT_COMMITTER_DATE": "2026-06-01T10:00:00 +0000"}
    subprocess.run(["git", "commit", "-q", "-m", subject], cwd=repo,
                   check=True, capture_output=True, env=env)


def test_build_index_attributes_and_rolls_up(tmp_path):
    repo, run = _repo(tmp_path)
    _commit(repo, run, "P1.S1: add feature", {"a.py": 10})       # slice S1: +10
    _commit(repo, run, "P1.S1: more", {"a.py": 15})              # slice S1: +5 (a.py grows)
    _commit(repo, run, "P1.S2: other", {"b.py": 8})              # slice S2: +8
    _commit(repo, run, "*DOCS* P1: plan", {"docs/p.md": 4})      # phase-level
    _commit(repo, run, "X9: cross thing", {"c.py": 3})           # cross-cutting
    _commit(repo, run, "no key here", {"d.py": 99})              # unattributed

    items = model.items_from_project(doc(
        phases=[phase("P1", slices=[slice_("S1"), slice_("S2")])],
        cross=[x("X9")]))

    idx = stats.build_index(repo, items)

    # slice S1: two commits touching a.py only
    assert idx["P1.S1"].commits == 2
    assert idx["P1.S1"].files == 1
    assert idx["P1.S1"].added == 15      # 10 + 5

    # slice S2: one commit
    assert idx["P1.S2"].commits == 1
    assert idx["P1.S2"].added == 8

    # cross-cutting
    assert idx["X9"].commits == 1
    assert idx["X9"].added == 3

    # phase rolls up its slices + its own phase-level commit (4 commits, not the
    # unattributed one), de-duplicated, with the union of files.
    assert idx["P1"].commits == 4        # S1(2) + S2(1) + P1-level(1)
    assert idx["P1"].files == 3          # a.py, b.py, docs/p.md
    assert idx["P1"].added == 27         # 15 + 8 + 4

    # the unattributed commit appears nowhere
    assert all(s.commits >= 1 for s in idx.values())


def test_noise_files_excluded_from_line_counts(tmp_path):
    repo, run = _repo(tmp_path)
    _commit(repo, run, "P1.S1: real work + lockfile churn",
            {"src/x.ts": 5, "package-lock.json": 5000, "docs/tasklist.json": 800})
    items = model.items_from_project(
        doc(phases=[phase("P1", slices=[slice_("S1")])]))
    idx = stats.build_index(repo, items)
    assert idx["P1.S1"].added == 5       # only the real file counts
    assert idx["P1.S1"].files == 1


def test_lines_property():
    assert stats.ItemStats(commits=1, added=10, removed=4).lines == 14


def test_empty_repo_degrades_gracefully(tmp_path):
    repo, _ = _repo(tmp_path)
    items = model.items_from_project(doc(phases=[phase("P1")]))
    assert stats.build_index(repo, items) == {}
