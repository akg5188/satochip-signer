import hashlib
import json
from pathlib import Path, PurePosixPath


DEFAULT_MANIFEST_PATH = Path("/opt/src/seedsigner/resources/offline-signer-firmware-integrity.json")
DEFAULT_SCAN_ROOTS = ("/opt/src", "/opt/pi-signer-py")
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


def _is_ignored_runtime_path(runtime_path: str) -> bool:
    pure_path = PurePosixPath(runtime_path)
    if runtime_path in IGNORED_RUNTIME_EXACT_PATHS:
        return True
    if any(runtime_path == prefix[:-1] or runtime_path.startswith(prefix) for prefix in IGNORED_RUNTIME_PREFIXES):
        return True
    if any(part in IGNORED_RUNTIME_PARTS for part in pure_path.parts):
        return True
    return pure_path.name.endswith(IGNORED_RUNTIME_SUFFIXES)


def _compute_tree_sha(file_entries: list[dict]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(file_entries, key=lambda item: item["path"]):
        digest.update(f'{entry["sha256"]}  {entry["path"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def build_manifest_payload(
    overlay_root: str | Path,
    repo_head: str = "unknown",
    build_commit_time: str = "",
    build_time_utc: str = "",
    source_snapshot_tree_sha256: str = "",
    exclude_rel_paths: set[str] | None = None,
) -> dict:
    overlay_root = Path(overlay_root)
    exclude_rel_paths = exclude_rel_paths or set()

    files = []
    for file_path in sorted(overlay_root.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(overlay_root).as_posix()
        if rel_path in exclude_rel_paths:
            continue
        runtime_path = f"/{rel_path}"
        if _is_ignored_runtime_path(runtime_path):
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
        "overlay_file_tree_sha256": _compute_tree_sha(files),
        "verified_file_count": len(files),
        "scan_roots": scan_roots,
        "files": files,
    }


def load_manifest(manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> dict:
    manifest_path = Path(manifest_path)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def verify_runtime_manifest(manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> dict:
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        return {
            "supported": False,
            "ok": False,
            "status": "missing-manifest",
            "manifest_path": str(manifest_path),
            "error": "当前固件还没有内置完整性清单，请刷新到最新正式版后再试。",
        }

    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        return {
            "supported": False,
            "ok": False,
            "status": "invalid-manifest",
            "manifest_path": str(manifest_path),
            "error": f"完整性清单读取失败: {exc}",
        }

    files = manifest.get("files") or []
    expected = {
        entry["path"]: entry
        for entry in files
        if entry.get("path") and not _is_ignored_runtime_path(entry["path"])
    }
    missing = []
    modified = []
    unexpected = []
    errors = []
    actual_entries = []

    for runtime_path, entry in expected.items():
        file_path = Path(runtime_path)
        if not file_path.exists():
            missing.append({"path": runtime_path})
            continue
        if not file_path.is_file():
            errors.append({"path": runtime_path, "error": "不是普通文件"})
            continue
        try:
            actual_sha = sha256_file(file_path)
        except Exception as exc:
            errors.append({"path": runtime_path, "error": str(exc)})
            continue

        actual_entries.append({"path": runtime_path, "sha256": actual_sha})
        if actual_sha != entry.get("sha256"):
            modified.append(
                {
                    "path": runtime_path,
                    "expected_sha256": entry.get("sha256", ""),
                    "actual_sha256": actual_sha,
                }
            )

    for scan_root in manifest.get("scan_roots") or []:
        root_path = Path(scan_root)
        if not root_path.is_dir():
            continue
        for file_path in sorted(root_path.rglob("*")):
            if not file_path.is_file():
                continue
            runtime_path = "/" + file_path.relative_to(Path("/")).as_posix()
            if _is_ignored_runtime_path(runtime_path):
                continue
            if runtime_path not in expected:
                unexpected.append({"path": runtime_path})

    current_tree_sha256 = _compute_tree_sha(actual_entries)
    ok = not missing and not modified and not unexpected and not errors
    effective_expected_entries = [
        {"path": runtime_path, "sha256": entry.get("sha256", "")}
        for runtime_path, entry in sorted(expected.items())
    ]
    expected_tree_sha256 = _compute_tree_sha(effective_expected_entries)
    manifest_tree_sha256 = manifest.get("overlay_file_tree_sha256", "")
    if expected_tree_sha256 and current_tree_sha256 != expected_tree_sha256:
        ok = False

    return {
        "supported": True,
        "ok": ok,
        "status": "ok" if ok else "mismatch",
        "manifest_path": str(manifest_path),
        "repo_head": manifest.get("repo_head", ""),
        "build_commit_time": manifest.get("build_commit_time", ""),
        "build_time_utc": manifest.get("build_time_utc", ""),
        "source_snapshot_tree_sha256": manifest.get("source_snapshot_tree_sha256", ""),
        "expected_overlay_file_tree_sha256": expected_tree_sha256,
        "manifest_overlay_file_tree_sha256": manifest_tree_sha256,
        "current_overlay_file_tree_sha256": current_tree_sha256,
        "verified_file_count": manifest.get("verified_file_count", len(expected)),
        "missing": missing,
        "modified": modified,
        "unexpected": unexpected,
        "errors": errors,
    }
