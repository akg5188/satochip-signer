import json
import logging
import os
import subprocess
import tempfile
import time
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs

from embit import script as embit_script
from embit.networks import NETWORKS
from gettext import gettext as _

from seedsigner.gui.components import GUIConstants
from seedsigner.gui.screens import RET_CODE__BACK_BUTTON, ButtonListScreen, WarningScreen, LargeIconStatusScreen, seed_screens
from seedsigner.gui.screens.scan_screens import ScanScreen
from seedsigner.gui.screens.screen import ButtonOption, LoadingScreenThread, QRDisplayScreen
from seedsigner.gui.screens.tools_screens import ToolsFormattedTextScreen, ToolsTextQRTextEntryScreen
from seedsigner.helpers.tp_fragment import FragmentParseError, MultiFragmentAssembler, parse_tp_multi_fragment
from seedsigner.helpers.tp_relay import RelayAssembler, RelayParseError, parse_tp_relay_fragment
from seedsigner.helpers import embit_utils, seedkeeper_utils
from seedsigner.models.decode_qr import DecodeQR, DecodeQRStatus
from seedsigner.models.encode_qr import GenericStaticQrEncoder
from seedsigner.models.mnemonic_steel import (
    DEFAULT_SHIFT_OPERATOR,
    OPERATOR_LABELS,
    WEIGHT_SET,
    WORDLIST as STEEL_WORDLIST,
    get_word_at_index,
    indices_to_words,
    lookup_word_index,
    parse_restore_indices,
    shift_mnemonic,
    solve_weights,
    words_to_plate_groups,
)
from seedsigner.models.seed import InvalidSeedException, Seed, TransientWordSeed
from seedsigner.models.steel_plate_scan import recognize_plate_groups_from_image
from seedsigner.models.settings import SettingsConstants

from .view import Destination, ErrorView, View


DEFAULT_DERIVATION_PATH = "m/44'/60'/0'/0/0"
DEFAULT_BTC_ADDRESS_PATH = "m/84'/0'/0'/0/0"
DEFAULT_READER_HINT = None
CAMO_BUTTON_TEXT = " "
CAMO_TEXT = " "
STEEL_WRAP_WIDTH = 18

logger = logging.getLogger(__name__)


def _localize_error_detail(detail: str) -> str:
    short = (detail or "").strip().replace("\n", " ")
    lowered = short.lower()
    known_messages = [
        (
            "hardwarebuttons.wait_for()" in lowered and "check_release" in lowered,
            "按钮输入模块不兼容，现已改为兼容官方输入流程，请刷新到最新固件。",
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

    TP-only mode tweaks several screens for the simplified launcher. For PIN entry we
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
    value = (path or "").strip()
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
    return (path or "").strip().replace("H", "'").replace("h", "'")


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
    return "\n".join(value[i:i + width] for i in range(0, len(value), width))


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


def _resolve_derivation_network(path_details: dict, current_network: str) -> str:
    parsed_network = path_details.get("network")
    if isinstance(parsed_network, list):
        if current_network in parsed_network:
            return current_network
        return parsed_network[0]
    if parsed_network:
        return parsed_network
    return current_network


def _derive_btc_address_from_seed(seed: Seed, derivation_path: str, current_network: str) -> dict:
    normalized_path = _normalize_bip32_path(derivation_path)
    if not _is_valid_bip32_path(normalized_path):
        raise ValueError("派生路径格式不正确。")
    if isinstance(seed, TransientWordSeed):
        raise ValueError("当前这条助记词不是有效 BIP39，无法派生地址。")

    path_details = embit_utils.parse_derivation_path(normalized_path.replace("'", "h"))
    script_type = path_details.get("script_type")
    if script_type in (None, SettingsConstants.CUSTOM_DERIVATION):
        raise ValueError("当前只支持 44'/49'/84'/86' 这几类 BTC 路径。")

    network = _resolve_derivation_network(path_details, current_network)
    embit_network = SettingsConstants.map_network_to_embit(network)
    if not embit_network:
        raise ValueError("无法识别这条路径对应的网络。")

    root = seed.get_root(network)
    pubkey = root.derive(normalized_path).key

    if script_type == SettingsConstants.LEGACY_P2PKH:
        address = embit_script.p2pkh(pubkey).address(network=NETWORKS[embit_network])
    elif script_type == SettingsConstants.NESTED_SEGWIT:
        address = embit_script.p2sh(embit_script.p2wpkh(pubkey)).address(network=NETWORKS[embit_network])
    elif script_type == SettingsConstants.NATIVE_SEGWIT:
        address = embit_script.p2wpkh(pubkey).address(network=NETWORKS[embit_network])
    elif script_type == SettingsConstants.TAPROOT:
        address = embit_script.p2tr(pubkey).address(network=NETWORKS[embit_network])
    else:
        raise ValueError("当前路径类型暂不支持显示地址。")

    return {
        "derivation_path": normalized_path,
        "network": network,
        "script_type": script_type,
        "address": address,
    }


def _extract_requested_derivation_path(payload: str) -> str:
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
        self.total_segments = 1
        self.collected_segments = 0
        self.is_nonUTF8 = False
        self.error = ""
        self._seen = set()
        self._assembler = MultiFragmentAssembler()
        self._relay_assembler = RelayAssembler()

    @property
    def is_complete(self) -> bool:
        return self.complete

    def get_text(self) -> str:
        return self.text or ""

    def get_percent_complete(self, weight_mixed_frames: bool = False) -> int:
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

        self.text = text
        self.complete = True
        self.collected_segments = 1
        return DecodeQRStatus.COMPLETE


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
    env_path = os.environ.get("TP_PI_SIGNER_BIN", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("/opt/tp-pi-signer/bin/pi-signer"))
    candidates.append(Path("/opt/pi-signer-py/bin/pi-signer"))
    candidates.append(Path(__file__).resolve().parents[3] / "pi-signer-py/bin/pi-signer")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[-1]


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


def _tp_home_destination() -> Destination:
    return Destination(ToolsTpHomeView, clear_history=True)


def _steel_camera_capture_destination() -> Destination:
    from seedsigner.views.tools_views import ToolsImageEntropyLivePreviewView

    return Destination(
        ToolsImageEntropyLivePreviewView,
        view_args=dict(next_view=ToolsTpSteelPlatePhotoProcessView),
    )


def _normalize_numeric_entry(raw: str) -> str:
    return " ".join(str(raw or "").replace("，", " ").replace(",", " ").split())


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
    total_pages = max(1, (len(entries) + entries_per_page - 1) // entries_per_page)
    start = page_index * entries_per_page
    selected_entries = entries[start:start + entries_per_page]
    lines = []
    for offset, entry in enumerate(selected_entries):
        if lines:
            lines.append("")
        lines.extend(_wrap_number_group(start + offset, entry))
    return "\n".join(lines), total_pages


def _format_shift_entries(entries: list[str], page_index: int, entries_per_page: int = 6) -> tuple[str, int]:
    total_pages = max(1, (len(entries) + entries_per_page - 1) // entries_per_page)
    start = page_index * entries_per_page
    selected_entries = entries[start:start + entries_per_page]
    lines = []
    for offset, entry in enumerate(selected_entries):
        normalized = str(entry or "").strip()
        lines.append(f"{start + offset + 1:02d}: {normalized or '（不变）'}")
    return "\n".join(lines), total_pages


def _is_lossy_operator(operator: str | None) -> bool:
    return operator in ("*", "/")


def _normalize_bip39_word(word: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(word or "")).lower()
    return "".join(ch for ch in normalized if "a" <= ch <= "z")


def _format_weight_line(index: int) -> str:
    weights = solve_weights(index)
    if not weights:
        return "0"
    return " ".join(str(weight) for weight in weights)


def _build_bip39_word_report(word: str) -> str:
    normalized = _normalize_bip39_word(word)
    if not normalized:
        raise ValueError("请输入英文单词。")
    index = lookup_word_index(normalized)
    previous_word = get_word_at_index(index - 1) if index > 0 else "（无）"
    next_word = get_word_at_index(index + 1) if index < 2047 else "（无）"
    return (
        f"单词:\n{normalized}\n\n"
        f"编号(0-2047):\n{index}\n\n"
        f"前一个:\n{previous_word}\n\n"
        f"后一个:\n{next_word}\n\n"
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
        f"编号:\n{index}\n\n"
        f"单词:\n{word}\n\n"
        f"前一个:\n{previous_word}\n\n"
        f"后一个:\n{next_word}\n\n"
        f"钢板位权:\n{_format_weight_line(index)}"
    )


def _operator_display_label(operator: str) -> str:
    return OPERATOR_LABELS.get(operator, operator)


class ToolsTpHomeView(View):
    SCAN = ButtonOption("扫码签名")
    EXPORT_BTC_ZPUB = ButtonOption("导出 BTC zpub")
    EXPORT_BTC_XPUB = ButtonOption("导出 BTC xpub")
    SEED_TOOLS = ButtonOption("助记词工具")
    SMARTCARD_TOOLS = ButtonOption("智能卡工具")

    def run(self):
        button_data = [
            self.SCAN,
            self.EXPORT_BTC_ZPUB,
            self.EXPORT_BTC_XPUB,
            self.SEED_TOOLS,
            self.SMARTCARD_TOOLS,
        ]

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="TP 签名器",
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return _tp_home_destination()

        if button_data[selected_menu_num] == self.SCAN:
            return Destination(ToolsTpSignerScanView)
        if button_data[selected_menu_num] == self.EXPORT_BTC_ZPUB:
            return Destination(ToolsTpBtcXpubPinEntryView, view_args=dict(xtype="zpub"))
        if button_data[selected_menu_num] == self.EXPORT_BTC_XPUB:
            return Destination(ToolsTpBtcXpubPinEntryView, view_args=dict(xtype="xpub"))
        if button_data[selected_menu_num] == self.SEED_TOOLS:
            return Destination(ToolsTpSeedToolsView)
        if button_data[selected_menu_num] == self.SMARTCARD_TOOLS:
            return Destination(ToolsTpSmartcardToolsView)

        return _tp_home_destination()


class ToolsTpSeedToolsView(View):
    CAMERA_CREATE = ButtonOption("拍照创建助记词")
    DICE_CREATE = ButtonOption("摇骰子创建助记词")
    IMPORT_SEED = ButtonOption("导入助记词")
    BIP39_CHECK = ButtonOption("BIP39 单词自检")
    STEEL_RESTORE = ButtonOption("从钢板数字恢复二次助记词")
    STEEL_SCAN = ButtonOption("拍照识别钢板/纸张点位")
    MANAGE_SEEDS = ButtonOption("已加载助记词")
    WRITE_TO_SATOCHIP = ButtonOption("写入助记词到 Satochip")

    def run(self):
        button_data = [
            self.CAMERA_CREATE,
            self.DICE_CREATE,
            self.IMPORT_SEED,
            self.BIP39_CHECK,
            self.STEEL_RESTORE,
            self.STEEL_SCAN,
            self.MANAGE_SEEDS,
            self.WRITE_TO_SATOCHIP,
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

        if selected == self.CAMERA_CREATE:
            from seedsigner.views.tools_views import ToolsImageEntropyLivePreviewView

            return Destination(ToolsImageEntropyLivePreviewView)

        if selected == self.DICE_CREATE:
            from seedsigner.views.tools_views import ToolsDiceEntropyMnemonicLengthView

            return Destination(ToolsDiceEntropyMnemonicLengthView)

        if selected == self.IMPORT_SEED:
            from seedsigner.views.seed_views import LoadSeedView

            return Destination(LoadSeedView)

        if selected == self.BIP39_CHECK:
            return Destination(ToolsTpBip39CheckMenuView)

        if selected == self.STEEL_RESTORE:
            return Destination(ToolsTpSteelPlateEntryView)

        if selected == self.STEEL_SCAN:
            return _steel_camera_capture_destination()

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

        if selected == self.WRITE_TO_SATOCHIP:
            if not self.controller.storage.seeds:
                self.run_screen(
                    WarningScreen,
                    title="提示",
                    status_headline=None,
                    text="请先用“拍照创建”“摇骰子创建”或“导入助记词”把助记词加载到内存，然后再执行写入。",
                    show_back_button=True,
                    button_data=[ButtonOption("继续")],
                )
                return Destination(ToolsTpSeedToolsView)

            from seedsigner.views.tools_views import ToolsSatochipImportSeedView

            return Destination(ToolsSatochipImportSeedView)

        return _tp_home_destination()


class ToolsTpBip39CheckMenuView(View):
    WORD_LOOKUP = ButtonOption("输入单词查编号")
    INDEX_LOOKUP = ButtonOption("输入编号查单词")

    def run(self):
        button_data = [self.WORD_LOOKUP, self.INDEX_LOOKUP]
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title="BIP39 单词自检",
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
                    title="BIP39 单词自检",
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
                    title="BIP39 单词自检",
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

    def __init__(self, title: str, text: str, return_view: str, return_value: str = ""):
        super().__init__()
        self.title = title
        self.text = text
        self.return_view = return_view
        self.return_value = return_value

    def run(self):
        selected_menu_num = self.run_screen(
            ToolsFormattedTextScreen,
            title=self.title,
            text=self.text,
            text_font_name=GUIConstants.get_body_font_name(),
            button_data=[self.RETRY, self.DONE],
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            selected = self.DONE
        else:
            selected = [self.RETRY, self.DONE][selected_menu_num]

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
    DERIVE_ADDRESS = ButtonOption("派生路径算地址")
    SECONDARY_ENCRYPT = ButtonOption("二次加密助记词")
    SECONDARY_DECRYPT = ButtonOption("二次还原助记词")
    PLATE_NUMBERS = ButtonOption("转成钢板打孔数字")
    WRITE_TO_SATOCHIP = ButtonOption("写入助记词到 Satochip")
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
        if not isinstance(self.seed, TransientWordSeed):
            button_data.insert(1, self.DERIVE_ADDRESS)
            button_data.insert(5, self.WRITE_TO_SATOCHIP)

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
        if selected == self.DERIVE_ADDRESS:
            return Destination(ToolsTpDeriveAddressPathView, view_args=dict(seed_num=self.seed_num))
        if selected == self.SECONDARY_ENCRYPT:
            return Destination(ToolsTpSteelShiftInputView, view_args=dict(mode="encrypt_seed", seed_num=self.seed_num, word_index=0))
        if selected == self.SECONDARY_DECRYPT:
            return Destination(ToolsTpSteelShiftInputView, view_args=dict(mode="decrypt_seed", seed_num=self.seed_num, word_index=0))
        if selected == self.PLATE_NUMBERS:
            return Destination(ToolsTpSteelShiftInputView, view_args=dict(mode="encrypt_seed_plate", seed_num=self.seed_num, word_index=0))
        if selected == self.WRITE_TO_SATOCHIP:
            from seedsigner.views.tools_views import ToolsSatochipImportSeedView
            return Destination(ToolsSatochipImportSeedView)
        if selected == self.DISCARD:
            from seedsigner.views.seed_views import SeedDiscardView
            return Destination(SeedDiscardView, view_args=dict(seed_num=self.seed_num))

        return _tp_home_destination()


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
                ),
            )
        except Exception as exc:
            self.run_screen(
                WarningScreen,
                title="派生失败",
                status_headline=None,
                text=str(exc) or "无法根据这条路径计算地址。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(
                ToolsTpDeriveAddressPathView,
                view_args=dict(seed_num=self.seed_num, derivation_path=normalized_path or DEFAULT_BTC_ADDRESS_PATH),
                clear_history=True,
            )


class ToolsTpDerivedAddressResultView(View):
    RETRY = ButtonOption("重新输入")
    DONE = ButtonOption("完成")

    def __init__(self, seed_num: int, derivation_path: str, address: str, network: str, script_type: str):
        super().__init__()
        self.seed_num = seed_num
        self.derivation_path = derivation_path
        self.address = address
        self.network = network
        self.script_type = script_type

    def _text(self) -> str:
        return (
            f"网络: {_network_label(self.network)}\n"
            f"类型: {_script_type_label(self.script_type)}\n\n"
            f"路径:\n{self.derivation_path}\n\n"
            f"地址:\n{self.address}"
        )

    def _pages(self) -> list[str]:
        return [
            (
                f"网络: {_network_label(self.network)}\n"
                f"类型: {_script_type_label(self.script_type)}\n\n"
                f"路径:\n{_wrap_path_text(self.derivation_path)}"
            ),
            f"地址:\n{_chunk_text(self.address)}",
        ]

    def run(self):
        pages = self._pages()
        button_data = [ButtonOption("下一页"), self.DONE] if len(pages) > 1 else [self.RETRY, self.DONE]
        selected_menu_num = self.run_screen(
            ToolsFormattedTextScreen,
            title="派生地址",
            text=pages[0],
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)

        if len(pages) > 1 and button_data[selected_menu_num].button_label == "下一页":
            selected_menu_num = self.run_screen(
                ToolsFormattedTextScreen,
                title="派生地址",
                text=pages[1],
                button_data=[self.RETRY, self.DONE],
            )
            if selected_menu_num == RET_CODE__BACK_BUTTON or [self.RETRY, self.DONE][selected_menu_num] == self.DONE:
                return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)
            return Destination(
                ToolsTpDeriveAddressPathView,
                view_args=dict(seed_num=self.seed_num, derivation_path=self.derivation_path),
                clear_history=True,
            )

        if button_data[selected_menu_num] == self.DONE:
            return Destination(ToolsTpLoadedSeedOptionsView, view_args=dict(seed_num=self.seed_num), clear_history=True)

        return Destination(
            ToolsTpDeriveAddressPathView,
            view_args=dict(seed_num=self.seed_num, derivation_path=self.derivation_path),
            clear_history=True,
        )


class ToolsTpSteelCipherOptionsView(View):
    VIEW_WORDS = ButtonOption("查看二次加密助记词")
    VIEW_PLATE = ButtonOption("查看钢板打孔数字")
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
            groups = words_to_plate_groups(self.controller.storage.get_steel_encrypted_mnemonic())
            self.controller.storage.set_steel_plate_groups(groups)
            return Destination(ToolsTpSteelPlateWordsView, view_args=dict(page_index=0))
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
            if len(words) != 12:
                raise ValueError("钢板二次加密流程当前只支持 12 词助记词。")
            return words
        if self.seed_num is None:
            raise ValueError("缺少助记词来源。")
        seed = self.controller.get_seed(self.seed_num)
        if seed is None:
            raise ValueError("没有找到这条已加载助记词，请重新进入后再试。")
        words = seed.mnemonic_display_list
        if len(words) != 12:
            raise ValueError("钢板二次加密流程当前只支持 12 词助记词。")
        return words

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

    def _default_entries(self, word_count: int) -> list[str]:
        return _ensure_shift_entry_list(None, word_count)

    def run(self):
        entries = list(self.entries or [])
        try:
            source_words = self._source_words()
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
    NEXT = ButtonOption("下一页")
    REENTER = ButtonOption("重新输入")
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
            return words
        seed = self.controller.get_seed(self.seed_num)
        if seed is None:
            raise ValueError("没有找到这条已加载助记词，请重新进入后再试。")
        return seed.mnemonic_display_list

    def _review_title(self, total_pages: int) -> str:
        return f"检查每词运算：{self.page_index + 1}/{total_pages}"

    def _review_text(self) -> str:
        text, _ = _format_shift_entries(self.entries, self.page_index, entries_per_page=4)
        return text

    def _has_lossy_entries(self) -> bool:
        for entry in self.entries:
            operator = _extract_entry_operator(entry, fallback="")
            if _is_lossy_operator(operator):
                return True
        return False

    def run(self):
        entries_per_page = 4
        total_pages = max(1, (len(self.entries) + entries_per_page - 1) // entries_per_page)
        is_last_page = self.page_index >= total_pages - 1
        button_data = [self.NEXT] if not is_last_page else [self.REENTER, self.CONFIRM]
        selected_menu_num = self.run_screen(
            ToolsFormattedTextScreen,
            title=self._review_title(total_pages),
            text=self._review_text(),
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            if self.page_index > 0:
                return Destination(
                    ToolsTpSteelShiftReviewView,
                    view_args=dict(
                        mode=self.mode,
                        seed_num=self.seed_num,
                        entries=self.entries,
                        page_index=self.page_index - 1,
                        warned_lossy=self.warned_lossy,
                    ),
                    clear_history=True,
                )
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
        if selected == self.NEXT:
            return Destination(
                ToolsTpSteelShiftReviewView,
                view_args=dict(
                    mode=self.mode,
                    seed_num=self.seed_num,
                    entries=self.entries,
                    page_index=self.page_index + 1,
                    warned_lossy=self.warned_lossy,
                ),
            )

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
            encrypt = self.mode in ("encrypt_seed", "encrypt_seed_plate")
            transformed_words = shift_mnemonic(
                source_words,
                operands,
                encrypt=encrypt,
                operators=operators,
            )

            if encrypt:
                source_fingerprint = None
                if self.seed_num is not None:
                    source_fingerprint = self.controller.get_seed(self.seed_num).get_fingerprint(self.settings.get_value(SettingsConstants.SETTING__NETWORK))
                single_operator = operators[0] if len(set(operators)) == 1 else None
                self.controller.storage.set_steel_encrypted_mnemonic(
                    transformed_words,
                    shift_values=operands,
                    shift_operators=operators,
                    shift_operator=single_operator,
                    source_fingerprint=source_fingerprint,
                )
                self.controller.storage.set_steel_plate_groups(words_to_plate_groups(transformed_words))
                if self.mode == "encrypt_seed_plate":
                    return Destination(ToolsTpSteelPlateWordsView, view_args=dict(page_index=0), clear_history=True)
                return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)

            try:
                restored_seed = Seed(transformed_words)
            except InvalidSeedException:
                restored_seed = TransientWordSeed(transformed_words)
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


class ToolsTpSteelPlateEntryView(View):
    def __init__(self, entries: list[str] | None = None, word_index: int = 0):
        super().__init__()
        self.entries = _ensure_entry_list(entries, 12)
        self.word_index = word_index

    def run(self):
        ret = ToolsTextQRTextEntryScreen(
            textToEncode=self.entries[self.word_index],
            title=f"第 {self.word_index + 1} 个词钢板数字",
            initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__DIGITS_BUTTON_TEXT,
            digits_entry_mode=True,
        ).display()

        if ret.get("is_back_button"):
            if self.word_index == 0:
                return Destination(ToolsTpSeedToolsView, clear_history=True)
            return Destination(
                ToolsTpSteelPlateEntryView,
                view_args=dict(entries=self.entries, word_index=self.word_index - 1),
                clear_history=True,
            )

        try:
            normalized_entry = _normalize_plate_group_entry(ret.get("textToEncode", ""))
            if not normalized_entry:
                raise ValueError("请输入当前这个助记词的钢板数字。")
            self.entries[self.word_index] = normalized_entry
            if self.word_index < len(self.entries) - 1:
                return Destination(
                    ToolsTpSteelPlateEntryView,
                    view_args=dict(entries=self.entries, word_index=self.word_index + 1),
                )
            return Destination(ToolsTpSteelPlateReviewView, view_args=dict(entries=self.entries, page_index=0))
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
                view_args=dict(entries=self.entries, word_index=self.word_index),
                clear_history=True,
            )


class ToolsTpSteelPlateReviewView(View):
    NEXT = ButtonOption("下一页")
    REENTER = ButtonOption("重新输入")
    CONFIRM = ButtonOption("确认恢复")

    def __init__(self, entries: list[str], page_index: int = 0, source: str = "manual"):
        super().__init__()
        self.entries = entries
        self.page_index = page_index
        self.source = source

    def run(self):
        page_text, total_pages = _format_number_groups(self.entries, self.page_index, entries_per_page=2)
        is_last_page = self.page_index >= total_pages - 1
        reshoot_button = ButtonOption("重新拍照")
        button_data = [self.NEXT] if not is_last_page else [reshoot_button if self.source == "camera" else self.REENTER, self.CONFIRM]
        selected_menu_num = self.run_screen(
            ToolsFormattedTextScreen,
            title=f"检查钢板数字：{self.page_index + 1}/{total_pages}",
            text=page_text,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            if self.page_index > 0:
                return Destination(
                    ToolsTpSteelPlateReviewView,
                    view_args=dict(entries=self.entries, page_index=self.page_index - 1, source=self.source),
                    clear_history=True,
                )
            if self.source == "camera":
                return _steel_camera_capture_destination()
            return Destination(
                ToolsTpSteelPlateEntryView,
                view_args=dict(entries=self.entries, word_index=len(self.entries) - 1),
                clear_history=True,
            )

        selected = button_data[selected_menu_num]
        if selected == self.NEXT:
            return Destination(
                ToolsTpSteelPlateReviewView,
                view_args=dict(entries=self.entries, page_index=self.page_index + 1, source=self.source),
            )

        if selected == reshoot_button:
            return _steel_camera_capture_destination()

        if selected == self.REENTER:
            return Destination(ToolsTpSteelPlateEntryView, view_args=dict(entries=self.entries, word_index=0), clear_history=True)

        try:
            indices = parse_restore_indices(",".join(self.entries))
            words = indices_to_words(indices)
            self.controller.storage.set_steel_encrypted_mnemonic(words, source_fingerprint="钢板恢复")
            self.controller.storage.set_steel_plate_groups(words_to_plate_groups(words))
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)
        except Exception as exc:
            self.run_screen(
                WarningScreen,
                title="钢板恢复失败",
                status_headline=None,
                text=str(exc) or "钢板数字有误，请重新检查。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(ToolsTpSteelPlateEntryView, view_args=dict(entries=self.entries, word_index=0), clear_history=True)


class ToolsTpSteelPlatePhotoProcessView(View):
    def run(self):
        image = getattr(self.controller, "image_entropy_final_image", None)
        preview_frames = getattr(self.controller, "image_entropy_preview_frames", None)
        self.controller.image_entropy_final_image = None
        self.controller.image_entropy_preview_frames = None

        if image is None:
            return Destination(ToolsTpSeedToolsView, clear_history=True)

        loading_screen = LoadingScreenThread(text="识别钢板点位...")
        loading_screen.start()
        try:
            groups = recognize_plate_groups_from_image(image)
        except Exception as exc:
            loading_screen.stop()
            self.run_screen(
                WarningScreen,
                title="拍照识别失败",
                status_headline=None,
                text=str(exc) or "请让单张钢板/纸卡铺满画面，并放在深色背景上重试。",
                show_back_button=False,
                button_data=[ButtonOption("继续")],
            )
            return Destination(ToolsTpSeedToolsView, clear_history=True)
        finally:
            image = None
            preview_frames = None

        loading_screen.stop()
        return Destination(
            ToolsTpSteelPlateReviewView,
            view_args=dict(entries=groups, page_index=0, source="camera"),
            clear_history=True,
        )


class ToolsTpSteelCipherWordsView(View):
    NEXT = ButtonOption("下一页")
    DONE = ButtonOption("完成")

    def __init__(self, page_index: int = 0):
        super().__init__()
        self.page_index = page_index

    def run(self):
        words = self.controller.storage.get_steel_encrypted_mnemonic()
        if not words:
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)

        words_per_page = 4
        num_pages = max(1, (len(words) + words_per_page - 1) // words_per_page)
        page_words = words[self.page_index * words_per_page:(self.page_index + 1) * words_per_page]
        button_data = [self.NEXT if self.page_index < num_pages - 1 else self.DONE]
        selected_menu_num = seed_screens.SeedWordsScreen(
            title=f"二次加密助记词：{self.page_index + 1}/{num_pages}",
            words=page_words,
            page_index=self.page_index,
            num_pages=num_pages,
            button_data=button_data,
        ).display()

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)

        if button_data[selected_menu_num] == self.NEXT:
            return Destination(ToolsTpSteelCipherWordsView, view_args=dict(page_index=self.page_index + 1))
        return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)


class ToolsTpSteelPlateWordsView(View):
    NEXT = ButtonOption("下一页")
    DONE = ButtonOption("完成")

    def __init__(self, page_index: int = 0):
        super().__init__()
        self.page_index = page_index

    def run(self):
        groups = self.controller.storage.get_steel_plate_groups()
        if not groups:
            groups = words_to_plate_groups(self.controller.storage.get_steel_encrypted_mnemonic())
            self.controller.storage.set_steel_plate_groups(groups)
        if not groups:
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)

        page_text, num_pages = _format_number_groups(groups, self.page_index, entries_per_page=2)
        button_data = [self.NEXT if self.page_index < num_pages - 1 else self.DONE]
        selected_menu_num = self.run_screen(
            ToolsFormattedTextScreen,
            title=f"钢板打孔数字：{self.page_index + 1}/{num_pages}",
            text=page_text,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)

        if button_data[selected_menu_num] == self.NEXT:
            return Destination(ToolsTpSteelPlateWordsView, view_args=dict(page_index=self.page_index + 1))
        return Destination(ToolsTpSteelCipherOptionsView, clear_history=True)


class ToolsTpSmartcardToolsView(View):
    CHANGE_PIN = ButtonOption("更改智能卡 PIN")
    FACTORY_RESET = ButtonOption("重置智能卡")

    def run(self):
        button_data = [
            self.CHANGE_PIN,
            self.FACTORY_RESET,
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

        if selected == self.CHANGE_PIN:
            from seedsigner.views.tools_views import ToolsSatochipChangePinView

            return Destination(ToolsSatochipChangePinView)

        if selected == self.FACTORY_RESET:
            from seedsigner.views.tools_views import ToolsSatochipFactoryResetView

            return Destination(ToolsSatochipFactoryResetView)

        return _tp_home_destination()


class ToolsTpSignerScanView(View):
    def run(self):
        decoder = TpRequestQrDecoder()
        ScanScreen(decoder=decoder, instructions_text="").display()

        self.controller.reset_screensaver_timeout()
        time.sleep(0.1)

        if decoder.is_complete:
            payload = decoder.get_text().strip()
            if not payload.startswith(("ethereum:", "tp:")):
                return _tp_home_destination()
            return Destination(
                ToolsTpSignerPinEntryView,
                view_args=dict(payload=payload),
            )

        if decoder.is_nonUTF8:
            return _tp_home_destination()

        return _tp_home_destination()


class ToolsTpBtcXpubPinEntryView(View):
    def __init__(self, xtype: str):
        super().__init__()
        self.xtype = xtype

    def run(self):
        try:
            pin = _prompt_for_tp_pin(self)
        except Exception as exc:
            logger.exception("TP BTC xpub PIN prompt failed")
            return _debug_error_destination("21", str(exc))

        if pin is None:
            return _tp_home_destination()

        pin = pin.strip()
        if not pin or len(pin) < 4:
            return _tp_home_destination()

        return Destination(
            ToolsTpBtcXpubRunView,
            view_args=dict(pin=pin, xtype=self.xtype),
            skip_current_view=True,
        )


class ToolsTpBtcXpubRunView(View):
    def __init__(self, pin: str, xtype: str):
        super().__init__()
        self.pin = pin
        self.xtype = xtype

    def run(self):
        signer_bin = _resolve_signer_bin()
        if not signer_bin.is_file():
            return _masked_error_destination("31")

        loading = LoadingScreenThread(text="")
        loading.start()
        try:
            cmd = [
                str(signer_bin),
                "get-xpub",
                "--pin",
                self.pin,
                "--xtype",
                self.xtype,
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
                detail = _extract_error(proc.stdout, proc.stderr, "get-xpub failed")
                code = _map_signer_error_code(detail)
                return _masked_error_destination(code)

            xpub_value = _extract_xpub_from_output(proc.stdout, self.xtype)
        except subprocess.TimeoutExpired:
            return _masked_error_destination("34")
        except Exception:
            return _masked_error_destination("48")
        finally:
            loading.stop()

        return Destination(
            ToolsTpBtcXpubQrView,
            view_args=dict(xpub=xpub_value, xtype=self.xtype),
            skip_current_view=True,
        )


class ToolsTpBtcXpubQrView(View):
    def __init__(self, xpub: str, xtype: str):
        super().__init__()
        self.xpub = xpub
        self.xtype = xtype

    def run(self):
        ret = self.run_screen(
            WarningScreen,
            title="提示",
            status_headline=None,
            text=f"{self.xtype} 可用于观察全部后续地址和交易，请只导入自己的手机。",
            show_back_button=True,
            button_data=[ButtonOption("继续")],
        )
        if ret == RET_CODE__BACK_BUTTON:
            return _tp_home_destination()

        encoder = GenericStaticQrEncoder(data=self.xpub)
        self.run_screen(QRDisplayScreen, qr_encoder=encoder)
        return _tp_home_destination()


class ToolsTpSignerPinEntryView(View):
    def __init__(self, payload: str):
        super().__init__()
        self.payload = payload

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

        if self.payload.lower().startswith("tp:signpsbt-"):
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
    def __init__(self, payload: str, pin: str):
        super().__init__()
        self.payload = payload
        self.pin = pin
        self.request_id, self.psbt_base64 = _extract_psbt_request(payload)

    def run(self):
        signer_bin = _resolve_signer_bin()
        if not signer_bin.is_file():
            return _masked_error_destination("31")

        loading = LoadingScreenThread(text="")
        loading.start()
        try:
            with tempfile.TemporaryDirectory(prefix="tp-btc-psbt-") as tmpdir:
                tmpdir_path = Path(tmpdir)
                psbt_input_path = tmpdir_path / "unsigned.psbt.txt"
                tx_path = tmpdir_path / "signed.tx.hex"
                psbt_input_path.write_text(self.psbt_base64 + "\n", encoding="utf-8")

                cmd = [
                    str(signer_bin),
                    "sign-psbt",
                    "--pin",
                    self.pin,
                    "--psbt-file",
                    str(psbt_input_path),
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
                    logger.warning("TP-only BTC PSBT signer failed: %s", detail)
                    code = _map_signer_error_code(detail)
                    return _masked_error_destination(code)

                if not tx_path.exists():
                    return _masked_error_destination("33")

                tx_hex = tx_path.read_text(encoding="utf-8").strip()
                if not tx_hex:
                    return _masked_error_destination("33")
        except subprocess.TimeoutExpired:
            return _masked_error_destination("34")
        except Exception as exc:
            logger.warning("TP-only BTC PSBT flow failed: %s", exc)
            return _masked_error_destination("35")
        finally:
            loading.stop()

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

    def run(self):
        signer_bin = _resolve_signer_bin()
        if not signer_bin.is_file():
            return _masked_error_destination("31")

        loading = LoadingScreenThread(text="")
        loading.start()
        try:
            with tempfile.TemporaryDirectory(prefix="tp-signer-") as tmpdir:
                tmpdir_path = Path(tmpdir)
                request_path = tmpdir_path / "request.txt"
                response_path = tmpdir_path / "response.txt"
                request_path.write_text(self.payload + "\n", encoding="utf-8")

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
                            return Destination(
                                ToolsTpSignerQrView,
                                view_args=dict(response_text=response_text),
                                skip_current_view=True,
                            )
                    detail = _extract_error(proc.stdout, proc.stderr, "sign failed")
                    logger.warning("TP-only signer failed: %s", detail)
                    code = _map_signer_error_code(detail)
                    if code == "51":
                        return _debug_error_destination(code, detail)
                    return _masked_error_destination(code)

                if not response_path.exists():
                    return _masked_error_destination("33")

                response_text = response_path.read_text(encoding="utf-8").strip()
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
    def __init__(self, response_text: str):
        super().__init__()
        self.response_text = response_text

    def run(self):
        encoder = GenericStaticQrEncoder(data=self.response_text)
        self.run_screen(QRDisplayScreen, qr_encoder=encoder)
        return _tp_home_destination()
