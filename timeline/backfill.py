#!/usr/bin/env python3
"""Run-once legacy backfill: migrate pre-tasktool archive markdown into the
canonical 'Full phase JSON' blocks so timeline.py never needs legacy parsing.

Dry-run by default (prints a unified diff); --write applies. Never invoked by
timeline.py.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/
    from timeline import extract
else:
    from . import extract

_PHASE_HEAD_RE = re.compile(
    r"^# (P\d+)\s+[—-]\s+(.+?)\s+✅\s+`?DONE (\d{4}-\d{2}-\d{2})`?", re.M)
_SLICE_HEAD_RE = re.compile(
    r"^## (S\d+)\s+[—-]\s+(.+?)\s+✅\s+`DONE (\d{4}-\d{2}-\d{2})`", re.M)
_MENTION_RE = re.compile(r"\b[pP](\d{1,2})(?:[.\-]?[sS](\d{1,2}))?\b")


@dataclass
class LegacySlice:
    sid: str
    title: str
    closed: str


@dataclass
class LegacyPhase:
    phase_id: str
    title: str
    closed: str
    slices: list


def parse_legacy(text):
    """Parse a pure-legacy archive markdown file. None if not legacy format."""
    head = _PHASE_HEAD_RE.search(text)
    if not head:
        return None
    slices = [LegacySlice(m.group(1), m.group(2), m.group(3))
              for m in _SLICE_HEAD_RE.finditer(text)]
    return LegacyPhase(head.group(1), head.group(2), head.group(3), slices)


def first_mentions(subjects):
    """subjects: iterable of (ts, subject). -> {key: first_ts} where key is
    'P<n>' or 'P<n>.S<m>'. A phase's first mention is the earliest of its own
    and any of its slices' mentions."""
    first = {}
    for ts, subject in subjects:
        for m in _MENTION_RE.finditer(subject):
            pid = f"P{m.group(1)}"
            keys = [pid]
            if m.group(2):
                keys.append(f"{pid}.S{int(m.group(2))}")
            for key in keys:
                if key not in first or ts < first[key]:
                    first[key] = ts
    return first


def commit_subjects(repo):
    out = extract.git(repo, "log", "--reverse", "--format=%ct%x01%s")
    pairs = []
    for line in out.splitlines():
        if "\x01" in line:
            ts, subject = line.split("\x01", 1)
            pairs.append((int(ts), subject))
    return pairs


_BLOCK_RE = re.compile(r"(^## Full phase JSON.*?^```json\n)(.*?)(^```)",
                       re.S | re.M)


def _json_block(text):
    m = _BLOCK_RE.search(text)
    return m.group(2) if m else None


def _ts_to_date(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _phase_closes(blocks, legacy):
    """{phase_id: closed_date} across every known source, for the
    sequential-era cross-check."""
    closes = {}
    for text in blocks.values():
        try:
            block = json.loads(_json_block(text))
        except (json.JSONDecodeError, TypeError):
            continue
        for p in block.get("phases", []):
            if p.get("closed"):
                closes[p["id"]] = p["closed"]
    for parsed in legacy.values():
        closes.setdefault(parsed.phase_id, parsed.closed)
    return closes


def _clamp_start(pid, mined_date, closes):
    """Sequential-era cross-check: a mined start earlier than the previous
    phase's close is mention noise (an early commit referencing the ID in
    passing). Clamp to the latest close among lower-numbered phases."""
    n = int(pid.split(".")[0][1:])
    prior = [d for p, d in closes.items() if int(p[1:]) < n and d]
    if prior:
        prev_close = max(prior)
        if mined_date < prev_close:
            return prev_close
    return mined_date


def plan_rewrites(root, mentions):
    """-> list of (path, new_text) for tasktool archive files whose phase has a
    matching legacy file. Fills empty slices arrays and null started fields
    (mined starts cross-checked against the previous phase close); never
    overwrites a present value."""
    arch = Path(root) / "docs" / "archived-tasks"
    files = sorted(arch.glob("*.md")) if arch.is_dir() else []
    legacy = {}
    blocks = {}
    for f in files:
        text = f.read_text()
        if _json_block(text) is not None:
            blocks[f] = text
        else:
            parsed = parse_legacy(text)
            if parsed:
                legacy[parsed.phase_id] = parsed
    closes = _phase_closes(blocks, legacy)

    changes = []
    for f, text in blocks.items():
        raw = _json_block(text)
        try:
            block = json.loads(raw)
        except json.JSONDecodeError:
            print(f"backfill: {f.name}: unparseable JSON block, skipped",
                  file=sys.stderr)
            continue
        dirty = False
        for p in block.get("phases", []):
            source = legacy.get(p["id"])
            if not p.get("slices") and source and source.slices:
                p["slices"] = [{
                    "blocked_on": None, "closed": s.closed, "created": None,
                    "id": s.sid, "notes": "", "plan_path": None, "refs": [],
                    "reviewer_chain": None, "started": None, "status": "done",
                    "tasks": [], "title": s.title,
                } for s in source.slices]
                dirty = True
            for obj, key in [(p, p["id"])] + [
                    (s, f"{p['id']}.{s['id']}") for s in p.get("slices", [])]:
                if not obj.get("started") and key in mentions:
                    candidate = _clamp_start(
                        key, _ts_to_date(mentions[key]), closes)
                    if obj.get("closed") and candidate > obj["closed"]:
                        continue  # never fill a start past the item's close
                    obj["started"] = candidate
                    dirty = True
        if dirty:
            new_raw = json.dumps(block, indent=2, sort_keys=True,
                                 ensure_ascii=False) + "\n"
            new_text = _BLOCK_RE.sub(
                lambda m: m.group(1) + new_raw + m.group(3), text, count=1)
            changes.append((f, new_text))
    return changes


def run(root, mentions=None, write=False):
    if mentions is None:
        mentions = first_mentions(commit_subjects(root))
    changes = plan_rewrites(root, mentions)
    if not changes:
        print("backfill: nothing to do")
        return
    for path, new_text in changes:
        old = path.read_text()
        diff = difflib.unified_diff(
            old.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=str(path), tofile=f"{path} (backfilled)")
        sys.stdout.writelines(diff)
        if write:
            path.write_text(new_text)
    verb = "wrote" if write else "would change (dry run; use --write)"
    print(f"backfill: {verb} {len(changes)} file(s)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--write", action="store_true",
                    help="apply changes (default: dry-run diff)")
    args = ap.parse_args(argv)
    root = extract.repo_root(args.repo)
    run(root, write=args.write)


if __name__ == "__main__":
    main()
