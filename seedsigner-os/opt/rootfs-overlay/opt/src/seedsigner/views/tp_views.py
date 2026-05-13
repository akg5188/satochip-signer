import json
import hashlib
import hmac
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from urllib.parse import parse_qs, quote
from gettext import gettext as _

from seedsigner.gui.components import GUIConstants
from seedsigner.gui.screens import RET_CODE__BACK_BUTTON, RET_CODE__POWER_BUTTON, ButtonListScreen, WarningScreen, LargeIconStatusScreen, seed_screens
from seedsigner.gui.screens.scan_screens import ScanScreen
from seedsigner.gui.screens.screen import BaseScreen, ButtonOption, LoadingScreenThread, QRDisplayScreen
from seedsigner.helpers.iso7816 import format_sw_error
from seedsigner.gui.screens.tools_screens import ToolsFormattedTextScreen, ToolsScrollableTextScreen, ToolsTextQRTextEntryScreen
from seedsigner.helpers.signature_health import (
    analyze_psbt_signature_health,
    analyze_tx_signature_health,
    build_signature_health_lines,
)
from seedsigner.helpers.firmware_integrity import DEFAULT_MANIFEST_PATH, verify_runtime_manifest
from seedsigner.helpers.tp_fragment import FragmentParseError, MultiFragmentAssembler, parse_tp_multi_fragment
from seedsigner.helpers.tp_relay import (
    RelayAssembler,
    RelayParseError,
    parse_tp_relay_fragment,
    parse_web3_relay_fragment,
    unwrap_web3_relay_payload,
)
from seedsigner.helpers import embit_utils, seedkeeper_utils
from seedsigner.helpers.ur2.cbor_lite import CBOREncoder, Tag_Major_semantic
from seedsigner.helpers.ur2.ur import UR
from seedsigner.helpers.ur2.ur_decoder import URDecoder
from seedsigner.helpers.ur2.ur_encoder import UREncoder
from seedsigner.hardware.microsd import MicroSD
from seedsigner.models.decode_qr import DecodeQR, DecodeQRStatus
from seedsigner.models.encode_qr import BaseSimpleAnimatedQREncoder, GenericStaticQrEncoder
from seedsigner.models.mnemonic_steel import (
    DEFAULT_SHIFT_OPERATOR,
    OPERATOR_LABELS,
    WEIGHTS,
    WEIGHT_SET,
    WORDLIST as STEEL_WORDLIST,
    get_word_at_index,
    indices_to_plate_groups,
    indices_to_words,
    lookup_word_index,
    parse_restore_indices,
    shift_indices,
    shift_mnemonic,
    solve_weights,
    words_to_indices,
    words_to_plate_groups,
)
from seedsigner.models.seed import InvalidSeedException, Seed, TransientWordSeed, XprvSeed
from seedsigner.models.settings import Settings, SettingsConstants
from seedsigner.hardware.buttons import HardwareButtonsConstants

from .view import BackStackView, Destination, ErrorView, View


DEFAULT_DERIVATION_PATH = "m/44'/60'/0'/0/0"
DEFAULT_BTC_ADDRESS_PATH = "m/84'/0'/0'/0/0"
WEB3_WALLET_PROFILE_OKX = "okx"
WEB3_WALLET_PROFILE_BITGET = "bitget"
WEB3_WALLET_PROFILE_METAMASK = "metamask"
WEB3_WALLET_PROFILE_RABBY = "rabby"
WEB3_WALLET_PROFILE_TOKENPOCKET = "tokenpocket"
WEB3_WALLET_PROFILE_LABELS = {
    WEB3_WALLET_PROFILE_OKX: "OKX Wallet",
    WEB3_WALLET_PROFILE_BITGET: "Bitget Wallet",
    WEB3_WALLET_PROFILE_METAMASK: "MetaMask",
    WEB3_WALLET_PROFILE_RABBY: "Rabby Wallet",
    WEB3_WALLET_PROFILE_TOKENPOCKET: "TokenPocket",
}
WEB3_OKX_DEVICE_TYPE = "Keystone 3 Pro"
WEB3_KEYSTONE_DEVICE_TYPE = "Keystone 3 Pro"
WEB3_KEYSTONE_DEVICE_VERSION = "1.0.4"
WEB3_ETH_COIN_TYPE = 0x3C
WEB3_BTC_COIN_TYPE = 0
WEB3_MAINNET_NETWORK = 0
WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT = 10
WEB3_OKX_BTC_ACCOUNT_PATHS = (
    "m/49'/0'/0'",
    "m/84'/0'/0'",
)
WEB3_OKX_CONNECT_QR_MAX_FRAGMENT_LEN = 160
WEB3_OKX_CONNECT_QR_FRAME_REPEAT = 1
WEB3_BITKEEP_BTC_ACCOUNT_PATHS = (
    "m/84'/0'/0'",
)
DEFAULT_SCREENSAVER_MS = 2 * 60 * 1000
TP_MODE_SCREENSAVER_MS = 10 * 365 * 24 * 60 * 60 * 1000
TP_BTC_XPUB_EXPORTS = {
    "xpub": ("m/44'/0'/0'", "standard"),
    "zpub": ("m/84'/0'/0'", "p2wpkh"),
}
DEFAULT_READER_HINT = None
CAMO_BUTTON_TEXT = " "
CAMO_TEXT = " "
STEEL_WRAP_WIDTH = 18
SECP256K1_FIELD_PRIME = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
TP_STEEL_SECRET_PREFIX = "TP-STEEL:"
TP_UI_LOCK_DIRNAME = ".offline-signer"
TP_UI_LOCK_FILENAME = "offline-signer-login.json"
TP_UI_LOCK_MIN_LEN = 4
TP_UI_LOCK_MAX_LEN = 12
TP_UI_LOCK_PBKDF2_ITERATIONS = 200_000
_TP_UI_LOCK_RECORD_CACHE: dict | None = None
_TP_UI_LOCK_CACHE_INITIALIZED = False

logger = logging.getLogger(__name__)
_SIGNER_PREVIEW_MODULE = None
WEB3_ETH_SIGNATURE_QR_MAX_FRAGMENT_LEN = 260
WEB3_ETH_SIGNATURE_QR_FRAME_REPEAT = 1
WEB3_ETH_SIGNATURE_LEGACY_V_MODE = os.environ.get("WEB3_ETH_SIGNATURE_LEGACY_V_MODE", "recovery_id")
WEB3_ETH_SIGNATURE_INCLUDE_ORIGIN = os.environ.get("WEB3_ETH_SIGNATURE_INCLUDE_ORIGIN", "1").strip().lower() in {"1", "true", "yes", "on"}
_WEB3_ETH_SIGNATURE_DEBUG_CACHE: dict[str, dict] = {}


def _tp_bluewallet_export_script_type(xtype: str) -> str:
    normalized = (xtype or "").strip().lower()
    if normalized == "zpub":
        return SettingsConstants.NATIVE_SEGWIT
    if normalized == "xpub":
        return SettingsConstants.LEGACY_P2PKH
    raise ValueError(f"unsupported BlueWallet xpub type: {xtype}")


def _smartcard_tools_destination() -> Destination:
    return Destination(ToolsTpSmartcardToolsView, clear_history=True)


def _runtime_tmp_dir() -> str | None:
    tmpdir = os.environ.get("TMPDIR")
    if not tmpdir:
        return None
    Path(tmpdir).mkdir(parents=True, exist_ok=True)
    return tmpdir


def _tp_ui_lock_path() -> Path:
    settings_path = Path(Settings.SETTINGS_FILENAME).expanduser()
    if not settings_path.is_absolute():
        settings_path = (Path.cwd() / settings_path).resolve()
    return settings_path.with_name(TP_UI_LOCK_FILENAME)


def _tp_ui_legacy_lock_path() -> Path:
    return Path.home() / TP_UI_LOCK_DIRNAME / TP_UI_LOCK_FILENAME


def _read_tp_ui_lock_record(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            return None
        if not data.get("salt_hex") or not data.get("hash_hex"):
            return None
        return data
    except Exception:
        logger.exception("Failed to load TP UI lock record from %s", path)
        return None


def _write_tp_ui_lock_record(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        logger.exception("Failed to tighten TP UI lock permissions")


def _load_tp_ui_lock_record() -> dict | None:
    global _TP_UI_LOCK_RECORD_CACHE, _TP_UI_LOCK_CACHE_INITIALIZED

    if _TP_UI_LOCK_RECORD_CACHE is not None:
        return dict(_TP_UI_LOCK_RECORD_CACHE)
    if _TP_UI_LOCK_CACHE_INITIALIZED:
        return None
    _TP_UI_LOCK_CACHE_INITIALIZED = True

    primary_path = _tp_ui_lock_path()
    primary_record = _read_tp_ui_lock_record(primary_path)
    if primary_record is not None:
        _TP_UI_LOCK_RECORD_CACHE = dict(primary_record)
        return dict(primary_record)

    legacy_path = _tp_ui_legacy_lock_path()
    if legacy_path == primary_path:
        return None

    legacy_record = _read_tp_ui_lock_record(legacy_path)
    if legacy_record is None:
        return None

    try:
        _write_tp_ui_lock_record(primary_path, legacy_record)
    except Exception:
        logger.exception("Failed to migrate TP UI lock record to %s", primary_path)
    _TP_UI_LOCK_RECORD_CACHE = dict(legacy_record)
    return dict(legacy_record)


def _normalize_tp_ui_password(raw: str) -> str:
    return "".join(ch for ch in str(raw or "").strip() if ch.isdigit())


def _validate_tp_ui_password(password: str) -> None:
    if not password:
        raise ValueError("请输入登录密码。")
    if not password.isdigit():
        raise ValueError("登录密码只能使用数字。")
    if not (TP_UI_LOCK_MIN_LEN <= len(password) <= TP_UI_LOCK_MAX_LEN):
        raise ValueError(f"登录密码长度必须在 {TP_UI_LOCK_MIN_LEN} 到 {TP_UI_LOCK_MAX_LEN} 位之间。")


def _hash_tp_ui_password(password: str, salt: bytes, iterations: int = TP_UI_LOCK_PBKDF2_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )


def _save_tp_ui_password(password: str) -> None:
    global _TP_UI_LOCK_RECORD_CACHE, _TP_UI_LOCK_CACHE_INITIALIZED

    _validate_tp_ui_password(password)
    salt = os.urandom(16)
    digest = _hash_tp_ui_password(password, salt)
    payload = {
        "version": 1,
        "kind": "tp_ui_lock",
        "iterations": TP_UI_LOCK_PBKDF2_ITERATIONS,
        "salt_hex": salt.hex(),
        "hash_hex": digest.hex(),
    }
    _write_tp_ui_lock_record(_tp_ui_lock_path(), payload)
    _TP_UI_LOCK_RECORD_CACHE = dict(payload)
    _TP_UI_LOCK_CACHE_INITIALIZED = True


def _verify_tp_ui_password(password: str) -> bool:
    record = _load_tp_ui_lock_record()
    if record is None:
        return False
    try:
        salt = bytes.fromhex(record["salt_hex"])
        expected = bytes.fromhex(record["hash_hex"])
        iterations = int(record.get("iterations", TP_UI_LOCK_PBKDF2_ITERATIONS))
    except Exception:
        logger.exception("Failed to parse TP UI lock record")
        return False

    actual = _hash_tp_ui_password(password, salt, iterations=iterations)
    return hmac.compare_digest(actual, expected)


def _prompt_for_tp_ui_password(parent_view, title: str, default: str = "") -> str | None:
    ret = ToolsTextQRTextEntryScreen(
        textToEncode=default,
        title=title,
        initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__DIGITS_BUTTON_TEXT,
    ).display()
    if ret.get("is_back_button"):
        return None
    return _normalize_tp_ui_password(ret.get("textToEncode", ""))


def _localize_error_detail(detail: str) -> str:
    short = (detail or "").strip().replace("\n", " ")
    lowered = short.lower()
    known_messages = [
        (
            "hardwarebuttons.wait_for()" in lowered and "check_release" in lowered,
            "按钮输入模块不兼容，现已改为兼容官方输入流程，请刷新到最新固件。",
        ),
        (
            "不是 tp 协议字符串" in short or "协议前缀不合法" in short,
            "当前扫码内容不是已接入的签名协议，请把原始二维码样本留给我继续兼容。",
        ),
        (
            "当前仅支持 signtransaction / personalsign / signtypeddata" in lowered
            or "未知请求类型" in short,
            "这个钱包发来的签名类型当前还没接入，请把原始二维码样本留给我继续兼容。",
        ),
        (
            "typeddata 解析失败" in short or "typeddata message" in lowered,
            "这个 typedData 签名请求格式当前不兼容，请把原始二维码样本留给我继续兼容。",
        ),
        (
            "failed to parse bip32 path" in lowered or "path length exceeds maximum depth" in lowered,
            "请求里的派生路径格式不对，当前无法签名。",
        ),
        (
            "分片未收齐" in short or "补齐所有" in short,
            "动态二维码没有扫完整，请继续扫描到 100%。",
        ),
        ("no card found" in lowered, "未检测到智能卡，请重新插卡后再试。"),
        ("timed out waiting for a card" in lowered, "等待智能卡超时，请确认读卡器和卡片连接。"),
        ("card select failed" in lowered, "选择智能卡应用失败，请确认插入的是正确卡片。"),
    ]
    for matched, message in known_messages:
        if matched:
            return message
    return short


def _prompt_for_tp_pin(parent_view):
    """Prompt for PIN using the standard SeedSigner flow.

    Offline-signer mode tweaks several screens for the simplified launcher. For PIN entry we
    intentionally fall back to the normal path so that it uses the most battle-tested
    input flow and title handling.
    """
    original_tp_only = os.environ.get("TP_ONLY_MODE")
    try:
        os.environ["TP_ONLY_MODE"] = "0"
        return seedkeeper_utils.prompt_for_pin(parent_view, "智能卡 PIN")
    finally:
        if original_tp_only is None:
            os.environ.pop("TP_ONLY_MODE", None)
        else:
            os.environ["TP_ONLY_MODE"] = original_tp_only


def _is_valid_bip32_path(path: str) -> bool:
    value = _normalize_bip32_path(path)
    if not value:
        return False
    if value == "m":
        return True
    if not value.startswith("m/"):
        return False
    parts = value.split("/")[1:]
    for part in parts:
        cleaned = part.rstrip("'hH")
        if not cleaned or not cleaned.isdigit():
            return False
    return True


def _normalize_bip32_path(path: str) -> str:
    value = unicodedata.normalize("NFKC", str(path or "").strip())
    replacements = {
        "H": "'",
        "h": "'",
        "’": "'",
        "‘": "'",
        "′": "'",
        "`": "'",
        "／": "/",
        "\\": "/",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = "/".join(part.strip() for part in value.split("/"))
    value = value.replace("m/", "m/", 1)
    if value == "M":
        value = "m"
    elif value.startswith("M/"):
        value = "m/" + value[2:]
    elif value and not value.startswith("m/") and value != "m":
        value = "m/" + value.lstrip("/")
    return value


def _script_type_label(script_type: str) -> str:
    labels = {
        SettingsConstants.LEGACY_P2PKH: "Legacy",
        SettingsConstants.NESTED_SEGWIT: "Nested SegWit",
        SettingsConstants.NATIVE_SEGWIT: "Native SegWit",
        SettingsConstants.TAPROOT: "Taproot",
    }
    return labels.get(script_type, str(script_type))


def _network_label(network: str) -> str:
    labels = {
        SettingsConstants.MAINNET: "主网",
        SettingsConstants.TESTNET: "测试网",
        SettingsConstants.REGTEST: "Regtest",
    }
    return labels.get(network, str(network))


def _chunk_text(text: str, width: int = 16) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    width = max(1, int(width))
    return "\n".join(value[i:i + width] for i in range(0, len(value), width))


def _short_hash(text: str, width: int = 16) -> str:
    value = str(text or "").strip()
    if not value:
        return "unknown"
    if len(value) <= width:
        return value
    return value[:width]


def _wrap_path_text(path: str, width: int = 16) -> str:
    normalized = _normalize_bip32_path(path)
    if not normalized:
        return ""
    if len(normalized) <= width:
        return normalized

    pieces = normalized.split("/")
    lines = [pieces[0]]
    current = pieces[0]
    for piece in pieces[1:]:
        candidate = f"{current}/{piece}"
        if len(candidate) <= width:
            current = candidate
            lines[-1] = current
        else:
            current = piece if piece.startswith("m") else f"/{piece}"
            lines.append(current)
    return "\n".join(lines)


def _is_evm_derivation_path(path: str) -> bool:
    normalized_path = _normalize_bip32_path(path)
    path_sections = normalized_path.replace("'", "h").split("/")
    return len(path_sections) >= 3 and path_sections[2] == "60h"


def _paginate_report_lines(lines: list[str], lines_per_page: int = 10) -> list[str]:
    cleaned = [line.rstrip() for line in lines]
    if not cleaned:
        return [""]
    lines_per_page = max(1, int(lines_per_page))
    pages = []
    for start in range(0, len(cleaned), lines_per_page):
        page = "\n".join(cleaned[start:start + lines_per_page]).strip("\n")
        pages.append(page if page else " ")
    return pages


def _append_issue_lines(lines: list[str], title: str, items: list[dict], limit: int = 5) -> None:
    if not items:
        return
    lines.append(title)
    for item in items[:limit]:
        lines.append(item.get("path", "unknown"))
    remaining = len(items) - limit
    if remaining > 0:
        lines.append(f"... 还有 {remaining} 项")
    lines.append("")


def _format_firmware_integrity_summary(result: dict) -> str:
    if not result.get("supported"):
        return (
            f"{result.get('error', '当前固件还没有内置完整性清单。')}\n\n"
            "这项功能会核对关键程序文件是否和刷机时一致。"
        )

    missing_count = len(result.get("missing", []))
    modified_count = len(result.get("modified", []))
    unexpected_count = len(result.get("unexpected", []))
    error_count = len(result.get("errors", []))
    status_text = "通过" if result.get("ok") else "发现异常"

    lines = [
        f"结果: {status_text}",
        f"关键文件: {result.get('verified_file_count', 0)}",
        f"缺失: {missing_count}  改动: {modified_count}",
        f"额外: {unexpected_count}  读取失败: {error_count}",
        "",
    ]

    repo_head = result.get("repo_head", "")
    if repo_head:
        lines.extend(["构建提交:", _short_hash(repo_head), ""])

    snapshot_sha = result.get("source_snapshot_tree_sha256", "")
    if snapshot_sha:
        lines.extend(["快照指纹:", _short_hash(snapshot_sha), ""])

    if result.get("ok"):
        lines.extend([
            "说明:",
            "这能发现关键文件被改动或损坏。",
            "若担心整卡被重刷，",
            "还要和 GitHub Release 指纹对照。",
        ])
    else:
        lines.extend([
            "建议:",
            "先不要导入助记词或签名。",
            "先换备用卡，或重新刷正式固件。",
        ])

    return "\n".join(lines)


def _build_firmware_integrity_detail_pages(result: dict) -> list[str]:
    def add_chunk_block(lines: list[str], label: str, value: str, width: int = 14) -> None:
        text = str(value or "").strip()
        if not text:
            return
        lines.append(f"{label}:")
        lines.extend(_chunk_text(text, width=width).splitlines())
        lines.append("")

    def add_time_block(lines: list[str], label: str, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        lines.append(f"{label}:")
        if "T" in text:
            date_part, time_part = text.split("T", 1)
            lines.append(date_part)
            lines.append(time_part.rstrip("Z"))
        else:
            lines.append(text)
        lines.append("")

    lines = []

    if not result.get("supported"):
        lines.extend(
            [
                "状态: 不支持",
                result.get("error", "当前固件还没有内置完整性清单。"),
                "",
                "清单路径:",
                result.get("manifest_path", str(DEFAULT_MANIFEST_PATH)),
                "",
                "说明:",
                "这项功能依赖内置清单，",
                "请刷新到最新正式版后再试。",
            ]
        )
        return _paginate_report_lines(lines, lines_per_page=7)

    lines.extend(
        [
            f"状态: {'通过' if result.get('ok') else '异常'}",
            f"关键文件: {result.get('verified_file_count', 0)}",
            "",
        ]
    )

    repo_head = result.get("repo_head", "")
    add_chunk_block(lines, "构建提交", repo_head)

    build_commit_time = result.get("build_commit_time", "")
    build_time_utc = result.get("build_time_utc", "")
    add_time_block(lines, "源码时间", build_commit_time)
    add_time_block(lines, "构建时间", build_time_utc)

    snapshot_sha = result.get("source_snapshot_tree_sha256", "")
    add_chunk_block(lines, "快照指纹", snapshot_sha)

    expected_tree = result.get("expected_overlay_file_tree_sha256", "")
    add_chunk_block(lines, "内置树摘要", expected_tree)

    current_tree = result.get("current_overlay_file_tree_sha256", "")
    add_chunk_block(lines, "当前树摘要", current_tree)

    _append_issue_lines(lines, "被改动:", result.get("modified", []))
    _append_issue_lines(lines, "已缺失:", result.get("missing", []))
    _append_issue_lines(lines, "额外文件:", result.get("unexpected", []))
    _append_issue_lines(lines, "读取失败:", result.get("errors", []))

    lines.extend(
        [
            "提示:",
            "自检只能发现关键文件和内置清单不一致。",
            "若担心整卡重刷，仍要和 GitHub Release",
            "里的 build-info 对照提交和指纹。",
        ]
    )
    return _paginate_report_lines(lines, lines_per_page=7)


def _format_derivation_failure(exc: Exception, derivation_path: str, fallback: str) -> str:
    detail = str(exc).strip() or fallback
    headline = detail if detail.startswith(exc.__class__.__name__) else f"{exc.__class__.__name__}: {detail}"
    return (
        f"{headline}\n\n"
        f"路径:\n{_wrap_path_text(derivation_path)}"
    )


def _resolve_derivation_network(path_details: dict, current_network: str) -> str:
    parsed_network = path_details.get("network")
    if isinstance(parsed_network, list):
        if current_network in parsed_network:
            return current_network
        return parsed_network[0]
    if parsed_network:
        return parsed_network
    return current_network


def _get_evm_vendor_dir() -> Path | None:
    candidates = [
        Path("/opt/pi-signer-py/vendor"),
        Path(__file__).resolve().parents[3] / "pi-signer-py/vendor",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _keccak256(data: bytes) -> bytes:
    try:
        from Crypto.Hash import keccak  # type: ignore

        digest = keccak.new(digest_bits=256)
        digest.update(data)
        return digest.digest()
    except Exception:
        pass

    vendor_dir = _get_evm_vendor_dir()
    if vendor_dir and str(vendor_dir) not in sys.path:
        sys.path.insert(0, str(vendor_dir))

    try:
        import sha3  # type: ignore

        return sha3.keccak_256(data).digest()
    except Exception:
        pass

    try:
        from eth_hash.auto import keccak as eth_keccak  # type: ignore

        return eth_keccak(data)
    except Exception as exc:
        raise ValueError("当前固件缺少 EVM 地址计算依赖，请刷新到最新测试包后再试。") from exc


def _to_eip55_address(address_hex: str) -> str:
    normalized = address_hex.lower().removeprefix("0x")
    checksum = _keccak256(normalized.encode("ascii")).hex()
    encoded = "".join(
        char.upper() if char in "abcdef" and int(checksum[index], 16) >= 8 else char
        for index, char in enumerate(normalized)
    )
    return f"0x{encoded}"


def _normalize_evm_address_for_compare(address: str) -> str:
    normalized = str(address or "").strip().lower().removeprefix("0x")
    if len(normalized) != 40 or not re.fullmatch(r"[0-9a-f]{40}", normalized):
        raise ValueError("观察地址格式错误，请使用 0x 开头的 EVM 地址。")
    return _to_eip55_address(normalized)


def _to_uncompressed_secp256k1_pubkey(pubkey: bytes | str) -> bytes:
    if isinstance(pubkey, str):
        pubkey = bytes.fromhex(pubkey)
    if not pubkey:
        raise ValueError("当前固件无法读取派生公钥。")
    if len(pubkey) == 65 and pubkey[0] == 0x04:
        return pubkey
    if len(pubkey) == 33 and pubkey[0] in (0x02, 0x03):
        x = int.from_bytes(pubkey[1:], "big")
        y_squared = (pow(x, 3, SECP256K1_FIELD_PRIME) + 7) % SECP256K1_FIELD_PRIME
        y = pow(y_squared, (SECP256K1_FIELD_PRIME + 1) // 4, SECP256K1_FIELD_PRIME)
        if (y & 1) != (pubkey[0] & 1):
            y = SECP256K1_FIELD_PRIME - y
        return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")
    raise ValueError("当前固件无法识别这条公钥格式。")


def _derive_evm_address_from_pubkey_bytes(pubkey: bytes | str) -> str:
    uncompressed_pubkey = _to_uncompressed_secp256k1_pubkey(pubkey)
    return _to_eip55_address(_keccak256(uncompressed_pubkey[1:])[-20:].hex())


def _derive_evm_address_from_seed(seed: Seed, derivation_path: str) -> dict:
    root = seed.get_root(SettingsConstants.MAINNET)
    pubkey = root.derive(derivation_path).key.get_public_key().sec()
    address = _derive_evm_address_from_pubkey_bytes(pubkey)
    return {
        "address_family": "evm",
        "derivation_path": derivation_path,
        "network": "EVM",
        "script_type": "0x 地址",
        "address": address,
        "notes": "同一个 0x 地址通常可用于 ETH、ARB、Base、OP、BSC、Polygon 等 EVM 网络。",
    }


def _derive_evm_address_from_satochip(connector, derivation_path: str) -> dict:
    from seedsigner.helpers.satochip_signer import format_path_string

    key, _chaincode = connector.card_bip32_get_extendedkey(format_path_string(derivation_path))
    pubkey = key.get_public_key_bytes(compressed=False)
    address = _derive_evm_address_from_pubkey_bytes(pubkey)
    return {
        "address_family": "evm",
        "derivation_path": derivation_path,
        "network": "EVM",
        "script_type": "0x 地址",
        "address": address,
        "notes": "同一个 0x 地址通常可用于 ETH、ARB、Base、OP、BSC、Polygon 等 EVM 网络。",
    }


def _extract_unlock_address(stdout: str) -> str:
    for line in (stdout or "").splitlines():
        text = line.strip()
        if text.startswith("地址:") or text.startswith("地址："):
            return text.split(":", 1)[-1].split("：", 1)[-1].strip()
        if text.lower().startswith("address:"):
            return text.split(":", 1)[1].strip()
    return ""


def _derive_evm_address_via_signer_unlock(pin: str, derivation_path: str) -> dict:
    signer_bin = _resolve_signer_bin()
    if not signer_bin.is_file():
        raise ValueError("未找到离线签名器命令，无法读取智能卡 EVM 地址。")

    normalized_path = _normalize_bip32_path(derivation_path)
    cmd = [
        str(signer_bin),
        "unlock",
        "--pin",
        pin,
        "--path",
        normalized_path,
        "--timeout-sec",
        "120",
    ]
    if DEFAULT_READER_HINT:
        cmd.extend(["--reader", DEFAULT_READER_HINT])

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=150,
    )
    if proc.returncode != 0:
        detail = _extract_error(proc.stdout, proc.stderr, "unlock failed")
        raise ValueError(_localize_error_detail(detail) or detail)

    address = _extract_unlock_address(proc.stdout)
    if not address:
        raise ValueError("已解锁智能卡，但没有拿到地址。")

    return {
        "address_family": "evm",
        "derivation_path": normalized_path,
        "network": "EVM",
        "script_type": "0x 地址",
        "address": _to_eip55_address(address),
        "notes": "同一个 0x 地址通常可用于 ETH、ARB、Base、OP、BSC、Polygon 等 EVM 网络。",
    }


def _satochip_btc_xtype(script_type: str) -> str:
    if script_type == SettingsConstants.NATIVE_SEGWIT:
        return "p2wpkh"
    if script_type == SettingsConstants.NESTED_SEGWIT:
        return "p2wpkh-p2sh"
    if script_type in (SettingsConstants.LEGACY_P2PKH, SettingsConstants.TAPROOT):
        return "standard"
    raise ValueError("当前路径类型暂不支持智能卡地址显示。")


def _derive_address_from_satochip(connector, derivation_path: str, current_network: str) -> dict:
    normalized_path = _normalize_bip32_path(derivation_path)
    if not _is_valid_bip32_path(normalized_path):
        raise ValueError("派生路径格式不正确。")

    path_sections = normalized_path.replace("'", "h").split("/")
    if len(path_sections) >= 3 and path_sections[2] == "60h":
        return _derive_evm_address_from_satochip(connector, normalized_path)

    from embit import bip32
    from seedsigner.helpers.satochip_signer import format_path_string

    path_details = embit_utils.parse_derivation_path(normalized_path.replace("'", "h"))
    script_type = path_details.get("script_type")
    if script_type in (None, SettingsConstants.CUSTOM_DERIVATION):
        raise ValueError("当前只支持 44'/49'/84'/86' 这几类 BTC 路径。")

    network = _resolve_derivation_network(path_details, current_network)
    embit_network = SettingsConstants.map_network_to_embit(network)
    if not embit_network:
        raise ValueError("无法识别这条路径对应的网络。")

    wallet_derivation_path = path_details.get("wallet_derivation_path")
    index = path_details.get("index")
    is_change = path_details.get("is_change")
    if wallet_derivation_path is None or index is None or is_change is None:
        raise ValueError("BTC 地址路径请完整输入到地址层，例如 m/84'/0'/0'/0/0。")

    xtype = _satochip_btc_xtype(script_type)
    is_mainnet = network == SettingsConstants.MAINNET
    xpub_base58 = connector.card_bip32_get_xpub(format_path_string(wallet_derivation_path), xtype, is_mainnet)
    xpub = bip32.HDKey.from_base58(xpub_base58)
    address = embit_utils.get_single_sig_address(
        xpub=xpub,
        script_type=script_type,
        index=index,
        is_change=is_change,
        embit_network=embit_network,
    )
    return {
        "address_family": "btc",
        "derivation_path": normalized_path,
        "network": network,
        "script_type": script_type,
        "address": address,
        "notes": "",
    }


def _derive_btc_address_from_seed(seed: Seed, derivation_path: str, current_network: str) -> dict:
    normalized_path = _normalize_bip32_path(derivation_path)
    if not _is_valid_bip32_path(normalized_path):
        raise ValueError("派生路径格式不正确。")
    if isinstance(seed, TransientWordSeed):
        raise ValueError("当前这条助记词不是有效 BIP39，无法派生地址。")

    path_sections = normalized_path.replace("'", "h").split("/")
    if len(path_sections) >= 3 and path_sections[2] == "60h":
        return _derive_evm_address_from_seed(seed, normalized_path)

    path_details = embit_utils.parse_derivation_path(normalized_path.replace("'", "h"))
    script_type = path_details.get("script_type")
    if script_type in (None, SettingsConstants.CUSTOM_DERIVATION):
        raise ValueError("当前只支持 44'/49'/84'/86' 这几类 BTC 路径。")

    network = _resolve_derivation_network(path_details, current_network)
    embit_network = SettingsConstants.map_network_to_embit(network)
    if not embit_network:
        raise ValueError("无法识别这条路径对应的网络。")

    wallet_derivation_path = path_details.get("wallet_derivation_path")
    index = path_details.get("index")
    is_change = path_details.get("is_change")
    if wallet_derivation_path is None or index is None or is_change is None:
        raise ValueError("BTC 地址路径请完整输入到地址层，例如 m/84'/0'/0'/0/0。")

    xpub = seed.get_xpub(wallet_path=wallet_derivation_path, network=network)
    address = embit_utils.get_single_sig_address(
        xpub=xpub,
        script_type=script_type,
        index=index,
        is_change=is_change,
        embit_network=embit_network,
    )

    return {
        "address_family": "btc",
        "derivation_path": normalized_path,
        "network": network,
        "script_type": script_type,
        "address": address,
        "notes": "",
    }


def _extract_requested_derivation_path_from_standard_payload(payload: str) -> str:
    normalized = (payload or "").strip()
    if not normalized or ":" not in normalized or "-" not in normalized:
        return DEFAULT_DERIVATION_PATH
    try:
        query = normalized.split("-", 1)[1]
        params = parse_qs(query, keep_blank_values=True)
        candidate = params.get("path", [DEFAULT_DERIVATION_PATH])[0].strip()
    except Exception:
        return DEFAULT_DERIVATION_PATH
    return candidate if _is_valid_bip32_path(candidate) else DEFAULT_DERIVATION_PATH


@dataclass
class Web3EthSignRequest:
    request_id: str | None
    sign_data: bytes
    data_type: int
    chain_id: int
    derivation_path: str
    address: str | None
    origin: str | None
    request_id_cbor: object | None = None


def _is_web3_eth_sign_request_payload(payload: str) -> bool:
    return str(payload or "").strip().lower().startswith("ur:eth-sign-request/")


def _read_cbor_length(buf: bytes, additional: int, pos: int) -> tuple[int, int]:
    if additional < 24:
        return additional, pos
    if additional == 24:
        return buf[pos], pos + 1
    if additional == 25:
        return int.from_bytes(buf[pos:pos + 2], "big"), pos + 2
    if additional == 26:
        return int.from_bytes(buf[pos:pos + 4], "big"), pos + 4
    if additional == 27:
        return int.from_bytes(buf[pos:pos + 8], "big"), pos + 8
    raise ValueError("暂不支持的 CBOR 长度编码")


def _parse_cbor_item(buf: bytes, pos: int = 0) -> tuple[object, int]:
    if pos >= len(buf):
        raise ValueError("CBOR 数据不完整")

    first = buf[pos]
    pos += 1
    major = first >> 5
    additional = first & 0x1F

    if major in (0, 1):
        value, pos = _read_cbor_length(buf, additional, pos)
        return (value if major == 0 else -1 - value), pos

    if major == 2:
        length, pos = _read_cbor_length(buf, additional, pos)
        return bytes(buf[pos:pos + length]), pos + length

    if major == 3:
        length, pos = _read_cbor_length(buf, additional, pos)
        return bytes(buf[pos:pos + length]).decode("utf-8"), pos + length

    if major == 4:
        length, pos = _read_cbor_length(buf, additional, pos)
        items = []
        for _ in range(length):
            item, pos = _parse_cbor_item(buf, pos)
            items.append(item)
        return items, pos

    if major == 5:
        length, pos = _read_cbor_length(buf, additional, pos)
        items: dict[object, object] = {}
        for _ in range(length):
            key, pos = _parse_cbor_item(buf, pos)
            value, pos = _parse_cbor_item(buf, pos)
            items[key] = value
        return items, pos

    if major == 6:
        tag, pos = _read_cbor_length(buf, additional, pos)
        value, pos = _parse_cbor_item(buf, pos)
        return {"tag": tag, "value": value}, pos

    if major == 7:
        if additional == 20:
            return False, pos
        if additional == 21:
            return True, pos
        if additional == 22:
            return None, pos
        raise ValueError("暂不支持的 CBOR simple 类型")

    raise ValueError("暂不支持的 CBOR major 类型")


def _decode_cbor_root_map(cbor_bytes: bytes) -> dict:
    value, next_pos = _parse_cbor_item(cbor_bytes, 0)
    if next_pos != len(cbor_bytes):
        raise ValueError("CBOR 数据存在多余字节")
    if not isinstance(value, dict):
        raise ValueError("CBOR 顶层不是对象")
    return value


def _tagged_value(value: object, expected_tag: int | None = None) -> object:
    if not isinstance(value, dict) or "tag" not in value or "value" not in value:
        return value
    tag_value = int(value["tag"])
    if expected_tag is not None and tag_value != expected_tag:
        raise ValueError(f"CBOR 标签不匹配: 需要 {expected_tag}，实际 {tag_value}")
    return value["value"]


def _canonicalize_request_id_cbor(value: object) -> object | None:
    if value is None:
        return None

    if isinstance(value, dict) and "tag" in value and "value" in value:
        try:
            tag = int(value["tag"])
        except Exception:
            tag = None
        inner = _canonicalize_request_id_cbor(value["value"])
        if inner is None:
            return None
        if tag == 37:
            if isinstance(inner, bytes) and len(inner) == 16:
                return {"tag": 37, "value": bytes(inner)}
            if isinstance(inner, str):
                try:
                    return {"tag": 37, "value": uuid.UUID(inner).bytes}
                except Exception:
                    return inner
            return inner
        if tag is None:
            return inner
        if isinstance(inner, (bytes, str, int)):
            return {"tag": tag, "value": inner}
        return inner

    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if len(raw) == 16:
            try:
                uuid.UUID(bytes=raw)
                return raw
            except Exception:
                pass
        try:
            decoded = raw.decode("utf-8").strip()
        except Exception:
            decoded = ""
        if decoded:
            return decoded
        return raw if raw else None

    if isinstance(value, str):
        text = value.strip()
        return text or None

    if isinstance(value, int):
        return int(value)

    text = str(value).strip()
    return text or None


def _request_id_from_cbor(value: object) -> tuple[str | None, object | None]:
    canonical = _canonicalize_request_id_cbor(value)
    if canonical is None:
        return None, None

    if isinstance(canonical, dict) and canonical.get("tag") == 37 and isinstance(canonical.get("value"), bytes):
        return str(uuid.UUID(bytes=bytes(canonical["value"]))), canonical

    if isinstance(canonical, bytes):
        raw = bytes(canonical)
        if len(raw) == 16:
            try:
                return str(uuid.UUID(bytes=raw)), canonical
            except Exception:
                pass
        try:
            decoded = raw.decode("utf-8").strip()
        except Exception:
            decoded = ""
        return (decoded or raw.hex()), canonical

    if isinstance(canonical, str):
        return canonical, canonical

    if isinstance(canonical, int):
        return str(canonical), canonical

    text = str(canonical).strip()
    return (text or None), canonical


def _uuid_from_cbor(value: object) -> str | None:
    request_id, _request_id_cbor = _request_id_from_cbor(value)
    return request_id


def _encode_request_id_cbor_value(cbor: CBOREncoder, value: object) -> None:
    if isinstance(value, dict) and "tag" in value and "value" in value:
        cbor.encodeTagAndValue(Tag_Major_semantic, int(value["tag"]))
        _encode_request_id_cbor_value(cbor, value["value"])
        return

    if isinstance(value, (bytes, bytearray)):
        cbor.encodeBytes(bytes(value))
        return

    if isinstance(value, str):
        cbor.encodeText(value)
        return

    if isinstance(value, int) and value >= 0:
        cbor.encodeUnsigned(value)
        return

    cbor.encodeText(str(value))


def _request_id_response_cbor(request_id: str | None, request_id_cbor: object | None = None) -> object | None:
    canonical = _canonicalize_request_id_cbor(request_id_cbor)
    if canonical is not None:
        return canonical

    request_text = str(request_id or "").strip()
    if not request_text:
        return None
    try:
        return {"tag": 37, "value": uuid.UUID(request_text).bytes}
    except Exception:
        return request_text


def _web3_address_from_cbor(value: object) -> str | None:
    if value is None:
        return None
    raw = value if isinstance(value, bytes) else _tagged_value(value)
    if raw in (None, b""):
        return None
    if not isinstance(raw, bytes) or len(raw) != 20:
        raise ValueError("Web3 地址长度不正确")
    return "0x" + raw.hex()


def _keypath_component_to_str(component: object, hardened: bool) -> str:
    suffix = "'" if hardened else ""
    if isinstance(component, int):
        return f"{component}{suffix}"
    if isinstance(component, list) and len(component) == 0:
        return f"*{suffix}"
    raise ValueError("当前暂不支持的 Web3 派生路径组件")


def _web3_keypath_to_bip32_path(value: object) -> str:
    raw = _tagged_value(value, expected_tag=304)
    if not isinstance(raw, dict):
        raise ValueError("Web3 派生路径不是对象")
    components = raw.get(1) or []
    if not isinstance(components, list):
        raise ValueError("Web3 派生路径组件格式错误")
    if len(components) % 2 != 0:
        raise ValueError("Web3 派生路径组件数量不合法")

    path_parts: list[str] = []
    index = 0
    while index < len(components):
        component = components[index]
        hardened = bool(components[index + 1])
        path_parts.append(_keypath_component_to_str(component, hardened))
        index += 2
    return "m" if not path_parts else "m/" + "/".join(path_parts)


def _parse_web3_eth_sign_request_cbor(cbor_bytes: bytes) -> Web3EthSignRequest:
    root = _decode_cbor_root_map(cbor_bytes)
    sign_data = root.get(2)
    if not isinstance(sign_data, bytes) or not sign_data:
        raise ValueError("签名请求缺少 signData")

    data_type = int(root.get(3) or 1)
    chain_id = int(root.get(4) or 1)
    derivation_path = _web3_keypath_to_bip32_path(root.get(5))
    origin = root.get(7)
    if origin is not None and not isinstance(origin, str):
        raise ValueError("origin 字段格式错误")
    request_id, request_id_cbor = _request_id_from_cbor(root.get(1))

    return Web3EthSignRequest(
        request_id=request_id,
        sign_data=sign_data,
        data_type=data_type,
        chain_id=chain_id,
        derivation_path=derivation_path,
        address=_web3_address_from_cbor(root.get(6)),
        origin=origin.strip() if isinstance(origin, str) and origin.strip() else None,
        request_id_cbor=request_id_cbor,
    )


def _web3_wallet_meta(origin: str | None) -> tuple[str, str]:
    normalized = str(origin or "").strip().lower()
    if "bitget" in normalized or "bitkeep" in normalized:
        return "BITGET", "Bitget Wallet"
    if "okx" in normalized or "okex" in normalized:
        return "OKX", "OKX Wallet"
    return "KEYSTONE", "Keystone"


def _web3_wallet_support_note(origin: str | None, chain_id: int) -> str | None:
    wallet_code, wallet_name = _web3_wallet_meta(origin)
    if wallet_code in {"OKX", "BITGET"} and int(chain_id or 0) != 1:
        return f"{wallet_name} 官方当前只标注支持 BTC/ETH；当前链 ID {int(chain_id)} 很可能在钱包端失败。"
    return None


def _web3_request_type_label(data_type: int) -> str:
    return {
        1: "TRANSACTION",
        2: "TYPED_DATA",
        3: "PERSONAL_MESSAGE",
        4: "TYPED_TRANSACTION",
    }.get(int(data_type), f"TYPE_{int(data_type)}")


def _build_tp_query(pairs: list[tuple[str, object | None]]) -> str:
    return "&".join(
        f"{key}={quote(str(value), safe='')}"
        for key, value in pairs
        if value is not None and str(value).strip()
    )


def _build_tp_sign_transaction_request(
    *,
    address: str | None,
    tx_data: dict,
    chain_id: int,
    request_id: str,
    derivation_path: str,
) -> str:
    data_obj = {"txData": dict(tx_data or {})}
    if address:
        data_obj["address"] = address
    data_json = json.dumps(data_obj, ensure_ascii=True, separators=(",", ":"))
    query = _build_tp_query(
        [
            ("version", "1.0"),
            ("protocol", "ArbitrumWallet"),
            ("network", "evm"),
            ("chain_id", str(chain_id)),
            ("requestId", request_id),
            ("path", derivation_path),
            ("data", data_json),
        ]
    )
    return f"tp:signTransaction-{query}"


def _build_tp_personal_sign_request(
    *,
    address: str | None,
    message: str,
    chain_id: int,
    request_id: str,
    derivation_path: str,
) -> str:
    data_obj = {"message": message}
    if address:
        data_obj["address"] = address
    data_json = json.dumps(data_obj, ensure_ascii=True, separators=(",", ":"))
    query = _build_tp_query(
        [
            ("version", "1.0"),
            ("protocol", "ArbitrumWallet"),
            ("network", "evm"),
            ("chain_id", str(chain_id)),
            ("requestId", request_id),
            ("path", derivation_path),
            ("data", data_json),
        ]
    )
    return f"tp:personalSign-{query}"


def _build_tp_sign_typed_data_request(
    *,
    address: str | None,
    typed_data_json: str,
    chain_id: int,
    request_id: str,
    derivation_path: str,
    origin: str | None,
) -> str:
    typed_message = json.loads(typed_data_json)
    data_obj = {"message": typed_message}
    if address:
        data_obj["address"] = address
    if origin:
        data_obj["dappName"] = origin
        data_obj["source"] = origin
    data_json = json.dumps(data_obj, ensure_ascii=False, separators=(",", ":"))
    query = _build_tp_query(
        [
            ("version", "1.0"),
            ("protocol", "ArbitrumWallet"),
            ("network", "evm"),
            ("chain_id", str(chain_id)),
            ("requestId", request_id),
            ("path", derivation_path),
            ("dappName", origin or ""),
            ("source", origin or ""),
            ("data", data_json),
        ]
    )
    return f"tp:signTypeDataV4-{query}"


def _parse_web3_access_list(value) -> list[dict]:
    entries = _rlp_require_list(value, "accessList")
    parsed_entries = []
    for item in entries:
        entry = _rlp_require_list(item, "accessList entry")
        if len(entry) != 2:
            raise ValueError("accessList entry 格式错误")
        address_bytes = _rlp_require_bytes(entry[0], "accessList.address")
        if len(address_bytes) != 20:
            raise ValueError("accessList.address 长度不正确")
        storage_keys = [
            "0x" + _rlp_require_bytes(storage_key, "storageKey").hex()
            for storage_key in _rlp_require_list(entry[1], "accessList.storageKeys")
        ]
        parsed_entries.append(
            {
                "address": "0x" + address_bytes.hex(),
                "storageKeys": storage_keys,
            }
        )
    return parsed_entries


def _parse_web3_typed_unsigned_transaction(sign_data: bytes, address: str | None) -> dict:
    if not sign_data:
        raise ValueError("typed transaction 为空")
    tx_type = sign_data[0]
    body = sign_data[1:]
    values = _rlp_require_list(_rlp_decode(body), "Typed unsigned tx")

    if tx_type == 0x01:
        if len(values) < 8:
            raise ValueError("EIP-2930 unsigned tx 字段不足")
        return {
            "from": address,
            "to": ("0x" + _rlp_require_bytes(values[4], "to").hex()) if _rlp_require_bytes(values[4], "to") else None,
            "value": str(_rlp_quantity(values[5], "value")),
            "data": "0x" + _rlp_require_bytes(values[6], "data").hex(),
            "gasLimit": str(_rlp_quantity(values[3], "gasLimit")),
            "nonce": str(_rlp_quantity(values[1], "nonce")),
            "gasPrice": str(_rlp_quantity(values[2], "gasPrice")),
            "type": 1,
            "accessList": _parse_web3_access_list(values[7]),
        }

    if tx_type == 0x02:
        if len(values) < 9:
            raise ValueError("EIP-1559 unsigned tx 字段不足")
        return {
            "from": address,
            "to": ("0x" + _rlp_require_bytes(values[5], "to").hex()) if _rlp_require_bytes(values[5], "to") else None,
            "value": str(_rlp_quantity(values[6], "value")),
            "data": "0x" + _rlp_require_bytes(values[7], "data").hex(),
            "gasLimit": str(_rlp_quantity(values[4], "gasLimit")),
            "nonce": str(_rlp_quantity(values[1], "nonce")),
            "maxPriorityFeePerGas": str(_rlp_quantity(values[2], "maxPriorityFeePerGas")),
            "maxFeePerGas": str(_rlp_quantity(values[3], "maxFeePerGas")),
            "type": 2,
            "accessList": _parse_web3_access_list(values[8]),
        }

    raise ValueError(f"当前暂不支持的 typed transaction 类型: 0x{tx_type:02x}")


def _build_tp_payload_from_web3_request(request: Web3EthSignRequest) -> str:
    request_id = request.request_id or str(uuid.uuid4())
    if request.data_type == 1:
        values = _rlp_require_list(_rlp_decode(request.sign_data), "Legacy unsigned tx")
        if len(values) < 6:
            raise ValueError("Legacy unsigned tx 字段不足")
        tx_data = {
            "to": ("0x" + _rlp_require_bytes(values[3], "to").hex()) if _rlp_require_bytes(values[3], "to") else None,
            "value": str(_rlp_quantity(values[4], "value")),
            "data": "0x" + _rlp_require_bytes(values[5], "data").hex(),
            "gasLimit": str(_rlp_quantity(values[2], "gasLimit")),
            "nonce": str(_rlp_quantity(values[0], "nonce")),
            "gasPrice": str(_rlp_quantity(values[1], "gasPrice")),
            "type": 0,
        }
        if request.address:
            tx_data["from"] = request.address
        return _build_tp_sign_transaction_request(
            address=request.address,
            tx_data=tx_data,
            chain_id=request.chain_id,
            request_id=request_id,
            derivation_path=request.derivation_path,
        )

    if request.data_type == 4:
        return _build_tp_sign_transaction_request(
            address=request.address,
            tx_data=_parse_web3_typed_unsigned_transaction(request.sign_data, request.address),
            chain_id=request.chain_id,
            request_id=request_id,
            derivation_path=request.derivation_path,
        )

    if request.data_type == 3:
        return _build_tp_personal_sign_request(
            address=request.address,
            message="0x" + request.sign_data.hex(),
            chain_id=request.chain_id,
            request_id=request_id,
            derivation_path=request.derivation_path,
        )

    if request.data_type == 2:
        return _build_tp_sign_typed_data_request(
            address=request.address,
            typed_data_json=request.sign_data.decode("utf-8"),
            chain_id=request.chain_id,
            request_id=request_id,
            derivation_path=request.derivation_path,
            origin=request.origin,
        )

    raise ValueError(f"暂不支持的 Web3 请求类型: {request.data_type}")


def _build_web3_native_payload_from_ur(ur: UR) -> str:
    if not isinstance(ur, UR) or ur.type != "eth-sign-request":
        raise ValueError("当前只支持 eth-sign-request")

    request = _parse_web3_eth_sign_request_cbor(ur.cbor)
    tp_payload = _build_tp_payload_from_web3_request(request)
    wallet_code, wallet_name = _web3_wallet_meta(request.origin)
    return _build_web3_native_relay_payload(
        tp_payload,
        {
            "version": "1",
            "wallet": wallet_code,
            "wallet_name": wallet_name,
            "format": "Keystone / AirGap UR",
            "qr_type": "eth-sign-request",
            "action": "EVM 签名请求",
            "response_protocol": "eth-signature",
            "request_id": request.request_id or "",
            "origin": request.origin or "",
            "data_type": _web3_request_type_label(request.data_type),
            "request_data_type_id": str(request.data_type),
            "request_sign_data_hex": request.sign_data.hex(),
            "chain_id": str(request.chain_id),
            "address": request.address or "",
            "expected_address": request.address or "",
            "address_path": request.derivation_path,
        },
    )


def _build_web3_native_payload_from_ur_text(ur_text: str) -> str:
    decoder = URDecoder()
    if not decoder.receive_part(str(ur_text or "").strip()) or not decoder.is_complete():
        raise ValueError("Web3 UR 请求未收齐")
    return _build_web3_native_payload_from_ur(decoder.result_message())


def _parse_web3_eth_sign_request_from_payload(payload: str) -> Web3EthSignRequest:
    normalized = str(payload or "").strip()
    if not _is_web3_eth_sign_request_payload(normalized):
        raise ValueError("不是 eth-sign-request")

    decoder = URDecoder()
    if not decoder.receive_part(normalized) or not decoder.is_complete():
        raise ValueError("Web3 UR 请求未收齐")

    ur = decoder.result_message()
    if not isinstance(ur, UR) or str(getattr(ur, "type", "")).lower() != "eth-sign-request":
        raise ValueError("当前只支持 eth-sign-request")
    return _parse_web3_eth_sign_request_cbor(ur.cbor)


def _is_web3_native_relay_payload(payload: str) -> bool:
    return (payload or "").strip().lower().startswith("tp:web3relaynative-")


def _extract_web3_native_relay_request(payload: str) -> dict:
    normalized = (payload or "").strip()
    if not _is_web3_native_relay_payload(normalized):
        raise ValueError("不是 Web3 原生回传请求")

    query = normalized.split("-", 1)[1].lstrip("?")
    params = {key: values[-1] for key, values in parse_qs(query, keep_blank_values=True).items()}
    relay_payload = str(params.get("payload") or "").strip()
    if not relay_payload.startswith(("ethereum:", "tp:")):
        raise ValueError("Web3 原生回传请求缺少可签名载荷")

    derivation_path = str(params.get("path") or "").strip() or _extract_requested_derivation_path_from_standard_payload(
        relay_payload
    )
    if not _is_valid_bip32_path(derivation_path):
        derivation_path = DEFAULT_DERIVATION_PATH

    request_data_type_id = str(params.get("request_data_type_id") or "").strip()
    request_sign_data_hex = str(params.get("request_sign_data_hex") or "").strip().lower()

    return {
        "version": str(params.get("version") or "1").strip() or "1",
        "wallet": str(params.get("wallet") or "").strip(),
        "wallet_name": str(params.get("wallet_name") or params.get("wallet") or "Web3 钱包").strip() or "Web3 钱包",
        "format": str(params.get("format") or "Keystone / AirGap UR").strip() or "Keystone / AirGap UR",
        "qr_type": str(params.get("qr_type") or "eth-sign-request").strip() or "eth-sign-request",
        "action": str(params.get("action") or "EVM 签名请求").strip() or "EVM 签名请求",
        "response_protocol": str(params.get("response_protocol") or "").strip().lower(),
        "request_id": str(params.get("request_id") or "").strip(),
        "origin": str(params.get("origin") or "").strip(),
        "data_type": str(params.get("data_type") or "").strip(),
        "request_data_type_id": request_data_type_id,
        "request_sign_data_hex": request_sign_data_hex,
        "chain_id": str(params.get("chain_id") or "").strip(),
        "address": str(params.get("address") or "").strip(),
        "expected_address": str(params.get("expected_address") or "").strip(),
        "derivation_path": derivation_path,
        "payload": relay_payload,
    }


def _build_web3_native_relay_payload(relay_payload: str, envelope: dict) -> str:
    derivation_path = str(envelope.get("address_path") or "").strip() or _extract_requested_derivation_path_from_standard_payload(
        relay_payload
    )
    request_data_type_id = str(envelope.get("request_data_type_id") or "").strip()
    request_sign_data_hex = str(envelope.get("request_sign_data_hex") or "").strip().lower()
    if not request_data_type_id or not request_sign_data_hex:
        derived_type_id, derived_sign_data = _derive_web3_native_request_sign_data(relay_payload)
        if not request_data_type_id and derived_type_id is not None:
            request_data_type_id = str(derived_type_id)
        if not request_sign_data_hex and isinstance(derived_sign_data, (bytes, bytearray)) and derived_sign_data:
            request_sign_data_hex = bytes(derived_sign_data).hex()
    query_pairs = [
        ("version", str(envelope.get("version") or "1")),
        ("wallet", str(envelope.get("wallet") or "")),
        ("wallet_name", str(envelope.get("wallet_name") or envelope.get("wallet") or "Web3 钱包")),
        ("format", str(envelope.get("format") or "Keystone / AirGap UR")),
        ("qr_type", str(envelope.get("qr_type") or "eth-sign-request")),
        ("action", str(envelope.get("action") or "EVM 签名请求")),
        ("response_protocol", str(envelope.get("response_protocol") or "")),
        ("request_id", str(envelope.get("request_id") or "")),
        ("origin", str(envelope.get("origin") or "")),
        ("data_type", str(envelope.get("data_type") or "")),
        ("request_data_type_id", request_data_type_id),
        ("request_sign_data_hex", request_sign_data_hex),
        ("chain_id", str(envelope.get("chain_id") or "")),
        ("address", str(envelope.get("address") or "")),
        ("expected_address", str(envelope.get("expected_address") or "")),
        ("path", derivation_path),
        ("payload", relay_payload),
    ]
    query = "&".join(
        f"{key}={quote(value, safe='')}" for key, value in query_pairs if str(value).strip() or key in ("path", "payload")
    )
    return f"tp:web3RelayNative-{query}"


def _extract_requested_derivation_path(payload: str) -> str:
    normalized = (payload or "").strip()
    if _is_web3_native_relay_payload(normalized):
        try:
            candidate = _extract_web3_native_relay_request(normalized).get("derivation_path", DEFAULT_DERIVATION_PATH)
        except Exception:
            return DEFAULT_DERIVATION_PATH
        return candidate if _is_valid_bip32_path(candidate) else DEFAULT_DERIVATION_PATH
    if _is_web3_eth_sign_request_payload(normalized):
        try:
            candidate = _parse_web3_eth_sign_request_from_payload(normalized).derivation_path
        except Exception:
            return DEFAULT_DERIVATION_PATH
        return candidate if _is_valid_bip32_path(candidate) else DEFAULT_DERIVATION_PATH
    return _extract_requested_derivation_path_from_standard_payload(normalized)


def _derive_web3_native_request_sign_data(relay_payload: str) -> tuple[int | None, bytes | None]:
    signer = _load_signer_preview_module()
    try:
        request = signer.parse_sign_request((relay_payload or "").strip())
    except Exception:
        return None, None

    if isinstance(request, signer.TpSignTransactionRequest):
        try:
            tx = signer.EvmTxEncoder.from_tp_request(request)
            tx_type = int(getattr(tx, "tx_type", 0) or 0)
            return (1 if tx_type == 0 else 4), bytes(signer.EvmTxEncoder.unsigned_payload(tx))
        except Exception:
            return None, None

    if isinstance(request, signer.TpSignPersonalMessageRequest):
        try:
            return 3, bytes(signer.decode_personal_message(request.message))
        except Exception:
            return None, None

    if isinstance(request, signer.TpSignTypedDataRequest):
        if request.is_legacy or request.typed_data_json.strip().startswith("["):
            return None, None
        return 2, request.typed_data_json.encode("utf-8")

    return None, None


def _extract_web3_export_request(payload: str) -> dict:
    normalized = (payload or "").strip()
    if not normalized.lower().startswith("tp:exportweb3account-"):
        raise ValueError("不是 Web3 账户导出请求")

    query = normalized.split("-", 1)[1].lstrip("?")
    params = parse_qs(query, keep_blank_values=True)
    data_raw = params.get("data", [""])[0].strip()
    data = {}
    if data_raw:
        try:
            parsed_data = json.loads(data_raw)
        except Exception as exc:
            raise ValueError(f"Web3 绑定 data JSON 无效: {exc}") from exc
        if not isinstance(parsed_data, dict):
            raise ValueError("Web3 绑定 data 不是对象")
        data = parsed_data

    derivation_path = _normalize_bip32_path(params.get("path", [DEFAULT_DERIVATION_PATH])[0].strip())
    data_path = str(data.get("path") or "").strip()
    if data_path:
        derivation_path = _normalize_bip32_path(data_path)
    if not _is_valid_bip32_path(derivation_path) or not _is_evm_derivation_path(derivation_path):
        raise ValueError("只支持 EVM 地址路径，例如 m/44'/60'/0'/0/0。")

    expected_address = str(data.get("expectedAddress") or data.get("address") or "").strip()
    if expected_address:
        expected_address = _normalize_evm_address_for_compare(expected_address)

    return {
        "version": params.get("version", ["1.0"])[0].strip() or "1.0",
        "protocol": params.get("protocol", ["ArbitrumWallet"])[0].strip() or "ArbitrumWallet",
        "network": params.get("network", ["evm"])[0].strip() or "evm",
        "chain_id": params.get("chain_id", ["1"])[0].strip() or "1",
        "request_id": params.get("requestId", [""])[0].strip(),
        "derivation_path": derivation_path,
        "expected_address": expected_address,
    }


def _split_evm_account_path(derivation_path: str) -> tuple[str, str]:
    normalized_path = _normalize_bip32_path(derivation_path)
    parts = normalized_path.split("/")
    if len(parts) < 6:
        raise ValueError("EVM 地址路径请完整输入到地址层，例如 m/44'/60'/0'/0/0。")
    if not all(parts[index].endswith("'") or parts[index].endswith("h") or parts[index].endswith("H") for index in (1, 2, 3)):
        raise ValueError("EVM 账户路径必须以 m/44'/60'/账户' 开头。")
    branch = parts[4].removesuffix("'").removesuffix("h").removesuffix("H")
    if not branch.isdigit():
        raise ValueError("EVM 路径的 change 分支必须是数字。")
    account_path = "/".join(parts[:4])
    children_path = f"{int(branch)}/*"
    return account_path, children_path


def _web3_path_depth(path: str) -> int:
    return len([segment for segment in _normalize_bip32_path(path).split("/")[1:] if segment])


def _web3_evm_coin_path(derivation_path: str) -> str:
    normalized_path = _normalize_bip32_path(derivation_path)
    parts = normalized_path.split("/")
    if len(parts) < 3:
        raise ValueError("EVM 路径格式不正确。")
    return "/".join(parts[:3])


def _web3_child_path(account_path: str, derivation_path: str, levels: int) -> str:
    parts = _normalize_bip32_path(derivation_path).split("/")
    account_parts = _normalize_bip32_path(account_path).split("/")
    wanted = account_parts + parts[len(account_parts):len(account_parts) + levels]
    return "/".join(wanted)


def _web3_pubkey_fingerprint(pubkey: bytes) -> str:
    from embit import hashes

    return hashes.hash160(bytes(pubkey))[:4].hex()


def _web3_key_entry(
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
        "originPath": _normalize_bip32_path(origin_path),
        "originDepth": origin_depth if origin_depth is not None else _web3_path_depth(origin_path),
        "parentFingerprint": str(parent_fingerprint or "").strip().lower(),
        "childrenPath": str(children_path or "").strip(),
        "childrenDepth": children_depth,
        "name": "Keystone",
        "note": str(note),
        "coinType": coin_type,
        "network": network,
    }


def _web3_attach_keystone_keys(
    web3_account: dict,
    standard: dict,
    ledger_legacy: dict,
    ledger_live: dict,
    okx_ledger_live: list[dict] | None = None,
    okx_bitcoin: list[dict] | None = None,
) -> dict:
    web3_account = dict(web3_account)
    keystone_keys = {
        "standard": standard,
        "ledgerLegacy": ledger_legacy,
        "ledgerLive": ledger_live,
    }
    if okx_ledger_live:
        keystone_keys["okxLedgerLive"] = [dict(entry) for entry in okx_ledger_live]
    if okx_bitcoin:
        keystone_keys["okxBitcoin"] = [dict(entry) for entry in okx_bitcoin]
    web3_account["keystoneKeys"] = keystone_keys
    return web3_account


def _web3_attach_bitkeep_keys(
    web3_account: dict,
    master_fingerprint: str | None,
    key_entries: list[dict],
) -> dict:
    web3_account = dict(web3_account)
    fingerprint = _web3_valid_fingerprint(master_fingerprint)
    if fingerprint:
        web3_account["bitkeepMasterFingerprint"] = fingerprint
    web3_account["bitkeepKeys"] = [dict(entry) for entry in key_entries if isinstance(entry, dict)]
    return web3_account


def _web3_bitkeep_btc_key_entry(
    *,
    pubkey_hex: str,
    chain_code_hex: str,
    origin_path: str,
    parent_fingerprint: str,
) -> dict:
    return _web3_key_entry(
        pubkey_hex=pubkey_hex,
        chain_code_hex=chain_code_hex,
        origin_path=origin_path,
        origin_depth=_web3_path_depth(origin_path),
        parent_fingerprint=parent_fingerprint,
        note="",
        coin_type=WEB3_BTC_COIN_TYPE,
        network=WEB3_MAINNET_NETWORK,
    )


def _web3_btc_key_entries_from_seed_root(root, account_paths: tuple[str, ...]) -> list[dict]:
    entries = []
    for account_path in account_paths:
        account_root = root.derive(account_path)
        parent_path = "/".join(account_path.split("/")[:-1]) or "m"
        parent_root = root.derive(parent_path)
        entries.append(
            _web3_bitkeep_btc_key_entry(
                pubkey_hex=account_root.key.get_public_key().sec().hex(),
                chain_code_hex=account_root.chain_code.hex(),
                origin_path=account_path,
                parent_fingerprint=_web3_pubkey_fingerprint(parent_root.key.get_public_key().sec()),
            )
        )
    return entries


def _web3_bitkeep_btc_key_entries_from_seed_root(root) -> list[dict]:
    return _web3_btc_key_entries_from_seed_root(root, WEB3_BITKEEP_BTC_ACCOUNT_PATHS)


def _web3_okx_btc_key_entries_from_seed_root(root) -> list[dict]:
    return _web3_btc_key_entries_from_seed_root(root, WEB3_OKX_BTC_ACCOUNT_PATHS)


def _web3_btc_key_entries_from_satochip(connector, account_paths: tuple[str, ...]) -> list[dict]:
    from seedsigner.helpers.satochip_signer import format_path_string

    entries = []
    for account_path in account_paths:
        key, chaincode = connector.card_bip32_get_extendedkey(format_path_string(account_path))
        parent_path = "/".join(account_path.split("/")[:-1]) or "m"
        parent_key, _parent_chaincode = connector.card_bip32_get_extendedkey(format_path_string(parent_path))
        entries.append(
            _web3_bitkeep_btc_key_entry(
                pubkey_hex=key.get_public_key_bytes(compressed=True).hex(),
                chain_code_hex=chaincode.hex(),
                origin_path=account_path,
                parent_fingerprint=_web3_pubkey_fingerprint(parent_key.get_public_key_bytes(compressed=True)),
            )
        )
    return entries


def _web3_bitkeep_btc_key_entries_from_satochip(connector) -> list[dict]:
    return _web3_btc_key_entries_from_satochip(connector, WEB3_BITKEEP_BTC_ACCOUNT_PATHS)


def _web3_okx_btc_key_entries_from_satochip(connector) -> list[dict]:
    return _web3_btc_key_entries_from_satochip(connector, WEB3_OKX_BTC_ACCOUNT_PATHS)


def _web3_bitkeep_master_fingerprint_from_satochip(connector) -> str | None:
    from embit import bip32

    for path in ("", "m"):
        try:
            master_xpub = connector.card_bip32_get_xpub(path, "standard", True)
            if master_xpub:
                return bytes(bip32.HDKey.from_base58(master_xpub).my_fingerprint).hex()
        except Exception:
            continue
    logger.info("TP Web3 smartcard master fingerprint export skipped for BitKeep", exc_info=True)
    return None


def _build_web3_account_export_response(request: dict, web3_account: dict) -> str:
    expected_address = str(request.get("expected_address") or "").strip()
    if expected_address:
        actual_address = _normalize_evm_address_for_compare(str(web3_account.get("address") or ""))
        if actual_address.lower() != expected_address.lower():
            raise ValueError(
                "派生地址与手机当前观察地址不一致。\n"
                f"手机: {expected_address}\n"
                f"树莓派: {actual_address}\n"
                "请检查首页观察地址、派生路径和选择的账户来源。"
            )

    query_pairs = [
        ("version", request.get("version", "1.0")),
        ("protocol", request.get("protocol", "ArbitrumWallet")),
        ("network", request.get("network", "evm")),
        ("chain_id", request.get("chain_id", "1")),
    ]
    request_id = str(request.get("request_id", "") or "").strip()
    if request_id:
        query_pairs.append(("requestId", request_id))

    data_json = json.dumps({"web3Account": web3_account}, ensure_ascii=True, separators=(",", ":"))
    query_pairs.append(("data", data_json))

    query = "&".join(
        f"{key}={quote(str(value), safe='')}"
        for key, value in query_pairs
        if str(value).strip()
    )
    return f"tp:exportWeb3AccountResult-{query}"


def _export_web3_account_from_seed(seed: Seed, derivation_path: str) -> dict:
    normalized_path = _normalize_bip32_path(derivation_path)
    account_path, children_path = _split_evm_account_path(normalized_path)
    evm_coin_path = _web3_evm_coin_path(normalized_path)
    root = seed.get_root(SettingsConstants.MAINNET)
    account_root = root.derive(account_path)
    parent_path = "/".join(account_path.split("/")[:-1]) or "m"
    parent_root = root.derive(parent_path)
    address_info = _derive_evm_address_from_seed(seed, normalized_path)

    master_fingerprint = getattr(root, "my_fingerprint", None)
    if master_fingerprint is None:
        master_fingerprint_hex = seed.get_fingerprint(SettingsConstants.MAINNET)
    else:
        master_fingerprint_hex = bytes(master_fingerprint).hex()

    xpub_value = account_root.to_public().to_string()
    if not xpub_value:
        raise ValueError("当前助记词无法导出 EVM 账户 xpub。")

    account_pubkey = account_root.key.get_public_key().sec()
    parent_pubkey = parent_root.key.get_public_key().sec()
    okx_ledger_live_entries = []
    for index in range(WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT):
        ledger_live_path = f"{evm_coin_path}/{index}'/0/0"
        ledger_live_root = root.derive(ledger_live_path)
        live_pubkey = ledger_live_root.key.get_public_key().sec()
        okx_ledger_live_entries.append(
            _web3_key_entry(
                pubkey_hex=live_pubkey.hex(),
                origin_path=ledger_live_path,
                origin_depth=_web3_path_depth(ledger_live_path),
                parent_fingerprint=None,
                note="account.ledger_live",
            )
        )

    standard_entry = _web3_key_entry(
        pubkey_hex=account_pubkey.hex(),
        chain_code_hex=account_root.chain_code.hex(),
        origin_path=account_path,
        origin_depth=_web3_path_depth(account_path),
        parent_fingerprint=_web3_pubkey_fingerprint(parent_pubkey),
        children_path=children_path,
        children_depth=0,
        note="account.standard",
        coin_type=WEB3_ETH_COIN_TYPE,
        network=WEB3_MAINNET_NETWORK,
    )
    ledger_legacy_entry = _web3_key_entry(
        pubkey_hex=account_pubkey.hex(),
        chain_code_hex=account_root.chain_code.hex(),
        origin_path=account_path,
        origin_depth=_web3_path_depth(account_path),
        parent_fingerprint=_web3_pubkey_fingerprint(parent_pubkey),
        children_path="*",
        children_depth=0,
        note="account.ledger_legacy",
        coin_type=WEB3_ETH_COIN_TYPE,
        network=WEB3_MAINNET_NETWORK,
    )

    base = {
        "address": address_info["address"],
        "addressPath": normalized_path,
        "accountPath": account_path,
        "masterFingerprint": master_fingerprint_hex,
        "parentFingerprint": _web3_pubkey_fingerprint(parent_pubkey),
        "compressedPubKeyHex": account_pubkey.hex(),
        "chainCodeHex": account_root.chain_code.hex(),
        "xpub": xpub_value,
        "sourceLabel": "已加载助记词",
        "importedAt": int(time.time() * 1000),
        "label": "Web3 账户",
        "childrenPath": children_path,
    }
    web3_account = _web3_attach_keystone_keys(
        base,
        standard=standard_entry,
        ledger_legacy=ledger_legacy_entry,
        ledger_live=dict(okx_ledger_live_entries[0] if okx_ledger_live_entries else standard_entry),
        okx_ledger_live=okx_ledger_live_entries,
        okx_bitcoin=_web3_okx_btc_key_entries_from_seed_root(root),
    )
    return _web3_attach_bitkeep_keys(
        web3_account,
        master_fingerprint_hex,
        [dict(standard_entry), *_web3_bitkeep_btc_key_entries_from_seed_root(root)],
    )


def _export_web3_account_from_satochip(connector, derivation_path: str) -> dict:
    from seedsigner.helpers.satochip_signer import format_path_string

    normalized_path = _normalize_bip32_path(derivation_path)
    account_path, children_path = _split_evm_account_path(normalized_path)
    evm_coin_path = _web3_evm_coin_path(normalized_path)
    parent_path = "/".join(account_path.split("/")[:-1]) or "m"
    account_xpub = ""
    try:
        account_xpub = connector.card_bip32_get_xpub(format_path_string(account_path), "standard", True)
    except Exception:
        logger.info("TP Web3 smartcard xpub export skipped; Keystone account QR will use raw public key data", exc_info=True)
    key, chaincode = connector.card_bip32_get_extendedkey(format_path_string(account_path))
    parent_key, _parent_chaincode = connector.card_bip32_get_extendedkey(format_path_string(parent_path))
    address_info = _derive_evm_address_from_satochip(connector, normalized_path)

    account_pubkey = key.get_public_key_bytes(compressed=True)
    parent_pubkey = parent_key.get_public_key_bytes(compressed=True)
    okx_ledger_live_entries = []
    for index in range(WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT):
        ledger_live_path = f"{evm_coin_path}/{index}'/0/0"
        ledger_live_key, _ledger_live_chaincode = connector.card_bip32_get_extendedkey(format_path_string(ledger_live_path))
        live_pubkey = ledger_live_key.get_public_key_bytes(compressed=True)
        okx_ledger_live_entries.append(
            _web3_key_entry(
                pubkey_hex=live_pubkey.hex(),
                origin_path=ledger_live_path,
                origin_depth=_web3_path_depth(ledger_live_path),
                parent_fingerprint=None,
                note="account.ledger_live",
            )
        )

    standard_entry = _web3_key_entry(
        pubkey_hex=account_pubkey.hex(),
        chain_code_hex=chaincode.hex(),
        origin_path=account_path,
        origin_depth=_web3_path_depth(account_path),
        parent_fingerprint=_web3_pubkey_fingerprint(parent_pubkey),
        children_path=children_path,
        children_depth=0,
        note="account.standard",
        coin_type=WEB3_ETH_COIN_TYPE,
        network=WEB3_MAINNET_NETWORK,
    )
    ledger_legacy_entry = _web3_key_entry(
        pubkey_hex=account_pubkey.hex(),
        chain_code_hex=chaincode.hex(),
        origin_path=account_path,
        origin_depth=_web3_path_depth(account_path),
        parent_fingerprint=_web3_pubkey_fingerprint(parent_pubkey),
        children_path="*",
        children_depth=0,
        note="account.ledger_legacy",
        coin_type=WEB3_ETH_COIN_TYPE,
        network=WEB3_MAINNET_NETWORK,
    )

    base = {
        "address": address_info["address"],
        "addressPath": normalized_path,
        "accountPath": account_path,
        "masterFingerprint": "00000000",
        "parentFingerprint": _web3_pubkey_fingerprint(parent_pubkey),
        "compressedPubKeyHex": account_pubkey.hex(),
        "chainCodeHex": chaincode.hex(),
        "xpub": account_xpub,
        "sourceLabel": "智能卡 Satochip",
        "importedAt": int(time.time() * 1000),
        "label": "Web3 账户",
        "childrenPath": children_path,
    }
    web3_account = _web3_attach_keystone_keys(
        base,
        standard=standard_entry,
        ledger_legacy=ledger_legacy_entry,
        ledger_live=dict(okx_ledger_live_entries[0] if okx_ledger_live_entries else standard_entry),
        okx_ledger_live=okx_ledger_live_entries,
        okx_bitcoin=_web3_okx_btc_key_entries_from_satochip(connector),
    )
    return _web3_attach_bitkeep_keys(
        web3_account,
        _web3_bitkeep_master_fingerprint_from_satochip(connector),
        [dict(standard_entry), *_web3_bitkeep_btc_key_entries_from_satochip(connector)],
    )


def _collect_manual_qr_parts(qr_encoder) -> list[str]:
    part_count = max(1, int(qr_encoder.seq_len()))
    qr_encoder.restart()
    parts = [qr_encoder.next_part() for _ in range(part_count)]
    qr_encoder.restart()
    return parts


def _collect_ur_encoder_parts(ur_encoder: UREncoder) -> list[str]:
    if ur_encoder.is_single_part():
        return [ur_encoder.next_part()]
    part_count = max(1, int(ur_encoder.fountain_encoder.seq_len()))
    ur_encoder.restart()
    parts = [ur_encoder.next_part() for _ in range(part_count)]
    ur_encoder.restart()
    return parts


def _extract_psbt_request(payload: str):
    normalized = (payload or "").strip()
    if not normalized.lower().startswith("tp:signpsbt-"):
        raise ValueError("不是 BTC PSBT 请求")
    query = normalized.split("-", 1)[1].lstrip("?")
    params = parse_qs(query, keep_blank_values=True)
    data_raw = params.get("data", ["{}"])[0]
    data = json.loads(data_raw)
    psbt_base64 = str(data.get("psbt") or "").strip()
    if not psbt_base64:
        raise ValueError("BTC PSBT 请求缺少 psbt")
    request_id = str(params.get("requestId", [""])[0]).strip()
    return request_id, psbt_base64


def _masked_error_destination(code: str) -> Destination:
    return Destination(
        ErrorView,
        view_args=dict(
            title=CAMO_TEXT,
            status_headline=CAMO_TEXT,
            text=code,
            button_text=CAMO_BUTTON_TEXT,
            show_back_button=False,
            next_destination=_tp_home_destination(),
        ),
    )


def _debug_error_destination(code: str, detail: str) -> Destination:
    short = _localize_error_detail(detail)
    if len(short) > 120:
        short = short[:120]
    text = f"{code}\n{short}".strip()
    return Destination(
        ErrorView,
        view_args=dict(
            title=CAMO_TEXT,
            status_headline=CAMO_TEXT,
            text=text,
            button_text=CAMO_BUTTON_TEXT,
            show_back_button=False,
            next_destination=_tp_home_destination(),
        ),
    )


def _map_signer_error_code(detail: str) -> str:
    if not detail:
        return "32"
    lowered = detail.lower()

    for code in ("50", "51", "52", "53", "54", "55", "56", "57", "511", "512", "513", "514", "515", "516"):
        if detail.startswith(f"{code}:") or detail.strip() == code:
            return code

    if "2FA" in detail or "needs2fa" in lowered:
        return "41"
    if "安全通道" in detail or "secure channel" in lowered or "0x9c21" in lowered:
        return "42"
    if (
        "未导入种子" in detail
        or "未导入助记词" in detail
        or "助记词" in detail
        or "seed is not initialized" in lowered
        or "0x9c14" in lowered
    ):
        return "43"
    if "尚未初始化" in detail or "not initialized" in lowered or "setup not done" in lowered or "0x9c04" in lowered:
        return "44"
    if "PIN 验证失败" in detail or "wrong pin" in lowered or "pin" in lowered and "remain" in lowered or "0x9c02" in lowered:
        return "45"
    if "未检测到读卡器" in detail or "超时未检测到插卡" in detail or "no card found" in lowered or "please insert card" in lowered:
        return "46"
    if "选择 Satochip Applet 失败" in detail or "cardselect error" in lowered or "no suitable card found" in lowered:
        return "47"
    if "BIP32 派生失败" in detail or "签名 APDU 失败" in detail or "unexpected error" in lowered:
        return "48"
    return "32"


class TpRequestQrDecoder:
    def __init__(self) -> None:
        self.complete = False
        self.text = None
        self.psbt_base64 = None
        self.psbt_input_qr_type = None
        self.total_segments = 1
        self.collected_segments = 0
        self.is_nonUTF8 = False
        self.error = ""
        self._seen = set()
        self._assembler = MultiFragmentAssembler()
        self._relay_assembler = RelayAssembler()
        self._web3_relay_assembler = RelayAssembler()
        self._web3_ur_decoder = URDecoder()
        self._psbt_decoder = DecodeQR()

    @property
    def is_complete(self) -> bool:
        return self.complete

    def get_text(self) -> str:
        return self.text or ""

    @property
    def has_psbt(self) -> bool:
        return bool(self.psbt_base64)

    def get_psbt_base64(self) -> str:
        return self.psbt_base64 or ""

    def get_psbt_input_qr_type(self) -> str | None:
        return self.psbt_input_qr_type

    def get_percent_complete(self, weight_mixed_frames: bool = False) -> int:
        if self._psbt_decoder.qr_type and self._psbt_decoder.is_psbt:
            return self._psbt_decoder.get_percent_complete(weight_mixed_frames=weight_mixed_frames)
        if self.complete:
            return 100
        if self.total_segments <= 1:
            return 0
        return int((self.collected_segments / self.total_segments) * 100)

    def add_image(self, image):
        raw = DecodeQR.extract_qr_data(image, is_binary=True)
        if raw is None:
            return DecodeQRStatus.FALSE

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            self.is_nonUTF8 = True
            self.error = "二维码不是 UTF-8 文本"
            return DecodeQRStatus.INVALID

        return self.add_data(text)

    def add_data(self, text: str):
        text = text.strip()
        if not text:
            return DecodeQRStatus.FALSE

        if text in self._seen:
            return DecodeQRStatus.PART_EXISTING
        self._seen.add(text)

        if text.lower().startswith("tpr1:"):
            try:
                fragment = parse_tp_relay_fragment(text)
            except RelayParseError as error:
                self.error = str(error)
                return DecodeQRStatus.INVALID

            self.total_segments = fragment.total
            status, detail = self._relay_assembler.accept(fragment)
            self.collected_segments = len(self._relay_assembler.raw_fragments)
            if status == "progress":
                return DecodeQRStatus.PART_COMPLETE
            if status == "error":
                self.error = detail or "中转分片处理失败"
                return DecodeQRStatus.INVALID

            self.text = detail or ""
            self.complete = True
            self.collected_segments = self.total_segments
            return DecodeQRStatus.COMPLETE

        if text.lower().startswith("w3r1:"):
            try:
                fragment = parse_web3_relay_fragment(text)
            except RelayParseError as error:
                self.error = str(error)
                return DecodeQRStatus.INVALID

            self.total_segments = fragment.total
            status, detail = self._web3_relay_assembler.accept(fragment)
            self.collected_segments = len(self._web3_relay_assembler.raw_fragments)
            if status == "progress":
                return DecodeQRStatus.PART_COMPLETE
            if status == "error":
                self.error = detail or "Web3 中转分片处理失败"
                return DecodeQRStatus.INVALID

            try:
                relay_payload, envelope = unwrap_web3_relay_payload(detail or "")
            except RelayParseError as error:
                self.error = str(error)
                self.complete = True
                self.collected_segments = self.total_segments
                return DecodeQRStatus.COMPLETE

            if relay_payload.startswith(("ethereum:", "tp:")):
                response_protocol = str(envelope.get("response_protocol") or "").strip().lower()
                if response_protocol == "eth-signature":
                    self.text = _build_web3_native_relay_payload(relay_payload, envelope)
                else:
                    self.text = relay_payload
                self.complete = True
                self.collected_segments = self.total_segments
                return DecodeQRStatus.COMPLETE

            wallet = str(envelope.get("wallet_name") or envelope.get("wallet") or "Web3")
            qr_type = str(envelope.get("qr_type") or "-")
            action = str(envelope.get("action") or "签名请求")
            self.error = (
                f"{wallet} {action} 已收齐，格式 {qr_type} 当前还未接入签名解析；"
                "请提供原始二维码样本继续兼容。"
            )
            self.complete = True
            self.collected_segments = self.total_segments
            return DecodeQRStatus.COMPLETE

        if text.lower().startswith("tp:multifragment-"):
            try:
                fragment = parse_tp_multi_fragment(text)
            except FragmentParseError as error:
                self.error = str(error)
                return DecodeQRStatus.INVALID

            self.total_segments = fragment.total
            status, detail = self._assembler.accept(fragment)
            self.collected_segments = len(self._assembler.raw_fragments)
            if status == "progress":
                return DecodeQRStatus.PART_COMPLETE
            if status == "error":
                self.error = detail or "TP 分片处理失败"
                return DecodeQRStatus.INVALID

            self.text = detail or ""
            self.complete = True
            self.collected_segments = self.total_segments
            return DecodeQRStatus.COMPLETE

        if text.lower().startswith("ur:eth-sign-request/"):
            if not self._web3_ur_decoder.receive_part(text):
                self.error = "Web3 签名请求二维码格式无效"
                return DecodeQRStatus.INVALID

            try:
                expected_parts = self._web3_ur_decoder.expected_part_count()
            except Exception:
                expected_parts = None
            received_indexes_getter = getattr(self._web3_ur_decoder, "received_part_indexes", None)
            received_indexes = received_indexes_getter() if callable(received_indexes_getter) else set()
            if received_indexes is None:
                received_indexes = set()
            self.total_segments = max(1, int(expected_parts or 1))
            self.collected_segments = max(1, len(received_indexes)) if self.total_segments > 1 else 1

            if not self._web3_ur_decoder.is_complete():
                return DecodeQRStatus.PART_COMPLETE

            try:
                self.text = UREncoder.encode(self._web3_ur_decoder.result_message())
            except Exception as error:
                self.error = str(error)
                return DecodeQRStatus.INVALID

            self.complete = True
            self.collected_segments = self.total_segments
            return DecodeQRStatus.COMPLETE

        psbt_status = self._psbt_decoder.add_data(text)
        if self._psbt_decoder.is_psbt:
            inner_decoder = getattr(self._psbt_decoder, "decoder", None)
            self.total_segments = getattr(inner_decoder, "total_segments", 1) or 1
            self.collected_segments = getattr(inner_decoder, "collected_segments", 0)
            if psbt_status == DecodeQRStatus.COMPLETE:
                self.psbt_base64 = self._psbt_decoder.get_base64_psbt()
                self.psbt_input_qr_type = self._psbt_decoder.qr_type
                self.complete = True
            return psbt_status

        if text.startswith(("ethereum:", "tp:")):
            self.text = text
            self.complete = True
            self.collected_segments = 1
            return DecodeQRStatus.COMPLETE

        self.error = "暂不支持的二维码格式"
        return DecodeQRStatus.INVALID


def _summarize_payload(payload: str) -> str:
    head = payload.split("?", 1)[0].strip()
    if ":" in head:
        return head
    return "request"


def _extract_error(stdout: str, stderr: str, fallback: str) -> str:
    if stderr:
        for line in reversed(stderr.splitlines()):
            text = line.strip()
            if text:
                return text[:160]
    if stdout:
        for line in reversed(stdout.splitlines()):
            text = line.strip()
            if not text:
                continue
            if text.startswith("卡 ATR:") or text.startswith("已连接读卡器:"):
                continue
            return text[:160]
    return fallback


def _resolve_signer_bin() -> Path:
    candidates = []
    for env_name in ("OFFLINE_SIGNER_BIN", "TP_PI_SIGNER_BIN"):
        env_path = os.environ.get(env_name, "").strip()
        if env_path:
            candidates.append(Path(env_path))
    candidates.append(Path("/opt/offline-signer/bin/pi-signer"))
    candidates.append(Path("/opt/offline-signer/bin/offline-signer"))
    candidates.append(Path("/opt/pi-signer-py/bin/pi-signer"))
    candidates.append(Path("/opt/pi-signer-py/bin/offline-signer"))
    candidates.append(Path(__file__).resolve().parents[3] / "pi-signer-py/bin/pi-signer")
    candidates.append(Path(__file__).resolve().parents[3] / "pi-signer-py/bin/offline-signer")
    for legacy_root in Path("/opt").glob("*pi-signer/bin"):
        candidates.append(legacy_root / "pi-signer")
        candidates.append(legacy_root / "offline-signer")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[-1]


def _load_signer_preview_module():
    global _SIGNER_PREVIEW_MODULE

    if _SIGNER_PREVIEW_MODULE is not None:
        return _SIGNER_PREVIEW_MODULE

    signer_bin = _resolve_signer_bin()
    if not signer_bin.is_file():
        raise FileNotFoundError("未找到离线签名器解析脚本。")

    loader = SourceFileLoader("_offline_signer_preview_module", str(signer_bin))
    spec = spec_from_loader(loader.name, loader)
    if spec is None:
        raise ImportError("无法加载离线签名器解析模块。")

    module = module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    _SIGNER_PREVIEW_MODULE = module
    return module


def _evm_chain_name(chain_id: int) -> str:
    names = {
        1: "Ethereum Mainnet",
        10: "Optimism",
        56: "BSC",
        137: "Polygon",
        42161: "Arbitrum One",
        8453: "Base",
        11155111: "Sepolia",
        421614: "Arbitrum Sepolia",
        84532: "Base Sepolia",
        11155420: "Optimism Sepolia",
    }
    return names.get(int(chain_id), "EVM")


def _append_chunked_value(lines: list[str], label: str, value: str, width: int = 18) -> None:
    text = str(value or "").strip() or "-"
    lines.append(label)
    lines.extend(_chunk_text(text, width=width).splitlines() or ["-"])


def _preview_text_line(text: str, max_len: int = 160) -> str:
    single_line = str(text or "").replace("\n", " ").strip()
    if len(single_line) <= max_len:
        return single_line
    return single_line[:max_len] + "..."


def _decode_message_bytes_for_preview(message: str) -> bytes:
    text = str(message or "")
    if text.startswith(("0x", "0X")):
        try:
            return bytes.fromhex(text[2:])
        except Exception:
            return text.encode("utf-8", errors="replace")
    return text.encode("utf-8", errors="replace")


def _format_native_amount_wei(value_wei: int) -> str:
    try:
        scaled = (Decimal(int(value_wei)) / (Decimal(10) ** 18)).quantize(
            Decimal("0.00000001"),
            rounding=ROUND_DOWN,
        )
        text = format(scaled.normalize(), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
    except Exception:
        return "?"


def _resolve_sign_execution_payload(payload: str) -> str:
    normalized = (payload or "").strip()
    if _is_web3_native_relay_payload(normalized):
        return _extract_web3_native_relay_request(normalized)["payload"]
    if _is_web3_eth_sign_request_payload(normalized):
        return _build_tp_payload_from_web3_request(_parse_web3_eth_sign_request_from_payload(normalized))
    return normalized


def _is_supported_sign_scan_payload(payload: str) -> bool:
    normalized = str(payload or "").strip()
    return (
        normalized.startswith(("ethereum:", "tp:"))
        or _is_web3_native_relay_payload(normalized)
        or _is_web3_eth_sign_request_payload(normalized)
    )


def _parse_tp_sign_response_payload(response_text: str) -> dict:
    normalized = str(response_text or "").strip()
    if not normalized or ":" not in normalized or "-" not in normalized:
        raise ValueError("签名结果格式不正确")

    namespace, remainder = normalized.split(":", 1)
    if "-" in remainder:
        action, query_text = remainder.split("-", 1)
    else:
        action, query_text = remainder, ""
    if query_text.startswith("?"):
        query_text = query_text[1:]

    params = {key: values[-1] for key, values in parse_qs(query_text, keep_blank_values=True).items()}
    raw_data = params.get("data", "")
    try:
        data = json.loads(raw_data) if raw_data else {}
    except Exception as exc:
        raise ValueError(f"签名结果里的 data JSON 无法解析: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("签名结果里的 data 不是对象")

    return {
        "namespace": namespace,
        "action": action,
        "params": params,
        "data": data,
    }


def _hex_to_bytes(value: str) -> bytes:
    normalized = str(value or "").strip()
    if normalized.startswith(("0x", "0X")):
        normalized = normalized[2:]
    if not normalized:
        return b""
    if len(normalized) % 2 != 0:
        raise ValueError("十六进制长度不正确")
    try:
        return bytes.fromhex(normalized)
    except Exception as exc:
        raise ValueError(f"十六进制内容无效: {exc}") from exc


def _int_to_fixed_bytes(value: int, size: int) -> bytes:
    if value < 0:
        raise ValueError("数值不能为负数")
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big") if value else b""
    if len(raw) > size:
        raise ValueError(f"数值长度超过 {size} 字节")
    return (b"\x00" * (size - len(raw))) + raw


def _int_to_minimal_bytes(value: int) -> bytes:
    if value < 0:
        raise ValueError("数值不能为负数")
    if value == 0:
        return b"\x00"
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def _rlp_decode(payload: bytes):
    value, next_offset = _rlp_decode_at(payload, 0)
    if next_offset != len(payload):
        raise ValueError("RLP 数据存在多余字节")
    return value


def _rlp_decode_at(payload: bytes, offset: int):
    if offset >= len(payload):
        raise ValueError("RLP 数据不完整")
    prefix = payload[offset]

    if prefix <= 0x7F:
        return payload[offset : offset + 1], offset + 1

    if prefix <= 0xB7:
        length = prefix - 0x80
        start = offset + 1
        end = start + length
        if end > len(payload):
            raise ValueError("RLP 字节串越界")
        return payload[start:end], end

    if prefix <= 0xBF:
        length_of_length = prefix - 0xB7
        start = offset + 1
        length = _rlp_parse_length(payload, start, length_of_length)
        data_start = start + length_of_length
        data_end = data_start + length
        if data_end > len(payload):
            raise ValueError("RLP 长字节串越界")
        return payload[data_start:data_end], data_end

    if prefix <= 0xF7:
        length = prefix - 0xC0
        start = offset + 1
        end = start + length
        if end > len(payload):
            raise ValueError("RLP 列表越界")
        return _rlp_decode_list(payload, start, end), end

    length_of_length = prefix - 0xF7
    start = offset + 1
    length = _rlp_parse_length(payload, start, length_of_length)
    data_start = start + length_of_length
    data_end = data_start + length
    if data_end > len(payload):
        raise ValueError("RLP 长列表越界")
    return _rlp_decode_list(payload, data_start, data_end), data_end


def _rlp_decode_list(payload: bytes, start: int, end: int) -> list:
    values = []
    cursor = start
    while cursor < end:
        item, next_cursor = _rlp_decode_at(payload, cursor)
        values.append(item)
        cursor = next_cursor
    if cursor != end:
        raise ValueError("RLP 列表边界不匹配")
    return values


def _rlp_parse_length(payload: bytes, offset: int, length_of_length: int) -> int:
    if length_of_length not in range(1, 9):
        raise ValueError("RLP 长度字段不合法")
    end = offset + length_of_length
    if end > len(payload):
        raise ValueError("RLP 长度字段越界")
    value = 0
    for index in range(offset, end):
        value = (value << 8) | payload[index]
    return value


def _rlp_require_list(value, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} 不是列表")
    return value


def _rlp_require_bytes(value, label: str) -> bytes:
    if not isinstance(value, (bytes, bytearray)):
        raise ValueError(f"{label} 不是字节串")
    return bytes(value)


def _rlp_quantity(value, label: str) -> int:
    raw = _rlp_require_bytes(value, label)
    return int.from_bytes(raw, "big") if raw else 0


def _normalize_legacy_v_mode(value: str | None = None) -> str:
    normalized = str(value or WEB3_ETH_SIGNATURE_LEGACY_V_MODE or "").strip().lower()
    if normalized in {"eip155_v", "eip155", "chain_v", "chainid_v", "37_38", "37/38"}:
        return "eip155_v"
    if normalized in {"ethereum_v", "ethereum", "eth_v", "27_28", "27/28"}:
        return "ethereum_v"
    return "recovery_id"


def _web3_legacy_signature_v_mode(origin: str | None, chain_id: int | None) -> str:
    default_mode = _normalize_legacy_v_mode()
    if default_mode != "recovery_id":
        return default_mode
    wallet_code, _ = _web3_wallet_meta(origin)
    if wallet_code in {"OKX", "BITGET"} and int(chain_id or 0) > 0:
        return "eip155_v"
    return default_mode


def _legacy_signature_output_bytes(recovery_id: int, v_mode: str | None = None, chain_id: int | None = None) -> bytes:
    mode = _normalize_legacy_v_mode(v_mode)
    if mode == "ethereum_v":
        return bytes([recovery_id + 27])
    if mode == "eip155_v":
        if chain_id is None:
            raise ValueError("legacy tx 缺少 chainId，无法编码 EIP-155 v")
        return _int_to_minimal_bytes(int(chain_id) * 2 + 35 + int(recovery_id))
    return bytes([recovery_id & 0xFF])


def _eth_signature_debug_cache_key(response_text: str) -> str:
    return hashlib.sha256(str(response_text or "").strip().encode("utf-8")).hexdigest()


def _remember_eth_signature_debug_context(response_text: str, context: dict | None) -> None:
    if not context:
        return
    cache_key = _eth_signature_debug_cache_key(response_text)
    merged = dict(_WEB3_ETH_SIGNATURE_DEBUG_CACHE.get(cache_key) or {})
    for key, value in dict(context).items():
        if value is not None and value != "":
            merged[key] = value
    _WEB3_ETH_SIGNATURE_DEBUG_CACHE[cache_key] = merged


def _get_eth_signature_debug_context(response_text: str) -> dict:
    return dict(_WEB3_ETH_SIGNATURE_DEBUG_CACHE.get(_eth_signature_debug_cache_key(response_text)) or {})


def _extract_legacy_transaction_signature_details(
    raw_transaction: str,
    chain_id: int,
    v_mode: str | None = None,
) -> tuple[bytes, dict]:
    values = _rlp_require_list(_rlp_decode(_hex_to_bytes(raw_transaction)), "Signed legacy tx")
    if len(values) < 9:
        raise ValueError("Signed legacy tx 字段不足")
    v = _rlp_quantity(values[6], "v")
    r = _int_to_fixed_bytes(_rlp_quantity(values[7], "r"), 32)
    s = _int_to_fixed_bytes(_rlp_quantity(values[8], "s"), 32)
    if v in (0, 1):
        recovery_id = v
    elif v in (27, 28):
        recovery_id = v - 27
    else:
        recovery_id = v - (int(chain_id) * 2 + 35)
    if recovery_id not in (0, 1):
        raise ValueError(f"Signed legacy tx recoveryId 不正确: {recovery_id}")
    output_bytes = _legacy_signature_output_bytes(recovery_id, v_mode=v_mode, chain_id=chain_id)
    output_value = int.from_bytes(output_bytes, "big")
    return (
        r + s + output_bytes,
        {
            "transaction_type": "legacy",
            "v": v,
            "recovery_id": recovery_id,
            "signature_output_byte": output_value,
            "legacy_v_mode": _normalize_legacy_v_mode(v_mode),
        },
    )


def _extract_legacy_transaction_signature(raw_transaction: str, chain_id: int) -> bytes:
    signature_bytes, _ = _extract_legacy_transaction_signature_details(raw_transaction, chain_id)
    return signature_bytes


def _extract_typed_transaction_signature_details(raw_transaction: str) -> tuple[bytes, dict]:
    tx_bytes = _hex_to_bytes(raw_transaction)
    if not tx_bytes:
        raise ValueError("Signed typed tx 为空")

    tx_type = tx_bytes[0]
    values = _rlp_require_list(_rlp_decode(tx_bytes[1:]), "Signed typed tx")
    if tx_type == 0x01:
        if len(values) < 11:
            raise ValueError("Signed EIP-2930 tx 字段不足")
        y_parity = _rlp_quantity(values[8], "yParity")
        r = _int_to_fixed_bytes(_rlp_quantity(values[9], "r"), 32)
        s = _int_to_fixed_bytes(_rlp_quantity(values[10], "s"), 32)
        return (
            r + s + bytes([y_parity & 0xFF]),
            {
                "transaction_type": "eip-2930",
                "y_parity": y_parity,
                "signature_output_byte": y_parity,
            },
        )

    if tx_type == 0x02:
        if len(values) < 12:
            raise ValueError("Signed EIP-1559 tx 字段不足")
        y_parity = _rlp_quantity(values[9], "yParity")
        r = _int_to_fixed_bytes(_rlp_quantity(values[10], "r"), 32)
        s = _int_to_fixed_bytes(_rlp_quantity(values[11], "s"), 32)
        return (
            r + s + bytes([y_parity & 0xFF]),
            {
                "transaction_type": "eip-1559",
                "y_parity": y_parity,
                "signature_output_byte": y_parity,
            },
        )

    raise ValueError(f"当前暂不支持的 typed transaction 回传类型: 0x{tx_type:02x}")


def _extract_typed_transaction_signature(raw_transaction: str) -> bytes:
    signature_bytes, _ = _extract_typed_transaction_signature_details(raw_transaction)
    return signature_bytes


def _normalize_eth_message_signature_bytes(signature_bytes: bytes) -> bytes:
    if len(signature_bytes) != 65:
        raise ValueError("签名结果必须是 65 字节")
    v = signature_bytes[-1]
    if v in (27, 28):
        recovery_id = v - 27
    elif v in (0, 1):
        recovery_id = v
    else:
        recovery_id = (v - 35) % 2
    return signature_bytes[:-1] + bytes([recovery_id & 0xFF])


def _eth_signature_recovery_id(signature_byte: int) -> int | None:
    value = int(signature_byte)
    if value in (0, 1):
        return value
    if value in (27, 28):
        return value - 27
    if value >= 35:
        return (value - 35) % 2
    return None


def _recover_eth_signature_address(digest: bytes, signature_bytes: bytes, expected_address: str | None = None) -> str | None:
    if len(digest) != 32 or len(signature_bytes) < 65:
        return None

    signer = _load_signer_preview_module()
    r = int.from_bytes(signature_bytes[0:32], "big")
    s = int.from_bytes(signature_bytes[32:64], "big")
    candidates: list[int] = []
    if expected_address:
        try:
            candidates.append(int(signer.recover_rec_id_by_address(digest, r, s, expected_address)))
        except Exception:
            pass

    rec_id = _eth_signature_recovery_id(int.from_bytes(signature_bytes[64:], "big"))
    if rec_id is not None:
        candidates.extend([rec_id, rec_id + 2])

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            pubkey = signer.recover_pubkey_from_digest(digest, r, s, candidate)
        except Exception:
            continue
        if not pubkey:
            continue
        try:
            return signer.ethereum_address_from_pubkey(pubkey)
        except Exception:
            continue
    return None


def _eth_signature_request_debug_context(request, signature_bytes: bytes) -> dict:
    signer = _load_signer_preview_module()
    request_address = str(getattr(request, "address", "") or "").strip() or None
    digest = None

    if isinstance(request, signer.TpSignTransactionRequest):
        tx = signer.EvmTxEncoder.from_tp_request(request)
        digest = signer.EvmTxEncoder.transaction_hash(tx)
    elif isinstance(request, signer.TpSignPersonalMessageRequest):
        digest = signer.personal_sign_hash(request.message)
    elif isinstance(request, signer.TpSignTypedDataRequest):
        digest = signer.typed_data_hash(request.typed_data_json)

    recovered_address = _recover_eth_signature_address(digest, signature_bytes, expected_address=request_address) if digest else None
    matches_request = None
    if recovered_address and request_address:
        matches_request = recovered_address.lower() == signer.normalize_eth_address(request_address).lower()

    return {
        "request_address": request_address,
        "digest_hex": digest.hex() if isinstance(digest, (bytes, bytearray)) else None,
        "recovered_address": recovered_address,
        "recovered_matches_request": matches_request,
    }


def _extract_signature_bytes_from_tp_response(request, response_text: str) -> bytes:
    signature_bytes, _ = _extract_signature_bytes_with_debug_from_tp_response(request, response_text)
    return signature_bytes


def _extract_signature_bytes_with_debug_from_tp_response(
    request,
    response_text: str,
    *,
    legacy_v_mode: str | None = None,
) -> tuple[bytes, dict]:
    parsed = _parse_tp_sign_response_payload(response_text)
    data = parsed["data"]

    signer = _load_signer_preview_module()
    request_type = type(request).__name__
    chain_id = int(getattr(request, "chain_id", 1) or 1)
    debug = {
        "request_type": request_type,
        "chain_id": chain_id,
    }
    if isinstance(request, signer.TpSignTransactionRequest):
        raw_transaction = str(data.get("rawTransaction") or "").strip()
        if not raw_transaction:
            raise ValueError("树莓派未返回签名交易")
        raw_bytes = _hex_to_bytes(raw_transaction)
        if raw_bytes and raw_bytes[0] in (0x01, 0x02):
            signature_bytes, signature_debug = _extract_typed_transaction_signature_details(raw_transaction)
        else:
            signature_bytes, signature_debug = _extract_legacy_transaction_signature_details(
                raw_transaction,
                chain_id,
                v_mode=legacy_v_mode,
            )
        debug.update(signature_debug)
        debug.update(_eth_signature_request_debug_context(request, signature_bytes))
        return signature_bytes, debug

    signature_hex = str(data.get("signature") or "").strip()
    if not signature_hex:
        raise ValueError("树莓派未返回签名结果")
    signature_bytes = _normalize_eth_message_signature_bytes(_hex_to_bytes(signature_hex))
    if len(signature_bytes) != 65:
        raise ValueError("树莓派返回的签名长度不正确")
    debug.update(
        {
            "transaction_type": "typed-data" if "typed" in request_type.lower() else "message",
            "v": signature_bytes[-1],
            "recovery_id": _eth_signature_recovery_id(signature_bytes[-1]),
            "signature_output_byte": signature_bytes[-1],
        }
    )
    debug.update(_eth_signature_request_debug_context(request, signature_bytes))
    return signature_bytes, debug


def _build_eth_signature_ur(
    request_id: str | None,
    signature_bytes: bytes,
    origin: str | None = None,
    request_id_cbor: object | None = None,
) -> str:
    if len(signature_bytes) < 65:
        raise ValueError("签名结果长度不正确")

    request_id_value = _request_id_response_cbor(request_id, request_id_cbor=request_id_cbor)
    origin_text = str(origin or "").strip()

    cbor = CBOREncoder()
    field_count = 1
    if request_id_value is not None:
        field_count += 1
    if origin_text and WEB3_ETH_SIGNATURE_INCLUDE_ORIGIN:
        field_count += 1
    cbor.encodeMapSize(field_count)
    if request_id_value is not None:
        cbor.encodeUnsigned(1)
        _encode_request_id_cbor_value(cbor, request_id_value)
    cbor.encodeUnsigned(2)
    cbor.encodeBytes(signature_bytes)
    if origin_text and WEB3_ETH_SIGNATURE_INCLUDE_ORIGIN:
        cbor.encodeUnsigned(3)
        cbor.encodeText(origin_text)
    return UREncoder.encode(UR("eth-signature", cbor.get_bytes()))


def _build_web3_request_header_pages(
    wallet_name: str | None,
    request_format: str | None,
    response_protocol: str | None,
    origin: str | None,
    chain_id: int,
) -> list[str]:
    native_header_lines = [
        f"来源钱包: {wallet_name or 'Web3 钱包'}",
        f"请求格式: {request_format or 'Keystone / AirGap UR'}",
        f"回传格式: {response_protocol or '-'}",
        "签名完成后",
        "原钱包直接扫树莓派结果码",
        "手机不用再回扫",
    ]
    if origin:
        native_header_lines.insert(3, f"DApp: {origin}")
    support_note = _web3_wallet_support_note(origin, chain_id)
    if support_note:
        native_header_lines.extend(["", support_note])
    return _paginate_report_lines(native_header_lines, lines_per_page=9)


def _finalize_native_wallet_response(payload: str, response_text: str) -> str:
    normalized = (payload or "").strip()
    if _is_web3_eth_sign_request_payload(normalized):
        request = _parse_web3_eth_sign_request_from_payload(normalized)
        signer = _load_signer_preview_module()
        tp_request = signer.parse_sign_request(_build_tp_payload_from_web3_request(request))
        signature_bytes, signature_debug = _extract_signature_bytes_with_debug_from_tp_response(
            tp_request,
            response_text,
            legacy_v_mode=_web3_legacy_signature_v_mode(request.origin, request.chain_id),
        )
        result = _build_eth_signature_ur(
            request.request_id,
            signature_bytes,
            origin=request.origin,
            request_id_cbor=request.request_id_cbor,
        )
        signature_debug.update(
            {
                "request_id": request.request_id or None,
                "origin": request.origin or None,
                "derivation_path": request.derivation_path or None,
                "request_address": request.address or None,
            }
        )
        _remember_eth_signature_debug_context(result, signature_debug)
        return result

    if not _is_web3_native_relay_payload(normalized):
        return response_text

    request_meta = _extract_web3_native_relay_request(normalized)
    if request_meta.get("response_protocol") != "eth-signature":
        return response_text

    signer = _load_signer_preview_module()
    request = signer.parse_sign_request(request_meta["payload"])
    request_id = request_meta.get("request_id") or getattr(request, "request_id", "")
    origin = request_meta.get("origin") or None
    legacy_v_mode = _web3_legacy_signature_v_mode(origin, int(getattr(request, "chain_id", 1) or 1))
    signature_bytes, signature_debug = _extract_signature_bytes_with_debug_from_tp_response(
        request,
        response_text,
        legacy_v_mode=legacy_v_mode,
    )
    result = _build_eth_signature_ur(request_id, signature_bytes, origin=origin)
    signature_debug.update(
        {
            "request_id": request_id or None,
            "origin": origin or None,
            "derivation_path": request_meta.get("derivation_path") or None,
        }
    )
    _remember_eth_signature_debug_context(result, signature_debug)
    return result


def _build_tp_request_review_pages(payload: str) -> tuple[str, list[str]]:
    signer = _load_signer_preview_module()
    review_payload = _resolve_sign_execution_payload(payload)
    request = signer.parse_sign_request(review_payload)
    request_type = type(request).__name__
    pages: list[str] = []
    if _is_web3_eth_sign_request_payload(payload):
        web3_request = _parse_web3_eth_sign_request_from_payload(payload)
        wallet_name = _web3_wallet_meta(web3_request.origin)[1]
        pages.extend(
            _build_web3_request_header_pages(
                wallet_name=wallet_name,
                request_format="Keystone / AirGap UR",
                response_protocol="eth-signature",
                origin=web3_request.origin,
                chain_id=int(getattr(request, "chain_id", web3_request.chain_id) or web3_request.chain_id or 1),
            )
        )
    elif _is_web3_native_relay_payload(payload):
        request_meta = _extract_web3_native_relay_request(payload)
        pages.extend(
            _build_web3_request_header_pages(
                wallet_name=request_meta.get("wallet_name") or "Web3 钱包",
                request_format=request_meta.get("format") or "Keystone / AirGap UR",
                response_protocol=request_meta.get("response_protocol") or "-",
                origin=request_meta.get("origin") or None,
                chain_id=int(getattr(request, "chain_id", 1) or 1),
            )
        )

    if request_type == "TpSignTransactionRequest":
        tx = signer.EvmTxEncoder.from_tp_request(request)
        data_hex = "0x" + tx.data.hex() if tx.data else "0x"
        method_id = f"0x{tx.data[:4].hex()}" if len(tx.data) >= 4 else "-"
        lines = [
            f"类型: 交易签名",
            f"动作: {request.action}",
            f"网络: {_evm_chain_name(request.chain_id)}",
            f"chainId: {request.chain_id}",
        ]
        _append_chunked_value(lines, "签名地址:", request.address or "-")
        _append_chunked_value(lines, "接收方:", tx.to or "(合约创建)")
        lines.extend(
            [
                f"金额: {tx.value} wei",
                f"约等于: {_format_native_amount_wei(tx.value)} ETH",
                f"nonce: {tx.nonce}",
                f"交易类型: {tx.tx_type}",
                f"requestId: {request.request_id or '-'}",
            ]
        )
        pages.extend(_paginate_report_lines(lines, lines_per_page=9))

        fee_lines = [f"gasLimit: {tx.gas_limit}"]
        if tx.gas_price is not None:
            fee_lines.append(f"gasPrice: {tx.gas_price}")
        else:
            fee_lines.append(f"maxPriorityFee: {tx.max_priority_fee_per_gas or 0}")
            fee_lines.append(f"maxFee: {tx.max_fee_per_gas or 0}")
        fee_lines.extend(
            [
                f"合约调用: {'是' if len(tx.data) > 0 else '否'}",
                f"methodId: {method_id}",
                f"dataBytes: {len(tx.data)}",
                f"accessList: {len(tx.access_list)}",
            ]
        )
        pages.extend(_paginate_report_lines(fee_lines, lines_per_page=9))

        if tx.data:
            data_lines = ["data 预览:"]
            data_lines.extend(_chunk_text(data_hex[:258], width=18).splitlines())
            if len(data_hex) > 258:
                data_lines.append("...")
            pages.extend(_paginate_report_lines(data_lines, lines_per_page=9))

        return "交易核对", pages

    if request_type == "TpSignPersonalMessageRequest":
        message_preview = _preview_text_line(request.message, max_len=180)
        lines = [
            "类型: personalSign",
            f"动作: {request.action}",
            f"网络: {_evm_chain_name(request.chain_id)}",
            f"chainId: {request.chain_id}",
        ]
        _append_chunked_value(lines, "签名地址:", request.address or "-")
        lines.extend(
            [
                f"消息字节数: {len(_decode_message_bytes_for_preview(request.message))}",
                f"requestId: {request.request_id or '-'}",
                "消息预览:",
            ]
        )
        lines.extend(_chunk_text(message_preview, width=18).splitlines())
        return "消息核对", _paginate_report_lines(lines, lines_per_page=9)

    if request_type == "TpSignTypedDataRequest":
        try:
            typed_data = json.loads(request.typed_data_json)
        except Exception:
            typed_data = {}
        domain = typed_data.get("domain") if isinstance(typed_data, dict) else {}
        if not isinstance(domain, dict):
            domain = {}
        message = typed_data.get("message") if isinstance(typed_data, dict) else None
        message_keys = len(message) if isinstance(message, dict) else 0
        lines = [
            "类型: signTypedData",
            f"动作: {request.action}",
            f"网络: {_evm_chain_name(request.chain_id)}",
            f"chainId: {request.chain_id}",
        ]
        _append_chunked_value(lines, "签名地址:", request.address or "-")
        lines.extend(
            [
                f"primaryType: {request.primary_type or '-'}",
                f"legacy: {'是' if request.is_legacy else '否'}",
                f"typedDataBytes: {len(request.typed_data_json.encode('utf-8'))}",
                f"messageFields: {message_keys}",
                f"requestId: {request.request_id or '-'}",
            ]
        )
        if domain.get("name"):
            _append_chunked_value(lines, "domain.name:", str(domain.get("name")))
        if domain.get("verifyingContract"):
            _append_chunked_value(lines, "verifyingContract:", str(domain.get("verifyingContract")))
        pages.extend(_paginate_report_lines(lines, lines_per_page=9))

        preview_lines = ["typedData 预览:"]
        preview_lines.extend(
            _chunk_text(_preview_text_line(request.typed_data_json, max_len=220), width=18).splitlines()
        )
        pages.extend(_paginate_report_lines(preview_lines, lines_per_page=9))
        return "TypedData 核对", pages

    raise ValueError(f"不支持的签名请求类型: {request_type}")


def _seed_sign_evm_digest(seed: Seed, derivation_path: str, digest: bytes):
    if isinstance(seed, TransientWordSeed):
        raise ValueError("这条是临时假助记词，不能用于真实签名。")
    if len(digest) != 32:
        raise ValueError("EVM 签名摘要长度不正确。")

    from embit.util import secp256k1

    signer = _load_signer_preview_module()
    normalized_path = _normalize_bip32_path(derivation_path)
    root = seed.get_root(SettingsConstants.MAINNET)
    derived_key = root.derive(normalized_path).key
    pubkey = _to_uncompressed_secp256k1_pubkey(derived_key.get_public_key().sec())
    signer_address = signer.ethereum_address_from_pubkey(pubkey)

    recoverable_sig = bytes(secp256k1.ecdsa_sign_recoverable(digest, derived_key._secret))
    if len(recoverable_sig) != 65:
        raise ValueError("助记词签名结果长度不正确。")

    compact_sig, rec_id = secp256k1.ecdsa_recoverable_signature_serialize_compact(recoverable_sig)
    compact_sig = bytes(compact_sig)
    rec_id = int(rec_id)
    if len(compact_sig) != 64:
        raise ValueError("助记词签名结果紧凑序列化长度不正确。")

    r = int.from_bytes(compact_sig[0:32], "big")
    s = int.from_bytes(compact_sig[32:64], "big")
    if s > signer.SECP256K1_HALF_N:
        s = signer.SECP256K1_N - s
        rec_id ^= 1

    try:
        rec_id = int(signer.recover_rec_id_by_address(digest, r, s, signer_address))
    except Exception as exc:
        raise ValueError("助记词签名结果无法恢复为派生地址。") from exc

    return signer.SignatureParts(rec_id=rec_id, r=r, s=s), signer_address


def _satochip_sign_evm_digest(connector, derivation_path: str, digest: bytes):
    if len(digest) != 32:
        raise ValueError("EVM 签名摘要长度不正确。")

    from seedsigner.helpers.satochip_signer import format_path_string

    signer = _load_signer_preview_module()
    normalized_path = _normalize_bip32_path(derivation_path)
    key, _chaincode = connector.card_bip32_get_extendedkey(format_path_string(normalized_path))
    pubkey = key.get_public_key_bytes(compressed=False)
    signer_address = _derive_evm_address_from_pubkey_bytes(pubkey)

    response, sw1, sw2 = connector.card_sign_transaction_hash(0xFF, list(digest), None)
    if sw1 != 0x90 or sw2 != 0x00:
        raise ValueError(format_sw_error(sw1, sw2))

    dersig = bytes(response or b"")
    if not dersig:
        raise ValueError("智能卡未返回签名结果。")

    parser = getattr(connector, "parser", None)
    parse_rsv = getattr(parser, "parse_rsv_from_dersig", None)
    if not callable(parse_rsv):
        raise ValueError("智能卡解析器缺少 EVM 签名恢复能力。")

    r, s, rec_id, _sigstring = parse_rsv(dersig, digest, key)
    r = int(r)
    s = int(s)
    rec_id = int(rec_id)
    try:
        rec_id = int(signer.recover_rec_id_by_address(digest, r, s, signer_address))
    except Exception:
        pass

    return signer.SignatureParts(rec_id=rec_id, r=r, s=s), signer_address


def _verify_seed_signer_address(signer, request, signer_address: str) -> None:
    request_address = str(getattr(request, "address", "") or "").strip()
    if not request_address:
        return
    expected = signer.normalize_eth_address(request_address)
    if expected and expected.lower() != signer_address.lower():
        raise ValueError(
            "签名地址与已加载助记词派生地址不一致。\n"
            f"请求地址: {expected}\n"
            f"助记词地址: {signer_address}"
        )


def _signature_output_value(signature_bytes: bytes) -> int:
    if len(signature_bytes) < 65:
        raise ValueError("签名结果长度不正确")
    return int.from_bytes(signature_bytes[64:], "big")


def _sign_web3_eth_request_with_seed(
    request: Web3EthSignRequest,
    seed: Seed,
    *,
    derivation_path: str | None = None,
    request_address: str | None = None,
    request_id: str | None = None,
    origin: str | None = None,
):
    signer = _load_signer_preview_module()
    request_sign_data = bytes(request.sign_data or b"")
    if not request_sign_data:
        raise ValueError("Web3 请求缺少 signData")

    normalized_path = _normalize_bip32_path(derivation_path or request.derivation_path or DEFAULT_DERIVATION_PATH)
    request_type_id = int(getattr(request, "data_type", 0) or 0)
    request_address = str(request_address or request.address or "").strip() or None
    request_id = str(request_id or request.request_id or "").strip() or None
    origin = str(origin or request.origin or "").strip() or None
    chain_id = int(getattr(request, "chain_id", 1) or 1)
    digest_label = "签名哈希"
    result_label = "签名Hex"
    debug_context = {
        "request_id": request_id,
        "origin": origin,
        "derivation_path": normalized_path,
        "chain_id": chain_id,
        "request_address": request_address,
    }

    if request_type_id in (1, 4):
        digest = signer.keccak256(request_sign_data)
        sig, signer_address = _seed_sign_evm_digest(seed, normalized_path, digest)
        if request_address:
            expected = signer.normalize_eth_address(request_address)
            if expected and expected.lower() != signer_address.lower():
                raise ValueError(
                    "签名地址与 Web3 请求不一致。\n"
                    f"请求地址: {expected}\n"
                    f"助记词地址: {signer_address}"
                )
        legacy_v_mode = _web3_legacy_signature_v_mode(origin, chain_id) if request_type_id == 1 else None
        signature_bytes = (
            _int_to_fixed_bytes(sig.r, 32)
            + _int_to_fixed_bytes(sig.s, 32)
            + (
                bytes([sig.rec_id & 0xFF])
                if request_type_id == 4
                else _legacy_signature_output_bytes(sig.rec_id, v_mode=legacy_v_mode, chain_id=chain_id)
            )
        )
        debug_context.update(
            {
                "transaction_type": (
                    "legacy"
                    if request_type_id == 1
                    else {0x01: "eip-2930", 0x02: "eip-1559"}.get(request_sign_data[0], "typed-transaction")
                ),
                "digest_hex": digest.hex(),
                "recovered_address": signer_address,
                "recovered_matches_request": (
                    signer_address.lower() == signer.normalize_eth_address(request_address).lower()
                    if request_address
                    else None
                ),
                "signature_output_byte": _signature_output_value(signature_bytes),
            }
        )
        if request_type_id == 1:
            debug_context.update(
                {
                    "v": chain_id * 2 + 35 + sig.rec_id,
                    "recovery_id": sig.rec_id,
                    "legacy_v_mode": _normalize_legacy_v_mode(legacy_v_mode),
                }
            )
        else:
            debug_context.update({"y_parity": sig.rec_id})
        digest_label = "交易哈希"
    elif request_type_id == 3:
        prefix = f"\x19Ethereum Signed Message:\n{len(request_sign_data)}".encode("utf-8")
        digest = signer.keccak256(prefix + request_sign_data)
        sig, signer_address = _seed_sign_evm_digest(seed, normalized_path, digest)
        if request_address:
            expected = signer.normalize_eth_address(request_address)
            if expected and expected.lower() != signer_address.lower():
                raise ValueError(
                    "签名地址与 Web3 请求不一致。\n"
                    f"请求地址: {expected}\n"
                    f"助记词地址: {signer_address}"
                )
        signature_bytes = _normalize_eth_message_signature_bytes(
            _int_to_fixed_bytes(sig.r, 32) + _int_to_fixed_bytes(sig.s, 32) + bytes([27 + sig.rec_id])
        )
        debug_context.update(
            {
                "transaction_type": "message",
                "digest_hex": digest.hex(),
                "recovered_address": signer_address,
                "recovered_matches_request": (
                    signer_address.lower() == signer.normalize_eth_address(request_address).lower()
                    if request_address
                    else None
                ),
                "v": signature_bytes[-1],
                "recovery_id": sig.rec_id,
                "signature_output_byte": signature_bytes[-1],
            }
        )
        digest_label = "消息哈希"
    elif request_type_id == 2:
        typed_data_json = request_sign_data.decode("utf-8")
        digest = signer.typed_data_hash(typed_data_json)
        sig, signer_address = _seed_sign_evm_digest(seed, normalized_path, digest)
        if request_address:
            expected = signer.normalize_eth_address(request_address)
            if expected and expected.lower() != signer_address.lower():
                raise ValueError(
                    "签名地址与 Web3 请求不一致。\n"
                    f"请求地址: {expected}\n"
                    f"助记词地址: {signer_address}"
                )
        signature_bytes = _normalize_eth_message_signature_bytes(
            _int_to_fixed_bytes(sig.r, 32) + _int_to_fixed_bytes(sig.s, 32) + bytes([27 + sig.rec_id])
        )
        debug_context.update(
            {
                "transaction_type": "typed-data",
                "digest_hex": digest.hex(),
                "recovered_address": signer_address,
                "recovered_matches_request": (
                    signer_address.lower() == signer.normalize_eth_address(request_address).lower()
                    if request_address
                    else None
                ),
                "v": signature_bytes[-1],
                "recovery_id": sig.rec_id,
                "signature_output_byte": signature_bytes[-1],
            }
        )
        digest_label = "TypedData哈希"
    else:
        raise ValueError(f"暂不支持的 Web3 请求类型: {request_type_id}")

    result = _build_eth_signature_ur(
        request_id,
        signature_bytes,
        origin=origin,
        request_id_cbor=request.request_id_cbor,
    )
    _remember_eth_signature_debug_context(result, debug_context)
    return signer.SigningOutcome(
        response_payload=result,
        signer_address=signer_address,
        digest_hex=signer.ensure_hex_prefix(digest.hex()),
        digest_label=digest_label,
        result_hex=signer.ensure_hex_prefix(signature_bytes.hex()),
        result_label=result_label,
    )


def _sign_web3_eth_request_with_satochip(
    request: Web3EthSignRequest,
    connector,
    *,
    derivation_path: str | None = None,
    request_address: str | None = None,
    request_id: str | None = None,
    origin: str | None = None,
):
    signer = _load_signer_preview_module()
    request_sign_data = bytes(request.sign_data or b"")
    if not request_sign_data:
        raise ValueError("Web3 请求缺少 signData")

    normalized_path = _normalize_bip32_path(derivation_path or request.derivation_path or DEFAULT_DERIVATION_PATH)
    request_type_id = int(getattr(request, "data_type", 0) or 0)
    request_address = str(request_address or request.address or "").strip() or None
    request_id = str(request_id or request.request_id or "").strip() or None
    origin = str(origin or request.origin or "").strip() or None
    chain_id = int(getattr(request, "chain_id", 1) or 1)
    digest_label = "签名哈希"
    result_label = "签名Hex"
    debug_context = {
        "request_id": request_id,
        "origin": origin,
        "derivation_path": normalized_path,
        "chain_id": chain_id,
        "request_address": request_address,
    }

    def _verify_request_address(signer_address: str) -> None:
        if not request_address:
            return
        expected = signer.normalize_eth_address(request_address)
        if expected and expected.lower() != signer_address.lower():
            raise ValueError(
                "签名地址与 Web3 请求不一致。\n"
                f"请求地址: {expected}\n"
                f"智能卡地址: {signer_address}"
            )

    if request_type_id in (1, 4):
        digest = signer.keccak256(request_sign_data)
        sig, signer_address = _satochip_sign_evm_digest(connector, normalized_path, digest)
        _verify_request_address(signer_address)
        legacy_v_mode = _web3_legacy_signature_v_mode(origin, chain_id) if request_type_id == 1 else None
        signature_bytes = (
            _int_to_fixed_bytes(sig.r, 32)
            + _int_to_fixed_bytes(sig.s, 32)
            + (
                bytes([sig.rec_id & 0xFF])
                if request_type_id == 4
                else _legacy_signature_output_bytes(sig.rec_id, v_mode=legacy_v_mode, chain_id=chain_id)
            )
        )
        debug_context.update(
            {
                "transaction_type": (
                    "legacy"
                    if request_type_id == 1
                    else {0x01: "eip-2930", 0x02: "eip-1559"}.get(request_sign_data[0], "typed-transaction")
                ),
                "digest_hex": digest.hex(),
                "recovered_address": signer_address,
                "recovered_matches_request": (
                    signer_address.lower() == signer.normalize_eth_address(request_address).lower()
                    if request_address
                    else None
                ),
                "signature_output_byte": _signature_output_value(signature_bytes),
            }
        )
        if request_type_id == 1:
            debug_context.update(
                {
                    "v": chain_id * 2 + 35 + sig.rec_id,
                    "recovery_id": sig.rec_id,
                    "legacy_v_mode": _normalize_legacy_v_mode(legacy_v_mode),
                }
            )
        else:
            debug_context.update({"y_parity": sig.rec_id})
        digest_label = "交易哈希"
    elif request_type_id == 3:
        prefix = f"\x19Ethereum Signed Message:\n{len(request_sign_data)}".encode("utf-8")
        digest = signer.keccak256(prefix + request_sign_data)
        sig, signer_address = _satochip_sign_evm_digest(connector, normalized_path, digest)
        _verify_request_address(signer_address)
        signature_bytes = _normalize_eth_message_signature_bytes(
            _int_to_fixed_bytes(sig.r, 32) + _int_to_fixed_bytes(sig.s, 32) + bytes([27 + sig.rec_id])
        )
        debug_context.update(
            {
                "transaction_type": "message",
                "digest_hex": digest.hex(),
                "recovered_address": signer_address,
                "recovered_matches_request": (
                    signer_address.lower() == signer.normalize_eth_address(request_address).lower()
                    if request_address
                    else None
                ),
                "v": signature_bytes[-1],
                "recovery_id": sig.rec_id,
                "signature_output_byte": signature_bytes[-1],
            }
        )
        digest_label = "消息哈希"
    elif request_type_id == 2:
        typed_data_json = request_sign_data.decode("utf-8")
        digest = signer.typed_data_hash(typed_data_json)
        sig, signer_address = _satochip_sign_evm_digest(connector, normalized_path, digest)
        _verify_request_address(signer_address)
        signature_bytes = _normalize_eth_message_signature_bytes(
            _int_to_fixed_bytes(sig.r, 32) + _int_to_fixed_bytes(sig.s, 32) + bytes([27 + sig.rec_id])
        )
        debug_context.update(
            {
                "transaction_type": "typed-data",
                "digest_hex": digest.hex(),
                "recovered_address": signer_address,
                "recovered_matches_request": (
                    signer_address.lower() == signer.normalize_eth_address(request_address).lower()
                    if request_address
                    else None
                ),
                "v": signature_bytes[-1],
                "recovery_id": sig.rec_id,
                "signature_output_byte": signature_bytes[-1],
            }
        )
        digest_label = "TypedData哈希"
    else:
        raise ValueError(f"暂不支持的 Web3 请求类型: {request_type_id}")

    result = _build_eth_signature_ur(
        request_id,
        signature_bytes,
        origin=origin,
        request_id_cbor=request.request_id_cbor,
    )
    _remember_eth_signature_debug_context(result, debug_context)
    return signer.SigningOutcome(
        response_payload=result,
        signer_address=signer_address,
        digest_hex=signer.ensure_hex_prefix(digest.hex()),
        digest_label=digest_label,
        result_hex=signer.ensure_hex_prefix(signature_bytes.hex()),
        result_label=result_label,
    )


def _sign_web3_native_relay_payload_with_seed(payload: str, seed: Seed, derivation_path: str):
    normalized = (payload or "").strip()
    if not _is_web3_native_relay_payload(normalized):
        return None

    request_meta = _extract_web3_native_relay_request(normalized)
    if request_meta.get("response_protocol") != "eth-signature":
        return None

    request_sign_data_hex = str(request_meta.get("request_sign_data_hex") or "").strip().lower()
    request_type_id = str(request_meta.get("request_data_type_id") or "").strip()
    if not request_sign_data_hex or not request_type_id:
        derived_type_id, derived_sign_data = _derive_web3_native_request_sign_data(request_meta.get("payload") or "")
        if not request_type_id and derived_type_id is not None:
            request_type_id = str(derived_type_id)
        if not request_sign_data_hex and isinstance(derived_sign_data, (bytes, bytearray)) and derived_sign_data:
            request_sign_data_hex = bytes(derived_sign_data).hex()

    try:
        request_sign_data = _hex_to_bytes(request_sign_data_hex)
    except Exception:
        return None
    if not request_sign_data or not request_type_id:
        return None

    request = Web3EthSignRequest(
        request_id=str(request_meta.get("request_id") or "").strip() or None,
        sign_data=request_sign_data,
        data_type=int(request_type_id),
        chain_id=int(str(request_meta.get("chain_id") or "1") or 1),
        derivation_path=str(request_meta.get("derivation_path") or derivation_path or DEFAULT_DERIVATION_PATH),
        address=str(request_meta.get("address") or "").strip() or None,
        origin=str(request_meta.get("origin") or "").strip() or None,
    )
    return _sign_web3_eth_request_with_seed(
        request,
        seed,
        derivation_path=str(request_meta.get("derivation_path") or derivation_path or DEFAULT_DERIVATION_PATH),
        request_address=str(request_meta.get("address") or request_meta.get("expected_address") or "").strip() or None,
        request_id=str(request_meta.get("request_id") or "").strip() or None,
        origin=str(request_meta.get("origin") or "").strip() or None,
    )


def _sign_web3_native_relay_payload_with_satochip(payload: str, connector, derivation_path: str):
    normalized = (payload or "").strip()
    if not _is_web3_native_relay_payload(normalized):
        return None

    request_meta = _extract_web3_native_relay_request(normalized)
    if request_meta.get("response_protocol") != "eth-signature":
        return None

    request_sign_data_hex = str(request_meta.get("request_sign_data_hex") or "").strip().lower()
    request_type_id = str(request_meta.get("request_data_type_id") or "").strip()
    if not request_sign_data_hex or not request_type_id:
        derived_type_id, derived_sign_data = _derive_web3_native_request_sign_data(request_meta.get("payload") or "")
        if not request_type_id and derived_type_id is not None:
            request_type_id = str(derived_type_id)
        if not request_sign_data_hex and isinstance(derived_sign_data, (bytes, bytearray)) and derived_sign_data:
            request_sign_data_hex = bytes(derived_sign_data).hex()

    try:
        request_sign_data = _hex_to_bytes(request_sign_data_hex)
    except Exception:
        return None
    if not request_sign_data or not request_type_id:
        return None

    request = Web3EthSignRequest(
        request_id=str(request_meta.get("request_id") or "").strip() or None,
        sign_data=request_sign_data,
        data_type=int(request_type_id),
        chain_id=int(str(request_meta.get("chain_id") or "1") or 1),
        derivation_path=str(request_meta.get("derivation_path") or derivation_path or DEFAULT_DERIVATION_PATH),
        address=str(request_meta.get("address") or "").strip() or None,
        origin=str(request_meta.get("origin") or "").strip() or None,
    )
    return _sign_web3_eth_request_with_satochip(
        request,
        connector,
        derivation_path=str(request_meta.get("derivation_path") or derivation_path or DEFAULT_DERIVATION_PATH),
        request_address=str(request_meta.get("address") or request_meta.get("expected_address") or "").strip() or None,
        request_id=str(request_meta.get("request_id") or "").strip() or None,
        origin=str(request_meta.get("origin") or "").strip() or None,
    )


def _sign_tp_payload_with_seed(payload: str, seed: Seed, derivation_path: str):
    normalized = (payload or "").strip()
    if _is_web3_eth_sign_request_payload(normalized):
        request = _parse_web3_eth_sign_request_from_payload(normalized)
        return _sign_web3_eth_request_with_seed(
            request,
            seed,
            derivation_path=request.derivation_path,
            request_address=request.address,
            request_id=request.request_id,
            origin=request.origin,
        )

    native_outcome = _sign_web3_native_relay_payload_with_seed(payload, seed, derivation_path)
    if native_outcome is not None:
        return native_outcome

    signer = _load_signer_preview_module()
    execution_payload = _resolve_sign_execution_payload(payload)
    request = signer.parse_sign_request(execution_payload)
    normalized_path = _normalize_bip32_path(derivation_path)

    if isinstance(request, signer.TpSignTransactionRequest):
        try:
            tx = signer.EvmTxEncoder.from_tp_request(request)
            digest = signer.EvmTxEncoder.transaction_hash(tx)
        except Exception as exc:
            raise ValueError(str(exc)) from exc

        sig, signer_address = _seed_sign_evm_digest(seed, normalized_path, digest)
        _verify_seed_signer_address(signer, request, signer_address)
        signed_payload = signer.EvmTxEncoder.signed_payload(tx, sig.rec_id, sig.r, sig.s)
        raw_tx = signer.ensure_hex_prefix(signed_payload.hex())
        outcome = signer.SigningOutcome(
            response_payload=signer.build_sign_response(request, raw_tx, signer_address),
            signer_address=signer_address,
            digest_hex=signer.ensure_hex_prefix(digest.hex()),
            digest_label="交易哈希",
            result_hex=raw_tx,
            result_label="RawTx",
        )
        return signer.SigningOutcome(
            response_payload=_finalize_native_wallet_response(payload, outcome.response_payload),
            signer_address=outcome.signer_address,
            digest_hex=outcome.digest_hex,
            digest_label=outcome.digest_label,
            result_hex=outcome.result_hex,
            result_label=outcome.result_label,
        )

    if isinstance(request, signer.TpSignPersonalMessageRequest):
        digest = signer.personal_sign_hash(request.message)
        sig, signer_address = _seed_sign_evm_digest(seed, normalized_path, digest)
        _verify_seed_signer_address(signer, request, signer_address)
        signature_hex = signer.build_eth_message_signature(sig.rec_id, sig.r, sig.s)
        outcome = signer.SigningOutcome(
            response_payload=signer.build_sign_response(request, signature_hex, signer_address),
            signer_address=signer_address,
            digest_hex=signer.ensure_hex_prefix(digest.hex()),
            digest_label="消息哈希",
            result_hex=signature_hex,
            result_label="签名Hex",
        )
        return signer.SigningOutcome(
            response_payload=_finalize_native_wallet_response(payload, outcome.response_payload),
            signer_address=outcome.signer_address,
            digest_hex=outcome.digest_hex,
            digest_label=outcome.digest_label,
            result_hex=outcome.result_hex,
            result_label=outcome.result_label,
        )

    if isinstance(request, signer.TpSignTypedDataRequest):
        if request.is_legacy or request.typed_data_json.strip().startswith("["):
            raise ValueError("暂不支持 signTypedDataLegacy 数组格式，请在 TP 端改用 signTypedData/signTypeDataV4。")
        digest = signer.typed_data_hash(request.typed_data_json)
        sig, signer_address = _seed_sign_evm_digest(seed, normalized_path, digest)
        _verify_seed_signer_address(signer, request, signer_address)
        signature_hex = signer.build_eth_message_signature(sig.rec_id, sig.r, sig.s)
        outcome = signer.SigningOutcome(
            response_payload=signer.build_sign_response(request, signature_hex, signer_address),
            signer_address=signer_address,
            digest_hex=signer.ensure_hex_prefix(digest.hex()),
            digest_label="TypedData哈希",
            result_hex=signature_hex,
            result_label="签名Hex",
        )
        return signer.SigningOutcome(
            response_payload=_finalize_native_wallet_response(payload, outcome.response_payload),
            signer_address=outcome.signer_address,
            digest_hex=outcome.digest_hex,
            digest_label=outcome.digest_label,
            result_hex=outcome.result_hex,
            result_label=outcome.result_label,
        )

    raise ValueError("未知签名请求类型。")


def _sign_tp_payload_with_satochip(payload: str, connector, derivation_path: str):
    normalized = (payload or "").strip()
    if _is_web3_eth_sign_request_payload(normalized):
        request = _parse_web3_eth_sign_request_from_payload(normalized)
        return _sign_web3_eth_request_with_satochip(
            request,
            connector,
            derivation_path=request.derivation_path,
            request_address=request.address,
            request_id=request.request_id,
            origin=request.origin,
        )

    native_outcome = _sign_web3_native_relay_payload_with_satochip(payload, connector, derivation_path)
    if native_outcome is not None:
        return native_outcome

    return None


def _hex_payload_stats(hex_text: str) -> tuple[int | None, int]:
    value = str(hex_text or "").strip()
    if not value:
        return None, 0
    if value.startswith(("0x", "0X")):
        value = value[2:]
    if len(value) % 2 != 0:
        return None, len(value)
    try:
        bytes.fromhex(value)
    except Exception:
        return None, len(value)
    return len(value) // 2, len(value)


def _format_signed_byte_size(byte_len: int | None, char_len: int) -> tuple[str, str]:
    return (
        f"{byte_len:,}" if byte_len is not None else "-",
        f"{char_len:,}",
    )


def _describe_review_qr_delivery(qr_encoder) -> tuple[str, int, str]:
    frame_count = 1
    if qr_encoder is not None:
        try:
            frame_count = max(1, int(qr_encoder.seq_len()))
        except Exception:
            frame_count = 1
    if frame_count == 1:
        return "单张二维码", frame_count, "下一步会显示 1 张二维码"
    return f"连续二维码（共 {frame_count} 张）", frame_count, f"下一步会显示 {frame_count} 张连续二维码"


def _eth_signature_qr_parts(response_text: str, qr_encoder=None) -> list[str]:
    if qr_encoder is not None:
        parts = [str(part).strip() for part in list(getattr(qr_encoder, "parts", []) or []) if str(part).strip()]
        if parts:
            return parts
    response = str(response_text or "").strip()
    return [response] if response else []


def _build_eth_signature_debug_snapshot(response_text: str, qr_encoder=None) -> dict:
    response = str(response_text or "").strip()
    decoder = URDecoder()
    if not decoder.receive_part(response) or not decoder.is_complete():
        raise ValueError("eth-signature UR 无法解析为诊断快照")

    ur = decoder.result_message()
    root = _decode_cbor_root_map(ur.cbor)
    signature_bytes = root.get(2)
    if not isinstance(signature_bytes, bytes):
        raise ValueError("eth-signature 缺少 signatureBytes")

    request_id = _uuid_from_cbor(root.get(1))
    origin = root.get(3)
    if origin is not None and not isinstance(origin, str):
        raise ValueError("eth-signature origin 字段格式错误")

    pages = _eth_signature_qr_parts(response, qr_encoder=qr_encoder)
    context = _get_eth_signature_debug_context(response)
    context_origin = str(context.get("origin") or "").strip() or None
    snapshot = {
        "ur_type": str(getattr(ur, "type", "eth-signature")),
        "request_id_present": request_id is not None,
        "request_id": request_id,
        "cbor_keys": sorted(root.keys()),
        "signature_len": len(signature_bytes),
        "transaction_type": context.get("transaction_type") or "unknown",
        "chain_id": context.get("chain_id"),
        "request_address": context.get("request_address"),
        "derivation_path": context.get("derivation_path"),
        "digest_hex": context.get("digest_hex"),
        "recovered_address": context.get("recovered_address"),
        "recovered_matches_request": context.get("recovered_matches_request"),
        "v": context.get("v"),
        "y_parity": context.get("y_parity"),
        "recovery_id": context.get("recovery_id"),
        "legacy_v_mode": context.get("legacy_v_mode"),
        "signature_output_byte": context.get("signature_output_byte", int.from_bytes(signature_bytes[64:], "big")),
        "origin": origin.strip() if isinstance(origin, str) and origin.strip() else context_origin,
        "fragment_count": len(pages),
        "frame_char_lengths": [len(page) for page in pages],
        "first_frame": pages[0] if pages else "",
        "last_frame": pages[-1] if pages else "",
        "frame_repeat": int(getattr(qr_encoder, "frame_repeat", 1) or 1),
        "text_length": len(response),
        "request_type": context.get("request_type"),
    }
    return snapshot


def _ensure_eth_signature_debug_snapshot(response_text: str, qr_encoder=None) -> dict:
    return _build_eth_signature_debug_snapshot(response_text, qr_encoder=qr_encoder)


def _friendly_signed_psbt_format_label(input_qr_type: str | None, tx_hex: str | None = None) -> str:
    mapping = {
        "psbt__base43": "BASE43",
        "psbt__base64": "BASE64",
        "psbt__specter": "Specter",
        "psbt__ur2": "UR",
        "psbt__bbqr": "BBQr",
    }
    if input_qr_type in mapping:
        return mapping[input_qr_type]
    return "-"


def _build_tp_signed_response_review_pages(response_text: str, qr_encoder=None) -> tuple[str, list[str]]:
    response = str(response_text or "").strip()
    if not response:
        return "签名结果摘要", ["签名结果为空"]

    qr_style, frame_count, qr_hint = _describe_review_qr_delivery(qr_encoder)

    if response.lower().startswith("ur:eth-signature/"):
        char_len = len(response)
        pages = [
            "\n".join(
                [
                    "签名已完成",
                    "回传格式: eth-signature",
                    f"扫码方式: {qr_style}",
                    "原钱包直接扫描树莓派",
                    "不需要再扫回手机",
                ]
            )
        ]
        pages.append(
            "\n".join(
                [
                    "钱包类型: Keystone / OKX / Bitget",
                    f"二维码帧数: {frame_count}",
                    f"文本长度: {char_len:,}",
                    "请回到原钱包继续扫码",
                ]
            )
        )
        pages.append(
            "\n".join(
                [
                    qr_hint,
                    "刚才确认过的内容",
                    "就是下一步二维码里的结果",
                    "确认没问题后再点",
                    "“显示二维码”",
                ]
            )
        )
        return "原生签名结果", pages

    if response.lower().startswith("btctx:"):
        tx_hex = response[6:].strip()
        byte_len, char_len = _hex_payload_stats(tx_hex)
        byte_len_text, char_len_text = _format_signed_byte_size(byte_len, char_len)
        pages = [
            "\n".join(
                [
                "签名已完成",
                "手机扫回后可直接广播",
                f"扫码方式: {qr_style}",
                f"交易大小: {byte_len_text} 字节",
                f"文本长度: {char_len_text} 个字符",
                "确认后再显示二维码",
                ]
            )
        ]
        pages.append("\n".join(build_signature_health_lines(analyze_tx_signature_health(tx_hex))))
        pages.append(
            "\n".join(
                [
                    qr_hint,
                    "刚才确认过的内容",
                    "和下一步二维码是同一份结果",
                    "确认没问题后再点",
                    "“显示二维码”",
                ]
            )
        )
        return "签名结果摘要", pages

    namespace = "-"
    action = "-"
    query_text = ""
    if ":" in response:
        namespace, remainder = response.split(":", 1)
    else:
        remainder = response
    if "-" in remainder:
        action, query_text = remainder.split("-", 1)
    else:
        action = remainder
    if query_text.startswith("?"):
        query_text = query_text[1:]

    params = {key: values[-1] for key, values in parse_qs(query_text, keep_blank_values=True).items()}
    raw_data = params.get("data", "")
    try:
        data = json.loads(raw_data) if raw_data else {}
    except Exception:
        data = {}

    lines = [
        "签名已完成",
        f"签名来源: {namespace}",
        f"动作类型: {action or '-'}",
        f"扫码方式: {qr_style}",
    ]
    if params.get("network"):
        lines.append(f"网络: {params['network']}")
    if params.get("chain_id"):
        lines.append(f"链ID: {params['chain_id']}")

    pages = ["\n".join(lines)]

    detail_lines = []
    if isinstance(data, dict):
        signer_address = str(data.get("address") or "").strip()
        signature_hex = str(data.get("signature") or "").strip()
        raw_transaction = str(data.get("rawTransaction") or "").strip()

        if signer_address:
            detail_lines.append("签名地址:")
            detail_lines.extend(_chunk_text(signer_address, width=18).splitlines() or ["-"])

        if raw_transaction:
            byte_len, char_len = _hex_payload_stats(raw_transaction)
            byte_len_text, char_len_text = _format_signed_byte_size(byte_len, char_len)
            detail_lines.extend(
                [
                    "手机扫回后可直接广播",
                    f"交易大小: {byte_len_text} 字节",
                    f"文本长度: {char_len_text} 个字符",
                ]
            )
        elif signature_hex:
            byte_len, char_len = _hex_payload_stats(signature_hex)
            byte_len_text, char_len_text = _format_signed_byte_size(byte_len, char_len)
            detail_lines.extend(
                [
                    "结果: 签名文本",
                    f"签名大小: {byte_len_text} 字节",
                    f"文本长度: {char_len_text} 个字符",
                ]
            )
        elif raw_data:
            detail_lines.extend(
                [
                    "结果: 文本结果",
                    f"文本长度: {len(raw_data):,}",
                ]
            )
    elif raw_data:
        detail_lines.extend(
            [
                "结果: 文本结果",
                f"文本长度: {len(raw_data):,}",
            ]
        )

    if detail_lines:
        pages.append("\n".join(detail_lines))

    pages.append(
        "\n".join(
            [
                qr_hint,
                "刚才确认过的内容",
                "就是下一步二维码里的结果",
                "确认没问题后再点",
                "“显示二维码”",
            ]
        )
    )
    return "签名结果摘要", pages


def _build_tp_signed_psbt_review_pages(
    psbt_base64: str,
    input_qr_type: str | None = None,
    tx_hex: str | None = None,
    qr_encoder=None,
) -> tuple[str, list[str]]:
    qr_style, frame_count, qr_hint = _describe_review_qr_delivery(qr_encoder)
    result_label = "可直接广播的交易" if tx_hex else "已签名 PSBT"

    lines = [
        "签名已完成",
        f"结果: {result_label}",
        f"扫码方式: {qr_style}",
    ]

    pages = []
    parser = None
    if psbt_base64:
        try:
            from embit.psbt import PSBT
            from seedsigner.models.psbt_parser import PSBTParser

            parser = PSBTParser(PSBT.from_base64(psbt_base64), allow_unverified_single_sig_change=True)
            parser.parse()
        except Exception as exc:
            logger.warning("Failed to parse signed PSBT for review: %s", exc)
            lines.append("摘要解析失败")
        else:
            lines.extend(
                [
                    f"输入数: {parser.num_inputs}",
                    f"金额: {parser.spend_amount:,} sats",
                    f"矿工费: {parser.fee_amount:,} sats",
                ]
            )

    if parser is not None and parser.change_amount:
        lines.append(f"找零: {parser.change_amount:,} sats")
    else:
        lines.append("找零: 无")
    if parser is not None and parser.num_destinations > 1:
        lines.append(f"收款地址: {parser.num_destinations} 个")
    pages.append("\n".join(lines))

    if parser is not None and parser.destination_addresses:
        address = parser.destination_addresses[0]
        address_lines = [
            "收款地址:",
        ]
        address_lines.extend(_chunk_text(address, width=18).splitlines() or ["-"])
        if getattr(parser, "destination_amounts", None):
            address_lines.append(f"金额: {parser.destination_amounts[0]:,} sats")
        else:
            address_lines.append("金额: -")
        if parser.num_destinations > 1:
            address_lines.append(f"另有 {parser.num_destinations - 1} 个其他收款地址")
        pages.append("\n".join(address_lines))

    if tx_hex:
        byte_len, char_len = _hex_payload_stats(tx_hex)
        byte_len_text, char_len_text = _format_signed_byte_size(byte_len, char_len)
        pages.append(
            "\n".join(
                [
                    f"交易大小: {byte_len_text} 字节",
                    f"文本长度: {char_len_text} 个字符",
                    "这份结果可直接广播",
                ]
            )
        )

    signature_health_report = None
    if tx_hex:
        signature_health_report = analyze_tx_signature_health(tx_hex)
    elif psbt_base64:
        signature_health_report = analyze_psbt_signature_health(psbt_base64)
    if signature_health_report is not None:
        pages.append("\n".join(build_signature_health_lines(signature_health_report)))

    pages.append(
        "\n".join(
            [
                qr_hint,
                "刚才确认过的金额和地址",
                "就是下一步二维码里的结果",
                "确认没问题后再点",
                "“显示二维码”",
            ]
        )
    )
    return "签名结果摘要", pages


def _extract_xpub_from_output(stdout: str, xtype: str) -> str:
    normalized_prefixes = ("xpub", "ypub", "zpub", "tpub", "upub", "vpub")

    for line in stdout.splitlines():
        text = line.strip()
        if text.lower().startswith(f"{xtype.lower()}:"):
            return text.split(":", 1)[1].strip()

    for line in stdout.splitlines():
        for prefix in normalized_prefixes:
            marker = f"{prefix}:"
            if marker in line.lower():
                value = line.split(":", 1)[1].strip()
                if value.startswith(prefix):
                    return value

    for token in stdout.replace("\n", " ").split():
        if token.startswith(normalized_prefixes):
            return token.strip()

    raise ValueError("未从输出中解析到扩展公钥")


def _set_runtime_mode(tp_only: bool) -> None:
    from seedsigner.controller import Controller

    os.environ["OFFLINE_SIGNER_MODE"] = "1" if tp_only else "0"
    os.environ["TP_ONLY_MODE"] = "1" if tp_only else "0"

    controller = Controller.get_instance()
    controller.screensaver_activation_ms = (
        TP_MODE_SCREENSAVER_MS if tp_only else DEFAULT_SCREENSAVER_MS
    )
    controller.reset_screensaver_timeout()


def _official_home_destination() -> Destination:
    from seedsigner.views.view import MainMenuView

    _set_runtime_mode(False)
    return Destination(MainMenuView, clear_history=True)


def _tp_home_destination() -> Destination:
    _set_runtime_mode(True)
    return Destination(ToolsTpUiLockView, clear_history=True)


def _normalize_numeric_entry(raw: str) -> str:
    return " ".join(str(raw or "").replace("，", " ").replace(",", " ").split())


def _decode_seedkeeper_text_payload(secret_hex: str) -> str:
    raw = bytes.fromhex(secret_hex)
    if len(raw) >= 2 and int.from_bytes(raw[:2], "big") == len(raw[2:]):
        return raw[2:].decode("utf-8")
    if len(raw) >= 1 and raw[0] == len(raw[1:]):
        return raw[1:].decode("utf-8")
    return raw.decode("utf-8")


def _parse_seedkeeper_steel_payload(secret_text: str) -> tuple[list[str], list[int] | None]:
    words, indices = seedkeeper_utils.decode_seedkeeper_tp_steel_payload(secret_text)
    if len(words) != 12:
        raise ValueError("当前钢板二次加密助记词只支持 12 词。")
    if indices is not None and len(indices) != len(words):
        indices = None
    return words, indices


def _parse_seedkeeper_steel_words(secret_text: str) -> list[str]:
    words, _ = _parse_seedkeeper_steel_payload(secret_text)
    return words


def _normalize_plate_group_entry(raw: str) -> str:
    normalized = _normalize_numeric_entry(raw)
    if not normalized:
        return ""
    tokens = normalized.split()
    if len(tokens) <= 1:
        return normalized
    if not all(token.isdigit() for token in tokens):
        return normalized
    numbers = [int(token) for token in tokens]
    if len(set(numbers)) != len(numbers):
        return normalized
    if all(number in WEIGHT_SET for number in numbers):
        return " ".join(str(number) for number in sorted(numbers))
    return normalized


def _parse_single_nonnegative_int(raw: str) -> int:
    normalized = _normalize_numeric_entry(raw)
    if not normalized:
        raise ValueError("请输入数字。")
    parts = normalized.split()
    if len(parts) != 1:
        raise ValueError("这里只能输入一个数字。")
    try:
        value = int(parts[0])
    except ValueError as exc:
        raise ValueError("请输入整数。") from exc
    if value < 0:
        raise ValueError("请输入非负整数。")
    return value


def _extract_entry_operator(entry: str | None, fallback: str = DEFAULT_SHIFT_OPERATOR) -> str:
    normalized = str(entry or "").strip()
    if normalized and normalized[0] in OPERATOR_LABELS:
        return normalized[0]
    return fallback


def _format_shift_entry(operator: str, value: int | str) -> str:
    if operator in (None, "") or value in (None, ""):
        return ""
    return f"{_extract_entry_operator(operator)}{_parse_single_nonnegative_int(str(value))}"


def _parse_shift_entry(
    raw: str,
    default_operator: str = DEFAULT_SHIFT_OPERATOR,
    require_operator: bool = False,
    allow_blank: bool = False,
) -> tuple[str | None, int | None]:
    normalized = _normalize_numeric_entry(raw)
    if not normalized:
        if allow_blank:
            return None, None
        raise ValueError("请输入运算方式和数字，例如 +8。")

    operator = default_operator
    payload = normalized
    if payload[0] in OPERATOR_LABELS:
        operator = payload[0]
        payload = payload[1:].strip()
    elif require_operator:
        raise ValueError("请先选择 +、-、* 或 /，再输入数字。")

    value = _parse_single_nonnegative_int(payload)
    return operator, value


def _ensure_entry_list(entries: list[str] | None, count: int, default_values: list[int] | None = None) -> list[str]:
    values = list(entries or [])
    defaults = list(default_values or [])
    while len(values) < count:
        if len(defaults) > len(values):
            values.append(str(defaults[len(values)]))
        else:
            values.append("")
    return values[:count]


def _normalize_multiplicative_defaults(values: list[int]) -> list[int]:
    normalized = []
    for value in values:
        candidate = int(value) % 2048
        if candidate == 0:
            candidate = 1
        if candidate % 2 == 0:
            candidate = 1 if candidate == 2047 else candidate + 1
        normalized.append(candidate)
    return normalized


def _ensure_shift_entry_list(
    entries: list[str] | None,
    count: int,
) -> list[str]:
    values = [str(value or "").strip() for value in list(entries or [])]
    while len(values) < count:
        values.append("")
    return values[:count]


def _wrap_number_group(index: int, entry: str, wrap_width: int = STEEL_WRAP_WIDTH) -> list[str]:
    label = f"{index + 1:02d}: "
    indent = " " * len(label)
    tokens = _normalize_numeric_entry(entry).split()
    if not tokens:
        return [f"{label}(空)"]

    lines = []
    current = label
    for token in tokens:
        candidate = f"{current}{token}" if current.endswith(": ") else f"{current} {token}"
        if len(candidate) > wrap_width and current != label:
            lines.append(current)
            current = f"{indent}{token}"
        else:
            current = candidate
    lines.append(current)
    return lines


def _format_number_groups(entries: list[str], page_index: int, entries_per_page: int) -> tuple[str, int]:
    entries_per_page = max(1, int(entries_per_page))
    total_pages = max(1, (len(entries) + entries_per_page - 1) // entries_per_page)
    start = page_index * entries_per_page
    selected_entries = entries[start:start + entries_per_page]
    lines = []
    for offset, entry in enumerate(selected_entries):
        if lines:
            lines.append("")
        lines.extend(_wrap_number_group(start + offset, entry))
    return "\n".join(lines), total_pages


def _format_all_number_groups(entries: list[str]) -> str:
    sections = []
    for index, entry in enumerate(entries):
        sections.append("\n".join(_wrap_number_group(index, entry)))
    return "\n\n".join(section for section in sections if section).strip()


def _store_restored_steel_cipher(view: View, words: list[str], indices: list[int] | None = None) -> int:
    if indices is not None:
        indices = [int(index) for index in list(indices)]
        canonical_words = [get_word_at_index(index) for index in indices]
    else:
        canonical_words = _canonicalize_bip39_words(words, context="钢板恢复结果")
        indices = words_to_indices(canonical_words)
    view.controller.storage.set_steel_encrypted_mnemonic(
        canonical_words,
        bip39_indices=indices,
        source_fingerprint="钢板恢复",
    )
    view.controller.storage.set_steel_plate_groups(indices_to_plate_groups(indices))
    view.controller.storage.set_pending_seed(
        TransientWordSeed(canonical_words, bip39_word_indices=indices)
    )
    return view.controller.storage.finalize_pending_seed()


def _format_shift_entries(entries: list[str], page_index: int, entries_per_page: int = 6) -> tuple[str, int]:
    total_pages = max(1, (len(entries) + entries_per_page - 1) // entries_per_page)
    start = page_index * entries_per_page
    selected_entries = entries[start:start + entries_per_page]
    lines = []
    for offset, entry in enumerate(selected_entries):
        normalized = str(entry or "").strip()
        lines.append(f"{start + offset + 1:02d}: {normalized or '（不变）'}")
    return "\n".join(lines), total_pages


def _format_all_shift_entries(entries: list[str]) -> str:
    lines = []
    for offset, entry in enumerate(entries):
        normalized = str(entry or "").strip()
        lines.append(f"{offset + 1:02d}: {normalized or '（不变）'}")
    return "\n".join(lines).strip()


def _resolve_plate_selected_weights(group: str) -> list[int]:
    normalized = _normalize_numeric_entry(group)
    selected_weights = []
    if normalized:
        tokens = normalized.split()
        if all(token.isdigit() for token in tokens):
            numbers = [int(token) for token in tokens]
            if len(numbers) == 1 and 0 <= numbers[0] < len(STEEL_WORDLIST):
                selected_weights = solve_weights(numbers[0])
            elif all(number in WEIGHT_SET for number in numbers):
                selected_weights = numbers
    return list(selected_weights)


def _format_plate_selected_weight_lines(selected_weights: list[int]) -> list[str]:
    if not selected_weights:
        return ["无需打孔"]

    selected_set = set(selected_weights)
    first_half = [weight for weight in WEIGHTS[:6] if weight in selected_set]
    second_half = [weight for weight in WEIGHTS[6:] if weight in selected_set]

    lines = []
    if first_half:
        lines.append(" ".join(str(weight) for weight in first_half))
    if second_half:
        lines.append(" ".join(str(weight) for weight in second_half))
    return lines


def _format_plate_word_page(
    words: list[str],
    groups: list[str],
    page_index: int,
    indices: list[int] | None = None,
) -> tuple[str, str]:
    if indices is not None and page_index < len(indices):
        index_text = f"{int(indices[page_index]):04d}"
    else:
        try:
            word = str(words[page_index] or "").strip() if page_index < len(words) else ""
            word_index = lookup_word_index(word)
            index_text = f"{word_index:04d}"
        except Exception:
            index_text = "----"
    selected_weights = _resolve_plate_selected_weights(groups[page_index])
    title = f"{page_index + 1:02d} 词"
    text = "\n".join([f"序号: {index_text}", "打孔位:", *_format_plate_selected_weight_lines(selected_weights)])
    return title, text


def _format_all_plate_word_pages(
    words: list[str],
    groups: list[str],
    indices: list[int] | None = None,
) -> str:
    sections = []
    for page_index in range(len(groups)):
        title, text = _format_plate_word_page(words, groups, page_index, indices=indices)
        sections.append(f"{title}\n{text}".strip())
    return "\n\n".join(section for section in sections if section).strip()


def _is_lossy_operator(operator: str | None) -> bool:
    return operator in ("*", "/")


def _normalize_bip39_word(word: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(word or "")).lower()
    return "".join(ch for ch in normalized if "a" <= ch <= "z")


def _resolve_seed_bip39_indices(seed) -> list[int] | None:
    explicit_indices = getattr(seed, "bip39_word_indices", None)
    if explicit_indices is not None:
        explicit_indices = list(explicit_indices)
        if len(explicit_indices) == len(getattr(seed, "mnemonic_list", [])):
            return explicit_indices
    if getattr(seed, "bip39_word_indices_supported", False):
        try:
            resolved = seed.get_bip39_word_indices()
            if len(resolved) == len(getattr(seed, "mnemonic_list", [])):
                return list(resolved)
        except Exception:
            return None
    return None


def _canonicalize_bip39_words(words: list[str], context: str = "助记词") -> list[str]:
    canonical_words = []
    for position, word in enumerate(list(words or []), 1):
        raw_word = str(word or "").strip()
        try:
            canonical_words.append(get_word_at_index(lookup_word_index(raw_word)))
        except Exception as exc:
            display_word = raw_word or "（空）"
            raise ValueError(f"{context}第 {position} 个单词不是官方 BIP39 英文词：{display_word}") from exc
    return canonical_words


def _prepare_shift_source_words(
    words: list[str],
    context: str = "助记词",
    expected_len: int = 12,
) -> list[str]:
    cleaned_words = []
    for position, word in enumerate(list(words or []), 1):
        display_word = str(word or "").strip()
        if not display_word:
            raise ValueError(f"{context}第 {position} 个单词为空，请先补全后再继续。")
        cleaned_words.append(display_word)

    if len(cleaned_words) != expected_len:
        raise ValueError(f"{context}当前只支持 {expected_len} 词助记词。")

    return cleaned_words


def _format_weight_line(index: int) -> str:
    weights = solve_weights(index)
    if not weights:
        return "0"
    chunks = [" ".join(str(weight) for weight in weights[i:i + 6]) for i in range(0, len(weights), 6)]
    return "\n".join(chunks)


def _build_bip39_word_report(word: str) -> str:
    normalized = _normalize_bip39_word(word)
    if not normalized:
        raise ValueError("请输入英文单词。")
    index = lookup_word_index(normalized)
    previous_word = get_word_at_index(index - 1) if index > 0 else "（无）"
    next_word = get_word_at_index(index + 1) if index < 2047 else "（无）"
    return (
        f"单词: {normalized}\n"
        f"编号: {index}\n"
        f"前词: {previous_word}\n"
        f"后词: {next_word}\n"
        f"钢板位权:\n{_format_weight_line(index)}"
    )


def _build_bip39_index_report(raw_index: str) -> str:
    normalized = _normalize_numeric_entry(raw_index)
    if not normalized:
        raise ValueError("请输入 0 到 2047 的编号。")
    parts = normalized.split()
    if len(parts) != 1:
        raise ValueError("这里只能输入一个编号。")
    if not parts[0].isdigit():
        raise ValueError("请输入纯数字编号。")

    index = int(parts[0])
    if index < 0 or index >= 2048:
        raise ValueError("编号必须在 0 到 2047 之间。")

    word = get_word_at_index(index)
    previous_word = get_word_at_index(index - 1) if index > 0 else "（无）"
    next_word = get_word_at_index(index + 1) if index < 2047 else "（无）"
    return (
        f"编号: {index}\n"
        f"单词: {word}\n"
        f"前词: {previous_word}\n"
        f"后词: {next_word}\n"
        f"钢板位权:\n{_format_weight_line(index)}"
    )


class ModeSelectView(View):
    def run(self):
        return _tp_home_destination()


def _operator_display_label(operator: str) -> str:
    return OPERATOR_LABELS.get(operator, operator)


class ToolsTpQrPagesEncoder(BaseSimpleAnimatedQREncoder):
    def __init__(self, pages: list[str], frame_repeat: int = 2):
        self.pages = [str(page).strip() for page in list(pages or []) if str(page).strip()]
        self.frame_repeat = max(1, int(frame_repeat))
        super().__post_init__()

    def _create_parts(self):
        self.parts = list(self.pages)


class ToolsTpEthSignatureQrEncoder(BaseSimpleAnimatedQREncoder):
    def __init__(
        self,
        ur_text: str,
        max_fragment_len: int = WEB3_ETH_SIGNATURE_QR_MAX_FRAGMENT_LEN,
        frame_repeat: int = WEB3_ETH_SIGNATURE_QR_FRAME_REPEAT,
    ):
        self.ur_text = str(ur_text or "").strip()
        if not self.ur_text:
            raise ValueError("eth-signature UR 不能为空")
        self.max_fragment_len = max(10, int(max_fragment_len))
        self.frame_repeat = max(1, int(frame_repeat))
        super().__post_init__()

    def _create_parts(self):
        decoder = URDecoder()
        if not decoder.receive_part(self.ur_text) or not decoder.is_complete():
            raise ValueError("eth-signature UR 无法解析")

        ur = decoder.result_message()
        encoder = UREncoder(ur, self.max_fragment_len)
        if encoder.is_single_part():
            self.parts = [UREncoder.encode(ur)]
            return

        part_count = max(1, int(encoder.fountain_encoder.seq_len()))
        self.parts = [encoder.next_part() for _ in range(part_count)]


def _configure_high_margin_qr_encoder(
    qr_encoder,
    *,
    border_modules: int = 2,
    display_size: int | None = None,
    min_background_brightness: int = 240,
    background_color: str = "ffffff",
):
    if qr_encoder is None:
        return None
    try:
        qr_encoder.display_border_modules = max(2, int(border_modules))
    except Exception:
        qr_encoder.display_border_modules = 5
    try:
        if display_size is None:
            from seedsigner.gui.renderer import Renderer

            renderer = Renderer.get_instance()
            display_size = min(int(renderer.canvas_width), int(renderer.canvas_height))
        size = max(64, int(display_size))
    except Exception:
        size = 240
    qr_encoder.display_image_size = (size, size)
    try:
        qr_encoder.display_min_background_brightness = max(0, min(255, int(min_background_brightness)))
    except Exception:
        qr_encoder.display_min_background_brightness = 240
    color = str(background_color or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9A-Fa-f]{6}", color):
        qr_encoder.display_background_color = color.lower()
    return qr_encoder


def _encode_web3_keypath_bytes(path: str, source_fingerprint_hex: str | None = None, depth: int | None = None) -> bytes:
    normalized = _normalize_bip32_path(path)
    parts = [segment for segment in normalized.split("/")[1:] if segment]
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


def _web3_valid_fingerprint(value: str | None) -> str | None:
    fingerprint = str(value or "").strip().lower()
    return fingerprint if re.fullmatch(r"[0-9a-f]{8}", fingerprint) else None


def _encode_web3_coin_info_bytes(coin_type: int | None = None, network: int | None = None) -> bytes | None:
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


def _web3_keystone_keys(web3_account: dict, key_name: str) -> list[dict]:
    keys = web3_account.get("keystoneKeys")
    if not isinstance(keys, dict):
        return []
    value = keys.get(key_name)
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(entry) for entry in value if isinstance(entry, dict)]
    return []


def _web3_keystone_key(web3_account: dict, key_name: str) -> dict:
    keys = _web3_keystone_keys(web3_account, key_name)
    if keys:
        return keys[0]
    return _web3_key_entry(
        pubkey_hex=str(web3_account["compressedPubKeyHex"]),
        chain_code_hex=str(web3_account.get("chainCodeHex") or ""),
        origin_path=str(web3_account.get("accountPath") or "m/44'/60'/0'"),
        origin_depth=_web3_path_depth(str(web3_account.get("accountPath") or "m/44'/60'/0'")),
        parent_fingerprint=str(web3_account.get("parentFingerprint") or ""),
        children_path=str(web3_account.get("childrenPath") or "0/*"),
        children_depth=0,
        note="account.standard",
        coin_type=WEB3_ETH_COIN_TYPE,
        network=WEB3_MAINNET_NETWORK,
    )


def _build_web3_hdkey_entry_cbor_bytes(entry: dict, master_fingerprint: str | None, include_children: bool) -> bytes:
    compressed_pubkey = _hex_to_bytes(str(entry["compressedPubKeyHex"]))
    chain_code_hex = str(entry.get("chainCodeHex") or "").strip()
    chain_code = _hex_to_bytes(chain_code_hex) if chain_code_hex else b""
    if len(compressed_pubkey) != 33:
        raise ValueError("Web3 连接公钥长度不正确。")
    if chain_code and len(chain_code) != 32:
        raise ValueError("Web3 连接链码长度不正确。")

    origin_path = str(entry["originPath"])
    children_path = str(entry.get("childrenPath") or "").strip()
    parent_fingerprint = _web3_valid_fingerprint(str(entry.get("parentFingerprint") or ""))
    coin_info_cbor = _encode_web3_coin_info_bytes(
        coin_type=entry.get("coinType"),
        network=entry.get("network"),
    )
    name = str(entry.get("name") or "Keystone")
    note = str(entry.get("note") or "")

    origin_cbor = _encode_web3_keypath_bytes(
        origin_path,
        source_fingerprint_hex=master_fingerprint,
        depth=None,
    )
    children_cbor = None
    if include_children and children_path:
        children_cbor = _encode_web3_keypath_bytes(
            children_path,
            depth=None,
        )

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


def _build_web3_hdkey_cbor_bytes(web3_account: dict) -> bytes:
    master_fingerprint = _web3_valid_fingerprint(str(web3_account.get("masterFingerprint") or ""))
    return _build_web3_hdkey_entry_cbor_bytes(
        _web3_keystone_key(web3_account, "standard"),
        master_fingerprint=master_fingerprint,
        include_children=True,
    )


def _build_web3_bitkeep_hdkey_entry_cbor_bytes(entry: dict, master_fingerprint: str | None) -> bytes:
    compressed_pubkey = _hex_to_bytes(str(entry["compressedPubKeyHex"]))
    chain_code_hex = str(entry.get("chainCodeHex") or "").strip()
    chain_code = _hex_to_bytes(chain_code_hex) if chain_code_hex else b""
    if len(compressed_pubkey) != 33:
        raise ValueError("Web3 连接公钥长度不正确。")
    if chain_code and len(chain_code) != 32:
        raise ValueError("Web3 连接链码长度不正确。")

    origin_path = str(entry["originPath"])
    children_path = str(entry.get("childrenPath") or "").strip()
    parent_fingerprint = _web3_valid_fingerprint(str(entry.get("parentFingerprint") or ""))
    coin_info_cbor = _encode_web3_coin_info_bytes(
        coin_type=entry.get("coinType"),
        network=entry.get("network"),
    )
    name = str(entry.get("name") or "Keystone")
    note = str(entry.get("note") or "")

    origin_cbor = _encode_web3_keypath_bytes(
        origin_path,
        source_fingerprint_hex=master_fingerprint,
        depth=entry.get("originDepth"),
    )
    children_cbor = None
    if children_path:
        children_cbor = _encode_web3_keypath_bytes(
            children_path,
            depth=entry.get("childrenDepth"),
        )

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


def _web3_bitkeep_master_fingerprint(web3_account: dict) -> str:
    return (
        _web3_valid_fingerprint(str(web3_account.get("bitkeepMasterFingerprint") or ""))
        or _web3_valid_fingerprint(str(web3_account.get("masterFingerprint") or ""))
        or "00000000"
    )


def _web3_bitkeep_key_entries(web3_account: dict) -> list[dict]:
    entries = web3_account.get("bitkeepKeys")
    if isinstance(entries, list):
        normalized_entries = [dict(entry) for entry in entries if isinstance(entry, dict)]
        if normalized_entries:
            return normalized_entries
    return [dict(_web3_keystone_key(web3_account, "standard"))]


def _build_web3_bitkeep_multi_accounts_cbor_bytes(web3_account: dict) -> bytes:
    master_fingerprint = _web3_bitkeep_master_fingerprint(web3_account)
    key_entries = _web3_bitkeep_key_entries(web3_account)

    encoder = CBOREncoder()
    encoder.encodeMapSize(3)
    encoder.encodeUnsigned(1)
    encoder.encodeUnsigned(int(master_fingerprint, 16))
    encoder.encodeUnsigned(2)
    encoder.encodeArraySize(len(key_entries))
    for entry in key_entries:
        encoder.encodeTagAndValue(Tag_Major_semantic, 303)
        encoder.buf += _build_web3_bitkeep_hdkey_entry_cbor_bytes(
            entry,
            master_fingerprint=master_fingerprint,
        )
    encoder.encodeUnsigned(3)
    encoder.encodeText("Keystone")
    return bytes(encoder.get_bytes())


def _web3_wallet_profile(value: str | None) -> str:
    normalized = str(value or WEB3_WALLET_PROFILE_OKX).strip().lower()
    compact = normalized.replace("-", "").replace("_", "").replace(" ", "")
    if normalized in {"bitget", "bitkeep"}:
        return WEB3_WALLET_PROFILE_BITGET
    if compact == WEB3_WALLET_PROFILE_METAMASK:
        return WEB3_WALLET_PROFILE_METAMASK
    if compact == WEB3_WALLET_PROFILE_RABBY:
        return WEB3_WALLET_PROFILE_RABBY
    if compact in {WEB3_WALLET_PROFILE_TOKENPOCKET, "tpwallet", "tp"}:
        return WEB3_WALLET_PROFILE_TOKENPOCKET
    return WEB3_WALLET_PROFILE_OKX


def _web3_okx_device_serial(web3_account: dict) -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as file:
            for line in file:
                if line.startswith("Serial"):
                    serial = line.split(":", 1)[-1].strip().replace("\x00", "")
                    if serial:
                        return serial
    except Exception:
        pass

    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r", encoding="utf-8") as file:
                machine_id = file.read().strip().replace("\x00", "")
            if machine_id:
                return machine_id
        except Exception:
            continue

    nodename = str(getattr(os.uname(), "nodename", "") or "").strip()
    if nodename:
        return nodename

    master_fingerprint = str(web3_account.get("masterFingerprint") or "00000000").strip().lower()
    address = str(web3_account.get("address") or "").strip().lower()
    fallback = f"tp-keystone-{master_fingerprint}-{address}"
    return fallback


def _web3_device_id(web3_account: dict, wallet_profile: str | None = None) -> str:
    profile = _web3_wallet_profile(wallet_profile)
    if profile == WEB3_WALLET_PROFILE_OKX:
        serial = f"keystone{_web3_okx_device_serial(web3_account)}"
        return hashlib.sha256(hashlib.sha256(serial.encode("utf-8")).digest()).hexdigest()[:40]

    master_fingerprint = str(web3_account.get("masterFingerprint") or "00000000").strip().lower()
    address = str(web3_account.get("address") or "").strip().lower()
    serial = f"tp-keystone-{master_fingerprint}-{address}"
    return hashlib.sha256(hashlib.sha256(serial.encode("utf-8")).digest()).digest()[:20].hex()


def _build_web3_multi_accounts_cbor_bytes(web3_account: dict, wallet_profile: str) -> bytes:
    master_fingerprint = _web3_valid_fingerprint(str(web3_account.get("masterFingerprint") or ""))
    if master_fingerprint is None:
        master_fingerprint = "00000000"

    profile = _web3_wallet_profile(wallet_profile)
    standard = _web3_keystone_key(web3_account, "standard")
    ledger_legacy = _web3_keystone_key(web3_account, "ledgerLegacy")
    ledger_live = _web3_keystone_key(web3_account, "ledgerLive")
    okx_ledger_live = _web3_keystone_keys(web3_account, "okxLedgerLive")
    if profile == WEB3_WALLET_PROFILE_BITGET:
        key_specs = [
            (standard, True),
            (ledger_legacy, True),
            (ledger_live, False),
        ]
    else:
        key_specs = [(standard, True)]

    encoder = CBOREncoder()
    encoder.encodeMapSize(5)
    encoder.encodeUnsigned(1)
    encoder.encodeUnsigned(int(master_fingerprint, 16))
    encoder.encodeUnsigned(2)
    encoder.encodeArraySize(len(key_specs))
    for entry, include_children in key_specs:
        encoder.encodeTagAndValue(Tag_Major_semantic, 303)
        encoder.buf += _build_web3_hdkey_entry_cbor_bytes(
            entry,
            master_fingerprint=master_fingerprint,
            include_children=include_children,
        )
    encoder.encodeUnsigned(3)
    encoder.encodeText(WEB3_OKX_DEVICE_TYPE if profile == WEB3_WALLET_PROFILE_OKX else WEB3_KEYSTONE_DEVICE_TYPE)
    encoder.encodeUnsigned(4)
    encoder.encodeText(_web3_device_id(web3_account, profile))
    encoder.encodeUnsigned(5)
    encoder.encodeText(WEB3_KEYSTONE_DEVICE_VERSION)
    return bytes(encoder.get_bytes())


def _build_web3_okx_multi_accounts_cbor_bytes(web3_account: dict) -> bytes:
    master_fingerprint = _web3_valid_fingerprint(str(web3_account.get("masterFingerprint") or ""))
    if master_fingerprint is None:
        master_fingerprint = "00000000"

    standard = _web3_keystone_key(web3_account, "standard")
    okx_ledger_live = _web3_keystone_keys(web3_account, "okxLedgerLive")
    okx_bitcoin = _web3_keystone_keys(web3_account, "okxBitcoin")

    encoder = CBOREncoder()
    encoder.encodeMapSize(5)
    encoder.encodeUnsigned(1)
    encoder.encodeUnsigned(int(master_fingerprint, 16))
    encoder.encodeUnsigned(2)
    encoder.encodeArraySize(1 + len(okx_ledger_live) + len(okx_bitcoin))

    encoder.encodeTagAndValue(Tag_Major_semantic, 303)
    encoder.buf += _build_web3_hdkey_entry_cbor_bytes(
        standard,
        master_fingerprint=master_fingerprint,
        include_children=True,
    )

    for entry in okx_ledger_live:
        encoder.encodeTagAndValue(Tag_Major_semantic, 303)
        encoder.buf += _build_web3_hdkey_entry_cbor_bytes(
            entry,
            master_fingerprint=master_fingerprint,
            include_children=False,
        )

    for entry in okx_bitcoin:
        encoder.encodeTagAndValue(Tag_Major_semantic, 303)
        encoder.buf += _build_web3_bitkeep_hdkey_entry_cbor_bytes(
            entry,
            master_fingerprint=master_fingerprint,
        )

    encoder.encodeUnsigned(3)
    encoder.encodeText(WEB3_OKX_DEVICE_TYPE)
    encoder.encodeUnsigned(4)
    encoder.encodeText(_web3_device_id(web3_account, WEB3_WALLET_PROFILE_OKX))
    encoder.encodeUnsigned(5)
    encoder.encodeText(WEB3_KEYSTONE_DEVICE_VERSION)
    return bytes(encoder.get_bytes())


def _build_web3_connect_qr_pages(web3_account: dict, wallet_profile: str = WEB3_WALLET_PROFILE_OKX) -> list[str]:
    profile = _web3_wallet_profile(wallet_profile)
    if profile == WEB3_WALLET_PROFILE_BITGET:
        ur = UR("crypto-multi-accounts", _build_web3_bitkeep_multi_accounts_cbor_bytes(web3_account))
        return [UREncoder.encode(ur).upper()]
    if profile == WEB3_WALLET_PROFILE_OKX:
        ur = UR("crypto-multi-accounts", _build_web3_okx_multi_accounts_cbor_bytes(web3_account))
        encoder = UREncoder(ur, WEB3_OKX_CONNECT_QR_MAX_FRAGMENT_LEN)
        return [part.upper() for part in _collect_ur_encoder_parts(encoder)]

    ur = UR("crypto-hdkey", _build_web3_hdkey_cbor_bytes(web3_account))
    return [UREncoder.encode(ur).upper()]


class ToolsTpHomeView(View):
    SCAN = ButtonOption("扫码签名")
    CONNECT_WALLET = ButtonOption("连接钱包")
    SEED_TOOLS = ButtonOption("助记词工具")
    FIRMWARE_CHECK = ButtonOption("固件自检")
    SMARTCARD_TOOLS = ButtonOption("智能卡工具")

    def run(self):
        button_data = [
            self.SCAN,
            self.CONNECT_WALLET,
            self.SEED_TOOLS,
            self.SMARTCARD_TOOLS,
            self.FIRMWARE_CHECK,
        ]

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="离线签名器",
            is_button_text_centered=False,
            button_data=button_data,
            show_back_button=False,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return _tp_home_destination()

        if button_data[selected_menu_num] == self.SCAN:
            return Destination(ToolsTpSignerScanView)
        if button_data[selected_menu_num] == self.CONNECT_WALLET:
            return Destination(ToolsTpConnectWalletMenuView)
        if button_data[selected_menu_num] == self.SEED_TOOLS:
            return Destination(ToolsTpSeedToolsView)
        if button_data[selected_menu_num] == self.FIRMWARE_CHECK:
            return Destination(ToolsTpFirmwareIntegrityRunView)
        if button_data[selected_menu_num] == self.SMARTCARD_TOOLS:
            return Destination(ToolsTpSmartcardToolsView)

        return _tp_home_destination()


class ToolsTpConnectWalletMenuView(View):
    WEB3 = ButtonOption("Web3钱包")
    BTC = ButtonOption("比特币钱包")

    def run(self):
        button_data = [self.WEB3, self.BTC]
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="连接钱包",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return _tp_home_destination()

        selected = button_data[selected_menu_num]
        if selected == self.WEB3:
            return Destination(ToolsTpWeb3WalletProfileSelectView)
        if selected == self.BTC:
            return Destination(ToolsTpBtcConnectSourceView)

        return _tp_home_destination()


class ToolsTpWeb3WalletProfileSelectView(View):
    OKX = ButtonOption("OKX钱包")
    BITGET = ButtonOption("Bitget钱包")
    METAMASK = ButtonOption("MetaMask")
    RABBY = ButtonOption("Rabby")
    TOKENPOCKET = ButtonOption("TokenPocket")

    def run(self):
        button_data = [
            self.OKX,
            self.BITGET,
            self.METAMASK,
            self.RABBY,
            self.TOKENPOCKET,
        ]
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="Web3钱包",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpConnectWalletMenuView, clear_history=True)

        selected_wallet = button_data[selected_menu_num]
        if selected_wallet == self.BITGET:
            wallet_profile = WEB3_WALLET_PROFILE_BITGET
        elif selected_wallet == self.METAMASK:
            wallet_profile = WEB3_WALLET_PROFILE_METAMASK
        elif selected_wallet == self.RABBY:
            wallet_profile = WEB3_WALLET_PROFILE_RABBY
        elif selected_wallet == self.TOKENPOCKET:
            wallet_profile = WEB3_WALLET_PROFILE_TOKENPOCKET
        else:
            wallet_profile = WEB3_WALLET_PROFILE_OKX
        return Destination(
            ToolsTpWeb3ConnectMethodSelectView,
            view_args=dict(wallet_profile=wallet_profile),
            skip_current_view=True,
        )


class ToolsTpBtcConnectSourceView(View):
    SMARTCARD = ButtonOption("智能卡账户")
    LOADED_SEED = ButtonOption("已加载助记词")

    def run(self):
        button_data = [self.SMARTCARD, self.LOADED_SEED]
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="比特币钱包",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpConnectWalletMenuView, clear_history=True)

        selected = button_data[selected_menu_num]
        if selected == self.SMARTCARD:
            return Destination(ToolsTpBtcConnectTypeView, view_args=dict(source="smartcard"))
        if selected == self.LOADED_SEED:
            return Destination(ToolsTpBtcConnectSeedSelectView)

        return Destination(ToolsTpConnectWalletMenuView, clear_history=True)


class ToolsTpBtcConnectSeedSelectView(View):
    def _eligible_seed_options(self) -> tuple[list[int], list[ButtonOption]]:
        seed_nums: list[int] = []
        button_data: list[ButtonOption] = []
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        for seed_num, seed in enumerate(self.controller.storage.seeds):
            if isinstance(seed, TransientWordSeed):
                continue
            try:
                seed.get_root(SettingsConstants.MAINNET)
                fingerprint = seed.get_fingerprint(network)
            except Exception:
                continue
            seed_nums.append(seed_num)
            button_data.append(ButtonOption(f"{seed_num + 1}. {fingerprint[:8]}"))
        return seed_nums, button_data

    def run(self):
        seed_nums, button_data = self._eligible_seed_options()
        if not button_data:
            self.run_screen(
                WarningScreen,
                title="没有可用助记词",
                status_headline=None,
                text="请先在“助记词工具”里导入或创建有效 BIP39 助记词，再连接比特币钱包。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(ToolsTpBtcConnectSourceView, clear_history=True)

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="选择助记词",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpBtcConnectSourceView, clear_history=True)

        return Destination(
            ToolsTpBtcConnectTypeView,
            view_args=dict(source="seed", seed_num=seed_nums[selected_menu_num]),
        )


class ToolsTpBtcConnectTypeView(View):
    ZPUB = ButtonOption("BlueWallet zpub")
    XPUB = ButtonOption("BlueWallet xpub")

    def __init__(self, source: str, seed_num: int | None = None):
        super().__init__()
        self.source = str(source or "").strip().lower()
        self.seed_num = None if seed_num is None else int(seed_num)

    def run(self):
        button_data = [self.ZPUB, self.XPUB]
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="比特币钱包",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpBtcConnectSourceView, clear_history=True)

        xtype = "zpub" if button_data[selected_menu_num] == self.ZPUB else "xpub"
        if self.source == "smartcard":
            return Destination(
                ToolsTpBtcXpubPinEntryView,
                view_args=dict(xtype=xtype, return_to_connect_wallet=True),
                skip_current_view=True,
            )

        if self.source == "seed" and self.seed_num is not None:
            return Destination(
                ToolsTpSeedBtcXpubQrView,
                view_args=dict(seed_num=self.seed_num, xtype=xtype, return_to_connect_wallet=True),
                skip_current_view=True,
            )

        return Destination(ToolsTpBtcConnectSourceView, clear_history=True)


class ToolsTpWeb3ConnectMethodSelectView(View):
    SMARTCARD = ButtonOption("智能卡账户")
    LOADED_SEED = ButtonOption("已加载助记词")

    def __init__(self, derivation_path: str = DEFAULT_DERIVATION_PATH, wallet_profile: str = WEB3_WALLET_PROFILE_OKX):
        super().__init__()
        self.derivation_path = _normalize_bip32_path(derivation_path)
        self.wallet_profile = _web3_wallet_profile(wallet_profile)

    def run(self):
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=WEB3_WALLET_PROFILE_LABELS.get(self.wallet_profile, "Web3钱包"),
            is_button_text_centered=False,
            button_data=[self.SMARTCARD, self.LOADED_SEED],
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpWeb3WalletProfileSelectView, clear_history=True)

        if selected_menu_num == 0:
            return Destination(
                ToolsTpWeb3ConnectPinEntryView,
                view_args=dict(derivation_path=self.derivation_path, wallet_profile=self.wallet_profile),
                skip_current_view=True,
            )

        return Destination(
            ToolsTpWeb3ConnectSeedSelectView,
            view_args=dict(derivation_path=self.derivation_path, wallet_profile=self.wallet_profile),
            skip_current_view=True,
        )


class ToolsTpWeb3ConnectPinEntryView(View):
    def __init__(self, derivation_path: str = DEFAULT_DERIVATION_PATH, wallet_profile: str = WEB3_WALLET_PROFILE_OKX):
        super().__init__()
        self.derivation_path = _normalize_bip32_path(derivation_path)
        self.wallet_profile = _web3_wallet_profile(wallet_profile)

    def run(self):
        try:
            pin = _prompt_for_tp_pin(self)
        except Exception as exc:
            logger.exception("TP Web3 connect PIN prompt failed")
            return _debug_error_destination("21", str(exc))

        if pin is None:
            return _tp_home_destination()

        pin = pin.strip()
        if not pin or len(pin) < 4:
            return _tp_home_destination()

        return Destination(
            ToolsTpWeb3ConnectRunView,
            view_args=dict(derivation_path=self.derivation_path, pin=pin, wallet_profile=self.wallet_profile),
            skip_current_view=True,
        )


class ToolsTpWeb3ConnectSeedSelectView(View):
    def __init__(self, derivation_path: str = DEFAULT_DERIVATION_PATH, wallet_profile: str = WEB3_WALLET_PROFILE_OKX):
        super().__init__()
        self.derivation_path = _normalize_bip32_path(derivation_path)
        self.wallet_profile = _web3_wallet_profile(wallet_profile)

    def _eligible_seed_options(self) -> tuple[list[int], list[ButtonOption]]:
        seed_nums: list[int] = []
        button_data: list[ButtonOption] = []
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        for seed_num, seed in enumerate(self.controller.storage.seeds):
            if isinstance(seed, TransientWordSeed):
                continue
            try:
                seed.get_root(SettingsConstants.MAINNET)
                fingerprint = seed.get_fingerprint(network)
            except Exception:
                continue
            seed_nums.append(seed_num)
            button_data.append(ButtonOption(f"{seed_num + 1}. {fingerprint[:8]}"))
        return seed_nums, button_data

    def run(self):
        seed_nums, button_data = self._eligible_seed_options()
        if not button_data:
            self.run_screen(
                WarningScreen,
                title="没有可用助记词",
                status_headline=None,
                text="请先在“助记词工具”里导入或创建有效 BIP39 助记词，再生成 Web3 连接二维码。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(
                ToolsTpWeb3ConnectMethodSelectView,
                view_args=dict(wallet_profile=self.wallet_profile, derivation_path=self.derivation_path),
                clear_history=True,
            )

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="选择助记词",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(
                ToolsTpWeb3ConnectMethodSelectView,
                view_args=dict(wallet_profile=self.wallet_profile, derivation_path=self.derivation_path),
                clear_history=True,
            )

        return Destination(
            ToolsTpWeb3ConnectSeedRunView,
            view_args=dict(
                seed_num=seed_nums[selected_menu_num],
                derivation_path=self.derivation_path,
                wallet_profile=self.wallet_profile,
            ),
            skip_current_view=True,
        )


class ToolsTpWeb3ConnectSeedRunView(View):
    def __init__(self, seed_num: int, derivation_path: str = DEFAULT_DERIVATION_PATH, wallet_profile: str = WEB3_WALLET_PROFILE_OKX):
        super().__init__()
        self.seed_num = int(seed_num)
        self.derivation_path = _normalize_bip32_path(derivation_path)
        self.wallet_profile = _web3_wallet_profile(wallet_profile)

    def run(self):
        try:
            seed = self.controller.get_seed(self.seed_num)
        except Exception as exc:
            return _debug_error_destination("63", str(exc))

        loading = LoadingScreenThread(text="生成 Web3 连接码...")
        loading.start()
        try:
            web3_account = _export_web3_account_from_seed(seed, self.derivation_path)
            qr_pages = _build_web3_connect_qr_pages(web3_account, self.wallet_profile)
        except Exception as exc:
            logger.warning("TP Web3 connect seed export failed: %s", exc)
            return _debug_error_destination("63", str(exc))
        finally:
            loading.stop()

        return Destination(
            ToolsTpWeb3ConnectQrView,
            view_args=dict(web3_account=web3_account, qr_pages=qr_pages, wallet_profile=self.wallet_profile),
            skip_current_view=True,
        )


class ToolsTpWeb3ConnectRunView(View):
    def __init__(self, derivation_path: str = DEFAULT_DERIVATION_PATH, pin: str = "", wallet_profile: str = WEB3_WALLET_PROFILE_OKX):
        super().__init__()
        self.derivation_path = _normalize_bip32_path(derivation_path)
        self.pin = pin
        self.wallet_profile = _web3_wallet_profile(wallet_profile)

    def run(self):
        connector = seedkeeper_utils.init_satochip(
            self,
            init_card_filter=["satochip"],
            require_pin=False,
        )
        if not connector:
            return _tp_home_destination()

        loading = LoadingScreenThread(text="验证智能卡...")
        loading.start()
        try:
            connector.set_pin(0, list(self.pin.encode("utf-8")))
            _response, sw1, sw2 = connector.card_verify_PIN()
            if sw1 != 0x90 or sw2 != 0x00:
                return _debug_error_destination("45", format_sw_error(sw1, sw2))
            web3_account = _export_web3_account_from_satochip(connector, self.derivation_path)
            qr_pages = _build_web3_connect_qr_pages(web3_account, self.wallet_profile)
        except Exception as exc:
            logger.warning("TP Web3 connect smartcard export failed: %s", exc)
            return _debug_error_destination("63", str(exc))
        finally:
            loading.stop()

        return Destination(
            ToolsTpWeb3ConnectQrView,
            view_args=dict(web3_account=web3_account, qr_pages=qr_pages, wallet_profile=self.wallet_profile),
            skip_current_view=True,
        )


class ToolsTpWeb3ConnectQrView(View):
    SHOW_QR = ButtonOption("显示连接二维码")

    def __init__(
        self,
        web3_account: dict,
        qr_pages: list[str],
        wallet_profile: str = WEB3_WALLET_PROFILE_OKX,
        skip_review: bool = False,
    ):
        super().__init__()
        self.web3_account = dict(web3_account or {})
        self.qr_pages = [str(page).strip() for page in list(qr_pages or []) if str(page).strip()]
        self.wallet_profile = _web3_wallet_profile(wallet_profile)
        self.skip_review = bool(skip_review)

    def run(self):
        if not self.qr_pages:
            return _debug_error_destination("33", "Web3 连接二维码为空")

        if not self.skip_review:
            qr_format = (
                "crypto-multi-accounts"
                if self.wallet_profile in {WEB3_WALLET_PROFILE_OKX, WEB3_WALLET_PROFILE_BITGET}
                else "crypto-hdkey"
            )
            pages = [
                "\n".join(
                    [
                        f"地址: {self.web3_account.get('address') or '-'}",
                        f"路径: {self.web3_account.get('addressPath') or DEFAULT_DERIVATION_PATH}",
                        f"来源: {self.web3_account.get('sourceLabel') or '-'}",
                        f"钱包: {WEB3_WALLET_PROFILE_LABELS.get(self.wallet_profile, 'Web3 钱包')}",
                        f"格式: {qr_format}",
                        "原钱包请选择 Keystone 硬件钱包扫码",
                    ]
                ),
                "\n".join(
                    [
                        "连接码类型: " + ("单张静态二维码" if len(self.qr_pages) == 1 else "动态连续二维码"),
                        f"二维码帧数: {len(self.qr_pages)}",
                        "连接后发起签名时",
                        "回到首页点“扫码签名”",
                        "签名请求太密时",
                        "再用安卓中转",
                    ]
                ),
            ]

            selected = self.run_screen(
                ToolsScrollableTextScreen,
                title="Web3钱包",
                text="\n\n".join(page for page in pages if str(page).strip()),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size() + 1, 19),
                button_data=[self.SHOW_QR],
            )

            if selected == RET_CODE__BACK_BUTTON:
                return _tp_home_destination()
            return Destination(
                ToolsTpWeb3ConnectQrView,
                view_args=dict(
                    web3_account=self.web3_account,
                    qr_pages=self.qr_pages,
                    wallet_profile=self.wallet_profile,
                    skip_review=True,
                ),
                clear_history=True,
            )

        qr_encoder = (
            GenericStaticQrEncoder(data=self.qr_pages[0])
            if len(self.qr_pages) == 1
            else ToolsTpQrPagesEncoder(
                self.qr_pages,
                frame_repeat=WEB3_OKX_CONNECT_QR_FRAME_REPEAT
                if self.wallet_profile == WEB3_WALLET_PROFILE_OKX
                else 2,
            )
        )
        if len(self.qr_pages) == 1:
            qr_encoder = _configure_high_margin_qr_encoder(
                qr_encoder,
                border_modules=2,
                min_background_brightness=248,
                background_color="ffffff",
            )
        self.run_screen(QRDisplayScreen, qr_encoder=qr_encoder)
        return _tp_home_destination()


class ToolsTpUiLockView(View):
    SETUP = ButtonOption("设置登录密码")
    UNLOCK = ButtonOption("输入登录密码")

    def _power_destination(self) -> Destination:
        from seedsigner.views.view import PowerOptionsView

        return Destination(PowerOptionsView)

    def _unlock_destination(self) -> Destination:
        self.controller.tp_ui_unlocked = True
        return Destination(ToolsTpHomeView, clear_history=True)

    def _warn_and_retry(self, text: str) -> Destination:
        self.run_screen(
            WarningScreen,
            title="登录密码",
            status_headline=None,
            text=text,
            show_back_button=False,
            button_data=[ButtonOption("继续")],
        )
        return Destination(ToolsTpUiLockView, clear_history=True)

    def _setup_password(self) -> Destination:
        self.run_screen(
            LargeIconStatusScreen,
            title="设备登录",
            status_headline=None,
            text=(
                "这是首次启动。\n"
                "请先设置 4 到 12 位数字登录密码。\n"
                "以后每次开机先输入它，才会进入离线签名器。"
            ),
            show_back_button=False,
            button_data=[self.SETUP],
        )

        password = _prompt_for_tp_ui_password(self, "设置登录密码")
        if password is None:
            return self._power_destination()
        try:
            _validate_tp_ui_password(password)
        except ValueError as exc:
            return self._warn_and_retry(str(exc))

        confirm_password = _prompt_for_tp_ui_password(self, "确认登录密码")
        if confirm_password is None:
            return self._power_destination()
        if password != confirm_password:
            return self._warn_and_retry("两次输入的登录密码不一致，请重新设置。")

        try:
            _save_tp_ui_password(password)
        except Exception as exc:
            logger.exception("Failed to save TP UI password")
            return self._warn_and_retry(str(exc) or "保存登录密码失败。")

        self.run_screen(
            LargeIconStatusScreen,
            title="设置完成",
            status_headline=None,
            text=(
                "登录密码已启用。\n"
                "以后开机要先输入它，才会进入离线签名器。\n\n"
                "如果以后忘记，需要删除设备本地保存的登录密码文件后重新设置。"
            ),
            show_back_button=False,
            button_data=[ButtonOption("进入离线签名器")],
        )
        return self._unlock_destination()

    def _enter_password(self) -> Destination:
        password = _prompt_for_tp_ui_password(self, "输入登录密码")
        if password is None:
            return self._power_destination()
        if _verify_tp_ui_password(password):
            return self._unlock_destination()
        return self._warn_and_retry("登录密码错误，请重试。")

    def run(self):
        if getattr(self.controller, "tp_ui_unlocked", False):
            return Destination(ToolsTpHomeView, clear_history=True)

        record = _load_tp_ui_lock_record()
        if record is None:
            return self._setup_password()

        self.run_screen(
            LargeIconStatusScreen,
            title="设备登录",
            status_headline=None,
            text="请输入登录密码后进入离线签名器。",
            show_back_button=False,
            button_data=[self.UNLOCK],
        )
        return self._enter_password()


class ToolsTpSeedCreateMnemonicView(View):
    SEEDKEEPER_CREATE = ButtonOption("智能卡创建")
    CAMERA_CREATE = ButtonOption("拍照创建")
    DICE_CREATE = ButtonOption("骰子创建")
    CARD_CREATE = ButtonOption("扑克牌创建")
    HEX_CREATE = ButtonOption("16进制创建")

    def run(self):
        button_data = [
            self.CARD_CREATE,
            self.HEX_CREATE,
            self.DICE_CREATE,
            self.CAMERA_CREATE,
            self.SEEDKEEPER_CREATE,
        ]

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="创建助记词",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpSeedToolsView)

        selected = button_data[selected_menu_num]

        if selected == self.SEEDKEEPER_CREATE:
            from seedsigner.views.tools_views import ToolsSeedkeeperGenerateMnemonicView

            return Destination(
                ToolsSeedkeeperGenerateMnemonicView,
                view_args=dict(
                    return_destination=Destination(
                        ToolsTpSeedCreateMnemonicView,
                        clear_history=True,
                    ),
                ),
            )

        if selected == self.CAMERA_CREATE:
            from seedsigner.views.tools_views import ToolsImageEntropyLivePreviewView

            return Destination(ToolsImageEntropyLivePreviewView)

        if selected == self.DICE_CREATE:
            from seedsigner.views.tools_views import ToolsDiceEntropyMnemonicLengthView

            return Destination(ToolsDiceEntropyMnemonicLengthView)

        if selected == self.CARD_CREATE:
            from seedsigner.views.tools_views import ToolsCardEntropyMnemonicLengthView

            return Destination(ToolsCardEntropyMnemonicLengthView)

        if selected == self.HEX_CREATE:
            from seedsigner.views.tools_views import ToolsHexEntropyMnemonicLengthView

            return Destination(ToolsHexEntropyMnemonicLengthView)

        return Destination(ToolsTpSeedToolsView)


class ToolsTpSeedToolsView(View):
    CREATE_MNEMONIC = ButtonOption("创建助记词")
    IMPORT_SEED = ButtonOption("导入助记词")
    BIP39_CHECK = ButtonOption("BIP39 查询")
    MANAGE_SEEDS = ButtonOption("管理助记词")

    def run(self):
        button_data = [
            self.CREATE_MNEMONIC,
            self.IMPORT_SEED,
            self.BIP39_CHECK,
            self.MANAGE_SEEDS,
        ]

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="助记词工具",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return _tp_home_destination()

        selected = button_data[selected_menu_num]

        if selected == self.CREATE_MNEMONIC:
            return Destination(ToolsTpSeedCreateMnemonicView)

        if selected == self.IMPORT_SEED:
            from seedsigner.views.seed_views import LoadSeedView

            return Destination(LoadSeedView)

        if selected == self.BIP39_CHECK:
            return Destination(ToolsTpBip39CheckMenuView)

        if selected == self.MANAGE_SEEDS:
            if not self.controller.storage.seeds and not self.controller.storage.has_steel_encrypted_mnemonic():
                self.run_screen(
                    WarningScreen,
                    title="提示",
                    status_headline=None,
                    text="当前还没有已加载的助记词，请先创建或导入助记词。",
                    show_back_button=True,
                    button_data=[ButtonOption("继续")],
                )
                return Destination(ToolsTpSeedToolsView)

            from seedsigner.views.seed_views import SeedsMenuView

            return Destination(SeedsMenuView)

        return _tp_home_destination()


class ToolsTpBip39CheckMenuView(View):
    WORD_LOOKUP = ButtonOption("单词查编号")
    INDEX_LOOKUP = ButtonOption("编号查单词")

    def run(self):
        button_data = [self.WORD_LOOKUP, self.INDEX_LOOKUP]
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="BIP39 查询",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpSeedToolsView, clear_history=True)

        selected = button_data[selected_menu_num]
        if selected == self.WORD_LOOKUP:
            return Destination(ToolsTpBip39WordLookupView)
        if selected == self.INDEX_LOOKUP:
            return Destination(ToolsTpBip39IndexLookupView)
        return Destination(ToolsTpSeedToolsView, clear_history=True)


class ToolsTpBip39WordLookupView(View):
    def __init__(self, current_word: str = ""):
        super().__init__()
        self.current_word = current_word

    def run(self):
        ret = ToolsTextQRTextEntryScreen(
            textToEncode=self.current_word,
            title="输入英文单词",
            initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__LOWERCASE_BUTTON_TEXT,
        ).display()

        if ret.get("is_back_button"):
            return Destination(ToolsTpBip39CheckMenuView, clear_history=True)

        word = _normalize_bip39_word(ret.get("textToEncode", ""))
        try:
            report = _build_bip39_word_report(word)
            return Destination(
                ToolsTpBip39CheckResultView,
                view_args=dict(
                    title="BIP39 查询",
                    text=report,
                    return_view="word",
                    return_value=word,
                ),
            )
        except Exception as exc:
            self.run_screen(
                WarningScreen,
                title="查询失败",
                status_headline=None,
                text=str(exc) or "请输入有效的 BIP39 英文单词。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(
                ToolsTpBip39WordLookupView,
                view_args=dict(current_word=word),
                clear_history=True,
            )


class ToolsTpBip39IndexLookupView(View):
    def __init__(self, current_index: str = ""):
        super().__init__()
        self.current_index = current_index

    def run(self):
        ret = ToolsTextQRTextEntryScreen(
            textToEncode=self.current_index,
            title="输入编号 0-2047",
            initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__DIGITS_BUTTON_TEXT,
            digits_entry_mode=True,
        ).display()

        if ret.get("is_back_button"):
            return Destination(ToolsTpBip39CheckMenuView, clear_history=True)

        index_text = _normalize_numeric_entry(ret.get("textToEncode", ""))
        try:
            report = _build_bip39_index_report(index_text)
            return Destination(
                ToolsTpBip39CheckResultView,
                view_args=dict(
                    title="BIP39 查询",
                    text=report,
                    return_view="index",
                    return_value=index_text,
                ),
            )
        except Exception as exc:
            self.run_screen(
                WarningScreen,
                title="查询失败",
                status_headline=None,
                text=str(exc) or "请输入 0 到 2047 的编号。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(
                ToolsTpBip39IndexLookupView,
                view_args=dict(current_index=index_text),
                clear_history=True,
            )


class ToolsTpBip39CheckResultView(View):
    RETRY = ButtonOption("重新查询")
    DONE = ButtonOption("完成")

    def __init__(self, title: str, text: str, return_view: str, return_value: str = "", page_index: int = 0):
        super().__init__()
        self.title = title
        self.text = text
        self.return_view = return_view
        self.return_value = return_value
        self.page_index = page_index

    def run(self):
        button_data = [self.RETRY, self.DONE]

        selected_menu_num = self.run_screen(
            ToolsScrollableTextScreen,
            title=self.title,
            text=self.text,
            text_font_name=GUIConstants.get_body_font_name(),
            text_font_size=max(GUIConstants.get_body_font_size() + 1, 19),
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            selected = self.DONE
        else:
            selected = button_data[selected_menu_num]

        if selected == self.RETRY:
            if self.return_view == "index":
                return Destination(
                    ToolsTpBip39IndexLookupView,
                    view_args=dict(current_index=self.return_value),
                    clear_history=True,
                )
            return Destination(
                ToolsTpBip39WordLookupView,
                view_args=dict(current_word=self.return_value),
                clear_history=True,
            )

        return Destination(ToolsTpBip39CheckMenuView, clear_history=True)


class ToolsTpLoadedSeedOptionsView(View):
    VIEW_WORDS = ButtonOption("查看助记词")
    VIEW_INDICES = ButtonOption("查看 BIP39 序号")
    VIEW_ENTROPY = ButtonOption("查看原始熵")
    SET_PASSPHRASE = ButtonOption("设置密码短语")
    CHANGE_PASSPHRASE = ButtonOption("修改密码短语")
    CLEAR_PASSPHRASE = ButtonOption("清除密码短语")
    DERIVE_ADDRESS = ButtonOption("按路径算地址")
    BIP85_CHILD_SEED = ButtonOption("BIP85 子助记词")
    IMPORT_TO_SMARTCARD = ButtonOption("写入到智能卡")
    SAVE_TO_SEEDKEEPER = ButtonOption("写入到 SeedKeeper")
    SECONDARY_ENCRYPT = ButtonOption("二次加密")
    SECONDARY_DECRYPT = ButtonOption("二次还原")
    PLATE_NUMBERS = ButtonOption("钢板数字")
    DISCARD = ButtonOption("删除助记词", button_label_color="red")

    def __init__(self, seed_num: int):
        super().__init__()
        self.seed_num = seed_num
        self.seed = self.controller.get_seed(seed_num)

    def run(self):
        fingerprint = self.seed.get_fingerprint(self.settings.get_value(SettingsConstants.SETTING__NETWORK))
        title = f"助记词 {fingerprint[:8]}"
        button_data = [
            self.VIEW_WORDS,
            self.SECONDARY_ENCRYPT,
            self.SECONDARY_DECRYPT,
            self.PLATE_NUMBERS,
            self.DISCARD,
        ]
        if getattr(self.seed, "bip39_entropy_supported", False):
            insert_at = 1
            button_data.insert(insert_at, self.VIEW_ENTROPY)
        if not isinstance(self.seed, TransientWordSeed):
            button_data.insert(1, self.DERIVE_ADDRESS)
        if type(self.seed) is Seed:
            if self.seed.has_passphrase:
                button_data.insert(2, self.CHANGE_PASSPHRASE)
                button_data.insert(3, self.CLEAR_PASSPHRASE)
            else:
                button_data.insert(2, self.SET_PASSPHRASE)
        if (
            self.seed.bip85_supported
            and self.settings.get_value(SettingsConstants.SETTING__BIP85_CHILD_SEEDS) == SettingsConstants.OPTION__ENABLED
        ):
            button_data.insert(-1, self.BIP85_CHILD_SEED)
        if self.settings.get_value(SettingsConstants.SETTING__SMARTCARD_SUPPORT) == SettingsConstants.OPTION__ENABLED:
            button_data.insert(-1, self.SAVE_TO_SEEDKEEPER)
        if not isinstance(self.seed, XprvSeed):
            button_data.insert(-1, self.IMPORT_TO_SMARTCARD)

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=title,
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            from seedsigner.views.seed_views import SeedsMenuView
            return Destination(SeedsMenuView, clear_history=True)

        selected = button_data[selected_menu_num]
        if selected == self.VIEW_WORDS:
            from seedsigner.views.seed_views import SeedWordsWarningView
            return Destination(SeedWordsWarningView, view_args=dict(seed_num=self.seed_num))
        if selected == self.VIEW_ENTROPY:
            from seedsigner.views.seed_views import SeedEntropyView
            return Destination(
                SeedEntropyView,
                view_args=dict(
                    seed_num=self.seed_num,
                    title="熵详情",
                    return_destination=Destination(
                        ToolsTpLoadedSeedOptionsView,
                        view_args=dict(seed_num=self.seed_num),
                        skip_current_view=True,
                    ),
                ),
            )
        if selected == self.DERIVE_ADDRESS:
            return Destination(ToolsTpDeriveAddressPathView, view_args=dict(seed_num=self.seed_num))
        if selected in (self.SET_PASSPHRASE, self.CHANGE_PASSPHRASE):
            return Destination(ToolsTpSeedPassphraseView, view_args=dict(seed_num=self.seed_num))
        if selected == self.CLEAR_PASSPHRASE:
            return Destination(ToolsTpSeedPassphraseView, view_args=dict(seed_num=self.seed_num, clear_passphrase=True))
        if selected == self.BIP85_CHILD_SEED:
            from seedsigner.views.seed_views import SeedBIP85ApplicationModeView
            return Destination(SeedBIP85ApplicationModeView, view_args=dict(seed_num=self.seed_num))
        if selected == self.IMPORT_TO_SMARTCARD:
            from seedsigner.views.tools_views import ToolsSatochipImportSeedView
            return Destination(
                ToolsSatochipImportSeedView,
                view_args=dict(
                    preferred_seed_num=self.seed_num,
                    return_destination=Destination(
                        ToolsTpLoadedSeedOptionsView,
                        view_args=dict(seed_num=self.seed_num),
                        clear_history=True,
                    ),
                ),
            )
        if selected == self.SAVE_TO_SEEDKEEPER:
            from seedsigner.views.seed_views import SaveToSeedkeeperView
            if isinstance(self.seed, TransientWordSeed):
                return Destination(
                    SaveToSeedkeeperView,
                    view_args=dict(
                        words_override=list(self.seed.mnemonic_list),
                        bip39_indices_override=_resolve_seed_bip39_indices(self.seed),
                        label_prefix=TP_STEEL_SECRET_PREFIX,
                        success_text="假助记词已保存到 SeedKeeper",
                        return_destination=Destination(
                            ToolsTpLoadedSeedOptionsView,
                            view_args=dict(seed_num=self.seed_num),
                            clear_history=True,
                        ),
                    ),
                )
            return Destination(
                SaveToSeedkeeperView,
                view_args=dict(
                    seed_num=self.seed_num,
                    return_destination=Destination(
                        ToolsTpLoadedSeedOptionsView,
                        view_args=dict(seed_num=self.seed_num),
                        clear_history=True,
                    ),
                ),
            )
        if selected == self.SECONDARY_ENCRYPT:
            return Destination(ToolsTpSteelShiftInputView, view_args=dict(mode="encrypt_seed", seed_num=self.seed_num, word_index=0))
        if selected == self.SECONDARY_DECRYPT:
            return Destination(ToolsTpSteelShiftInputView, view_args=dict(mode="decrypt_seed", seed_num=self.seed_num, word_index=0))
        if selected == self.PLATE_NUMBERS:
            return Destination(ToolsTpSteelShiftInputView, view_args=dict(mode="encrypt_seed_plate", seed_num=self.seed_num, word_index=0))
        if selected == self.DISCARD:
            from seedsigner.views.seed_views import SeedDiscardView
            return Destination(SeedDiscardView, view_args=dict(seed_num=self.seed_num))

        return _tp_home_destination()


class ToolsTpSeedPassphraseView(View):
    DONE = ButtonOption("完成")
    EDIT = ButtonOption("重新输入")
    CONFIRM_CLEAR = ButtonOption("确认清除", button_label_color="red")
    KEEP = ButtonOption("保留密码短语")

    def __init__(self, seed_num: int, clear_passphrase: bool = False):
        super().__init__()
        self.seed_num = seed_num
        self.seed = self.controller.get_seed(seed_num)
        self.clear_passphrase = bool(clear_passphrase)

    def _return_destination(self) -> Destination:
        return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)

    def _fingerprint(self) -> str:
        return self.seed.get_fingerprint(self.settings.get_value(SettingsConstants.SETTING__NETWORK))

    def _show_result(self, title: str, text: str) -> None:
        self.run_screen(
            LargeIconStatusScreen,
            title=title,
            status_headline=None,
            text=text,
            show_back_button=False,
            button_data=[ButtonOption("完成")],
        )

    def _clear_passphrase(self) -> Destination:
        if not self.seed.has_passphrase:
            self._show_result("没有密码短语", "当前助记词未设置 BIP39 密码短语。")
            return self._return_destination()

        selected_menu_num = self.run_screen(
            WarningScreen,
            title="清除密码短语？",
            status_headline=None,
            status_icon_size=GUIConstants.ICON_PRIMARY_SCREEN_SIZE - 8,
            text="清除后会恢复为无 BIP39 密码短语的钱包。\n恢复时只需要助记词。",
            show_back_button=True,
            button_data=[self.KEEP, self.CONFIRM_CLEAR],
        )
        if selected_menu_num == RET_CODE__BACK_BUTTON or [self.KEEP, self.CONFIRM_CLEAR][selected_menu_num] == self.KEEP:
            return self._return_destination()

        old_fingerprint = self._fingerprint()
        self.seed.set_passphrase("")
        new_fingerprint = self._fingerprint()
        self._show_result(
            "密码短语已清除",
            f"原指纹: {old_fingerprint}\n新指纹: {new_fingerprint}",
        )
        return self._return_destination()

    def run(self):
        if type(self.seed) is not Seed:
            self.run_screen(
                WarningScreen,
                title="不支持",
                status_headline=None,
                text="当前这类助记词不支持在这里设置 BIP39 密码短语。",
                show_back_button=False,
                button_data=[ButtonOption("返回")],
            )
            return self._return_destination()

        if self.clear_passphrase:
            return self._clear_passphrase()

        old_passphrase = self.seed.passphrase
        old_fingerprint = self._fingerprint()
        ret_dict = self.run_screen(
            seed_screens.SeedAddPassphraseScreen,
            passphrase=self.seed.passphrase_display,
            title="BIP39 密码短语",
        )
        if ret_dict.get("is_back_button"):
            return self._return_destination()

        new_passphrase = ret_dict["passphrase"]
        if new_passphrase == "":
            if old_passphrase:
                return Destination(ToolsTpSeedPassphraseView, view_args=dict(seed_num=self.seed_num, clear_passphrase=True))
            self._show_result("未设置密码短语", "当前助记词仍为无 BIP39 密码短语。")
            return self._return_destination()

        try:
            self.seed.set_passphrase(new_passphrase)
        except InvalidSeedException as exc:
            self.seed.set_passphrase(old_passphrase)
            self.run_screen(
                WarningScreen,
                title="密码短语无效",
                status_headline=None,
                text=str(exc),
                show_back_button=False,
                button_data=[ButtonOption("重试")],
            )
            return Destination(ToolsTpSeedPassphraseView, view_args=dict(seed_num=self.seed_num), clear_history=True)

        new_fingerprint = self._fingerprint()
        selected_menu_num = self.run_screen(
            seed_screens.SeedReviewPassphraseScreen,
            fingerprint_without=old_fingerprint,
            fingerprint_with=new_fingerprint,
            passphrase=self.seed.passphrase_display,
            button_data=[self.DONE, self.EDIT],
        )
        if selected_menu_num == RET_CODE__BACK_BUTTON or [self.DONE, self.EDIT][selected_menu_num] == self.EDIT:
            self.seed.set_passphrase(old_passphrase)
            return Destination(ToolsTpSeedPassphraseView, view_args=dict(seed_num=self.seed_num), clear_history=True)

        self._show_result(
            "密码短语已更新",
            f"原指纹: {old_fingerprint}\n新指纹: {new_fingerprint}\n\n恢复时需要助记词和密码短语。",
        )
        return self._return_destination()


class ToolsTpDeriveAddressPathView(View):
    def __init__(self, seed_num: int, derivation_path: str = DEFAULT_BTC_ADDRESS_PATH):
        super().__init__()
        self.seed_num = seed_num
        self.derivation_path = derivation_path

    def run(self):
        ret = ToolsTextQRTextEntryScreen(
            textToEncode=self.derivation_path,
            title="派生路径",
            initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__DIGITS_BUTTON_TEXT,
        ).display()

        if ret.get("is_back_button"):
            return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)

        normalized_path = _normalize_bip32_path(ret.get("textToEncode", ""))
        try:
            result = _derive_btc_address_from_seed(
                self.controller.get_seed(self.seed_num),
                normalized_path,
                self.settings.get_value(SettingsConstants.SETTING__NETWORK),
            )
            return Destination(
                ToolsTpDerivedAddressResultView,
                view_args=dict(
                    seed_num=self.seed_num,
                    derivation_path=result["derivation_path"],
                    address=result["address"],
                    network=result["network"],
                    script_type=result["script_type"],
                    address_family=result.get("address_family", "btc"),
                    notes=result.get("notes", ""),
                ),
            )
        except Exception as exc:
            self.run_screen(
                WarningScreen,
                title="派生失败",
                status_headline=None,
                text=_format_derivation_failure(exc, normalized_path or DEFAULT_BTC_ADDRESS_PATH, "无法根据这条路径计算地址。"),
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(
                ToolsTpDeriveAddressPathView,
                view_args=dict(seed_num=self.seed_num, derivation_path=normalized_path or DEFAULT_BTC_ADDRESS_PATH),
                clear_history=True,
            )


class ToolsTpDerivedAddressResultView(View):
    SHOW_QR = ButtonOption("显示二维码")
    DONE = ButtonOption("完成")

    def __init__(
        self,
        seed_num: int | None,
        derivation_path: str,
        address: str,
        network: str,
        script_type: str,
        address_family: str = "btc",
        notes: str = "",
        return_to: str = "seed",
    ):
        super().__init__()
        self.seed_num = seed_num
        self.derivation_path = derivation_path
        self.address = address
        self.network = network
        self.script_type = script_type
        self.address_family = address_family
        self.notes = notes
        self.return_to = return_to

    def _done_destination(self) -> Destination:
        if self.return_to == "smartcard":
            return _smartcard_tools_destination()
        return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)

    def _text(self) -> str:
        text = (
            f"网络: {_network_label(self.network)}\n"
            f"类型: {_script_type_label(self.script_type)}\n\n"
            f"路径:\n{self.derivation_path}\n\n"
            f"地址:\n{self.address}"
        )
        if self.notes:
            text += f"\n\n说明:\n{self.notes}"
        return text

    def _page_specs(self) -> list[dict]:
        pages = [
            dict(
                text=(
                    f"网络: {_network_label(self.network)}\n"
                    f"类型: {_script_type_label(self.script_type)}\n\n"
                    f"路径:\n{_wrap_path_text(self.derivation_path)}"
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=GUIConstants.get_body_font_size(),
            ),
            dict(
                text=_chunk_text(self.address, width=20),
                text_font_name=GUIConstants.FIXED_WIDTH_FONT_NAME,
                text_font_size=GUIConstants.get_body_font_size(),
            ),
        ]
        if self.notes:
            pages.append(
                dict(
                    text=f"说明:\n{self.notes}",
                    text_font_name=GUIConstants.get_body_font_name(),
                    text_font_size=GUIConstants.BODY_FONT_MIN_SIZE,
                )
            )
        return pages

    def _show_qr(self) -> None:
        encoder = GenericStaticQrEncoder(data=self.address)
        self.run_screen(QRDisplayScreen, qr_encoder=encoder)

    def run(self):
        pages = self._page_specs()
        sections = []
        for page in pages:
            text = str(page.get("text") or "").strip()
            if text:
                sections.append(text)

        selected_menu_num = self.run_screen(
            ToolsScrollableTextScreen,
            title="派生地址",
            text="\n\n".join(sections),
            text_font_name=GUIConstants.get_body_font_name(),
            text_font_size=max(GUIConstants.get_body_font_size(), 18),
            button_data=[self.SHOW_QR, self.DONE],
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return self._done_destination()

        selected = [self.SHOW_QR, self.DONE][selected_menu_num]
        if selected == self.SHOW_QR:
            self._show_qr()
        return self._done_destination()


class ToolsTpSeedBtcXpubQrView(View):
    def __init__(self, seed_num: int, xtype: str, return_to_connect_wallet: bool = False):
        super().__init__()
        self.seed_num = seed_num
        self.xtype = xtype.strip().lower()
        self.return_to_connect_wallet = bool(return_to_connect_wallet)

    def _done_destination(self):
        if self.return_to_connect_wallet:
            return Destination(ToolsTpConnectWalletMenuView, clear_history=True)
        return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)

    def run(self):
        export_profile = TP_BTC_XPUB_EXPORTS.get(self.xtype)
        if export_profile is None:
            return _debug_error_destination("32", f"unsupported seed xpub type: {self.xtype}")

        derivation_path = export_profile[0]
        seed = self.controller.get_seed(self.seed_num)

        loading = LoadingScreenThread(text="Generating xpub...")
        loading.start()
        try:
            version = seed.detect_version(
                derivation_path,
                SettingsConstants.MAINNET,
                SettingsConstants.SINGLE_SIG,
            )
            xpub_value = seed.get_root(SettingsConstants.MAINNET).derive(derivation_path).to_public().to_string(version=version)
        except Exception as exc:
            logger.exception("TP seed xpub export failed")
            return _debug_error_destination("53", str(exc))
        finally:
            loading.stop()

        ret = self.run_screen(
            WarningScreen,
            title="提示",
            status_headline=None,
            text=(
                f"当前助记词的 {self.xtype} 可用于观察全部后续 BTC 地址和交易，请只导入自己的手机。\n\n"
                f"账户路径:\n{derivation_path}"
            ),
            show_back_button=True,
            button_data=[ButtonOption("继续")],
        )
        if ret == RET_CODE__BACK_BUTTON:
            return self._done_destination()

        encoder = GenericStaticQrEncoder(data=xpub_value)
        self.run_screen(QRDisplayScreen, qr_encoder=encoder)
        return self._done_destination()


class ToolsTpSteelCipherOptionsView(View):
    VIEW_WORDS = ButtonOption("查看二次加密单词")
    VIEW_INDICES = ButtonOption("查看 BIP39 序号")
    VIEW_PLATE = ButtonOption("查看钢板打孔数字")
    SAVE_TO_SEEDKEEPER = ButtonOption("保存到 SeedKeeper")
    DECRYPT = ButtonOption("二次还原为真实助记词")
    CLEAR = ButtonOption("删除钢板缓存", button_label_color="red")

    def run(self):
        if not self.controller.storage.has_steel_encrypted_mnemonic():
            self.run_screen(
                WarningScreen,
                title="提示",
                status_headline=None,
                text="当前没有钢板二次加密助记词缓存，请先加密或从钢板数字恢复。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(ToolsTpSeedToolsView, clear_history=True)

        button_data = [
            self.VIEW_WORDS,
            self.VIEW_PLATE,
            self.SAVE_TO_SEEDKEEPER,
            self.DECRYPT,
            self.CLEAR,
        ]
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="钢板缓存管理",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            from seedsigner.views.seed_views import SeedsMenuView
            return Destination(SeedsMenuView, clear_history=True)

        selected = button_data[selected_menu_num]
        if selected == self.VIEW_WORDS:
            return Destination(ToolsTpSteelCipherWordsView, view_args=dict(page_index=0))
        if selected == self.VIEW_PLATE:
            groups = self.controller.storage.get_steel_plate_groups()
            if not groups:
                cached_indices = self.controller.storage.get_steel_bip39_indices()
                if cached_indices:
                    groups = indices_to_plate_groups(cached_indices)
                else:
                    try:
                        groups = words_to_plate_groups(self.controller.storage.get_steel_encrypted_mnemonic())
                    except Exception:
                        groups = []
            self.controller.storage.set_steel_plate_groups(groups)
            return Destination(ToolsTpSteelPlateWordsView, view_args=dict(page_index=0))
        if selected == self.SAVE_TO_SEEDKEEPER:
            from seedsigner.views.seed_views import SaveToSeedkeeperView
            return Destination(
                SaveToSeedkeeperView,
                view_args=dict(
                    words_override=self.controller.storage.get_steel_encrypted_mnemonic(),
                    bip39_indices_override=self.controller.storage.get_steel_bip39_indices(),
                    label_prefix=TP_STEEL_SECRET_PREFIX,
                    success_text="二次加密助记词已保存到 SeedKeeper",
                    return_destination=Destination(ToolsTpSteelCipherOptionsView, clear_history=True),
                ),
            )
        if selected == self.DECRYPT:
            return Destination(ToolsTpSteelShiftInputView, view_args=dict(mode="decrypt_cache", word_index=0))
        if selected == self.CLEAR:
            self.controller.storage.clear_steel_cache()
            from seedsigner.views.seed_views import SeedsMenuView
            if self.controller.storage.seeds:
                return Destination(SeedsMenuView, clear_history=True)
            return Destination(ToolsTpSeedToolsView, clear_history=True)
        return _tp_home_destination()


class ToolsTpSteelOperatorSelectView(View):
    ADD = ButtonOption("加法 (+)")
    SUB = ButtonOption("减法 (-)")
    MUL = ButtonOption("乘法 (*)")
    DIV = ButtonOption("除法 (/)")

    def __init__(self, mode: str, seed_num: int | None = None):
        super().__init__()
        self.mode = mode
        self.seed_num = seed_num

    def _back_destination(self) -> Destination:
        if self.mode == "decrypt_cache":
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)
        if self.seed_num is not None:
            return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)
        return Destination(ToolsTpSeedToolsView, clear_history=True)

    def run(self):
        button_data = [self.ADD, self.SUB, self.MUL, self.DIV]
        stored_operator = self.controller.storage.get_steel_shift_operator()
        title = "选择运算方式"
        if self.mode == "decrypt_cache" and stored_operator:
            title = f"选择运算方式（上次：{_operator_display_label(stored_operator)}）"

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=title,
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return self._back_destination()

        operator = ["+", "-", "*", "/"][selected_menu_num]
        return Destination(
            ToolsTpSteelShiftInputView,
            view_args=dict(mode=self.mode, seed_num=self.seed_num, operator=operator, word_index=0),
        )


class ToolsTpSteelShiftInputView(View):
    def __init__(self, mode: str, seed_num: int | None = None, entries: list[str] | None = None, word_index: int = 0):
        super().__init__()
        self.mode = mode
        self.seed_num = seed_num
        self.entries = entries
        self.word_index = word_index

    def _source_words(self) -> list[str]:
        if self.mode == "decrypt_cache":
            words = self.controller.storage.get_steel_encrypted_mnemonic()
            if not words:
                raise ValueError("当前没有可还原的钢板二次加密助记词缓存。")
            return _prepare_shift_source_words(words, context="当前缓存")
        if self.seed_num is None:
            raise ValueError("缺少助记词来源。")
        seed = self.controller.get_seed(self.seed_num)
        if seed is None:
            raise ValueError("没有找到这条已加载助记词，请重新进入后再试。")
        words = seed.mnemonic_display_list
        return _prepare_shift_source_words(words, context="当前助记词")

    def _back_destination(self) -> Destination:
        if self.word_index > 0:
            return Destination(
                ToolsTpSteelShiftInputView,
                view_args=dict(
                    mode=self.mode,
                    seed_num=self.seed_num,
                    entries=self.entries,
                    word_index=self.word_index - 1,
                ),
                clear_history=True,
            )
        if self.mode == "decrypt_cache":
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)
        if self.seed_num is not None:
            return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)
        return Destination(ToolsTpSeedToolsView, clear_history=True)

    def _source_error_destination(self) -> Destination:
        if self.mode == "decrypt_cache":
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)
        if self.seed_num is not None:
            return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)
        return Destination(ToolsTpSeedToolsView, clear_history=True)

    def _default_entries(self, word_count: int) -> list[str]:
        return _ensure_shift_entry_list(None, word_count)

    def run(self):
        entries = list(self.entries or [])
        try:
            source_words = self._source_words()
        except Exception as exc:
            self.run_screen(
                WarningScreen,
                title="操作失败",
                status_headline=None,
                text=str(exc) or "当前助记词词数不完整，暂时不能继续二次加密/还原。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return self._source_error_destination()

        try:
            entries = _ensure_shift_entry_list(entries, len(source_words))

            current_entry = str(entries[self.word_index] or "").strip()
            default_operator = _extract_entry_operator(current_entry)
            result = ToolsTextQRTextEntryScreen(
                textToEncode=current_entry,
                title=f"第 {self.word_index + 1} 个词运算",
                initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__DIGITS_BUTTON_TEXT,
                steel_entry_mode=True,
            ).display()

            if result.get("is_back_button"):
                return self._back_destination()

            operator, value = _parse_shift_entry(
                result.get("textToEncode", ""),
                default_operator=default_operator,
                require_operator=True,
                allow_blank=True,
            )
            entries[self.word_index] = _format_shift_entry(operator, value)
            if self.word_index < len(source_words) - 1:
                return Destination(
                    ToolsTpSteelShiftInputView,
                    view_args=dict(
                        mode=self.mode,
                        seed_num=self.seed_num,
                        entries=entries,
                        word_index=self.word_index + 1,
                    ),
                )
            return Destination(
                ToolsTpSteelShiftReviewView,
                view_args=dict(
                    mode=self.mode,
                    seed_num=self.seed_num,
                    entries=entries,
                    page_index=0,
                ),
            )
        except Exception as exc:
            self.run_screen(
                WarningScreen,
                title="操作失败",
                status_headline=None,
                text=str(exc) or "请输入有效的运算方式和数字，例如 +8。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(
                ToolsTpSteelShiftInputView,
                view_args=dict(
                    mode=self.mode,
                    seed_num=self.seed_num,
                    entries=entries,
                    word_index=self.word_index,
                ),
                clear_history=True,
            )


class ToolsTpSteelShiftReviewView(View):
    REENTER = ButtonOption("重新输入")
    PREVIEW_INDICES = ButtonOption("预览结果序号")
    CONFIRM = ButtonOption("确认执行")

    def __init__(self, mode: str, entries: list[str], seed_num: int | None = None, page_index: int = 0, warned_lossy: bool = False):
        super().__init__()
        self.mode = mode
        self.entries = entries
        self.seed_num = seed_num
        self.page_index = page_index
        self.warned_lossy = warned_lossy

    def _source_words(self) -> list[str]:
        if self.mode == "decrypt_cache":
            words = self.controller.storage.get_steel_encrypted_mnemonic()
            if not words:
                raise ValueError("当前没有可还原的钢板二次加密助记词缓存。")
            return _prepare_shift_source_words(words, context="当前缓存")
        seed = self.controller.get_seed(self.seed_num)
        if seed is None:
            raise ValueError("没有找到这条已加载助记词，请重新进入后再试。")
        return _prepare_shift_source_words(seed.mnemonic_display_list, context="当前助记词")

    def _source_indices(self, source_words: list[str]) -> list[int]:
        if self.mode == "decrypt_cache":
            cached_indices = self.controller.storage.get_steel_bip39_indices()
            if len(cached_indices) == len(source_words):
                return cached_indices
        if self.mode != "decrypt_cache" and self.seed_num is not None:
            seed = self.controller.get_seed(self.seed_num)
            if seed is not None and getattr(seed, "bip39_word_indices_supported", False):
                try:
                    indices = seed.get_bip39_word_indices()
                    if len(indices) == len(source_words):
                        return indices
                except Exception:
                    pass
        return words_to_indices(source_words)

    def _source_error_destination(self) -> Destination:
        if self.mode == "decrypt_cache":
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)
        if self.seed_num is not None:
            return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)
        return Destination(ToolsTpSeedToolsView, clear_history=True)

    def _input_destination(self, word_index: int = 0) -> Destination:
        return Destination(
            ToolsTpSteelShiftInputView,
            view_args=dict(
                mode=self.mode,
                seed_num=self.seed_num,
                entries=self.entries,
                word_index=word_index,
            ),
            clear_history=True,
        )

    def _has_lossy_entries(self) -> bool:
        for entry in self.entries:
            operator = _extract_entry_operator(entry, fallback="")
            if _is_lossy_operator(operator):
                return True
        return False

    def run(self):
        button_data = [self.REENTER, self.PREVIEW_INDICES, self.CONFIRM]
        selected_menu_num = self.run_screen(
            ToolsScrollableTextScreen,
            title="检查运算",
            text=_format_all_shift_entries(self.entries),
            text_font_name=GUIConstants.get_body_font_name(),
            text_font_size=max(GUIConstants.get_body_font_size(), 18),
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(
                ToolsTpSteelShiftInputView,
                view_args=dict(
                    mode=self.mode,
                    seed_num=self.seed_num,
                    entries=self.entries,
                    word_index=len(self.entries) - 1,
                ),
                clear_history=True,
            )

        selected = button_data[selected_menu_num]
        if selected == self.REENTER:
            return Destination(
                ToolsTpSteelShiftInputView,
                view_args=dict(
                    mode=self.mode,
                    seed_num=self.seed_num,
                    entries=self.entries,
                    word_index=0,
                ),
                clear_history=True,
            )

        if selected == self.PREVIEW_INDICES:
            try:
                source_words = self._source_words()
                source_indices = self._source_indices(source_words)
                parsed_entries = [
                    _parse_shift_entry(
                        entry,
                        default_operator=DEFAULT_SHIFT_OPERATOR,
                        require_operator=True,
                        allow_blank=True,
                    )
                    for entry in self.entries[:len(source_words)]
                ]
                operators = [operator for operator, _ in parsed_entries]
                operands = [value for _, value in parsed_entries]
                preview_indices = shift_indices(
                    source_indices,
                    operands,
                    encrypt=True,
                    operators=operators,
                )
                preview_words = indices_to_words(
                    preview_indices
                )
                from seedsigner.views.seed_views import SeedWordIndexView
                return Destination(
                    SeedWordIndexView,
                    view_args=dict(
                        words=preview_words,
                        indices=preview_indices,
                        title="结果 BIP39 序号",
                        return_destination=Destination(
                            ToolsTpSteelShiftReviewView,
                            view_args=dict(
                                mode=self.mode,
                                seed_num=self.seed_num,
                                entries=self.entries,
                                page_index=self.page_index,
                                warned_lossy=self.warned_lossy,
                            ),
                            skip_current_view=True,
                        ),
                    ),
                )
            except Exception as exc:
                self.run_screen(
                    WarningScreen,
                    title="无法预览序号",
                    status_headline=None,
                    text=str(exc) or "当前结果不能转换成 BIP39 0-2047 序号。",
                    show_back_button=False,
                    button_data=[ButtonOption("继续")],
                )
                return Destination(
                    ToolsTpSteelShiftReviewView,
                    view_args=dict(
                        mode=self.mode,
                        seed_num=self.seed_num,
                        entries=self.entries,
                        page_index=self.page_index,
                        warned_lossy=self.warned_lossy,
                    ),
                    clear_history=True,
                )

        if not self.warned_lossy and self._has_lossy_entries():
            warning_selected = self.run_screen(
                WarningScreen,
                title="风险提示",
                status_headline=None,
                text="乘法/除法会丢失信息，不能保证之后一定精确还原。\n真钱请优先用加法/减法。",
                show_back_button=False,
                button_data=[ButtonOption("继续执行"), ButtonOption("返回修改")],
            )
            if warning_selected == RET_CODE__BACK_BUTTON or warning_selected == 1:
                return Destination(
                    ToolsTpSteelShiftInputView,
                    view_args=dict(
                        mode=self.mode,
                        seed_num=self.seed_num,
                        entries=self.entries,
                        word_index=0,
                    ),
                    clear_history=True,
                )
            return Destination(
                ToolsTpSteelShiftReviewView,
                view_args=dict(
                    mode=self.mode,
                    seed_num=self.seed_num,
                    entries=self.entries,
                    page_index=self.page_index,
                    warned_lossy=True,
                ),
                clear_history=True,
            )

        try:
            source_words = self._source_words()
            source_indices = self._source_indices(source_words)
            parsed_entries = [
                _parse_shift_entry(
                    entry,
                    default_operator=DEFAULT_SHIFT_OPERATOR,
                    require_operator=True,
                    allow_blank=True,
                )
                for entry in self.entries[:len(source_words)]
            ]
            operators = [operator for operator, _ in parsed_entries]
            operands = [value for _, value in parsed_entries]
            transformed_indices = shift_indices(
                source_indices,
                operands,
                encrypt=True,
                operators=operators,
            )
            transformed_words = indices_to_words(transformed_indices)

            if self.mode in ("encrypt_seed", "encrypt_seed_plate"):
                source_fingerprint = None
                if self.seed_num is not None:
                    source_fingerprint = self.controller.get_seed(self.seed_num).get_fingerprint(self.settings.get_value(SettingsConstants.SETTING__NETWORK))
                single_operator = operators[0] if len(set(operators)) == 1 else None
                self.controller.storage.set_steel_encrypted_mnemonic(
                    transformed_words,
                    bip39_indices=transformed_indices,
                    shift_values=operands,
                    shift_operators=operators,
                    shift_operator=single_operator,
                    source_fingerprint=source_fingerprint,
                )
                self.controller.storage.set_steel_plate_groups(indices_to_plate_groups(transformed_indices))
                if self.mode == "encrypt_seed_plate":
                    return Destination(ToolsTpSteelPlateWordsView, view_args=dict(page_index=0), clear_history=True)
                return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)

            try:
                restored_seed = Seed(transformed_words)
            except InvalidSeedException:
                restored_seed = TransientWordSeed(
                    transformed_words,
                    bip39_word_indices=transformed_indices,
                )
            self.controller.storage.set_pending_seed(restored_seed)
            seed_num = self.controller.storage.finalize_pending_seed()
            return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=seed_num), clear_history=True)
        except Exception as exc:
            self.run_screen(
                WarningScreen,
                title="操作失败",
                status_headline=None,
                text=str(exc) or "二次加密/还原失败，请返回重试。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            if "当前助记词" in str(exc) or "当前缓存" in str(exc):
                return self._source_error_destination()
            return self._input_destination(word_index=0)


class ToolsTpSteelPlateEntryView(View):
    def __init__(
        self,
        entries: list[str] | None = None,
        word_index: int = 0,
        review_page_index: int | None = None,
        launched_from_load_seed: bool = False,
    ):
        super().__init__()
        self.entries = _ensure_entry_list(entries, 12)
        self.word_index = word_index
        self.review_page_index = review_page_index
        self.launched_from_load_seed = launched_from_load_seed

    def run(self):
        ret = ToolsTextQRTextEntryScreen(
            textToEncode=self.entries[self.word_index],
            title=f"第 {self.word_index + 1} 个词钢板数字",
            initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__DIGITS_BUTTON_TEXT,
            digits_entry_mode=True,
            quick_space_backspace=True,
        ).display()

        if ret.get("is_back_button"):
            if self.review_page_index is not None:
                return Destination(
                    ToolsTpSteelPlateReviewView,
                    view_args=dict(
                        entries=self.entries,
                        page_index=self.review_page_index,
                        launched_from_load_seed=self.launched_from_load_seed,
                    ),
                    clear_history=True,
                )
            if self.word_index == 0:
                if self.launched_from_load_seed:
                    from seedsigner.views.seed_views import LoadSeedView

                    return Destination(LoadSeedView, clear_history=True)
                return Destination(ToolsTpSeedToolsView, clear_history=True)
            return Destination(
                ToolsTpSteelPlateEntryView,
                view_args=dict(
                    entries=self.entries,
                    word_index=self.word_index - 1,
                    launched_from_load_seed=self.launched_from_load_seed,
                ),
                clear_history=True,
            )

        try:
            normalized_entry = _normalize_plate_group_entry(ret.get("textToEncode", ""))
            if not normalized_entry:
                raise ValueError("请输入当前这个助记词的钢板数字。")
            self.entries[self.word_index] = normalized_entry
            if self.review_page_index is not None:
                return Destination(
                    ToolsTpSteelPlateReviewView,
                    view_args=dict(
                        entries=self.entries,
                        page_index=self.review_page_index,
                        launched_from_load_seed=self.launched_from_load_seed,
                    ),
                    clear_history=True,
                )
            if self.word_index < len(self.entries) - 1:
                return Destination(
                    ToolsTpSteelPlateEntryView,
                    view_args=dict(
                        entries=self.entries,
                        word_index=self.word_index + 1,
                        launched_from_load_seed=self.launched_from_load_seed,
                    ),
                )
            return Destination(
                ToolsTpSteelPlateReviewView,
                view_args=dict(
                    entries=self.entries,
                    page_index=0,
                    launched_from_load_seed=self.launched_from_load_seed,
                ),
            )
        except Exception as exc:
            self.run_screen(
                WarningScreen,
                title="钢板恢复失败",
                status_headline=None,
                text=str(exc) or "请输入有效的钢板数字。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(
                ToolsTpSteelPlateEntryView,
                view_args=dict(
                    entries=self.entries,
                    word_index=self.word_index,
                    review_page_index=self.review_page_index,
                    launched_from_load_seed=self.launched_from_load_seed,
                ),
                clear_history=True,
            )


class ToolsTpSteelPlateEditSelectView(View):
    def __init__(self, entries: list[str], page_index: int = 0):
        super().__init__()
        self.entries = entries
        self.page_index = page_index

    def run(self):
        indices = list(range(len(self.entries)))
        button_data = [ButtonOption(f"编辑第 {index + 1:02d} 词") for index in indices]
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="编辑词条",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(
                ToolsTpSteelPlateReviewView,
                view_args=dict(entries=self.entries, page_index=0),
                clear_history=True,
            )

        selected_index = indices[selected_menu_num]
        return Destination(
            ToolsTpSteelPlateEntryView,
            view_args=dict(
                entries=self.entries,
                word_index=selected_index,
                review_page_index=self.page_index,
            ),
            clear_history=True,
        )


class ToolsTpSteelPlateReviewView(View):
    EDIT_PAGE = ButtonOption("编辑词条")
    PREVIEW_INDICES = ButtonOption("预览恢复序号")
    CONFIRM = ButtonOption("确认恢复")

    def __init__(self, entries: list[str], page_index: int = 0, launched_from_load_seed: bool = False):
        super().__init__()
        self.entries = entries
        self.page_index = page_index
        self.launched_from_load_seed = launched_from_load_seed

    def run(self):
        button_data = [self.EDIT_PAGE, self.PREVIEW_INDICES, self.CONFIRM]
        selected_menu_num = self.run_screen(
            ToolsScrollableTextScreen,
            title="检查数字",
            text=_format_all_number_groups(self.entries),
            text_font_name=GUIConstants.get_body_font_name(),
            text_font_size=max(GUIConstants.get_body_font_size(), 18),
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(
                ToolsTpSteelPlateEntryView,
                view_args=dict(
                    entries=self.entries,
                    word_index=len(self.entries) - 1,
                    launched_from_load_seed=self.launched_from_load_seed,
                ),
                clear_history=True,
            )

        selected = button_data[selected_menu_num]
        if selected == self.EDIT_PAGE:
            return Destination(
                ToolsTpSteelPlateEditSelectView,
                view_args=dict(
                    entries=self.entries,
                    page_index=0,
                ),
                clear_history=True,
            )

        if selected == self.PREVIEW_INDICES:
            try:
                indices = parse_restore_indices(",".join(self.entries))
                words = indices_to_words(indices)
                from seedsigner.views.seed_views import SeedWordIndexView
                return Destination(
                    SeedWordIndexView,
                    view_args=dict(
                        words=words,
                        indices=indices,
                        title="恢复结果 BIP39 序号",
                        return_destination=Destination(
                            ToolsTpSteelPlateReviewView,
                            view_args=dict(
                                entries=self.entries,
                                page_index=self.page_index,
                                launched_from_load_seed=self.launched_from_load_seed,
                            ),
                            skip_current_view=True,
                        ),
                    ),
                )
            except Exception as exc:
                self.run_screen(
                    WarningScreen,
                    title="无法预览序号",
                    status_headline=None,
                    text=str(exc) or "钢板数字当前不能转换成 BIP39 0-2047 序号。",
                    show_back_button=False,
                    button_data=[ButtonOption("继续")],
                )
                return Destination(
                    ToolsTpSteelPlateReviewView,
                    view_args=dict(
                        entries=self.entries,
                        page_index=self.page_index,
                        launched_from_load_seed=self.launched_from_load_seed,
                    ),
                    clear_history=True,
                )

        try:
            indices = parse_restore_indices(",".join(self.entries))
            words = indices_to_words(indices)
            seed_num = _store_restored_steel_cipher(self, words, indices=indices)
            return Destination(
                ToolsTpLoadedSeedOptionsView,
                view_args=dict(seed_num=seed_num),
                clear_history=True,
            )
        except Exception as exc:
            self.run_screen(
                WarningScreen,
                title="钢板恢复失败",
                status_headline=None,
                text=str(exc) or "钢板数字有误，请重新检查。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(
                ToolsTpSteelPlateEntryView,
                view_args=dict(
                    entries=self.entries,
                    word_index=0,
                    launched_from_load_seed=self.launched_from_load_seed,
                ),
                clear_history=True,
            )


class ToolsTpSteelCipherWordsView(View):
    DONE = ButtonOption("完成")

    def __init__(self, page_index: int = 0):
        super().__init__()
        self.page_index = page_index

    def run(self):
        from seedsigner.views.seed_views import _format_word_position_lines

        words = self.controller.storage.get_steel_encrypted_mnemonic()
        if not words:
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)

        all_indices = self.controller.storage.get_steel_bip39_indices()
        if len(all_indices) != len(words):
            all_indices = []
        selected_menu_num = self.run_screen(
            ToolsScrollableTextScreen,
            title="假助记词序号",
            text=_format_word_position_lines(
                [str(word or "").strip() or "（空）" for word in words],
                1,
                all_indices if all_indices else None,
                show_index_placeholders=True,
            ),
            text_font_name=GUIConstants.FIXED_WIDTH_FONT_NAME,
            text_font_size=max(GUIConstants.get_body_font_size(), 18),
            button_data=[self.DONE],
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)

        return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)


class ToolsTpSteelPlateWordsView(View):
    VIEW_INDICES = ButtonOption("查看 BIP39 序号")
    DONE = ButtonOption("完成")

    def __init__(self, page_index: int = 0):
        super().__init__()
        self.page_index = page_index

    def run(self):
        groups = self.controller.storage.get_steel_plate_groups()
        cached_indices = self.controller.storage.get_steel_bip39_indices()
        if not groups:
            if cached_indices:
                groups = indices_to_plate_groups(cached_indices)
            else:
                try:
                    groups = words_to_plate_groups(self.controller.storage.get_steel_encrypted_mnemonic())
                except Exception:
                    groups = []
            self.controller.storage.set_steel_plate_groups(groups)
        if not groups:
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)

        words = self.controller.storage.get_steel_encrypted_mnemonic()
        page_text = _format_all_plate_word_pages(
            words,
            groups,
            indices=cached_indices if len(cached_indices) == len(groups) else None,
        )
        button_data = [self.VIEW_INDICES, self.DONE]
        selected_menu_num = self.run_screen(
            ToolsScrollableTextScreen,
            title="打孔位",
            text=page_text,
            text_font_name=GUIConstants.get_body_font_name(),
            text_font_size=max(GUIConstants.get_body_font_size(), 18),
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)

        if button_data[selected_menu_num] == self.VIEW_INDICES:
            from seedsigner.views.seed_views import SeedWordIndexView
            return Destination(
                SeedWordIndexView,
                view_args=dict(
                    title="钢板打孔对应 BIP39 序号",
                    use_steel_cache=True,
                    return_destination=Destination(
                        ToolsTpSteelPlateWordsView,
                        view_args=dict(page_index=self.page_index),
                        skip_current_view=True,
                    ),
                ),
            )
        return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)


class ToolsTpSmartcardToolsView(View):
    SATOCHIP_TOOLS = ButtonOption("Satochip 功能")
    SEEDKEEPER_TOOLS = ButtonOption("SeedKeeper 功能")
    FULL_SMARTCARD_MENU = ButtonOption("完整菜单")

    def run(self):
        button_data = [
            self.SATOCHIP_TOOLS,
            self.SEEDKEEPER_TOOLS,
            self.FULL_SMARTCARD_MENU,
        ]

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="智能卡工具",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return _tp_home_destination()

        selected = button_data[selected_menu_num]

        if selected == self.SATOCHIP_TOOLS:
            return Destination(ToolsTpSatochipToolsView)

        if selected == self.SEEDKEEPER_TOOLS:
            return Destination(ToolsTpSeedkeeperToolsView)

        if selected == self.FULL_SMARTCARD_MENU:
            from seedsigner.views.tools_views import ToolsSmartcardMenuView

            return Destination(ToolsSmartcardMenuView)

        return _tp_home_destination()


class ToolsTpSatochipToolsView(View):
    VIEW_ADDRESS = ButtonOption("按路径看地址")
    IMPORT_LOADED_SEED = ButtonOption("写入助记词")
    CHANGE_PIN = ButtonOption("更改卡 PIN")
    FACTORY_RESET = ButtonOption("重置卡")
    MORE = ButtonOption("更多功能")

    def run(self):
        button_data = [
            self.VIEW_ADDRESS,
            self.IMPORT_LOADED_SEED,
            self.CHANGE_PIN,
            self.FACTORY_RESET,
            self.MORE,
        ]

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="Satochip 功能",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return _smartcard_tools_destination()

        selected = button_data[selected_menu_num]
        if selected == self.VIEW_ADDRESS:
            return Destination(ToolsTpSmartcardAddressPathView)
        if selected == self.IMPORT_LOADED_SEED:
            from seedsigner.views.tools_views import ToolsSatochipImportSeedView
            return Destination(
                ToolsSatochipImportSeedView,
                view_args=dict(
                    return_destination=Destination(ToolsTpSatochipToolsView, clear_history=True),
                ),
            )
        if selected == self.CHANGE_PIN:
            from seedsigner.views.tools_views import ToolsSatochipChangePinView
            return Destination(
                ToolsSatochipChangePinView,
                view_args=dict(
                    card_filter=["satochip"],
                    card_label="Satochip",
                    return_destination=Destination(ToolsTpSatochipToolsView, clear_history=True),
                ),
            )
        if selected == self.FACTORY_RESET:
            from seedsigner.views.tools_views import ToolsSatochipFactoryResetView
            return Destination(
                ToolsSatochipFactoryResetView,
                view_args=dict(
                    card_filter=["satochip"],
                    card_label="Satochip",
                    return_destination=Destination(ToolsTpSatochipToolsView, clear_history=True),
                ),
            )
        if selected == self.MORE:
            from seedsigner.views.tools_views import ToolsSatochipView
            return Destination(ToolsSatochipView)
        return _smartcard_tools_destination()


class ToolsTpSeedkeeperSelectLoadedSeedView(View):
    def run(self):
        from seedsigner.views.seed_views import SaveToSeedkeeperView

        seeds = self.controller.storage.seeds
        if not seeds:
            self.run_screen(
                WarningScreen,
                title="提示",
                status_headline=None,
                text="请先在“助记词工具”里导入或创建助记词，再写入 SeedKeeper。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(ToolsTpSeedkeeperToolsView, clear_history=True)

        button_data = []
        for seed in seeds:
            button_str = seed.get_fingerprint(self.settings.get_value(SettingsConstants.SETTING__NETWORK))
            seed_type = "假助记词" if isinstance(seed, TransientWordSeed) else "助记词"
            button_data.append(ButtonOption(f"{button_str} ({seed_type})"))

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="选择要写入的助记词",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpSeedkeeperToolsView, clear_history=True)

        selected_seed = seeds[selected_menu_num]
        if isinstance(selected_seed, TransientWordSeed):
            return Destination(
                SaveToSeedkeeperView,
                view_args=dict(
                    words_override=list(selected_seed.mnemonic_list),
                    bip39_indices_override=_resolve_seed_bip39_indices(selected_seed),
                    label_prefix=TP_STEEL_SECRET_PREFIX,
                    success_text="假助记词已保存到 SeedKeeper",
                    return_destination=Destination(ToolsTpSeedkeeperToolsView, clear_history=True),
                ),
            )

        return Destination(
            SaveToSeedkeeperView,
            view_args=dict(
                seed_num=selected_menu_num,
                return_destination=Destination(ToolsTpSeedkeeperToolsView, clear_history=True),
            ),
        )


class ToolsTpSeedkeeperLoadSteelCipherView(View):
    def run(self):
        connector = seedkeeper_utils.init_satochip(self, init_card_filter=["seedkeeper"])
        if not connector:
            return Destination(ToolsTpSeedkeeperToolsView, clear_history=True)

        loading = LoadingScreenThread(text="读取 SeedKeeper 列表\n\n\n\n\n\n")
        loading.start()
        try:
            headers = connector.seedkeeper_list_secret_headers()
        finally:
            loading.stop()

        entries = []
        button_data = []
        for header in headers:
            label = header.get("label", "")
            if not label.startswith(TP_STEEL_SECRET_PREFIX):
                continue
            entries.append(header)
            source_label = label[len(TP_STEEL_SECRET_PREFIX):].strip() or f"记录 {header.get('id', len(entries))}"
            display_label = f"假助记词 · {source_label}"
            button_data.append(ButtonOption(display_label))

        if not button_data:
            self.run_screen(
                WarningScreen,
                title="没有可加载内容",
                status_headline=None,
                text="SeedKeeper 里没有已保存的假助记词。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(ToolsTpSeedkeeperToolsView, clear_history=True)

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="选择假助记词",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpSeedkeeperToolsView, clear_history=True)

        selected_entry = entries[selected_menu_num]
        loading = LoadingScreenThread(text="读取 SeedKeeper 内容\n\n\n\n\n\n")
        loading.start()
        try:
            secret_dict = connector.seedkeeper_export_secret(selected_entry["id"], None)
            secret_text = _decode_seedkeeper_text_payload(secret_dict["secret"])
            words, loaded_indices = _parse_seedkeeper_steel_payload(secret_text)
        except Exception as exc:
            loading.stop()
            self.run_screen(
                WarningScreen,
                title="加载失败",
                status_headline=None,
                text=str(exc) or "无法从 SeedKeeper 读取假助记词。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(ToolsTpSeedkeeperToolsView, clear_history=True)
        finally:
            loading.stop()

        label = selected_entry.get("label", "")
        source_label = label[len(TP_STEEL_SECRET_PREFIX):] if label.startswith(TP_STEEL_SECRET_PREFIX) else label
        self.controller.storage.set_steel_encrypted_mnemonic(
            words,
            bip39_indices=loaded_indices,
            source_fingerprint=f"SeedKeeper:{source_label}",
        )
        if loaded_indices is not None:
            self.controller.storage.set_steel_plate_groups(indices_to_plate_groups(loaded_indices))
        else:
            self.controller.storage.set_steel_plate_groups([])
        self.controller.storage.set_pending_seed(
            TransientWordSeed(words, bip39_word_indices=loaded_indices)
        )
        seed_num = self.controller.storage.finalize_pending_seed()

        self.run_screen(
            LargeIconStatusScreen,
            title="加载完成",
            status_headline=None,
            text="已从 SeedKeeper 加载假助记词，并保存到当前助记词列表，可继续查看、核对或二次还原。",
            show_back_button=False,
            button_data=[ButtonOption("继续")],
        )
        return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=seed_num), clear_history=True)


class ToolsTpSeedkeeperToolsView(View):
    GENERATE_MNEMONIC = ButtonOption("智能卡创建")
    SAVE_CURRENT_SEED = ButtonOption("写入到 SeedKeeper")
    SAVE_STEEL_CIPHER = ButtonOption("保存二次加密")
    LOAD_STEEL_CIPHER = ButtonOption("加载二次加密")
    CHANGE_PIN = ButtonOption("更改卡 PIN")
    FACTORY_RESET = ButtonOption("重置卡")
    MORE = ButtonOption("更多功能")

    def run(self):
        button_data = [
            self.GENERATE_MNEMONIC,
            self.SAVE_CURRENT_SEED,
            self.SAVE_STEEL_CIPHER,
            self.LOAD_STEEL_CIPHER,
            self.CHANGE_PIN,
            self.FACTORY_RESET,
            self.MORE,
        ]

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="SeedKeeper 功能",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return _smartcard_tools_destination()

        selected = button_data[selected_menu_num]
        if selected == self.GENERATE_MNEMONIC:
            from seedsigner.views.tools_views import ToolsSeedkeeperGenerateMnemonicView
            return Destination(
                ToolsSeedkeeperGenerateMnemonicView,
                view_args=dict(
                    return_destination=Destination(ToolsTpSeedkeeperToolsView, clear_history=True),
                ),
            )
        if selected == self.SAVE_CURRENT_SEED:
            return Destination(ToolsTpSeedkeeperSelectLoadedSeedView)
        if selected == self.SAVE_STEEL_CIPHER:
            if not self.controller.storage.has_steel_encrypted_mnemonic():
                self.run_screen(
                    WarningScreen,
                    title="提示",
                    status_headline=None,
                    text="当前没有钢板二次加密助记词缓存，请先完成二次加密后再保存。",
                    show_back_button=False,
                    button_data=[ButtonOption("继续")],
                )
                return Destination(ToolsTpSeedkeeperToolsView, clear_history=True)
            from seedsigner.views.seed_views import SaveToSeedkeeperView
            return Destination(
                SaveToSeedkeeperView,
                view_args=dict(
                    words_override=self.controller.storage.get_steel_encrypted_mnemonic(),
                    bip39_indices_override=self.controller.storage.get_steel_bip39_indices(),
                    label_prefix=TP_STEEL_SECRET_PREFIX,
                    success_text="二次加密助记词已保存到 SeedKeeper",
                    return_destination=Destination(ToolsTpSeedkeeperToolsView, clear_history=True),
                ),
            )
        if selected == self.LOAD_STEEL_CIPHER:
            return Destination(ToolsTpSeedkeeperLoadSteelCipherView)
        if selected == self.CHANGE_PIN:
            from seedsigner.views.tools_views import ToolsSatochipChangePinView
            return Destination(
                ToolsSatochipChangePinView,
                view_args=dict(
                    card_filter=["seedkeeper"],
                    card_label="SeedKeeper",
                    return_destination=Destination(ToolsTpSeedkeeperToolsView, clear_history=True),
                ),
            )
        if selected == self.FACTORY_RESET:
            from seedsigner.views.tools_views import ToolsSatochipFactoryResetView
            return Destination(
                ToolsSatochipFactoryResetView,
                view_args=dict(
                    card_filter=["seedkeeper"],
                    card_label="SeedKeeper",
                    return_destination=Destination(ToolsTpSeedkeeperToolsView, clear_history=True),
                ),
            )
        if selected == self.MORE:
            from seedsigner.views.tools_views import ToolsSeedkeeperView
            return Destination(ToolsSeedkeeperView)
        return _smartcard_tools_destination()


class ToolsTpSmartcardAddressPathView(View):
    def __init__(self, derivation_path: str = DEFAULT_BTC_ADDRESS_PATH):
        super().__init__()
        self.derivation_path = derivation_path

    def run(self):
        ret = ToolsTextQRTextEntryScreen(
            textToEncode=self.derivation_path,
            title="智能卡派生路径",
            initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__DIGITS_BUTTON_TEXT,
        ).display()

        if ret.get("is_back_button"):
            return _smartcard_tools_destination()

        normalized_path = _normalize_bip32_path(ret.get("textToEncode", ""))

        try:
            pin = _prompt_for_tp_pin(self)
        except Exception as exc:
            logger.exception("TP smartcard address PIN prompt failed")
            return _debug_error_destination("21", str(exc))

        if pin is None:
            return _smartcard_tools_destination()

        pin = pin.strip()
        if not pin or len(pin) < 4:
            return _smartcard_tools_destination()

        return Destination(
            ToolsTpSmartcardAddressRunView,
            view_args=dict(derivation_path=normalized_path, pin=pin),
            skip_current_view=True,
        )


class ToolsTpSmartcardAddressRunView(View):
    def __init__(self, derivation_path: str, pin: str):
        super().__init__()
        self.derivation_path = derivation_path
        self.pin = pin

    def run(self):
        normalized_path = _normalize_bip32_path(self.derivation_path)
        if _is_evm_derivation_path(normalized_path):
            loading = LoadingScreenThread(text="Calculating address...")
            loading.start()
            try:
                result = _derive_evm_address_via_signer_unlock(self.pin, normalized_path)
            except Exception as exc:
                logger.exception("TP smartcard EVM address derivation failed")
                self.run_screen(
                    WarningScreen,
                    title="派生失败",
                    status_headline=None,
                    text=_format_derivation_failure(exc, normalized_path or DEFAULT_DERIVATION_PATH, "无法根据这条路径计算智能卡地址。"),
                    show_back_button=False,
                    button_data=[ButtonOption("继续")],
                )
                return Destination(
                    ToolsTpSmartcardAddressPathView,
                    view_args=dict(derivation_path=normalized_path or DEFAULT_DERIVATION_PATH),
                    clear_history=True,
                )
            finally:
                loading.stop()

            return Destination(
                ToolsTpDerivedAddressResultView,
                view_args=dict(
                    seed_num=None,
                    derivation_path=result["derivation_path"],
                    address=result["address"],
                    network=result["network"],
                    script_type=result["script_type"],
                    address_family=result.get("address_family", "btc"),
                    notes=result.get("notes", ""),
                    return_to="smartcard",
                ),
                skip_current_view=True,
            )

        connector = seedkeeper_utils.init_satochip(
            self,
            init_card_filter=["satochip"],
            require_pin=False,
        )
        if not connector:
            return _smartcard_tools_destination()

        loading = LoadingScreenThread(text="Verifying PIN")
        loading.start()
        try:
            connector.set_pin(0, list(self.pin.encode("utf-8")))
            _response, sw1, sw2 = connector.card_verify_PIN()
            if sw1 != 0x90 or sw2 != 0x00:
                return _debug_error_destination("45", format_sw_error(sw1, sw2))
        except Exception as exc:
            logger.exception("TP smartcard address PIN verify failed")
            return _debug_error_destination("45", str(exc))
        finally:
            loading.stop()

        loading = LoadingScreenThread(text="Calculating address...")
        loading.start()
        try:
            result = _derive_address_from_satochip(
                connector,
                normalized_path,
                self.settings.get_value(SettingsConstants.SETTING__NETWORK),
            )
        except Exception as exc:
            logger.exception("TP smartcard address derivation failed")
            self.run_screen(
                WarningScreen,
                title="派生失败",
                status_headline=None,
                text=_format_derivation_failure(exc, normalized_path or DEFAULT_BTC_ADDRESS_PATH, "无法根据这条路径计算智能卡地址。"),
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(
                ToolsTpSmartcardAddressPathView,
                view_args=dict(derivation_path=normalized_path or DEFAULT_BTC_ADDRESS_PATH),
                clear_history=True,
            )
        finally:
            loading.stop()

        return Destination(
            ToolsTpDerivedAddressResultView,
            view_args=dict(
                seed_num=None,
                derivation_path=result["derivation_path"],
                address=result["address"],
                network=result["network"],
                script_type=result["script_type"],
                address_family=result.get("address_family", "btc"),
                notes=result.get("notes", ""),
                return_to="smartcard",
            ),
            skip_current_view=True,
        )


class ToolsTpFirmwareIntegrityRunView(View):
    def run(self):
        loading = LoadingScreenThread(text="校验固件...")
        loading.start()
        try:
            result = verify_runtime_manifest()
        except Exception as exc:
            logger.exception("Firmware integrity self-check failed")
            result = {
                "supported": False,
                "ok": False,
                "status": "runtime-error",
                "manifest_path": str(DEFAULT_MANIFEST_PATH),
                "error": f"固件自检运行失败: {exc}",
            }
        finally:
            loading.stop()

        return Destination(
            ToolsTpFirmwareIntegrityResultView,
            view_args=dict(result=result),
            skip_current_view=True,
        )


class ToolsTpFirmwareIntegrityResultView(View):
    VIEW_DETAILS = ButtonOption("查看详情")
    RETRY = ButtonOption("重新自检")
    DONE = ButtonOption("完成")

    def __init__(self, result: dict):
        super().__init__()
        self.result = result

    def run(self):
        button_data = [self.VIEW_DETAILS, self.RETRY, self.DONE]
        selected_menu_num = self.run_screen(
            ToolsScrollableTextScreen,
            title="固件完整性",
            text=_format_firmware_integrity_summary(self.result),
            text_font_name=GUIConstants.get_body_font_name(),
            text_font_size=max(GUIConstants.BODY_FONT_MIN_SIZE, GUIConstants.get_body_font_size() - 2),
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return _tp_home_destination()

        selected = button_data[selected_menu_num]
        if selected == self.VIEW_DETAILS:
            return Destination(
                ToolsTpFirmwareIntegrityDetailsView,
                view_args=dict(result=self.result, page_index=0),
                clear_history=True,
            )
        if selected == self.RETRY:
            return Destination(ToolsTpFirmwareIntegrityRunView, clear_history=True)
        return _tp_home_destination()


class ToolsTpFirmwareIntegrityDetailsView(View):
    BACK = ButtonOption("返回")

    def __init__(self, result: dict, page_index: int = 0):
        super().__init__()
        self.result = result
        self.page_index = page_index

    def run(self):
        pages = _build_firmware_integrity_detail_pages(self.result)

        selected_menu_num = self.run_screen(
            ToolsScrollableTextScreen,
            title="固件完整性",
            text="\n\n".join(page for page in pages if str(page).strip()),
            text_font_name=GUIConstants.get_body_font_name(),
            text_font_size=max(GUIConstants.get_body_font_size(), 18),
            button_data=[self.BACK],
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(
                ToolsTpFirmwareIntegrityResultView,
                view_args=dict(result=self.result),
                clear_history=True,
            )
        return Destination(
            ToolsTpFirmwareIntegrityResultView,
            view_args=dict(result=self.result),
            clear_history=True,
        )


class ToolsTpSignerScanView(View):
    def run(self):
        decoder = TpRequestQrDecoder()
        ret = ScanScreen(
            decoder=decoder,
            instructions_text="",
            show_top_nav=False,
            show_status_overlay=False,
            exit_on_any_button=True,
        ).display()
        if ret == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        self.controller.reset_screensaver_timeout()
        time.sleep(0.1)

        if decoder.is_complete:
            if decoder.error:
                return _debug_error_destination("32", decoder.error)
            if decoder.has_psbt:
                return Destination(
                    ToolsTpSignerPsbtReviewPrepView,
                    view_args=dict(
                        psbt_base64=decoder.get_psbt_base64(),
                        psbt_input_qr_type=decoder.get_psbt_input_qr_type(),
                    ),
                )
            payload = decoder.get_text().strip()
            if not _is_supported_sign_scan_payload(payload):
                return _debug_error_destination("32", "当前扫码内容不是已接入的签名协议，请把原始二维码样本留给我继续兼容。")
            if payload.lower().startswith("tp:exportweb3account-"):
                return Destination(
                    ToolsTpExportWeb3MethodSelectView,
                    view_args=dict(payload=payload),
                )
            return Destination(
                ToolsTpSignerPayloadReviewView,
                view_args=dict(payload=payload),
            )

        if decoder.is_nonUTF8:
            return _tp_home_destination()

        return _tp_home_destination()


class ToolsTpExportWeb3MethodSelectView(View):
    SMARTCARD = ButtonOption("智能卡账户")
    LOADED_SEED = ButtonOption("已加载助记词账户")

    def __init__(self, payload: str):
        super().__init__()
        self.payload = (payload or "").strip()

    def run(self):
        try:
            request = _extract_web3_export_request(self.payload)
        except Exception as exc:
            return _debug_error_destination("32", str(exc))

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="绑定 Web3 账户",
            is_button_text_centered=False,
            button_data=[self.SMARTCARD, self.LOADED_SEED],
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return _tp_home_destination()

        if selected_menu_num == 0:
            return Destination(
                ToolsTpExportWeb3PinEntryView,
                view_args=dict(payload=self.payload),
                skip_current_view=True,
            )

        return Destination(
            ToolsTpExportWeb3SeedSelectView,
            view_args=dict(payload=self.payload, derivation_path=request["derivation_path"]),
            skip_current_view=True,
        )


class ToolsTpExportWeb3PinEntryView(View):
    def __init__(self, payload: str):
        super().__init__()
        self.payload = (payload or "").strip()

    def run(self):
        try:
            pin = _prompt_for_tp_pin(self)
        except Exception as exc:
            logger.exception("TP Web3 export PIN prompt failed")
            return _debug_error_destination("21", str(exc))

        if pin is None:
            return _tp_home_destination()

        pin = pin.strip()
        if not pin or len(pin) < 4:
            return _tp_home_destination()

        return Destination(
            ToolsTpExportWeb3RunView,
            view_args=dict(payload=self.payload, pin=pin),
            skip_current_view=True,
        )


class ToolsTpExportWeb3SeedSelectView(View):
    def __init__(self, payload: str, derivation_path: str):
        super().__init__()
        self.payload = (payload or "").strip()
        self.derivation_path = _normalize_bip32_path(derivation_path)

    def _eligible_seed_options(self) -> tuple[list[int], list[ButtonOption]]:
        seed_nums: list[int] = []
        button_data: list[ButtonOption] = []
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        for seed_num, seed in enumerate(self.controller.storage.seeds):
            if isinstance(seed, TransientWordSeed):
                continue
            try:
                seed.get_root(SettingsConstants.MAINNET)
                fingerprint = seed.get_fingerprint(network)
            except Exception:
                continue
            seed_nums.append(seed_num)
            button_data.append(ButtonOption(f"{seed_num + 1}. {fingerprint[:8]}"))
        return seed_nums, button_data

    def run(self):
        seed_nums, button_data = self._eligible_seed_options()
        if not button_data:
            self.run_screen(
                WarningScreen,
                title="没有可用助记词",
                status_headline=None,
                text="请先在“助记词工具”里导入或创建有效 BIP39 助记词，再绑定 Web3 观察地址。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(
                ToolsTpExportWeb3MethodSelectView,
                view_args=dict(payload=self.payload),
                clear_history=True,
            )

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="选择助记词",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(
                ToolsTpExportWeb3MethodSelectView,
                view_args=dict(payload=self.payload),
                clear_history=True,
            )

        return Destination(
            ToolsTpExportWeb3SeedRunView,
            view_args=dict(payload=self.payload, seed_num=seed_nums[selected_menu_num]),
            skip_current_view=True,
        )


class ToolsTpExportWeb3SeedRunView(View):
    def __init__(self, payload: str, seed_num: int):
        super().__init__()
        self.payload = (payload or "").strip()
        self.seed_num = seed_num

    def run(self):
        try:
            request = _extract_web3_export_request(self.payload)
            seed = self.controller.get_seed(self.seed_num)
        except Exception as exc:
            return _debug_error_destination("63", str(exc))

        loading = LoadingScreenThread(text="绑定 Web3 账户...")
        loading.start()
        try:
            web3_account = _export_web3_account_from_seed(seed, request["derivation_path"])
            response_text = _build_web3_account_export_response(request, web3_account)
        except Exception as exc:
            logger.warning("TP Web3 seed export failed: %s", exc)
            return _debug_error_destination("63", str(exc))
        finally:
            loading.stop()

        return Destination(
            ToolsTpSignerQrView,
            view_args=dict(response_text=response_text, skip_review=True),
            skip_current_view=True,
        )


class ToolsTpExportWeb3RunView(View):
    def __init__(self, payload: str, pin: str):
        super().__init__()
        self.payload = (payload or "").strip()
        self.pin = pin

    def run(self):
        try:
            request = _extract_web3_export_request(self.payload)
        except Exception as exc:
            return _debug_error_destination("32", str(exc))

        connector = seedkeeper_utils.init_satochip(
            self,
            init_card_filter=["satochip"],
            require_pin=False,
        )
        if not connector:
            return _tp_home_destination()

        loading = LoadingScreenThread(text="验证智能卡...")
        loading.start()
        try:
            connector.set_pin(0, list(self.pin.encode("utf-8")))
            _response, sw1, sw2 = connector.card_verify_PIN()
            if sw1 != 0x90 or sw2 != 0x00:
                return _debug_error_destination("45", format_sw_error(sw1, sw2))
            web3_account = _export_web3_account_from_satochip(connector, request["derivation_path"])
            response_text = _build_web3_account_export_response(request, web3_account)
        except Exception as exc:
            logger.warning("TP Web3 smartcard export failed: %s", exc)
            return _debug_error_destination("63", str(exc))
        finally:
            loading.stop()

        return Destination(
            ToolsTpSignerQrView,
            view_args=dict(response_text=response_text, skip_review=True),
            skip_current_view=True,
        )


class ToolsTpBtcXpubPinEntryView(View):
    def __init__(self, xtype: str, return_to_connect_wallet: bool = False):
        super().__init__()
        self.xtype = xtype
        self.return_to_connect_wallet = bool(return_to_connect_wallet)

    def _back_destination(self):
        if self.return_to_connect_wallet:
            return Destination(ToolsTpBtcConnectTypeView, view_args=dict(source="smartcard"), clear_history=True)
        return _smartcard_tools_destination()

    def run(self):
        try:
            pin = _prompt_for_tp_pin(self)
        except Exception as exc:
            logger.exception("TP BTC xpub PIN prompt failed")
            return _debug_error_destination("21", str(exc))

        if pin is None:
            return self._back_destination()

        pin = pin.strip()
        if not pin or len(pin) < 4:
            return self._back_destination()

        return Destination(
            ToolsTpBtcXpubRunView,
            view_args=dict(pin=pin, xtype=self.xtype, return_to_connect_wallet=self.return_to_connect_wallet),
            skip_current_view=True,
        )


class ToolsTpBtcXpubRunView(View):
    def __init__(self, pin: str, xtype: str, return_to_connect_wallet: bool = False):
        super().__init__()
        self.pin = pin
        self.xtype = xtype
        self.return_to_connect_wallet = bool(return_to_connect_wallet)

    def _back_destination(self):
        if self.return_to_connect_wallet:
            return Destination(ToolsTpConnectWalletMenuView, clear_history=True)
        return _smartcard_tools_destination()

    def run(self):
        export_profile = TP_BTC_XPUB_EXPORTS.get(self.xtype.strip().lower())
        if export_profile is None:
            return _debug_error_destination("32", f"unsupported xpub type: {self.xtype}")

        derivation_path, card_xtype = export_profile
        connector = seedkeeper_utils.init_satochip(
            self,
            init_card_filter=["satochip"],
            require_pin=False,
        )
        if not connector:
            return self._back_destination()

        loading = LoadingScreenThread(text="Verifying PIN")
        loading.start()
        try:
            connector.set_pin(0, list(self.pin.encode("utf-8")))
            _response, sw1, sw2 = connector.card_verify_PIN()
            if sw1 != 0x90 or sw2 != 0x00:
                return _debug_error_destination("45", format_sw_error(sw1, sw2))
        except Exception as exc:
            logger.exception("TP BTC xpub PIN verify failed")
            return _debug_error_destination("45", str(exc))
        finally:
            loading.stop()

        loading = LoadingScreenThread(text="Exporting xpub...")
        loading.start()
        try:
            xpub_value = connector.card_bip32_get_xpub(derivation_path, card_xtype, True)
        except Exception as exc:
            logger.exception("TP BTC xpub export failed")
            return _debug_error_destination("53", str(exc))
        finally:
            loading.stop()

        return Destination(
            ToolsTpBtcXpubQrView,
            view_args=dict(xpub=xpub_value, xtype=self.xtype, return_to_connect_wallet=self.return_to_connect_wallet),
            skip_current_view=True,
        )


class ToolsTpBtcXpubQrView(View):
    def __init__(self, xpub: str, xtype: str, return_to_connect_wallet: bool = False):
        super().__init__()
        self.xpub = xpub
        self.xtype = xtype
        self.return_to_connect_wallet = bool(return_to_connect_wallet)

    def _done_destination(self):
        if self.return_to_connect_wallet:
            return Destination(ToolsTpConnectWalletMenuView, clear_history=True)
        return _smartcard_tools_destination()

    def run(self):
        ret = self.run_screen(
            WarningScreen,
            title="提示",
            status_headline=None,
            text=f"智能卡 {self.xtype} 可用于观察全部后续 BTC 地址和交易，请只导入自己的手机。",
            show_back_button=True,
            button_data=[ButtonOption("继续")],
        )
        if ret == RET_CODE__BACK_BUTTON:
            return self._done_destination()

        encoder = GenericStaticQrEncoder(data=self.xpub)
        self.run_screen(QRDisplayScreen, qr_encoder=encoder)
        return self._done_destination()


@dataclass
class ToolsTpDirectQrPagerScreen(BaseScreen):
    title: str = ""
    parts: list[str] = None
    current_index: int = 0

    def __post_init__(self):
        from seedsigner.models.settings import Settings

        super().__post_init__()
        self.parts = [str(part) for part in (self.parts or [""])]
        self.current_index = max(0, min(int(self.current_index), len(self.parts) - 1))
        self.qr_brightness = int(Settings.get_instance().get_value(SettingsConstants.SETTING__QR_BRIGHTNESS))

    def _render(self):
        self.clear_screen()
        hex_color = (hex(max(31, min(255, self.qr_brightness))).split("x")[1]) * 3
        qr_part = self.parts[self.current_index]
        qr_size = min(self.canvas_width, self.canvas_height)
        qr_image = GenericStaticQrEncoder(data=qr_part).part_to_image(
            qr_part,
            qr_size,
            qr_size,
            border=2,
            background_color=hex_color,
        )
        paste_x = max(0, (self.canvas_width - qr_size) // 2)
        paste_y = max(0, (self.canvas_height - qr_size) // 2)
        self.canvas.paste(qr_image, (paste_x, paste_y))

    def _run(self):
        from seedsigner.models.settings import Settings

        while True:
            user_input = self.hw_inputs.wait_for(
                [
                    HardwareButtonsConstants.KEY1,
                    HardwareButtonsConstants.KEY2,
                    HardwareButtonsConstants.KEY3,
                    HardwareButtonsConstants.KEY_PRESS,
                    HardwareButtonsConstants.KEY_LEFT,
                    HardwareButtonsConstants.KEY_RIGHT,
                    HardwareButtonsConstants.KEY_UP,
                    HardwareButtonsConstants.KEY_DOWN,
                ]
            )

            should_rerender = False
            if user_input in (HardwareButtonsConstants.KEY1, HardwareButtonsConstants.KEY_LEFT):
                if self.current_index > 0:
                    self.current_index -= 1
                    should_rerender = True
            elif user_input in (HardwareButtonsConstants.KEY2, HardwareButtonsConstants.KEY_RIGHT):
                if self.current_index < len(self.parts) - 1:
                    self.current_index += 1
                    should_rerender = True
            elif user_input == HardwareButtonsConstants.KEY_UP:
                new_value = min(self.qr_brightness + 31, 255)
                if new_value != self.qr_brightness:
                    self.qr_brightness = new_value
                    should_rerender = True
            elif user_input == HardwareButtonsConstants.KEY_DOWN:
                new_value = max(31, self.qr_brightness - 31)
                if new_value != self.qr_brightness:
                    self.qr_brightness = new_value
                    should_rerender = True
            else:
                break

            if should_rerender:
                with self.renderer.lock:
                    self._render()
                    self.renderer.show_image()

        Settings.get_instance().set_value(SettingsConstants.SETTING__QR_BRIGHTNESS, self.qr_brightness)


class ToolsTpManualQrPartsView(View):
    SHOW_QR = ButtonOption("显示当前二维码")
    PREV = ButtonOption("上一张")
    NEXT = ButtonOption("下一张")
    DONE = ButtonOption("完成")

    def __init__(self, title: str, parts: list[str], current_index: int = 0):
        super().__init__()
        self.title = title
        self.parts = parts or [""]
        self.current_index = max(0, min(current_index, len(self.parts) - 1))

    def _text(self) -> str:
        part_count = len(self.parts)
        return (
            f"当前第 {self.current_index + 1}/{part_count} 张\n\n"
            "先显示这一张二维码，让手机扫完后，再手动切到下一张。\n\n"
            "如果手机漏扫了，可以回到上一张重扫。"
        )

    def _button_data(self) -> list[ButtonOption]:
        button_data = [self.SHOW_QR]
        if self.current_index > 0:
            button_data.append(self.PREV)
        if self.current_index < len(self.parts) - 1:
            button_data.append(self.NEXT)
        button_data.append(self.DONE)
        return button_data

    def _reload(self, current_index: int) -> Destination:
        return Destination(
            ToolsTpManualQrPartsView,
            view_args=dict(
                title=self.title,
                parts=self.parts,
                current_index=current_index,
            ),
            clear_history=True,
        )

    def run(self):
        button_data = self._button_data()
        selected_menu_num = self.run_screen(
            ToolsFormattedTextScreen,
            title=self.title,
            text=self._text(),
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            if self.current_index > 0:
                return self._reload(self.current_index - 1)
            return _tp_home_destination()

        selected = button_data[selected_menu_num]
        if selected == self.SHOW_QR:
            self.run_screen(QRDisplayScreen, qr_encoder=GenericStaticQrEncoder(data=self.parts[self.current_index]))
            return self._reload(self.current_index)
        if selected == self.PREV:
            return self._reload(self.current_index - 1)
        if selected == self.NEXT:
            return self._reload(self.current_index + 1)
        return _tp_home_destination()


class ToolsTpSignerMethodSelectView(View):
    SMARTCARD = ButtonOption("智能卡签名")
    LOADED_SEED = ButtonOption("已加载助记词签名")

    def __init__(
        self,
        payload: str | None = None,
        psbt_base64: str | None = None,
        psbt_input_qr_type: str | None = None,
        response_mode: str | None = None,
    ):
        super().__init__()
        self.payload = (payload or "").strip() or None
        self.psbt_base64 = (psbt_base64 or "").strip() or None
        self.psbt_input_qr_type = psbt_input_qr_type
        self.response_mode = (response_mode or "").strip().lower() or None

    def run(self):
        button_data = [self.SMARTCARD, self.LOADED_SEED]
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="选择签名方式",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return _tp_home_destination()

        selected = button_data[selected_menu_num]
        if selected == self.SMARTCARD:
            return Destination(
                ToolsTpSignerPinEntryView,
                view_args=dict(
                    payload=self.payload,
                    psbt_base64=self.psbt_base64,
                    psbt_input_qr_type=self.psbt_input_qr_type,
                    response_mode=self.response_mode,
                ),
                skip_current_view=True,
            )

        if self.payload and self.payload.lower().startswith("tp:signpsbt-"):
            try:
                _request_id, psbt_base64 = _extract_psbt_request(self.payload)
            except Exception as exc:
                logger.warning("Failed to extract TP PSBT for seed signing: %s", exc)
                return _debug_error_destination("32", str(exc))
            return Destination(
                ToolsTpSignerPsbtSeedSelectView,
                view_args=dict(
                    psbt_base64=psbt_base64,
                    psbt_input_qr_type=self.psbt_input_qr_type,
                    response_mode=self.response_mode or "btctx",
                ),
                skip_current_view=True,
            )

        if self.psbt_base64:
            return Destination(
                ToolsTpSignerPsbtSeedSelectView,
                view_args=dict(
                    psbt_base64=self.psbt_base64,
                    psbt_input_qr_type=self.psbt_input_qr_type,
                    response_mode=self.response_mode,
                ),
                skip_current_view=True,
            )

        if not self.payload:
            return _tp_home_destination()
        return Destination(
            ToolsTpSignerSeedSelectView,
            view_args=dict(payload=self.payload),
            skip_current_view=True,
        )


class ToolsTpSignerSeedSelectView(View):
    def __init__(self, payload: str):
        super().__init__()
        self.payload = (payload or "").strip()

    def _eligible_seed_options(self) -> tuple[list[int], list[ButtonOption]]:
        seed_nums: list[int] = []
        button_data: list[ButtonOption] = []
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        for seed_num, seed in enumerate(self.controller.storage.seeds):
            if isinstance(seed, TransientWordSeed):
                continue
            try:
                seed.get_root(SettingsConstants.MAINNET)
                fingerprint = seed.get_fingerprint(network)
            except Exception:
                continue
            seed_nums.append(seed_num)
            button_data.append(ButtonOption(f"{seed_num + 1}. {fingerprint[:8]}"))
        return seed_nums, button_data

    def run(self):
        seed_nums, button_data = self._eligible_seed_options()
        if not button_data:
            self.run_screen(
                WarningScreen,
                title="没有可用助记词",
                status_headline=None,
                text="请先在“助记词工具”里导入或创建有效 BIP39 助记词，再选择助记词签名。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(ToolsTpSignerMethodSelectView, view_args=dict(payload=self.payload), clear_history=True)

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="选择助记词",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpSignerMethodSelectView, view_args=dict(payload=self.payload), clear_history=True)

        return Destination(
            ToolsTpSignerSeedRunView,
            view_args=dict(payload=self.payload, seed_num=seed_nums[selected_menu_num]),
            skip_current_view=True,
        )


class ToolsTpSignerSeedRunView(View):
    def __init__(self, payload: str, seed_num: int):
        super().__init__()
        self.payload = (payload or "").strip()
        self.seed_num = seed_num
        self.derivation_path = _extract_requested_derivation_path(self.payload)

    def run(self):
        try:
            seed = self.controller.get_seed(self.seed_num)
        except Exception as exc:
            return _debug_error_destination("61", str(exc))

        loading = LoadingScreenThread(text="")
        loading.start()
        try:
            outcome = _sign_tp_payload_with_seed(self.payload, seed, self.derivation_path)
        except Exception as exc:
            logger.warning("TP seed signer failed: %s", exc)
            return _debug_error_destination("61", str(exc))
        finally:
            loading.stop()

        return Destination(
            ToolsTpSignerQrView,
            view_args=dict(response_text=outcome.response_payload),
            skip_current_view=True,
        )


class ToolsTpSignerPsbtSeedSelectView(View):
    def __init__(
        self,
        psbt_base64: str | None = None,
        psbt_input_qr_type: str | None = None,
        response_mode: str | None = None,
    ):
        super().__init__()
        self.psbt_base64 = (psbt_base64 or "").strip()
        self.psbt_input_qr_type = psbt_input_qr_type
        self.response_mode = (response_mode or "").strip().lower() or None

    def _ensure_psbt_loaded(self) -> bool:
        if getattr(self.controller, "psbt", None) is not None:
            return True
        try:
            from embit.psbt import PSBT

            self.controller.psbt = PSBT.from_base64(self.psbt_base64)
        except Exception as exc:
            logger.warning("Failed to load PSBT for seed signing: %s", exc)
            self.run_screen(
                WarningScreen,
                title="PSBT 解析失败",
                status_headline=None,
                text=str(exc) or "当前二维码里的 PSBT 无法读取。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return False
        return True

    def _eligible_seed_options(self) -> tuple[list[int], list[ButtonOption]]:
        from seedsigner.models.psbt_parser import PSBTParser

        seed_nums: list[int] = []
        button_data: list[ButtonOption] = []
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        for seed_num, seed in enumerate(self.controller.storage.seeds):
            if isinstance(seed, TransientWordSeed):
                continue
            try:
                fingerprint = seed.get_fingerprint(network)
            except Exception:
                continue
            try:
                can_sign = PSBTParser.has_matching_input_fingerprint(
                    psbt=self.controller.psbt,
                    seed=seed,
                    network=network,
                )
            except Exception:
                can_sign = True
            label = fingerprint[:8] if can_sign else f"{fingerprint[:8]} (?)"
            seed_nums.append(seed_num)
            button_data.append(ButtonOption(f"{seed_num + 1}. {label}"))
        return seed_nums, button_data

    def run(self):
        if not self._ensure_psbt_loaded():
            return _tp_home_destination()

        seed_nums, button_data = self._eligible_seed_options()
        if not button_data:
            self.run_screen(
                WarningScreen,
                title="没有可用助记词",
                status_headline=None,
                text="请先在“助记词工具”里导入或创建有效 BIP39 助记词，再选择助记词签名。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return _tp_home_destination()

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="选择助记词",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(
                ToolsTpSignerMethodSelectView,
                view_args=dict(
                    psbt_base64=self.psbt_base64,
                    psbt_input_qr_type=self.psbt_input_qr_type,
                    response_mode=self.response_mode,
                ),
                clear_history=True,
            )

        from seedsigner.views.psbt_views import PSBTOverviewView

        self.controller.psbt_seed = self.controller.get_seed(seed_nums[selected_menu_num])
        self.controller.psbt_parser = None
        self.controller.psbt_input_qr_type = self.psbt_input_qr_type
        self.controller.psbt_response_mode = self.response_mode
        self.controller.psbt_sign_with_satochip = False
        self.controller.psbt_external_signer_flow = False
        return Destination(PSBTOverviewView, clear_history=True)


class ToolsTpSignerPayloadReviewView(View):
    def __init__(self, payload: str, page_index: int = 0):
        super().__init__()
        self.payload = (payload or "").strip()
        self.page_index = max(0, int(page_index))

    def run(self):
        if self.payload.lower().startswith("tp:exportweb3account-"):
            return Destination(
                ToolsTpExportWeb3MethodSelectView,
                view_args=dict(payload=self.payload),
                skip_current_view=True,
            )

        if self.payload.lower().startswith("tp:signpsbt-"):
            try:
                _request_id, psbt_base64 = _extract_psbt_request(self.payload)
            except Exception as exc:
                logger.warning("Failed to extract legacy TP PSBT request: %s", exc)
                return _debug_error_destination("32", str(exc))
            return Destination(
                ToolsTpSignerPsbtReviewPrepView,
                view_args=dict(
                    psbt_base64=psbt_base64,
                    psbt_input_qr_type=None,
                    response_mode="btctx",
                ),
                skip_current_view=True,
            )

        try:
            title_base, pages = _build_tp_request_review_pages(self.payload)
        except Exception as exc:
            logger.warning("Offline-signer review parse failed; falling back to direct sign: %s", exc)
            selected = self.run_screen(
                WarningScreen,
                title="无法完整核对",
                status_headline=None,
                text=_localize_error_detail(str(exc)) or "当前无法生成详情页，可以直接输入 PIN 签名。",
                show_back_button=True,
                button_data=[ButtonOption("继续签名")],
            )
            if selected == RET_CODE__BACK_BUTTON:
                return _tp_home_destination()
            return Destination(
                ToolsTpSignerMethodSelectView,
                view_args=dict(payload=self.payload),
                skip_current_view=True,
            )

        if not pages:
            return Destination(
                ToolsTpSignerMethodSelectView,
                view_args=dict(payload=self.payload),
                skip_current_view=True,
            )

        selected = self.run_screen(
            ToolsScrollableTextScreen,
            title=title_base,
            text="\n\n".join(page for page in pages if str(page).strip()),
            text_font_name=GUIConstants.get_body_font_name(),
            text_font_size=max(GUIConstants.get_body_font_size(), 18),
            button_data=[ButtonOption("选择签名方式")],
        )

        if selected == RET_CODE__BACK_BUTTON:
            return _tp_home_destination()

        return Destination(
            ToolsTpSignerMethodSelectView,
            view_args=dict(payload=self.payload),
            skip_current_view=True,
        )


class ToolsTpSignerPsbtReviewPrepView(View):
    def __init__(
        self,
        psbt_base64: str,
        psbt_input_qr_type: str | None = None,
        response_mode: str | None = None,
    ):
        super().__init__()
        self.psbt_base64 = (psbt_base64 or "").strip()
        self.psbt_input_qr_type = psbt_input_qr_type
        self.response_mode = (response_mode or "").strip().lower() or None

    def _warning(self, title: str, text: str):
        self.run_screen(
            WarningScreen,
            title=title,
            status_headline=None,
            text=text,
            show_back_button=False,
            button_data=[ButtonOption("继续")],
        )

    def run(self):
        from embit.psbt import PSBT

        from seedsigner.models.psbt_parser import PSBTParser
        from seedsigner.views.psbt_views import PSBTOverviewView

        try:
            psbt = PSBT.from_base64(self.psbt_base64)
        except Exception as exc:
            logger.warning("Offline-signer PSBT decode failed before review: %s", exc)
            self._warning("PSBT 解析失败", str(exc) or "当前二维码里的 PSBT 无法读取。")
            return _tp_home_destination()

        self.controller.psbt = psbt
        self.controller.psbt_parser = None
        self.controller.psbt_seed = None
        self.controller.psbt_input_qr_type = self.psbt_input_qr_type
        self.controller.psbt_response_mode = self.response_mode
        self.controller.psbt_sign_with_satochip = True
        self.controller.psbt_external_signer_flow = True

        is_multisig_psbt = False
        try:
            if psbt and psbt.inputs:
                first_input = psbt.inputs[0]
                if first_input.witness_utxo:
                    script_pubkey = first_input.witness_utxo.script_pubkey
                elif first_input.non_witness_utxo:
                    script_pubkey = first_input.script_pubkey
                else:
                    script_pubkey = None

                if script_pubkey is not None:
                    policy = PSBTParser._get_policy(first_input, script_pubkey, psbt.xpubs)
                    is_multisig_psbt = isinstance(policy, dict) and "m" in policy
        except Exception as exc:
            logger.debug("Unable to determine PSBT policy in offline-signer review flow", exc_info=exc)

        if is_multisig_psbt:
            try:
                parser = PSBTParser(psbt)
                parser.parse()
            except Exception as exc:
                logger.exception("Failed to parse multisig PSBT for review", exc_info=exc)
                self._warning("无法核对交易", str(exc) or "当前多签 PSBT 不能生成核对页面。")
                return _tp_home_destination()

            self.controller.psbt_parser = parser
            return Destination(PSBTOverviewView, clear_history=True)

        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)

        try:
            first_derivation = next(iter(psbt.inputs[0].bip32_derivations.values()))
            first_der = first_derivation.derivation
        except Exception:
            self._warning("无法核对交易", "PSBT 缺少派生路径，当前不能生成完整核对页面。")
            return _tp_home_destination()

        account_path = []
        hardened_index = 0x80000000
        for idx in first_der:
            if idx & hardened_index:
                account_path.append(idx)
            else:
                break

        account_path_str = "m"
        for idx in account_path:
            hardened = bool(idx & hardened_index)
            index = idx & 0x7FFFFFFF
            suffix = "'" if hardened else ""
            account_path_str += f"/{index}{suffix}"

        purpose = account_path[0] & 0x7FFFFFFF if account_path else 0
        xtype = {
            44: "standard",
            49: "p2wpkh-p2sh",
            84: "p2wpkh",
            48: "p2wsh-p2sh" if len(account_path) > 3 and (account_path[3] & 0x7FFFFFFF) == 1 else "p2wsh",
        }.get(purpose, "standard")

        loading = LoadingScreenThread(text=_("Parsing PSBT..."))
        loading.start()
        loading_stopped = False
        try:
            try:
                parser = PSBTParser(
                    psbt,
                    seed=None,
                    root=None,
                    root_path=account_path,
                    master_fingerprint=getattr(first_derivation, "fingerprint", None),
                    network=network,
                    allow_unverified_single_sig_change=True,
                )
                parser.parse()
            except Exception as exc:
                logger.exception("Failed to build PSBT parser in offline-signer review flow", exc_info=exc)
                loading.stop()
                loading_stopped = True
                self._warning("无法核对交易", str(exc) or "当前 PSBT 不能生成完整核对页面。")
                return _tp_home_destination()
        finally:
            if not loading_stopped:
                loading.stop()

        self.controller.psbt_parser = parser
        return Destination(PSBTOverviewView, clear_history=True)


class ToolsTpSignerPinEntryView(View):
    def __init__(
        self,
        payload: str | None = None,
        psbt_base64: str | None = None,
        psbt_input_qr_type: str | None = None,
        response_mode: str | None = None,
    ):
        super().__init__()
        self.payload = payload
        self.psbt_base64 = psbt_base64
        self.psbt_input_qr_type = psbt_input_qr_type
        self.response_mode = (response_mode or "").strip().lower() or None

    def run(self):
        try:
            pin = _prompt_for_tp_pin(self)
        except Exception as exc:
            logger.exception("TP signer PIN prompt failed")
            return _debug_error_destination("21", str(exc))

        if pin is None:
            return _tp_home_destination()

        pin = pin.strip()
        if not pin or len(pin) < 4:
            return _tp_home_destination()

        if self.psbt_base64:
            return Destination(
                ToolsTpSignerPsbtRunView,
                view_args=dict(
                    pin=pin,
                    psbt_base64=self.psbt_base64,
                    psbt_input_qr_type=self.psbt_input_qr_type,
                    response_mode=self.response_mode,
                ),
                skip_current_view=True,
            )

        if self.payload and self.payload.lower().startswith("tp:signpsbt-"):
            return Destination(
                ToolsTpSignerPsbtRunView,
                view_args=dict(payload=self.payload, pin=pin),
                skip_current_view=True,
            )

        return Destination(
            ToolsTpSignerRunView,
            view_args=dict(payload=self.payload, pin=pin),
            skip_current_view=True,
        )


class ToolsTpSignerPsbtRunView(View):
    def __init__(
        self,
        payload: str | None = None,
        pin: str = "",
        psbt_base64: str | None = None,
        psbt_input_qr_type: str | None = None,
        response_mode: str | None = None,
    ):
        super().__init__()
        self.payload = payload
        self.pin = pin
        self.psbt_input_qr_type = psbt_input_qr_type
        self.response_mode = (response_mode or "").strip().lower() or None
        self.request_id = ""
        self.legacy_tp_request = False

        if payload and payload.lower().startswith("tp:signpsbt-"):
            self.legacy_tp_request = True
            self.response_mode = self.response_mode or "btctx"
            self.request_id, self.psbt_base64 = _extract_psbt_request(payload)
        else:
            self.psbt_base64 = (psbt_base64 or "").strip()

    def run(self):
        if _is_web3_eth_sign_request_payload(self.payload) or _is_web3_native_relay_payload(self.payload):
            loading = LoadingScreenThread(text="")
            loading.start()
            try:
                connector = seedkeeper_utils.init_satochip(
                    self,
                    init_card_filter=["satochip"],
                    require_pin=False,
                )
                if not connector:
                    return _tp_home_destination()

                connector.set_pin(0, list(self.pin.encode("utf-8")))
                _response, sw1, sw2 = connector.card_verify_PIN()
                if sw1 != 0x90 or sw2 != 0x00:
                    return _debug_error_destination("45", format_sw_error(sw1, sw2))

                outcome = _sign_tp_payload_with_satochip(self.payload, connector, self.derivation_path)
                if outcome is None:
                    return _debug_error_destination("32", "当前 Web3 请求暂不支持直接智能卡签名。")
            except Exception as exc:
                logger.warning("Offline-signer Web3 smartcard signer failed: %s", exc)
                return _debug_error_destination("63", str(exc))
            finally:
                loading.stop()

            return Destination(
                ToolsTpSignerQrView,
                view_args=dict(response_text=outcome.response_payload),
                skip_current_view=True,
            )

        signer_bin = _resolve_signer_bin()
        if not signer_bin.is_file():
            return _masked_error_destination("31")

        loading = LoadingScreenThread(text="")
        loading.start()
        try:
            with tempfile.TemporaryDirectory(prefix="offline-btc-psbt-", dir=_runtime_tmp_dir()) as tmpdir:
                tmpdir_path = Path(tmpdir)
                psbt_input_path = tmpdir_path / "unsigned.psbt.txt"
                signed_psbt_path = tmpdir_path / "signed.psbt.txt"
                tx_path = tmpdir_path / "signed.tx.hex"
                psbt_input_path.write_text(self.psbt_base64 + "\n", encoding="utf-8")

                cmd = [
                    str(signer_bin),
                    "sign-psbt",
                    "--pin",
                    self.pin,
                    "--psbt-file",
                    str(psbt_input_path),
                    "--out-psbt-base64",
                    str(signed_psbt_path),
                    "--out-tx",
                    str(tx_path),
                    "--timeout-sec",
                    "120",
                ]
                if DEFAULT_READER_HINT:
                    cmd.extend(["--reader", DEFAULT_READER_HINT])

                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    timeout=150,
                )
                if proc.returncode != 0:
                    detail = _extract_error(proc.stdout, proc.stderr, "sign-psbt failed")
                    logger.warning("Offline-signer BTC PSBT signer failed: %s", detail)
                    code = _map_signer_error_code(detail)
                    if code == "32":
                        return _debug_error_destination(code, detail)
                    return _masked_error_destination(code)

                signed_psbt_base64 = ""
                if signed_psbt_path.exists():
                    signed_psbt_base64 = signed_psbt_path.read_text(encoding="utf-8").strip()

                tx_hex = ""
                if tx_path.exists():
                    tx_hex = tx_path.read_text(encoding="utf-8").strip()

                if (self.response_mode == "btctx" or self.legacy_tp_request) and not tx_hex:
                    return _masked_error_destination("33")
                if self.response_mode != "btctx" and not self.legacy_tp_request and not signed_psbt_base64:
                    return _masked_error_destination("33")
        except subprocess.TimeoutExpired:
            return _masked_error_destination("34")
        except Exception as exc:
            logger.warning("Offline-signer BTC PSBT flow failed: %s", exc)
            return _masked_error_destination("35")
        finally:
            loading.stop()

        if self.response_mode == "btctx" or self.legacy_tp_request:
            return Destination(
                ToolsTpSignerQrView,
                view_args=dict(response_text=f"btctx:{tx_hex}"),
                skip_current_view=True,
            )

        if not self.legacy_tp_request:
            return Destination(
                ToolsTpSignerPsbtQrView,
                view_args=dict(
                    psbt_base64=signed_psbt_base64,
                    input_qr_type=self.psbt_input_qr_type,
                    tx_hex=tx_hex or None,
                ),
                skip_current_view=True,
            )

        return Destination(
            ToolsTpSignerQrView,
            view_args=dict(response_text=f"btctx:{tx_hex}"),
            skip_current_view=True,
        )


class ToolsTpSignerRunView(View):
    def __init__(self, payload: str, pin: str):
        super().__init__()
        self.payload = payload
        self.pin = pin
        self.derivation_path = _extract_requested_derivation_path(payload)
        self.execution_payload = _resolve_sign_execution_payload(payload)

    def run(self):
        if _is_web3_eth_sign_request_payload(self.payload) or _is_web3_native_relay_payload(self.payload):
            loading = LoadingScreenThread(text="")
            loading.start()
            try:
                connector = seedkeeper_utils.init_satochip(
                    self,
                    init_card_filter=["satochip"],
                    require_pin=False,
                )
                if not connector:
                    return _tp_home_destination()

                connector.set_pin(0, list(self.pin.encode("utf-8")))
                _response, sw1, sw2 = connector.card_verify_PIN()
                if sw1 != 0x90 or sw2 != 0x00:
                    return _debug_error_destination("45", format_sw_error(sw1, sw2))

                outcome = _sign_tp_payload_with_satochip(self.payload, connector, self.derivation_path)
                if outcome is None:
                    return _debug_error_destination("32", "当前 Web3 请求暂不支持直接智能卡签名。")
            except Exception as exc:
                logger.warning("Offline-signer Web3 smartcard signer failed: %s", exc)
                return _debug_error_destination("63", str(exc))
            finally:
                loading.stop()

            return Destination(
                ToolsTpSignerQrView,
                view_args=dict(response_text=outcome.response_payload),
                skip_current_view=True,
            )

        signer_bin = _resolve_signer_bin()
        if not signer_bin.is_file():
            return _masked_error_destination("31")

        loading = LoadingScreenThread(text="")
        loading.start()
        try:
            with tempfile.TemporaryDirectory(prefix="offline-signer-", dir=_runtime_tmp_dir()) as tmpdir:
                tmpdir_path = Path(tmpdir)
                request_path = tmpdir_path / "request.txt"
                response_path = tmpdir_path / "response.txt"
                request_path.write_text(self.execution_payload + "\n", encoding="utf-8")

                cmd = [
                    str(signer_bin),
                    "sign",
                    "--pin",
                    self.pin,
                    "--path",
                    self.derivation_path,
                    "--payload-file",
                    str(request_path),
                    "--out",
                    str(response_path),
                    "--timeout-sec",
                    "120",
                ]
                if DEFAULT_READER_HINT:
                    cmd.extend(["--reader", DEFAULT_READER_HINT])
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    timeout=150,
                )
                if proc.returncode != 0:
                    if response_path.exists():
                        response_text = response_path.read_text(encoding="utf-8").strip()
                        if response_text:
                            response_text = _finalize_native_wallet_response(self.payload, response_text)
                            return Destination(
                                ToolsTpSignerQrView,
                                view_args=dict(response_text=response_text),
                                skip_current_view=True,
                            )
                    detail = _extract_error(proc.stdout, proc.stderr, "sign failed")
                    logger.warning("Offline-signer signer failed: %s", detail)
                    code = _map_signer_error_code(detail)
                    if code == "51":
                        return _debug_error_destination(code, detail)
                    if code == "32":
                        return _debug_error_destination(code, detail)
                    return _masked_error_destination(code)

                if not response_path.exists():
                    return _masked_error_destination("33")

                response_text = response_path.read_text(encoding="utf-8").strip()
                response_text = _finalize_native_wallet_response(self.payload, response_text)
        except subprocess.TimeoutExpired:
            return _masked_error_destination("34")
        except Exception as exc:
            _ = exc
            return _masked_error_destination("35")
        finally:
            loading.stop()

        return Destination(
            ToolsTpSignerQrView,
            view_args=dict(response_text=response_text),
            skip_current_view=True,
        )


class ToolsTpSignerQrView(View):
    SHOW_QR = ButtonOption("显示签名二维码")

    def __init__(self, response_text: str, page_index: int = 0, skip_review: bool = False):
        super().__init__()
        self.response_text = response_text
        self.page_index = max(0, int(page_index))
        self.skip_review = bool(skip_review)

    def _reload(self, page_index: int, skip_review: bool = False) -> Destination:
        return Destination(
            ToolsTpSignerQrView,
            view_args=dict(
                response_text=self.response_text,
                page_index=page_index,
                skip_review=skip_review,
            ),
            clear_history=True,
        )

    def _get_qr_encoder(self):
        response = str(self.response_text or "").strip()
        if response.lower().startswith("ur:eth-signature/"):
            return _configure_high_margin_qr_encoder(ToolsTpEthSignatureQrEncoder(response))
        return GenericStaticQrEncoder(data=response)

    def run(self):
        qr_encoder = self._get_qr_encoder()
        if not self.skip_review:
            title_base, pages = _build_tp_signed_response_review_pages(self.response_text, qr_encoder=qr_encoder)
            button_data = [self.SHOW_QR]

            selected = self.run_screen(
                ToolsScrollableTextScreen,
                title=title_base,
                text="\n\n".join(page for page in pages if str(page).strip()),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size() + 1, 19),
                button_data=button_data,
            )

            if selected == RET_CODE__BACK_BUTTON:
                return _tp_home_destination()
            return self._reload(0, skip_review=True)

        self.run_screen(QRDisplayScreen, qr_encoder=qr_encoder)
        return _tp_home_destination()


class ToolsTpSignerPsbtQrView(View):
    SHOW_QR = ButtonOption("显示签名二维码")

    def __init__(
        self,
        psbt_base64: str,
        input_qr_type: str | None = None,
        tx_hex: str | None = None,
        page_index: int = 0,
        skip_review: bool = False,
    ):
        super().__init__()
        self.psbt_base64 = psbt_base64
        self.input_qr_type = input_qr_type
        self.tx_hex = tx_hex
        self.page_index = max(0, int(page_index))
        self.skip_review = bool(skip_review)

    def _reload(self, page_index: int, skip_review: bool = False) -> Destination:
        return Destination(
            ToolsTpSignerPsbtQrView,
            view_args=dict(
                psbt_base64=self.psbt_base64,
                input_qr_type=self.input_qr_type,
                tx_hex=self.tx_hex,
                page_index=page_index,
                skip_review=skip_review,
            ),
            clear_history=True,
        )

    def _qr_encoder_cache_key(self):
        return (self.psbt_base64, self.input_qr_type, self.tx_hex)

    def _get_qr_encoder(self):
        cache_key = self._qr_encoder_cache_key()
        if getattr(self.controller, "_tp_signed_psbt_qr_encoder_cache_key", None) == cache_key:
            cached_encoder = getattr(self.controller, "_tp_signed_psbt_qr_encoder", None)
            if cached_encoder is not None:
                return cached_encoder

        if not self.psbt_base64 and self.tx_hex:
            from seedsigner.models.encode_qr import BbqrTextQrEncoder

            encoder = BbqrTextQrEncoder(
                text=self.tx_hex,
                file_type="U",
                encoding_preference="Z",
                min_version=4,
                max_version=4,
                min_split=1,
                max_split=8,
                frame_repeat=1,
            )
        else:
            from embit.psbt import PSBT
            from seedsigner.models.encode_qr import build_signed_psbt_qr_encoder

            psbt = PSBT.from_base64(self.psbt_base64)
            qr_density = self.settings.get_value(SettingsConstants.SETTING__QR_DENSITY)
            encoder = build_signed_psbt_qr_encoder(
                psbt=psbt,
                qr_density=qr_density,
                input_qr_type=self.input_qr_type,
            )

        self.controller._tp_signed_psbt_qr_encoder_cache_key = cache_key
        self.controller._tp_signed_psbt_qr_encoder = encoder
        return encoder

    def _clear_qr_encoder_cache(self) -> None:
        self.controller._tp_signed_psbt_qr_encoder_cache_key = None
        self.controller._tp_signed_psbt_qr_encoder = None

    def run(self):
        try:
            qr_encoder = self._get_qr_encoder()
        except Exception as exc:
            logger.warning("Offline-signer signed PSBT QR render failed: %s", exc)
            if not self.tx_hex:
                return _masked_error_destination("33")
            if not self.psbt_base64:
                qr_encoder = GenericStaticQrEncoder(data=self.tx_hex)
            else:
                return _masked_error_destination("33")

        if not self.skip_review:
            title_base, pages = _build_tp_signed_psbt_review_pages(
                psbt_base64=self.psbt_base64,
                input_qr_type=self.input_qr_type,
                tx_hex=self.tx_hex,
                qr_encoder=qr_encoder,
            )
            button_data = [self.SHOW_QR]

            selected = self.run_screen(
                ToolsScrollableTextScreen,
                title=title_base,
                text="\n\n".join(page for page in pages if str(page).strip()),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size() + 1, 19),
                button_data=button_data,
            )

            if selected == RET_CODE__BACK_BUTTON:
                self._clear_qr_encoder_cache()
                return _tp_home_destination()
            return self._reload(0, skip_review=True)

        if not self.psbt_base64 and self.tx_hex:
            self.run_screen(QRDisplayScreen, qr_encoder=qr_encoder)
            self._clear_qr_encoder_cache()
            return _tp_home_destination()

        self.run_screen(QRDisplayScreen, qr_encoder=qr_encoder)
        self._clear_qr_encoder_cache()
        return _tp_home_destination()
