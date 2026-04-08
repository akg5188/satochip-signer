#!/usr/bin/env python3
import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


API_BASE = "https://api.github.com"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def github_request(
    method: str,
    url: str,
    token: str,
    data: bytes | None = None,
    content_type: str = "application/json",
):
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", content_type)
        request.add_header("Content-Length", str(len(data)))
    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read()
            if not payload:
                return None
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        fail(f"{method} {url} failed: {error.code} {detail}")


def load_release_by_tag(owner_repo: str, tag: str, token: str):
    url = f"{API_BASE}/repos/{owner_repo}/releases/tags/{urllib.parse.quote(tag)}"
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        detail = error.read().decode("utf-8", errors="replace")
        fail(f"GET {url} failed: {error.code} {detail}")


def ensure_release(owner_repo: str, tag: str, title: str, body: str, token: str):
    existing = load_release_by_tag(owner_repo, tag, token)
    payload = {
        "tag_name": tag,
        "name": title,
        "body": body,
        "draft": False,
        "prerelease": False,
        "make_latest": "true",
    }
    if existing is None:
        url = f"{API_BASE}/repos/{owner_repo}/releases"
        return github_request("POST", url, token, json.dumps(payload).encode("utf-8"))

    release_id = existing["id"]
    url = f"{API_BASE}/repos/{owner_repo}/releases/{release_id}"
    return github_request("PATCH", url, token, json.dumps(payload).encode("utf-8"))


def delete_asset(owner_repo: str, asset_id: int, token: str) -> None:
    url = f"{API_BASE}/repos/{owner_repo}/releases/assets/{asset_id}"
    github_request("DELETE", url, token, data=b"")


def upload_asset(upload_url: str, asset_path: str, token: str) -> None:
    asset_name = os.path.basename(asset_path)
    base_url = upload_url.split("{", 1)[0]
    url = f"{base_url}?name={urllib.parse.quote(asset_name)}"
    with open(asset_path, "rb") as handle:
        payload = handle.read()
    content_type = mimetypes.guess_type(asset_name)[0] or "application/octet-stream"
    request = urllib.request.Request(url, data=payload, method="POST")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("Content-Type", content_type)
    request.add_header("Content-Length", str(len(payload)))
    try:
        with urllib.request.urlopen(request) as response:
            response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        fail(f"upload asset {asset_name} failed: {error.code} {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or update a GitHub release and upload assets."
    )
    parser.add_argument("tag", help="Git tag to publish")
    parser.add_argument("title", help="Release title")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", "akg5188/satochip-signer"),
        help="owner/repo, defaults to GITHUB_REPOSITORY or akg5188/satochip-signer",
    )
    parser.add_argument(
        "--body-file",
        help="Markdown file used as the release body",
    )
    parser.add_argument(
        "assets",
        nargs="*",
        help="Files to upload as release assets",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        fail("Set GITHUB_TOKEN or GH_TOKEN before running this script.")

    for asset in args.assets:
        if not os.path.isfile(asset):
            fail(f"Asset not found: {asset}")

    body = ""
    if args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as handle:
            body = handle.read()

    release = ensure_release(args.repo, args.tag, args.title, body, token)
    upload_url = release["upload_url"]
    existing_assets = {asset["name"]: asset for asset in release.get("assets", [])}

    for asset_path in args.assets:
        asset_name = os.path.basename(asset_path)
        existing = existing_assets.get(asset_name)
        if existing is not None:
            delete_asset(args.repo, existing["id"], token)
        upload_asset(upload_url, asset_path, token)
        print(f"uploaded {asset_name}")

    print(f"release_ready tag={args.tag}")


if __name__ == "__main__":
    main()
