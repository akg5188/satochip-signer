#!/usr/bin/env python3
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


DEFAULT_SCAN_ROOTS = ("/opt/src", "/opt/pi-signer-py")
IGNORED_SOURCE_SNAPSHOT_REL_PATHS = {
    "seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/resources/offline-signer-firmware-integrity.json",
}
IGNORED_RUNTIME_PARTS = {"__pycache__"}
IGNORED_RUNTIME_SUFFIXES = (".pyc", ".pyo", ".swp", ".tmp", ".bak", "~")
IGNORED_RUNTIME_PREFIXES = ("/var/run/", "/run/", "/tmp/", "/var/tmp/", "/app-assets/")
IGNORED_RUNTIME_EXACT_PATHS = {
    "/opt/src/seedsigner/resources/offline-signer-firmware-integrity.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as infile:
        for chunk in iter(lambda: infile.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_tree_sha(file_entries: list[dict]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(file_entries, key=lambda item: item["path"]):
        digest.update(f'{entry["sha256"]}  {entry["path"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def compute_source_snapshot_tree_sha(repo_root: Path) -> str:
    snapshot_rel = "seedsigner-os/opt/rootfs-overlay/opt"
    snapshot_dir = repo_root / snapshot_rel
    if not snapshot_dir.is_dir():
        return ""

    proc = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--", snapshot_rel],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return ""

    digest = hashlib.sha256()
    for rel_bytes in proc.stdout.split(b"\0"):
        if not rel_bytes:
            continue
        rel_path = rel_bytes.decode("utf-8")
        if rel_path in IGNORED_SOURCE_SNAPSHOT_REL_PATHS:
            continue
        file_path = repo_root / rel_path
        if not file_path.is_file():
            continue
        inner_rel_path = file_path.relative_to(snapshot_dir).as_posix()
        digest.update(f"{sha256_file(file_path)}  ./{inner_rel_path}\n".encode("utf-8"))
    return digest.hexdigest()


def is_ignored_runtime_path(runtime_path: str) -> bool:
    pure_path = Path(runtime_path)
    if runtime_path in IGNORED_RUNTIME_EXACT_PATHS:
        return True
    if any(runtime_path == prefix[:-1] or runtime_path.startswith(prefix) for prefix in IGNORED_RUNTIME_PREFIXES):
        return True
    if any(part in IGNORED_RUNTIME_PARTS for part in pure_path.parts):
        return True
    return pure_path.name.endswith(IGNORED_RUNTIME_SUFFIXES)


def build_manifest_payload(
    overlay_root: Path,
    repo_head: str,
    build_commit_time: str,
    build_time_utc: str,
    source_snapshot_tree_sha256: str,
    exclude_rel_paths: set[str],
) -> dict:
    files = []
    for file_path in sorted(overlay_root.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(overlay_root).as_posix()
        if rel_path in exclude_rel_paths:
            continue
        runtime_path = f"/{rel_path}"
        if is_ignored_runtime_path(runtime_path):
            continue
        files.append(
            {
                "path": runtime_path,
                "sha256": sha256_file(file_path),
                "size": file_path.stat().st_size,
            }
        )

    scan_roots = [
        scan_root
        for scan_root in DEFAULT_SCAN_ROOTS
        if any(
            entry["path"] == scan_root or entry["path"].startswith(f"{scan_root}/")
            for entry in files
        )
    ]

    return {
        "manifest_format_version": 1,
        "firmware_name": "离线签名器",
        "generated_by": "scripts/write_runtime_firmware_manifest.py",
        "repo_head": repo_head or "unknown",
        "build_commit_time": build_commit_time or "",
        "build_time_utc": build_time_utc or "",
        "source_snapshot_tree_sha256": source_snapshot_tree_sha256 or "",
        "overlay_file_tree_sha256": compute_tree_sha(files),
        "verified_file_count": len(files),
        "scan_roots": scan_roots,
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--overlay-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repo-head", default="unknown")
    parser.add_argument("--build-commit-time", default="")
    parser.add_argument("--build-time-utc", default="")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    overlay_root = Path(args.overlay_root).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    exclude_rel_paths = set()
    try:
        exclude_rel_paths.add(output_path.relative_to(overlay_root).as_posix())
    except ValueError:
        pass

    payload = build_manifest_payload(
        overlay_root=overlay_root,
        repo_head=args.repo_head,
        build_commit_time=args.build_commit_time,
        build_time_utc=args.build_time_utc,
        source_snapshot_tree_sha256=compute_source_snapshot_tree_sha(repo_root),
        exclude_rel_paths=exclude_rel_paths,
    )

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
