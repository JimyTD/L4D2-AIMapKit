"""Fail if any tracked file mentions a project-specific keyword.

This repository is public and must stay free of any concrete map project's
content. Keywords are listed one per line in tools/forbidden.local.txt, which
is git-ignored so the sensitive words themselves never get committed.

Usage:
    python tools/check_clean.py            # scan tracked + staged files
    python tools/check_clean.py --install  # install as a git pre-commit hook
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS = ROOT / "tools" / "forbidden.local.txt"
HOOK = ROOT / ".git" / "hooks" / "pre-commit"


def load_words() -> list[str]:
    if not WORDS.exists():
        sys.exit(f"missing {WORDS.relative_to(ROOT)}: create it with one forbidden keyword per line")
    words = []
    for line in WORDS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(line)
    return words


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z", "--cached"], cwd=ROOT, capture_output=True, check=True)
    names = [n for n in out.stdout.decode("utf-8").split("\0") if n]
    return [ROOT / n for n in names if (ROOT / n).is_file()]


def main() -> int:
    if "--install" in sys.argv:
        HOOK.write_text('#!/bin/sh\nexec python tools/check_clean.py\n', encoding="ascii", newline="\n")
        print(f"installed {HOOK.relative_to(ROOT)}")
        return 0
    words = load_words()
    lowered = [w.lower() for w in words]
    hits = []
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            for word, w in zip(words, lowered):
                if w in low:
                    hits.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}: [{word}] {line.strip()[:120]}")
    if hits:
        print("project-specific content found; remove it before committing:")
        print("\n".join(hits))
        return 1
    print(f"clean: {len(lowered)} keywords, {len(tracked_files())} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
