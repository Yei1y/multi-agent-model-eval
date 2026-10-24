#!/usr/bin/env python
"""Lightweight README self-check: local paths and heading anchors.

Matches the check recommended by the readme-craft skill. External URLs are
ignored; this script only verifies that repository-relative links resolve and
that in-page anchors point at existing headings.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def slug(heading: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", heading.strip().lower(), flags=re.UNICODE)
    return cleaned.replace(" ", "-")


def main() -> int:
    if not README.exists():
        print("README.md not found")
        return 1
    md = README.read_text(encoding="utf-8")
    targets = set(re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", md))
    targets |= set(re.findall(r'src="([^"]+)"', md))
    missing = [
        target
        for target in sorted(targets)
        if not target.startswith(("http", "#"))
        and not (ROOT / target.split("#")[0]).exists()
    ]
    headings = [
        slug(match) for match in re.findall(r"^#{2,3}\s+(.+)$", md, flags=re.MULTILINE)
    ]
    anchors = re.findall(r"\]\(#([^)]+)\)", md)
    broken = [anchor for anchor in anchors if anchor not in headings]

    print("missing paths:", missing or "none")
    print("broken anchors:", broken or "none")
    return 1 if missing or broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
