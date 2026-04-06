#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


MANIFEST_NAME = "钛板工具包_SHA256SUMS.txt"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_manifest(path: Path) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"无法解析 manifest 行: {raw_line!r}")
        digest, rel_path = parts
        items.append((digest.lower(), rel_path.strip()))
    return items


def main() -> int:
    base = Path(__file__).resolve().parent
    manifest_path = base / MANIFEST_NAME

    if not manifest_path.exists():
        print(f"缺少 {MANIFEST_NAME}", file=sys.stderr)
        return 1

    try:
        entries = parse_manifest(manifest_path)
    except Exception as exc:
        print(f"解析 {MANIFEST_NAME} 失败: {exc}", file=sys.stderr)
        return 1

    ok = True
    tracked = set()

    for expected, rel_path in entries:
        tracked.add(rel_path)
        target = base / rel_path
        if not target.exists():
            ok = False
            print(f"MISSING  {rel_path}")
            continue

        actual = sha256_file(target)
        if actual != expected:
            ok = False
            print(f"MISMATCH {rel_path}")
            print(f"  expected: {expected}")
            print(f"  actual:   {actual}")
        else:
            print(f"OK       {rel_path}")

    current_files = {
        p.name for p in base.iterdir() if p.is_file() and p.name != MANIFEST_NAME
    }
    untracked = sorted(current_files - tracked)
    stale = sorted(tracked - current_files)

    for rel_path in untracked:
        ok = False
        print(f"UNTRACKED {rel_path}")

    for rel_path in stale:
        ok = False
        print(f"STALE    {rel_path}")

    if not ok:
        print("\nTOOLKIT VERIFICATION FAILED", file=sys.stderr)
        return 1

    print("\nTOOLKIT VERIFICATION OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
