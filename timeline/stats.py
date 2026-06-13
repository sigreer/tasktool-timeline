"""Per-item work-magnitude stats derived from git history.

Attributes commits, line changes, and files-touched to each timeline item by
matching tasktool item keys (``P25``, ``P25.S2``, ``X72``) in commit subjects —
the near-universal convention in tasktool projects (in multistore, ~93% of
commit subjects carry such a key). Phase stats roll up their slices' commits
(de-duplicated) plus any phase-level commits.

The numbers are meant to convey *scale of effort* to a non-technical reader, so
machine-generated churn that would distort that impression — lock files, build
output, minified bundles, and the tracker's own ``docs/tasklist.json`` /
archived-task bookkeeping — is excluded from the line counts. Binary files
(which git cannot line-count) are skipped.

Pure stdlib + git. Read-only; never mutates the repo.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Item-key references in a commit subject. Case-insensitive, and tolerant of the
# branch-slug form ("p25-s1") that merge subjects sometimes carry; both normalize
# to the canonical dotted upper form ("P25.S1"). A slice reference greedily
# includes its ".S<n>" so a slice commit attributes to the slice, not the phase —
# the phase still picks it up through the slice during roll-up.
_KEY_RE = re.compile(r"(?i)(?<![\w.])([px]\d+(?:[.\-]s\d+)?)(?![\w])")

# Line-count noise: machine-generated or bookkeeping paths that would inflate the
# "lines of work" figure without reflecting authored effort.
_NOISE_DIRS = {"node_modules", "dist", "build", ".next", "out", "coverage",
               "vendor", ".yarn", ".pnp", "__pycache__", ".pytest_cache"}
_NOISE_BASENAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock",
                    "composer.lock", "Cargo.lock", "poetry.lock", "Gemfile.lock"}
_NOISE_SUFFIXES = (".lock", ".min.js", ".min.css", ".map", ".snap")
_NOISE_FULL = ("docs/tasklist.json",)               # exact repo-relative path
_NOISE_CONTAINS = ("docs/archived-tasks/",)         # substring anywhere in path


def normalize_key(raw: str) -> str:
    return raw.upper().replace("-", ".")


def extract_keys(subject: str) -> set:
    return {normalize_key(m) for m in _KEY_RE.findall(subject)}


def is_noise_path(path: str) -> bool:
    if path in _NOISE_FULL or any(path.endswith("/" + f) for f in _NOISE_FULL):
        return True
    if any(c in path for c in _NOISE_CONTAINS):
        return True
    parts = path.split("/")
    if parts[-1] in _NOISE_BASENAMES:
        return True
    if any(seg in _NOISE_DIRS for seg in parts[:-1]):
        return True
    return any(path.endswith(suf) for suf in _NOISE_SUFFIXES)


@dataclass
class ItemStats:
    commits: int = 0
    added: int = 0
    removed: int = 0
    files: int = 0

    @property
    def lines(self) -> int:
        return self.added + self.removed


@dataclass
class _Commit:
    sha: str
    keys: frozenset
    added: int = 0
    removed: int = 0
    files: frozenset = field(default_factory=frozenset)


# ASCII control chars as field/record separators — they never appear in subjects.
_REC = "\x01"
_FS = "\x1f"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def collect_commits(repo) -> list:
    """One ``git log --numstat`` pass -> list of _Commit (real commits only).

    Merges are excluded: their combined diff has no numstat, so they would add
    commit count without line signal. Returns [] on any git failure (e.g. an
    empty repo) so stats degrade gracefully rather than breaking rendering.
    """
    proc = _git(repo, "log", "--no-merges", "--numstat",
                f"--format={_REC}%H{_FS}%s")
    if proc.returncode != 0:
        return []
    commits, cur = [], None
    add = rem = 0
    files: set = set()
    for line in proc.stdout.split("\n"):
        if line.startswith(_REC):
            if cur is not None:
                commits.append(_Commit(cur[0], cur[1], add, rem, frozenset(files)))
            sha, _, subject = line[1:].partition(_FS)
            cur, add, rem, files = (sha, frozenset(extract_keys(subject))), 0, 0, set()
        elif line.strip() and cur is not None:
            cols = line.split("\t")
            if len(cols) < 3:
                continue
            a, r, path = cols[0], cols[1], cols[2]
            if a == "-" or r == "-":        # binary file — not line-countable
                continue
            if is_noise_path(path):
                continue
            add += int(a)
            rem += int(r)
            files.add(path)
    if cur is not None:
        commits.append(_Commit(cur[0], cur[1], add, rem, frozenset(files)))
    return commits


def _aggregate(idxs, commits) -> ItemStats:
    added = removed = 0
    files: set = set()
    for i in idxs:
        c = commits[i]
        added += c.added
        removed += c.removed
        files |= c.files
    return ItemStats(len(idxs), added, removed, len(files))


def build_index(repo, items) -> dict:
    """Return {item_key: ItemStats} for every item with attributable commits.

    A slice/cross item gets the commits whose subject references its exact key.
    A phase gets the de-duplicated union of its own phase-level commits and all
    of its slices' commits, so the phase band reflects total effort.
    """
    commits = collect_commits(repo)
    if not commits:
        return {}

    key_to_idxs: dict = {}
    for i, c in enumerate(commits):
        for k in c.keys:
            key_to_idxs.setdefault(k, set()).add(i)

    children: dict = {}
    for it in items:
        if it.kind == "slice" and it.parent:
            children.setdefault(it.parent, []).append(it.key)

    index: dict = {}
    for it in items:
        if it.kind == "phase":
            idxs = set(key_to_idxs.get(it.key, ()))
            for child_key in children.get(it.key, ()):
                idxs |= key_to_idxs.get(child_key, set())
        else:
            idxs = key_to_idxs.get(it.key, set())
        if idxs:
            index[it.key] = _aggregate(idxs, commits)
    return index
