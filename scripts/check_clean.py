"""Fail if any tracked file mentions a project-specific keyword.

This repository is public and must stay free of any concrete map project's content. Keywords are listed
one per line in scripts/forbidden.local.txt, which is git-ignored so the words themselves never get committed.

    python scripts/check_clean.py            # scan tracked and staged files
    python scripts/check_clean.py --install  # install as a git pre-commit hook
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS = ROOT / "scripts" / "forbidden.local.txt"
HOOK = ROOT / ".git" / "hooks" / "pre-commit"


def words() -> list[str]:
    if not WORDS.exists():
        sys.exit(f"missing {WORDS.relative_to(ROOT)}: one forbidden keyword per line")
    return [w.strip() for w in WORDS.read_text(encoding="utf-8").splitlines() if w.strip() and not w.startswith("#")]


def tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z", "--cached"], cwd=ROOT, capture_output=True, check=True)
    return [ROOT / n for n in out.stdout.decode("utf-8").split("\0") if n and (ROOT / n).is_file()]


def main() -> int:
    if "--install" in sys.argv:
        HOOK.write_text("#!/bin/sh\nexec python scripts/check_clean.py\n", encoding="ascii", newline="\n")
        print(f"installed {HOOK.relative_to(ROOT)}")
        return 0
    ws = words()
    low = [w.lower() for w in ws]
    files = tracked()
    hits = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            l = line.lower()
            hits += [f"{p.relative_to(ROOT).as_posix()}:{n}: [{w}] {line.strip()[:120]}" for w, x in zip(ws, low) if x in l]
    if hits:
        print("project-specific content found; remove it before committing:")
        print("\n".join(hits))
        return 1
    print(f"clean: {len(ws)} keywords, {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())

