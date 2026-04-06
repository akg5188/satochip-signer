#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path


MANIFEST_NAME = "钛板工具包_SHA256SUMS.txt"
SELF_NAME = "refresh_titanium_manifest.py"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    base = Path(__file__).resolve().parent
    manifest_path = base / MANIFEST_NAME

    files = sorted(
        p.name
        for p in base.iterdir()
        if p.is_file() and p.name != MANIFEST_NAME
    )

    lines = [
        "# 钛板工具包完整文件 SHA-256 清单",
        "# 生成日期: 2026-04-06",
        "# 使用前可运行: python3 verify_titanium_backup_kit.py",
        f"# 如有新增、删除或更新文件，可运行: python3 {SELF_NAME}",
        "",
    ]

    for name in files:
        lines.append(f"{sha256_file(base / name)}  {name}")

    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Refreshed: {manifest_path}")
    print(f"Tracked files: {len(files)}")


if __name__ == "__main__":
    main()
