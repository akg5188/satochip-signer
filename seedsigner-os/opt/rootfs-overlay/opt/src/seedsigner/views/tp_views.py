import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs

from gettext import gettext as _

from seedsigner.gui.screens import RET_CODE__BACK_BUTTON, ButtonListScreen, WarningScreen
from seedsigner.gui.screens.scan_screens import ScanScreen
from seedsigner.gui.screens.screen import ButtonOption, LoadingScreenThread, QRDisplayScreen
from seedsigner.helpers.tp_fragment import FragmentParseError, MultiFragmentAssembler, parse_tp_multi_fragment
from seedsigner.helpers.tp_relay import RelayAssembler, RelayParseError, parse_tp_relay_fragment
from seedsigner.helpers import seedkeeper_utils
from seedsigner.models.decode_qr import DecodeQR, DecodeQRStatus
from seedsigner.models.encode_qr import GenericStaticQrEncoder

from .view import Destination, ErrorView, View


DEFAULT_DERIVATION_PATH = "m/44'/60'/0'/0/0"
DEFAULT_READER_HINT = None
CAMO_BUTTON_TEXT = " "
CAMO_TEXT = " "

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
    MANAGE_SEEDS = ButtonOption("已加载助记词")
    WRITE_TO_SATOCHIP = ButtonOption("写入助记词到 Satochip")

    def run(self):
        button_data = [
            self.CAMERA_CREATE,
            self.DICE_CREATE,
            self.IMPORT_SEED,
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

        if selected == self.MANAGE_SEEDS:
            if not self.controller.storage.seeds:
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
