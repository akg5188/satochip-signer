from __future__ import annotations

import hashlib
import sys
from pathlib import Path


OFFICIAL_INFO_URL = "https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki"
OFFICIAL_RAW_URL = "https://raw.githubusercontent.com/bitcoin/bips/master/bip-0039/english.txt"
PINNED_RAW_URL = (
    "https://raw.githubusercontent.com/bitcoin/bips/"
    "805c9b54f6d38f644d1f9c3ce871e2ea3df1f7d8/bip-0039/english.txt"
)
EXPECTED_SHA256 = "2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda"
EXPECTED_COUNT = 2048
EXPECTED_FIRST4 = ["abandon", "ability", "able", "about"]
EXPECTED_LAST4 = ["zebra", "zero", "zone", "zoo"]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_file(path: Path) -> int:
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return 1

    data = path.read_bytes()
    words = path.read_text(encoding="utf-8").splitlines()
    digest = sha256_hex(data)

    ok = True

    print(f"File: {path}")
    print(f"Official info: {OFFICIAL_INFO_URL}")
    print(f"Official raw: {OFFICIAL_RAW_URL}")
    print(f"Pinned raw: {PINNED_RAW_URL}")
    print()
    print(f"SHA256 actual   : {digest}")
    print(f"SHA256 expected : {EXPECTED_SHA256}")
    print(f"Line count      : {len(words)} / expected {EXPECTED_COUNT}")
    print(f"First 4 words   : {words[:4]}")
    print(f"Last 4 words    : {words[-4:]}")

    if digest != EXPECTED_SHA256:
        print("FAIL: sha256 mismatch")
        ok = False
    if len(words) != EXPECTED_COUNT:
        print("FAIL: line count mismatch")
        ok = False
    if words[:4] != EXPECTED_FIRST4:
        print("FAIL: first words mismatch")
        ok = False
    if words[-4:] != EXPECTED_LAST4:
        print("FAIL: last words mismatch")
        ok = False

    if ok:
        print("VERIFICATION OK")
        return 0

    print("VERIFICATION FAILED")
    return 2


def main() -> int:
    if len(sys.argv) > 2:
        print("Usage: python3 verify_bip39_wordlist.py [path/to/english.txt]")
        return 1

    if len(sys.argv) == 2:
        target = Path(sys.argv[1]).expanduser().resolve()
    else:
        target = Path(__file__).resolve().parent / "bip39_english.txt"

    return verify_file(target)


if __name__ == "__main__":
    raise SystemExit(main())
