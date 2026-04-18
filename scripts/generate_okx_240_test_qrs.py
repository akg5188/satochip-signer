#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from embit import bip39, bip32, hashes

from seedsigner.helpers.qr import QR
from seedsigner.helpers.ur2.cbor_lite import CBOREncoder, Tag_Major_semantic
from seedsigner.helpers.ur2.ur import UR
from seedsigner.helpers.ur2.ur_encoder import UREncoder


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
DEFAULT_DERIVATION_PATH = "m/44'/60'/0'/0/0"
WEB3_ETH_COIN_TYPE = 0x3C
WEB3_BTC_COIN_TYPE = 0
WEB3_MAINNET_NETWORK = 0
WEB3_OKX_DEVICE_TYPE = "Keystone 3 Pro"
WEB3_KEYSTONE_DEVICE_VERSION = "1.0.4"
SECP256K1_FIELD_PRIME = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F


@dataclass(frozen=True)
class Variant:
    slug: str
    title: str
    note: str
    okx_ledger_live_count: int
    okx_btc_paths: tuple[str, ...]


VARIANTS = [
    Variant(
        slug="okx-lite-84-only",
        title="方案 1: OKX 极简版",
        note="只保留 1 个标准 EVM 账户 + BTC 84'，不再塞额外 OKX EVM 账户。",
        okx_ledger_live_count=0,
        okx_btc_paths=("m/84'/0'/0'",),
    ),
    Variant(
        slug="okx-1-evm-84-only",
        title="方案 2: OKX 折中版",
        note="保留 1 个标准 EVM 账户 + 1 个 OKX Ledger Live EVM 账户 + BTC 84'。",
        okx_ledger_live_count=1,
        okx_btc_paths=("m/84'/0'/0'",),
    ),
]


def normalize_bip32_path(path: str) -> str:
    text = str(path or "").strip().replace("H", "'").replace("h", "'")
    if not text:
        raise ValueError("empty bip32 path")
    if text == "m":
        return text
    if not text.startswith("m/"):
        raise ValueError(f"invalid bip32 path: {path}")
    parts = []
    for segment in text.split("/"):
        if segment == "m":
            parts.append(segment)
            continue
        if segment == "*":
            parts.append(segment)
            continue
        hardened = segment.endswith("'")
        core = segment[:-1] if hardened else segment
        if not core.isdigit():
            raise ValueError(f"invalid bip32 segment: {segment}")
        parts.append(core + ("'" if hardened else ""))
    return "/".join(parts)


def normalize_bip32_relative_path(path: str) -> str:
    text = str(path or "").strip().replace("H", "'").replace("h", "'")
    if not text:
        return ""
    parts = []
    for segment in text.split("/"):
        if segment == "*":
            parts.append(segment)
            continue
        hardened = segment.endswith("'")
        core = segment[:-1] if hardened else segment
        if not core.isdigit():
            raise ValueError(f"invalid bip32 relative segment: {segment}")
        parts.append(core + ("'" if hardened else ""))
    return "/".join(parts)


def split_evm_account_path(derivation_path: str) -> tuple[str, str]:
    normalized_path = normalize_bip32_path(derivation_path)
    parts = normalized_path.split("/")
    if len(parts) < 6:
        raise ValueError("EVM path must reach the address level")
    account_path = "/".join(parts[:4])
    branch = parts[4].rstrip("'")
    children_path = f"{int(branch)}/*"
    return account_path, children_path


def web3_path_depth(path: str) -> int:
    return len([segment for segment in normalize_bip32_path(path).split("/")[1:] if segment])


def web3_evm_coin_path(derivation_path: str) -> str:
    parts = normalize_bip32_path(derivation_path).split("/")
    return "/".join(parts[:3])


def web3_pubkey_fingerprint(pubkey: bytes) -> str:
    return hashes.hash160(pubkey)[:4].hex()


def to_uncompressed_secp256k1_pubkey(pubkey: bytes) -> bytes:
    if len(pubkey) == 65 and pubkey[0] == 0x04:
        return pubkey
    if len(pubkey) == 33 and pubkey[0] in (0x02, 0x03):
        x = int.from_bytes(pubkey[1:], "big")
        y_squared = (pow(x, 3, SECP256K1_FIELD_PRIME) + 7) % SECP256K1_FIELD_PRIME
        y = pow(y_squared, (SECP256K1_FIELD_PRIME + 1) // 4, SECP256K1_FIELD_PRIME)
        if (y & 1) != (pubkey[0] & 1):
            y = SECP256K1_FIELD_PRIME - y
        return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")
    raise ValueError("unsupported secp256k1 key format")


def keccak256(data: bytes) -> bytes:
    from Crypto.Hash import keccak

    digest = keccak.new(digest_bits=256)
    digest.update(data)
    return digest.digest()


def to_eip55_address(address_hex: str) -> str:
    normalized = address_hex.lower().removeprefix("0x")
    checksum = keccak256(normalized.encode("ascii")).hex()
    encoded = "".join(
        char.upper() if char in "abcdef" and int(checksum[index], 16) >= 8 else char
        for index, char in enumerate(normalized)
    )
    return f"0x{encoded}"


def derive_evm_address_from_pubkey_bytes(pubkey: bytes) -> str:
    uncompressed_pubkey = to_uncompressed_secp256k1_pubkey(pubkey)
    return to_eip55_address(keccak256(uncompressed_pubkey[1:])[-20:].hex())


def web3_key_entry(
    *,
    pubkey_hex: str,
    origin_path: str,
    parent_fingerprint: str | None,
    note: str,
    chain_code_hex: str | None = None,
    children_path: str | None = None,
    children_depth: int | None = None,
    origin_depth: int | None = None,
    coin_type: int | None = None,
    network: int | None = None,
) -> dict:
    return {
        "compressedPubKeyHex": str(pubkey_hex),
        "chainCodeHex": str(chain_code_hex or ""),
        "originPath": normalize_bip32_path(origin_path),
        "originDepth": origin_depth if origin_depth is not None else web3_path_depth(origin_path),
        "parentFingerprint": str(parent_fingerprint or "").strip().lower(),
        "childrenPath": str(children_path or "").strip(),
        "childrenDepth": children_depth,
        "name": "Keystone",
        "note": str(note),
        "coinType": coin_type,
        "network": network,
    }


def web3_valid_fingerprint(value: str | None) -> str | None:
    fingerprint = str(value or "").strip().lower()
    return fingerprint if re.fullmatch(r"[0-9a-f]{8}", fingerprint) else None


def encode_web3_keypath_bytes(path: str, source_fingerprint_hex: str | None = None, depth: int | None = None) -> bytes:
    text = str(path or "").strip()
    if text == "m" or text.startswith("m/"):
        parts = [segment for segment in normalize_bip32_path(text).split("/")[1:] if segment]
    else:
        parts = [segment for segment in normalize_bip32_relative_path(text).split("/") if segment]
    components = []
    for segment in parts:
        if segment == "*":
            components.append((None, False))
            continue
        hardened = segment.endswith("'")
        index = int(segment.rstrip("'"))
        components.append((index, hardened))

    encoder = CBOREncoder()
    field_count = 1
    if source_fingerprint_hex:
        field_count += 1
    if depth is not None:
        field_count += 1
    encoder.encodeMapSize(field_count)
    encoder.encodeUnsigned(1)
    encoder.encodeArraySize(len(components) * 2)
    for index, hardened in components:
        if index is None:
            encoder.encodeArraySize(0)
        else:
            encoder.encodeUnsigned(index)
        encoder.encodeBool(hardened)
    if source_fingerprint_hex:
        encoder.encodeUnsigned(2)
        encoder.encodeUnsigned(int(source_fingerprint_hex, 16))
    if depth is not None:
        encoder.encodeUnsigned(3)
        encoder.encodeUnsigned(depth)
    return bytes(encoder.get_bytes())


def encode_web3_coin_info_bytes(coin_type: int | None = None, network: int | None = None) -> bytes | None:
    if coin_type is None and network is None:
        return None
    encoder = CBOREncoder()
    field_count = 0
    if coin_type is not None:
        field_count += 1
    if network is not None:
        field_count += 1
    encoder.encodeMapSize(field_count)
    if coin_type is not None:
        encoder.encodeUnsigned(1)
        encoder.encodeUnsigned(int(coin_type))
    if network is not None:
        encoder.encodeUnsigned(2)
        encoder.encodeUnsigned(int(network))
    return bytes(encoder.get_bytes())


def hex_to_bytes(value: str) -> bytes:
    return bytes.fromhex(str(value or "").strip())


def build_web3_hdkey_entry_cbor_bytes(entry: dict, master_fingerprint: str | None, include_children: bool) -> bytes:
    compressed_pubkey = hex_to_bytes(entry["compressedPubKeyHex"])
    chain_code_hex = str(entry.get("chainCodeHex") or "").strip()
    chain_code = hex_to_bytes(chain_code_hex) if chain_code_hex else b""
    origin_path = str(entry["originPath"])
    children_path = str(entry.get("childrenPath") or "").strip()
    parent_fingerprint = web3_valid_fingerprint(str(entry.get("parentFingerprint") or ""))
    coin_info_cbor = encode_web3_coin_info_bytes(
        coin_type=entry.get("coinType"),
        network=entry.get("network"),
    )
    name = str(entry.get("name") or "Keystone")
    note = str(entry.get("note") or "")

    origin_cbor = encode_web3_keypath_bytes(origin_path, source_fingerprint_hex=master_fingerprint)
    children_cbor = None
    if include_children and children_path:
        children_cbor = encode_web3_keypath_bytes(children_path)

    encoder = CBOREncoder()
    field_count = 3
    if chain_code:
        field_count += 1
    if coin_info_cbor is not None:
        field_count += 1
    if children_cbor is not None:
        field_count += 1
    if parent_fingerprint:
        field_count += 1
    if name:
        field_count += 1
    if note:
        field_count += 1
    encoder.encodeMapSize(field_count)
    encoder.encodeUnsigned(2)
    encoder.encodeBool(False)
    encoder.encodeUnsigned(3)
    encoder.encodeBytes(compressed_pubkey)
    if chain_code:
        encoder.encodeUnsigned(4)
        encoder.encodeBytes(chain_code)
    if coin_info_cbor is not None:
        encoder.encodeUnsigned(5)
        encoder.encodeTagAndValue(Tag_Major_semantic, 305)
        encoder.buf += coin_info_cbor
    encoder.encodeUnsigned(6)
    encoder.encodeTagAndValue(Tag_Major_semantic, 304)
    encoder.buf += origin_cbor
    if children_cbor is not None:
        encoder.encodeUnsigned(7)
        encoder.encodeTagAndValue(Tag_Major_semantic, 304)
        encoder.buf += children_cbor
    if parent_fingerprint:
        encoder.encodeUnsigned(8)
        encoder.encodeUnsigned(int(parent_fingerprint, 16))
    if name:
        encoder.encodeUnsigned(9)
        encoder.encodeText(name)
    if note:
        encoder.encodeUnsigned(10)
        encoder.encodeText(note)
    return bytes(encoder.get_bytes())


def build_web3_bitkeep_hdkey_entry_cbor_bytes(entry: dict, master_fingerprint: str | None) -> bytes:
    compressed_pubkey = hex_to_bytes(entry["compressedPubKeyHex"])
    chain_code_hex = str(entry.get("chainCodeHex") or "").strip()
    chain_code = hex_to_bytes(chain_code_hex) if chain_code_hex else b""
    origin_path = str(entry["originPath"])
    children_path = str(entry.get("childrenPath") or "").strip()
    parent_fingerprint = web3_valid_fingerprint(str(entry.get("parentFingerprint") or ""))
    coin_info_cbor = encode_web3_coin_info_bytes(
        coin_type=entry.get("coinType"),
        network=entry.get("network"),
    )
    name = str(entry.get("name") or "Keystone")
    note = str(entry.get("note") or "")

    origin_cbor = encode_web3_keypath_bytes(
        origin_path,
        source_fingerprint_hex=master_fingerprint,
        depth=entry.get("originDepth"),
    )
    children_cbor = None
    if children_path:
        children_cbor = encode_web3_keypath_bytes(children_path, depth=entry.get("childrenDepth"))

    encoder = CBOREncoder()
    field_count = 3
    if chain_code:
        field_count += 1
    if coin_info_cbor is not None:
        field_count += 1
    if children_cbor is not None:
        field_count += 1
    if parent_fingerprint:
        field_count += 1
    if name:
        field_count += 1
    if note:
        field_count += 1
    encoder.encodeMapSize(field_count)
    encoder.encodeUnsigned(2)
    encoder.encodeBool(False)
    encoder.encodeUnsigned(3)
    encoder.encodeBytes(compressed_pubkey)
    if chain_code:
        encoder.encodeUnsigned(4)
        encoder.encodeBytes(chain_code)
    if coin_info_cbor is not None:
        encoder.encodeUnsigned(5)
        encoder.encodeTagAndValue(Tag_Major_semantic, 305)
        encoder.buf += coin_info_cbor
    encoder.encodeUnsigned(6)
    encoder.encodeTagAndValue(Tag_Major_semantic, 304)
    encoder.buf += origin_cbor
    if children_cbor is not None:
        encoder.encodeUnsigned(7)
        encoder.encodeTagAndValue(Tag_Major_semantic, 304)
        encoder.buf += children_cbor
    if parent_fingerprint:
        encoder.encodeUnsigned(8)
        encoder.encodeUnsigned(int(parent_fingerprint, 16))
    if name:
        encoder.encodeUnsigned(9)
        encoder.encodeText(name)
    if note:
        encoder.encodeUnsigned(10)
        encoder.encodeText(note)
    return bytes(encoder.get_bytes())


def okx_device_id(master_fingerprint: str, address: str, variant_slug: str) -> str:
    serial = f"keystone-desktop-{variant_slug}-{master_fingerprint}-{address.lower()}"
    return hashlib.sha256(hashlib.sha256(serial.encode("utf-8")).digest()).hexdigest()[:40]


def export_web3_account_from_mnemonic(mnemonic: str, derivation_path: str, variant: Variant) -> dict:
    seed_bytes = bip39.mnemonic_to_seed(mnemonic)
    root = bip32.HDKey.from_seed(seed_bytes)
    normalized_path = normalize_bip32_path(derivation_path)
    account_path, children_path = split_evm_account_path(normalized_path)
    evm_coin_path = web3_evm_coin_path(normalized_path)
    account_root = root.derive(account_path)
    parent_path = "/".join(account_path.split("/")[:-1]) or "m"
    parent_root = root.derive(parent_path)
    address_root = root.derive(normalized_path)

    master_fingerprint_hex = bytes(root.my_fingerprint).hex()
    account_pubkey = account_root.key.get_public_key().sec()
    parent_pubkey = parent_root.key.get_public_key().sec()
    address_pubkey = address_root.key.get_public_key().sec()
    address = derive_evm_address_from_pubkey_bytes(address_pubkey)

    okx_ledger_live_entries = []
    for index in range(variant.okx_ledger_live_count):
        ledger_live_path = f"{evm_coin_path}/{index}'/0/0"
        ledger_live_root = root.derive(ledger_live_path)
        live_pubkey = ledger_live_root.key.get_public_key().sec()
        okx_ledger_live_entries.append(
            web3_key_entry(
                pubkey_hex=live_pubkey.hex(),
                origin_path=ledger_live_path,
                origin_depth=web3_path_depth(ledger_live_path),
                parent_fingerprint=None,
                note="account.ledger_live",
            )
        )

    standard_entry = web3_key_entry(
        pubkey_hex=account_pubkey.hex(),
        chain_code_hex=account_root.chain_code.hex(),
        origin_path=account_path,
        origin_depth=web3_path_depth(account_path),
        parent_fingerprint=web3_pubkey_fingerprint(parent_pubkey),
        children_path=children_path,
        children_depth=0,
        note="account.standard",
        coin_type=WEB3_ETH_COIN_TYPE,
        network=WEB3_MAINNET_NETWORK,
    )
    ledger_legacy_entry = web3_key_entry(
        pubkey_hex=account_pubkey.hex(),
        chain_code_hex=account_root.chain_code.hex(),
        origin_path=account_path,
        origin_depth=web3_path_depth(account_path),
        parent_fingerprint=web3_pubkey_fingerprint(parent_pubkey),
        children_path="*",
        children_depth=0,
        note="account.ledger_legacy",
        coin_type=WEB3_ETH_COIN_TYPE,
        network=WEB3_MAINNET_NETWORK,
    )

    okx_bitcoin_entries = []
    for account_path in variant.okx_btc_paths:
        btc_account_root = root.derive(account_path)
        btc_parent_path = "/".join(account_path.split("/")[:-1]) or "m"
        btc_parent_root = root.derive(btc_parent_path)
        okx_bitcoin_entries.append(
            web3_key_entry(
                pubkey_hex=btc_account_root.key.get_public_key().sec().hex(),
                chain_code_hex=btc_account_root.chain_code.hex(),
                origin_path=account_path,
                origin_depth=web3_path_depth(account_path),
                parent_fingerprint=web3_pubkey_fingerprint(btc_parent_root.key.get_public_key().sec()),
                note="",
                coin_type=WEB3_BTC_COIN_TYPE,
                network=WEB3_MAINNET_NETWORK,
            )
        )

    keystone_keys = {
        "standard": standard_entry,
        "ledgerLegacy": ledger_legacy_entry,
        "ledgerLive": dict(okx_ledger_live_entries[0]) if okx_ledger_live_entries else dict(standard_entry),
    }
    if okx_ledger_live_entries:
        keystone_keys["okxLedgerLive"] = [dict(entry) for entry in okx_ledger_live_entries]
    if okx_bitcoin_entries:
        keystone_keys["okxBitcoin"] = [dict(entry) for entry in okx_bitcoin_entries]

    return {
        "address": address,
        "addressPath": normalized_path,
        "accountPath": account_path,
        "masterFingerprint": master_fingerprint_hex,
        "parentFingerprint": web3_pubkey_fingerprint(parent_pubkey),
        "compressedPubKeyHex": account_pubkey.hex(),
        "chainCodeHex": account_root.chain_code.hex(),
        "childrenPath": children_path,
        "keystoneKeys": keystone_keys,
        "deviceId": okx_device_id(master_fingerprint_hex, address, variant.slug),
    }


def build_web3_okx_multi_accounts_cbor_bytes(web3_account: dict) -> bytes:
    master_fingerprint = web3_valid_fingerprint(str(web3_account.get("masterFingerprint") or "")) or "00000000"
    standard = dict(web3_account["keystoneKeys"]["standard"])
    okx_ledger_live = [dict(entry) for entry in web3_account["keystoneKeys"].get("okxLedgerLive", [])]
    okx_bitcoin = [dict(entry) for entry in web3_account["keystoneKeys"].get("okxBitcoin", [])]

    encoder = CBOREncoder()
    encoder.encodeMapSize(5)
    encoder.encodeUnsigned(1)
    encoder.encodeUnsigned(int(master_fingerprint, 16))
    encoder.encodeUnsigned(2)
    encoder.encodeArraySize(1 + len(okx_ledger_live) + len(okx_bitcoin))

    encoder.encodeTagAndValue(Tag_Major_semantic, 303)
    encoder.buf += build_web3_hdkey_entry_cbor_bytes(
        standard,
        master_fingerprint=master_fingerprint,
        include_children=True,
    )

    for entry in okx_ledger_live:
        encoder.encodeTagAndValue(Tag_Major_semantic, 303)
        encoder.buf += build_web3_hdkey_entry_cbor_bytes(
            entry,
            master_fingerprint=master_fingerprint,
            include_children=False,
        )

    for entry in okx_bitcoin:
        encoder.encodeTagAndValue(Tag_Major_semantic, 303)
        encoder.buf += build_web3_bitkeep_hdkey_entry_cbor_bytes(
            entry,
            master_fingerprint=master_fingerprint,
        )

    encoder.encodeUnsigned(3)
    encoder.encodeText(WEB3_OKX_DEVICE_TYPE)
    encoder.encodeUnsigned(4)
    encoder.encodeText(str(web3_account["deviceId"]))
    encoder.encodeUnsigned(5)
    encoder.encodeText(WEB3_KEYSTONE_DEVICE_VERSION)
    return bytes(encoder.get_bytes())


def render_variant(variant: Variant) -> dict:
    web3_account = export_web3_account_from_mnemonic(MNEMONIC, DEFAULT_DERIVATION_PATH, variant)
    ur_text = UREncoder.encode(UR("crypto-multi-accounts", build_web3_okx_multi_accounts_cbor_bytes(web3_account))).upper()

    image_name = f"{variant.slug}-240x240-whitebg.png"
    text_name = f"{variant.slug}-whitebg.txt"
    image_path = DIST / image_name
    text_path = DIST / text_name

    qr = QR()
    img = qr.qrimage_io(
        ur_text,
        width=240,
        height=240,
        border=2,
        background_color="ffffff",
    )
    img.save(image_path)
    text_path.write_text(ur_text, encoding="utf-8")

    return {
        "slug": variant.slug,
        "title": variant.title,
        "note": variant.note,
        "image": image_name,
        "text": text_name,
        "length": len(ur_text),
        "okx_ledger_live_count": variant.okx_ledger_live_count,
        "okx_btc_paths": list(variant.okx_btc_paths),
        "address": web3_account["address"],
    }


def write_html(results: list[dict]) -> Path:
    html_path = DIST / "okx-240x240-test-20260415-whitebg.html"
    cards = []
    nav = []
    for index, item in enumerate(results, start=1):
        nav.append(f'<a href="#item-{index}">{index}. {item["title"]}</a>')
        btc_paths = ", ".join(item["okx_btc_paths"])
        cards.append(
            f"""<section class="card" id="item-{index}">
  <div class="meta">
    <div class="number">{index}</div>
    <div>
      <h2>{item["title"]}</h2>
      <p class="wallet">协议: <code>crypto-multi-accounts</code></p>
      <p>模式: <code>{item["okx_ledger_live_count"]} 个额外 OKX EVM + BTC {btc_paths}</code></p>
      <p>长度: <code>{item["length"]}</code> 字符</p>
      <p class="hint">{item["note"]}</p>
    </div>
  </div>
  <img class="qr" src="{item["image"]}" alt="{item["title"]}">
</section>"""
        )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OKX 240x240 测试二维码</title>
<style>
:root {{ color-scheme: light; --ink:#111827; --muted:#475569; --paper:#fff; --line:#d7dee8; --soft:#f6f8fb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:linear-gradient(180deg,#f8fafc 0%,#ffffff 28%,#eef2f7 100%); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif; }}
header {{ max-width:980px; margin:0 auto; padding:26px 18px 10px; }}
h1 {{ margin:0 0 10px; font-size:30px; }}
p {{ margin:6px 0; line-height:1.55; }}
.nav {{ display:flex; flex-wrap:wrap; gap:8px; margin:16px 0 0; }}
.nav a {{ color:#0f172a; text-decoration:none; border:1px solid var(--line); background:white; border-radius:999px; padding:7px 11px; }}
main {{ max-width:1040px; margin:0 auto; padding:12px 14px 28px; }}
.card {{ background:var(--paper); border:1px solid var(--line); border-radius:24px; box-shadow:0 18px 50px rgba(15,23,42,.10); margin:18px 0; padding:18px; }}
.meta {{ display:flex; gap:14px; align-items:flex-start; text-align:left; }}
.number {{ flex:0 0 auto; width:38px; height:38px; border-radius:50%; background:#111827; color:white; display:grid; place-items:center; font-weight:700; }}
h2 {{ margin:0 0 8px; font-size:24px; }}
.wallet,.hint {{ color:var(--muted); }}
code {{ background:var(--soft); border:1px solid #e2e8f0; border-radius:7px; padding:2px 6px; }}
.note {{ border-left:5px solid #111827; padding:10px 12px; background:white; border-radius:12px; }}
.qr {{ display:block; width:240px; height:240px; margin:18px auto 4px; image-rendering:pixelated; background:white; border:1px solid #e2e8f0; }}
@media (max-width:700px) {{ h1 {{ font-size:24px; }} h2 {{ font-size:20px; }} .card {{ padding:12px; border-radius:18px; }} }}
</style>
</head>
<body>
<header>
  <h1>OKX 240x240 测试二维码</h1>
  <p class="note">这页只测 OKX 小屏难扫的问题。两张图都是固定 <code>240x240</code>，白底黑码，边框按 OKX 现在固件的 <code>border=2</code> 模式来出。</p>
  <p>测试助记词: <code>{MNEMONIC}</code></p>
  <p>派生路径: <code>{DEFAULT_DERIVATION_PATH}</code></p>
  <div class="nav">{''.join(nav)}</div>
</header>
<main>
{''.join(cards)}
</main>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return html_path


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    results = [render_variant(variant) for variant in VARIANTS]
    html_path = write_html(results)
    build_info_path = DIST / "okx-240x240-test-20260415-whitebg.build-info.json"
    build_info_path.write_text(
        json.dumps(
            {
                "mnemonic": MNEMONIC,
                "derivation_path": DEFAULT_DERIVATION_PATH,
                "variants": results,
                "html": html_path.name,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(str(html_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
