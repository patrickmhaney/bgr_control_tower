"""Fail if a blocked word appears in tracked files, branch names or commit messages.

    python -m checks.blocked_words              # tracked files and the current branch
    python -m checks.blocked_words --commits    # also every commit message on this branch

The words themselves never live in the repo - a check that spelled them out
would leak them. They come from the BLOCKED_WORDS environment variable
(comma-separated; a CI secret) or an untracked .blocked_words file, one word
per line. Matching is case-insensitive and on word boundaries. With no words
configured the check passes and says so.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

from core.settings import ROOT


def words() -> list[str]:
    raw = os.environ.get("BLOCKED_WORDS", "")
    found = [w.strip() for w in raw.split(",") if w.strip()]
    path = os.path.join(ROOT, ".blocked_words")
    if os.path.exists(path):
        with open(path) as fh:
            found += [line.strip() for line in fh if line.strip() and not line.startswith("#")]
    return found


def found(text: str) -> list[str]:
    """The blocked words in one piece of text, e.g. a new project's name."""
    ws = words()
    if not ws:
        return []
    return sorted({m.group(1).lower() for m in re.finditer(
        r"(?<![a-z0-9])(" + "|".join(map(re.escape, ws)) + r")(?![a-z0-9])", text, re.I)})


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def scan(include_commits: bool = False) -> list[str]:
    ws = words()
    if not ws:
        return []
    pattern = re.compile(r"(?<![a-z0-9])(" + "|".join(map(re.escape, ws)) + r")(?![a-z0-9])", re.I)
    hits = []
    for rel in _git("ls-files").splitlines():
        path = os.path.join(ROOT, rel)
        if pattern.search(rel):
            hits.append(f"path: {rel}")
        try:
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if pattern.search(line):
                        hits.append(f"{rel}:{n}")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    if pattern.search(branch):
        hits.append(f"branch name: {branch}")
    if include_commits:
        base = _git("merge-base", "HEAD", "origin/main").strip() or ""
        rng = f"{base}..HEAD" if base else "HEAD"
        for line in _git("log", "--format=%h %s%n%b", rng).splitlines():
            if pattern.search(line):
                hits.append(f"commit message: {line[:60]}")
    return hits


def main() -> None:
    if not words():
        print("blocked words: none configured (set BLOCKED_WORDS or create .blocked_words)")
        sys.exit(0)
    hits = scan("--commits" in sys.argv)
    for h in hits:
        print(f"blocked word in {h}")
    print("blocked words: ok" if not hits else f"blocked words: {len(hits)} hit(s)")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
