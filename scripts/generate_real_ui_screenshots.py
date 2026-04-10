#!/usr/bin/env python3
"""Generate real firmware UI screenshots for the beginner guide.

This script renders the actual SeedSigner/TP firmware UI on a desktop display
backend and saves the resulting screenshots into the docs assets directory.

It intentionally favors reproducibility over interactivity:
- it runs headlessly with SDL's dummy video backend
- it injects the desktop smoke venv's site-packages when available
- it stubs optional hardware-only modules that are not needed for screenshoting
"""

from __future__ import annotations

import argparse
import gettext
import os
import sys
import time
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "seedsigner-os" / "opt" / "rootfs-overlay" / "opt" / "src"
DEFAULT_VENV = Path("/tmp/satochip-desktop-smoke-venv")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "assets" / "real-ui-screenshot-guide"
SIGNED_TX_SAMPLE_HEX = (
    "020000000001045c007cd8e90d93ea21de219dad7acffecc21c1c8e5c34cbecfc5ef6b38d70d450100000000"
    "ffffffff171cd0ce826655bf4b1219be2a2dd9aeeddbf9309eeaced3595b3719c2eb27f80000000000ffffffff"
    "d2fe1e143c6a11a6b0ae8d790d6edf0a73edffa5c29da6ab7ef3408bc4e851bd0100000000ffffffff3547f8bc"
    "22a72ee0b91fcda2f0c8e095d1420c1e1386ad4131d58d28aab979ce0100000000ffffffff01fa490000000000"
    "0016001403884d74b4b5b49467c2db589761ff34107ccdfa024730440220535132af4c52275e4ef68204375a90"
    "4f4a0536960f2e37be66f3c3369e30a94502202850588eeb2be48189680d9800807d7288a8acde12612258bc3b"
    "151937159bf6012103c49cf3c490ec8c75de934ff4891a79787714e086406786d54a52a1d6aa6944cf02483045"
    "022100bf6c5cf707afa35b999b3ebc4c775034ca7b32a1159c69d3512781132b4d3f9002200d6a02dee1cecd09"
    "7bd09e1c722986e764153478573b9fafd9d6bc1093c5b2c30121026493ffe864c9f4e214a3a0625393df43157a"
    "46e7b0454d247ad3dcb6f8761ead0247304402207aba706b25ffbc1923672195086acc96334dd80594019b7b0f"
    "e2d9fdecbe7a870220611931dcd6d38293f8bf0da70373cbc6a73386a215d2d7f31d5ebde2b629767b0121032b"
    "6fe88c6ff8daf40153d8c643799f2c6cd11ef6b86e309e2279495ff218f9d102483045022100f16d58022bac16"
    "cdb454b27eacf122b641caac848f251f6dc404dbbfc1c79b3d02205f4de7b1b4866fc823419b6def7ee3101910"
    "a5a0df0e1294de25ede40069c0dd0121035fbdb82c74ea685f476d59a500c3e618b278a6a321636e25ac9ba517"
    "84b9766b00000000"
)


def _add_python_paths(venv_root: Path | None) -> None:
    sys.path.insert(0, str(SRC_ROOT))

    candidate_roots: list[Path] = []
    if venv_root:
        candidate_roots.append(venv_root)
    candidate_roots.append(DEFAULT_VENV)

    for root in candidate_roots:
        if not root.exists():
            continue
        for site_packages in root.glob("lib/python*/site-packages"):
            sys.path.insert(0, str(site_packages))


def _install_dependency_stubs() -> None:
    if "smartcard" not in sys.modules:
        smartcard_mod = types.ModuleType("smartcard")
        smartcard_mod.__path__ = []  # Mark as package for nested imports.
        system_mod = types.ModuleType("smartcard.System")
        exceptions_mod = types.ModuleType("smartcard.Exceptions")
        util_mod = types.ModuleType("smartcard.util")
        cardtype_mod = types.ModuleType("smartcard.CardType")
        cardrequest_mod = types.ModuleType("smartcard.CardRequest")
        observer_mod = types.ModuleType("smartcard.CardConnectionObserver")
        monitoring_mod = types.ModuleType("smartcard.CardMonitoring")
        sw_pkg = types.ModuleType("smartcard.sw")
        sw_pkg.__path__ = []
        sw_exceptions_mod = types.ModuleType("smartcard.sw.SWExceptions")

        class CardConnectionException(Exception):
            pass

        class NoReadersException(Exception):
            pass

        class CardRequestTimeoutException(Exception):
            pass

        class AnyCardType:
            pass

        class CardRequest:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def waitforcard(self):
                raise CardRequestTimeoutException("No card available in screenshot runtime")

        class CardConnectionObserver:
            pass

        class CardObserver:
            pass

        class CardMonitor:
            def addObserver(self, *args, **kwargs):
                return None

            def deleteObserver(self, *args, **kwargs):
                return None

        class SWException(Exception):
            pass

        system_mod.readers = lambda: []
        exceptions_mod.CardConnectionException = CardConnectionException
        exceptions_mod.NoReadersException = NoReadersException
        exceptions_mod.CardRequestTimeoutException = CardRequestTimeoutException
        util_mod.toHexString = lambda data: " ".join(f"{byte:02X}" for byte in data)
        util_mod.toBytes = lambda data: list(data) if isinstance(data, (bytes, bytearray)) else []
        cardtype_mod.AnyCardType = AnyCardType
        cardrequest_mod.CardRequest = CardRequest
        observer_mod.CardConnectionObserver = CardConnectionObserver
        monitoring_mod.CardMonitor = CardMonitor
        monitoring_mod.CardObserver = CardObserver
        sw_exceptions_mod.SWException = SWException

        smartcard_mod.System = system_mod
        smartcard_mod.Exceptions = exceptions_mod
        smartcard_mod.util = util_mod
        smartcard_mod.CardType = cardtype_mod
        smartcard_mod.CardRequest = cardrequest_mod
        smartcard_mod.CardConnectionObserver = observer_mod
        smartcard_mod.CardMonitoring = monitoring_mod
        smartcard_mod.sw = sw_pkg

        sys.modules["smartcard"] = smartcard_mod
        sys.modules["smartcard.System"] = system_mod
        sys.modules["smartcard.Exceptions"] = exceptions_mod
        sys.modules["smartcard.util"] = util_mod
        sys.modules["smartcard.CardType"] = cardtype_mod
        sys.modules["smartcard.CardRequest"] = cardrequest_mod
        sys.modules["smartcard.CardConnectionObserver"] = observer_mod
        sys.modules["smartcard.CardMonitoring"] = monitoring_mod
        sys.modules["smartcard.sw"] = sw_pkg
        sys.modules["smartcard.sw.SWExceptions"] = sw_exceptions_mod

    if "pyzbar" not in sys.modules:
        pyzbar_pkg = types.ModuleType("pyzbar")
        pyzbar_mod = types.ModuleType("pyzbar.pyzbar")

        class ZBarSymbol:
            QRCODE = "QRCODE"

        pyzbar_mod.decode = lambda *args, **kwargs: []
        pyzbar_mod.ZBarSymbol = ZBarSymbol
        pyzbar_pkg.pyzbar = pyzbar_mod

        sys.modules["pyzbar"] = pyzbar_pkg
        sys.modules["pyzbar.pyzbar"] = pyzbar_mod


def _prepare_runtime(venv_root: Path | None):
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    _add_python_paths(venv_root)
    _install_dependency_stubs()

    from PIL import Image, ImageDraw
    import pygame  # type: ignore

    from seedsigner.gui.renderer import Renderer
    from seedsigner.hardware import buttons as buttons_mod
    from seedsigner.models.settings import Settings
    from seedsigner.models.settings_definition import SettingsConstants

    class FakeSettings:
        def __init__(self) -> None:
            self._data = {
                SettingsConstants.SETTING__LOCALE: SettingsConstants.LOCALE__CHINESE_SIMPLIFIED,
                SettingsConstants.SETTING__DISPLAY_CONFIGURATION: SettingsConstants.DISPLAY_CONFIGURATION__DESKTOP__240x240,
                SettingsConstants.SETTING__DISPLAY_COLOR_INVERTED: SettingsConstants.OPTION__DISABLED,
                SettingsConstants.SETTING__NETWORK: SettingsConstants.MAINNET,
                SettingsConstants.SETTING__BTC_DENOMINATION: SettingsConstants.BTC_DENOMINATION__THRESHOLD,
                SettingsConstants.SETTING__QR_BRIGHTNESS_TIPS: SettingsConstants.OPTION__DISABLED,
                SettingsConstants.SETTING__QR_BRIGHTNESS: 255,
                SettingsConstants.SETTING__CAMERA_ROTATION: SettingsConstants.CAMERA_ROTATION__0,
                SettingsConstants.SETTING__CAMERA_DEVICE: 0,
            }

        def get_value(self, key: str, default: object | None = None, default_if_none: bool = False):
            if key not in self._data:
                return default
            value = self._data[key]
            if value is None and default_if_none:
                return default
            return value

        def set_value(self, key: str, value: object) -> None:
            self._data[key] = value

        def update(self, *args, **kwargs) -> None:
            return None

    settings = FakeSettings()
    Settings._instance = settings

    translations_root = SRC_ROOT / "seedsigner" / "resources" / "seedsigner-translations" / "l10n"
    os.environ["LANGUAGE"] = SettingsConstants.LOCALE__CHINESE_SIMPLIFIED
    gettext.bindtextdomain("messages", localedir=str(translations_root))
    gettext.textdomain("messages")

    buttons_mod.USING_GPIO = False
    buttons_mod.pygame = pygame
    buttons_mod.HardwareButtons._instance = None

    Renderer._instance = None
    Renderer.configure_instance()
    renderer = Renderer.get_instance()
    renderer.display_type = "desktop"

    return {
        "Image": Image,
        "ImageDraw": ImageDraw,
        "Renderer": Renderer,
        "renderer": renderer,
        "SettingsConstants": SettingsConstants,
        "settings": settings,
        "buttons_mod": buttons_mod,
        "pygame": pygame,
    }


def _create_phone_qr_frame(runtime, qr_text: str):
    Image = runtime["Image"]
    ImageDraw = runtime["ImageDraw"]

    from seedsigner.models.encode_qr import GenericStaticQrEncoder

    phone = Image.new("RGB", (480, 480), "#111827")
    draw = ImageDraw.Draw(phone)
    draw.rounded_rectangle((120, 20, 360, 460), radius=28, fill="#dbe3ea")
    draw.rounded_rectangle((137, 60, 343, 410), radius=18, fill="#fbfdff")
    draw.rounded_rectangle((214, 34, 266, 42), radius=4, fill="#93a3b5")

    qr = GenericStaticQrEncoder(data=qr_text).next_part_image(width=180, height=180, border=2, background_color="ffffff")
    phone.paste(qr, (150, 120))
    draw.text((240, 332), "手机待签名二维码", fill="#334155", anchor="mm")
    draw.text((240, 360), "保持屏幕常亮并对准镜头", fill="#64748b", anchor="mm")
    return phone


def _capture_static_screen(path: Path, screen) -> None:
    screen.renderer.canvas.paste("black", (0, 0, screen.renderer.canvas_width, screen.renderer.canvas_height))
    screen._render()
    screen.renderer.canvas.save(path)


def _capture_scrollable_screen(path: Path, screen, scroll_y: int = 0) -> None:
    if hasattr(screen, "text_component"):
        screen.text_component.set_vertical_scroll_y(scroll_y)
    _capture_static_screen(path, screen)


def _spread_scroll_offsets(max_scroll: int, count: int) -> list[int]:
    if count <= 1 or max_scroll <= 0:
        return [0] * max(1, count)
    return [int(round(max_scroll * index / (count - 1))) for index in range(count)]


def _capture_live_display(path: Path, runtime, starter) -> None:
    renderer = runtime["renderer"]
    renderer.canvas.paste("black", (0, 0, renderer.canvas_width, renderer.canvas_height))
    original_show_image = renderer.disp.show_image
    last_image = {"image": None}

    def wrapped_show_image(image, x_start=0, y_start=0):
        result = original_show_image(image, x_start, y_start)
        # Capture the full composed canvas, not just the most recent image fragment.
        last_image["image"] = renderer.canvas.copy()
        return result

    renderer.disp.show_image = wrapped_show_image
    try:
        starter()
        if last_image["image"] is None:
            raise RuntimeError(f"Failed to capture rendered display for {path.name}")
        last_image["image"].save(path)
    finally:
        renderer.disp.show_image = original_show_image


def _capture_scan_screen(path: Path, runtime) -> None:
    from seedsigner.gui.screens.scan_screens import ScanScreen
    from seedsigner.hardware.camera import Camera

    phone_frame = _create_phone_qr_frame(runtime, "ur:crypto-psbt/otadgdaeotadgdae")

    class FakeCamera:
        def __init__(self, frame):
            self.frame = frame
            self._video_stream = object()

        def start_video_stream_mode(self, **kwargs):
            self._video_stream = object()
            return None

        def read_video_stream(self, as_image: bool = False, preview: bool = False):
            return self.frame.copy()

        def stop_video_stream_mode(self):
            self._video_stream = None
            return None

    class FakeDecoder:
        def get_percent_complete(self, weight_mixed_frames: bool = False):
            return 0

    original_camera_instance = Camera._instance
    Camera._instance = FakeCamera(phone_frame)
    try:
        def starter():
            screen = ScanScreen(
                decoder=FakeDecoder(),
                instructions_text=None,
            )
            preview_thread = screen.threads[-1]
            preview_thread.start()
            time.sleep(0.18)
            preview_thread.stop()
            while preview_thread.is_alive():
                time.sleep(0.01)

        _capture_live_display(path, runtime, starter)
    finally:
        Camera._instance = original_camera_instance


def _capture_qr_screen(path: Path, runtime) -> None:
    from seedsigner.models.encode_qr import GenericStaticQrEncoder

    image = GenericStaticQrEncoder(
        data=f"btctx:{SIGNED_TX_SAMPLE_HEX}"
    ).next_part_image(width=240, height=240, border=2, background_color="ffffff")
    image.save(path)


def _create_entropy_demo_image(runtime, label: str) -> object:
    Image = runtime["Image"]
    ImageDraw = runtime["ImageDraw"]

    image = Image.new("RGB", (240, 240), "#0f172a")
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 18, 96, 102), fill="#2563eb")
    draw.ellipse((150, 30, 224, 104), fill="#f97316")
    draw.rectangle((24, 120, 216, 212), fill="#1e293b", outline="#94a3b8", width=2)
    draw.text((120, 136), label, fill="#e2e8f0", anchor="mm")
    draw.text((120, 168), "离线随机源演示图", fill="#94a3b8", anchor="mm")
    return image


def _capture_camera_entropy_preview_screen(path: Path, runtime) -> None:
    from seedsigner.gui.components import Fonts, GUIConstants

    frame = _create_entropy_demo_image(runtime, "拍照取熵").resize((240, 240))
    draw = runtime["ImageDraw"].Draw(frame)
    body_font = Fonts.get_font(GUIConstants.get_body_font_name(), GUIConstants.get_button_font_size())
    draw.text((12, 12), "5.21", fill="#ffffff", font=body_font)
    draw.ellipse((64, 18, 74, 28), fill="#22c55e", outline="#000000", width=1)
    draw.text((82, 12), "GOOD ENTROPY", fill="#ffffff", font=body_font)
    draw.text((120, 224), "< 返回 | 长按摇杆拍照", fill="#ffffff", font=body_font, anchor="ms")
    frame.save(path)


def _capture_camera_entropy_final_screen(path: Path, runtime) -> None:
    from seedsigner.gui.screens.tools_screens import ToolsImageEntropyFinalImageScreen
    from seedsigner.hardware.buttons import HardwareButtonsConstants

    final_image = _create_entropy_demo_image(runtime, "拍照确认")

    def starter():
        screen = ToolsImageEntropyFinalImageScreen(final_image=final_image)
        screen.hw_inputs.wait_for = lambda keys: HardwareButtonsConstants.KEY_RIGHT
        screen._run()

    _capture_live_display(path, runtime, starter)


def _capture_keyboard_screen(path: Path, screen, before_capture=None) -> None:
    if before_capture:
        before_capture(screen)
    _capture_static_screen(path, screen)


def _build_seed_tools_screens(output_dir: Path, runtime) -> list[Path]:
    from seedsigner.gui.components import GUIConstants
    from seedsigner.gui.screens.screen import ButtonListScreen, ButtonOption
    from seedsigner.gui.screens.tools_screens import ToolsFormattedTextScreen, ToolsScrollableTextScreen, ToolsTextQRTextEntryScreen, ToolsDiceEntropyEntryScreen
    from seedsigner.helpers import mnemonic_generation
    from seedsigner.models.mnemonic_steel import get_word_at_index, lookup_word_index, solve_weights
    from seedsigner.models.seed import Seed

    def format_weight_line(index: int) -> str:
        weights = solve_weights(index)
        if not weights:
            return "0"
        chunks = [" ".join(str(weight) for weight in weights[i:i + 6]) for i in range(0, len(weights), 6)]
        return "\n".join(chunks)

    def build_bip39_word_report(word: str) -> str:
        index = lookup_word_index(word)
        previous_word = get_word_at_index(index - 1) if index > 0 else "（无）"
        next_word = get_word_at_index(index + 1) if index < 2047 else "（无）"
        return (
            f"单词: {word}\n"
            f"编号: {index}\n"
            f"前词: {previous_word}\n"
            f"后词: {next_word}\n"
            f"钢板位权:\n{format_weight_line(index)}"
        )

    def build_bip39_index_report(raw_index: str) -> str:
        index = int(raw_index)
        word = get_word_at_index(index)
        previous_word = get_word_at_index(index - 1) if index > 0 else "（无）"
        next_word = get_word_at_index(index + 1) if index < 2047 else "（无）"
        return (
            f"编号: {index}\n"
            f"单词: {word}\n"
            f"前词: {previous_word}\n"
            f"后词: {next_word}\n"
            f"钢板位权:\n{format_weight_line(index)}"
        )

    def paginate_lines(text: str, per_page: int) -> list[str]:
        lines = str(text or "").splitlines()
        return ["\n".join(lines[i:i + per_page]) for i in range(0, len(lines), per_page)] or [""]

    def chunk_entropy_value(value: str, input_format_label: str) -> list[str]:
        raw_value = str(value or "").strip()
        if not raw_value:
            return ["-"]
        normalized_format = str(input_format_label or "").strip().lower()
        if normalized_format == "card":
            tokens = raw_value.split()
            return [" ".join(tokens[i:i + 4]) for i in range(0, len(tokens), 4)] or ["-"]
        if normalized_format == "hex":
            tokens = raw_value.split()
            if tokens:
                return [" ".join(tokens[i:i + 6]) for i in range(0, len(tokens), 6)] or ["-"]
            compact = "".join(raw_value.split())
            return [compact[i:i + 18] for i in range(0, len(compact), 18)] or ["-"]
        if normalized_format == "dice":
            compact = "".join(raw_value.split())
            return [compact[i:i + 18] for i in range(0, len(compact), 18)] or ["-"]
        return [raw_value[i:i + 18] for i in range(0, len(raw_value), 18)] or ["-"]

    def entropy_input_title(input_format_label: str) -> str:
        normalized_format = str(input_format_label or "").strip().lower()
        if normalized_format == "card":
            return "牌序"
        if normalized_format == "dice":
            return "掷骰"
        if normalized_format == "hex":
            return "Hex"
        return "原始输入"

    def build_entropy_pages(seed: Seed) -> list[dict]:
        info = seed.get_entropy_display_info()
        summary_lines = [
            f"来源: {info['source_label']}",
            f"格式: {info['input_format_label']}",
            f"熵值: {info['entropy_bits']} bits",
            f"难度: {info['search_space_label']}",
        ]

        pages = [
            {
                "title": "熵详情",
                "text": "\n".join(summary_lines),
                "fixed_width": False,
            }
        ]
        input_lines = chunk_entropy_value(info["display_text"], str(info["input_format_label"]))
        for start in range(0, len(input_lines), 6):
            pages.append(
                {
                    "title": entropy_input_title(str(info["input_format_label"])),
                    "text": "\n".join(input_lines[start:start + 6]),
                    "fixed_width": True,
                }
            )
        return pages

    demo_card_entropy_seed = Seed(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split(),
        entropy_source_label="扑克牌",
        entropy_input_format_label="Card",
        entropy_display_text="AH QS 9D TC 4H 8S KD 2C",
        entropy_qr_text="AH QS 9D TC 4H 8S KD 2C",
        entropy_transform_label="SHA256 后截位",
    )
    card_entropy_pages = build_entropy_pages(demo_card_entropy_seed)
    bip39_index_pages = paginate_lines(build_bip39_index_report("2047"), 5)

    demo_hex_entropy_seed = Seed(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split(),
    )
    hex_entropy_pages = build_entropy_pages(demo_hex_entropy_seed)
    camera_entropy_bytes = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    camera_entropy_seed = Seed(
        mnemonic_generation.generate_mnemonic_from_bytes(camera_entropy_bytes),
        entropy_source_label="拍照随机源",
        entropy_input_format_label="Hex",
        entropy_display_text="00 11 22 33 44 55 66 77 88 99 AA BB CC DD EE FF",
        entropy_qr_text="00112233445566778899AABBCCDDEEFF",
        entropy_transform_label="直接作为随机数",
    )
    camera_entropy_pages = build_entropy_pages(camera_entropy_seed)

    generated_files: list[Path] = []
    seed_words_text = "\n".join(
        f"{index:02d}. abandon  0000" for index in range(1, 25)
    )
    seed_words_bottom_screen = ToolsScrollableTextScreen(
        title="BIP39 序号",
        text=seed_words_text,
        text_font_name=GUIConstants.FIXED_WIDTH_FONT_NAME,
        text_font_size=max(GUIConstants.get_body_font_size(), 19),
        text_is_centered=False,
        button_data=[ButtonOption("完成")],
    )
    seed_words_bottom_scroll = max(0, seed_words_bottom_screen.text_component.max_vertical_scroll)

    specs = [
        (
            "03-seed-tools.png",
            ButtonListScreen(
                title="助记词工具",
                is_button_text_centered=False,
                selected_button=0,
                button_data=[
                    ButtonOption("卡上真随机创建"),
                    ButtonOption("拍照创建"),
                    ButtonOption("骰子创建"),
                    ButtonOption("扑克牌创建"),
                    ButtonOption("16进制创建"),
                    ButtonOption("导入助记词"),
                    ButtonOption("BIP39 单词自检"),
                    ButtonOption("已加载助记词"),
                ],
            ),
            None,
        ),
        (
            "03-seed-tools-more.png",
            ButtonListScreen(
                title="助记词工具",
                is_button_text_centered=False,
                selected_button=7,
                button_data=[
                    ButtonOption("卡上真随机创建"),
                    ButtonOption("拍照创建"),
                    ButtonOption("骰子创建"),
                    ButtonOption("扑克牌创建"),
                    ButtonOption("16进制创建"),
                    ButtonOption("导入助记词"),
                    ButtonOption("BIP39 单词自检"),
                    ButtonOption("已加载助记词"),
                ],
            ),
            None,
        ),
        (
            "29-seedkeeper-rng-length.png",
            ButtonListScreen(
                title="卡上真随机创建",
                is_button_text_centered=False,
                button_data=[
                    ButtonOption("12 个单词"),
                    ButtonOption("15 个单词"),
                    ButtonOption("18 个单词"),
                    ButtonOption("21 个单词"),
                    ButtonOption("24 个单词"),
                ],
            ),
            None,
        ),
        (
            "32-camera-mnemonic-length.png",
            ButtonListScreen(
                title="助记词长度",
                button_data=[
                    ButtonOption("12 个单词"),
                    ButtonOption("15 个单词"),
                    ButtonOption("18 个单词"),
                    ButtonOption("21 个单词"),
                    ButtonOption("24 个单词"),
                ],
            ),
            None,
        ),
        (
            "33-dice-length.png",
            ButtonListScreen(
                title="助记词长度",
                is_bottom_list=True,
                is_button_text_centered=True,
                button_data=[
                    ButtonOption("12 个单词"),
                    ButtonOption("15 个单词"),
                    ButtonOption("18 个单词"),
                    ButtonOption("21 个单词"),
                    ButtonOption("24 个单词"),
                ],
            ),
            None,
        ),
        (
            "34-dice-entry.png",
            ToolsDiceEntropyEntryScreen(return_after_n_chars=50, initial_value="1234561234"),
            lambda screen: (
                setattr(screen, "cursor_position", len(screen.user_input)),
                screen.update_title(),
            ),
        ),
        (
            "35-card-length.png",
            ButtonListScreen(
                title="助记词长度",
                is_bottom_list=True,
                is_button_text_centered=True,
                button_data=[
                    ButtonOption("12 个单词"),
                    ButtonOption("15 个单词"),
                    ButtonOption("18 个单词"),
                    ButtonOption("21 个单词"),
                    ButtonOption("24 个单词"),
                ],
            ),
            None,
        ),
        (
            "36-card-intro.png",
            ToolsFormattedTextScreen(
                title="扑克牌创建",
                text=(
                    "输入示例：AH QS 9D TC\n"
                    "也支持连续输入\n"
                    "网站核验：选 Card\n"
                    "只识别 A23456789TJQK+CDHS"
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                button_data=[ButtonOption("开始输入")],
            ),
            None,
        ),
        (
            "37-card-entry.png",
            ToolsTextQRTextEntryScreen(
                textToEncode="AH QS 9D TC 4H 8S",
                title="扑克牌熵",
                quick_space_backspace=True,
                custom_charset_rows=["23456789", "ATJQKCDHS"],
                custom_selected_char="A",
            ),
            None,
        ),
        (
            "38-card-review-1.png",
            ToolsScrollableTextScreen(
                title="核对牌序",
                text="已录入 16 张\n熵值: 64/128 bits\nAH QS 9D TC\n4H 8S KD 2C\n7H 5D JC 3S\n6C TH AD 9S\nQH 8D KS 4C",
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=20,
                button_data=[ButtonOption("确认生成"), ButtonOption("继续编辑")],
            ),
            None,
        ),
        (
            "39-card-review-2.png",
            ToolsScrollableTextScreen(
                title="核对牌序",
                text="已录入 16 张\n熵值: 64/128 bits\nAH QS 9D TC\n4H 8S KD 2C\n7H 5D JC 3S\n6C TH AD 9S\nQH 8D KS 4C",
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=20,
                initial_text_scroll_y=80,
                button_data=[ButtonOption("确认生成"), ButtonOption("继续编辑")],
            ),
            None,
        ),
        (
            "40-hex-length.png",
            ButtonListScreen(
                title="助记词长度",
                is_bottom_list=True,
                is_button_text_centered=True,
                button_data=[
                    ButtonOption("12 个单词"),
                    ButtonOption("15 个单词"),
                    ButtonOption("18 个单词"),
                    ButtonOption("21 个单词"),
                    ButtonOption("24 个单词"),
                ],
            ),
            None,
        ),
        (
            "41-hex-intro.png",
            ToolsFormattedTextScreen(
                title="16进制创建",
                text=(
                    "输入示例：60 55 17 82\n"
                    "也支持连续输入\n"
                    "网站核验：选 Hex\n"
                    "只识别 0-9 和 A-F"
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                button_data=[ButtonOption("开始输入")],
            ),
            None,
        ),
        (
            "42-hex-entry.png",
            ToolsTextQRTextEntryScreen(
                textToEncode="60 55 17 82 11 46 41 6F",
                title="16进制熵",
                quick_space_backspace=True,
                custom_charset_rows=["0123456789", "ABCDEF"],
                custom_selected_char="0",
            ),
            None,
        ),
        (
            "43-hex-review-1.png",
            ToolsScrollableTextScreen(
                title="核对 Hex",
                text="已录入 16 位 Hex\n熵值: 64/128 bits\n60 55 17 82\n11 46 41 6F\nAA 7F 3C 10\n2D 81 94 E2",
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=20,
                button_data=[ButtonOption("确认生成"), ButtonOption("继续编辑")],
            ),
            None,
        ),
        (
            "44-hex-review-2.png",
            ToolsScrollableTextScreen(
                title="核对 Hex",
                text="已录入 16 位 Hex\n熵值: 64/128 bits\n60 55 17 82\n11 46 41 6F\nAA 7F 3C 10\n2D 81 94 E2",
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=20,
                initial_text_scroll_y=80,
                button_data=[ButtonOption("确认生成"), ButtonOption("继续编辑")],
            ),
            None,
        ),
        (
            "45-load-seed-menu-1.png",
            ButtonListScreen(
                title="导入助记词",
                is_button_text_centered=False,
                selected_button=0,
                button_data=[
                    ButtonOption("扫描 SeedQR"),
                    ButtonOption("输入 12 个单词"),
                    ButtonOption("输入 15 个单词"),
                    ButtonOption("输入 18 个单词"),
                    ButtonOption("输入 21 个单词"),
                    ButtonOption("输入 24 个单词"),
                    ButtonOption("按编号导入 BIP39"),
                    ButtonOption("从钢板数字恢复"),
                    ButtonOption("从 SeedKeeper 导入"),
                    ButtonOption("输入 Electrum"),
                ],
            ),
            None,
        ),
        (
            "46-load-seed-menu-2.png",
            ButtonListScreen(
                title="导入助记词",
                is_button_text_centered=False,
                selected_button=9,
                button_data=[
                    ButtonOption("扫描 SeedQR"),
                    ButtonOption("输入 12 个单词"),
                    ButtonOption("输入 15 个单词"),
                    ButtonOption("输入 18 个单词"),
                    ButtonOption("输入 21 个单词"),
                    ButtonOption("输入 24 个单词"),
                    ButtonOption("按编号导入 BIP39"),
                    ButtonOption("从钢板数字恢复"),
                    ButtonOption("从 SeedKeeper 导入"),
                    ButtonOption("输入 Electrum"),
                ],
            ),
            None,
        ),
        (
            "47-bip39-word-entry.png",
            ToolsTextQRTextEntryScreen(
                textToEncode="abandon",
                title="输入英文单词",
                initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__LOWERCASE_BUTTON_TEXT,
            ),
            None,
        ),
        (
            "48-bip39-word-result.png",
            ToolsFormattedTextScreen(
                title="BIP39 单词自检",
                text=build_bip39_word_report("abandon"),
                text_font_name=GUIConstants.get_body_font_name(),
                button_data=[ButtonOption("重新查询"), ButtonOption("完成")],
            ),
            None,
        ),
        (
            "49-bip39-index-entry.png",
            ToolsTextQRTextEntryScreen(
                textToEncode="2047",
                title="输入编号 0-2047",
                initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__DIGITS_BUTTON_TEXT,
                digits_entry_mode=True,
            ),
            None,
        ),
        (
            "50-bip39-index-result.png",
            ToolsScrollableTextScreen(
                title="BIP39 单词自检",
                text="\n\n".join(page for page in bip39_index_pages if str(page).strip()),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size(), 19),
                button_data=[ButtonOption("重新查询"), ButtonOption("完成")],
            ),
            None,
        ),
        (
            "50b-bip39-index-result-2.png",
            ToolsScrollableTextScreen(
                title="BIP39 单词自检",
                text="\n\n".join(page for page in bip39_index_pages if str(page).strip()),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size(), 19),
                initial_text_scroll_y=72,
                button_data=[ButtonOption("重新查询"), ButtonOption("完成")],
            ),
            None,
        ),
        (
            "51-entropy-summary.png",
            ToolsScrollableTextScreen(
                title="熵详情",
                text="\n\n".join(
                    [
                        card_entropy_pages[0]["text"],
                        f"{card_entropy_pages[1]['title']}:\n{card_entropy_pages[1]['text']}",
                    ]
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.BODY_FONT_MIN_SIZE, GUIConstants.get_body_font_size()),
                button_data=[ButtonOption("显示二维码"), ButtonOption("完成")],
            ),
            None,
        ),
        (
            "52-entropy-card-input.png",
            ToolsScrollableTextScreen(
                title="熵详情",
                text="\n\n".join(
                    [
                        card_entropy_pages[0]["text"],
                        f"{card_entropy_pages[1]['title']}:\n{card_entropy_pages[1]['text']}",
                    ]
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.BODY_FONT_MIN_SIZE, GUIConstants.get_body_font_size()),
                initial_text_scroll_y=88,
                button_data=[ButtonOption("显示二维码"), ButtonOption("完成")],
            ),
            None,
        ),
        (
            "53-entropy-hex-input.png",
            ToolsScrollableTextScreen(
                title="熵详情",
                text="\n\n".join(
                    [
                        hex_entropy_pages[0]["text"],
                        f"{hex_entropy_pages[1]['title']}:\n{hex_entropy_pages[1]['text']}",
                    ]
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.BODY_FONT_MIN_SIZE, GUIConstants.get_body_font_size()),
                initial_text_scroll_y=88,
                button_data=[ButtonOption("显示二维码"), ButtonOption("完成")],
            ),
            None,
        ),
        (
            "53a-entropy-camera-input.png",
            ToolsScrollableTextScreen(
                title="熵详情",
                text="\n\n".join(
                    [
                        camera_entropy_pages[0]["text"],
                        f"{camera_entropy_pages[1]['title']}:\n{camera_entropy_pages[1]['text']}",
                    ]
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.BODY_FONT_MIN_SIZE, GUIConstants.get_body_font_size()),
                initial_text_scroll_y=88,
                button_data=[ButtonOption("显示二维码"), ButtonOption("完成")],
            ),
            None,
        ),
        (
            "53b-seed-words-bottom.png",
            seed_words_bottom_screen,
            lambda screen: screen.text_component.set_vertical_scroll_y(seed_words_bottom_scroll),
        ),
    ]

    for filename, screen, before_capture in specs:
        out_path = output_dir / filename
        _capture_keyboard_screen(out_path, screen, before_capture=before_capture)
        generated_files.append(out_path)

    preview_path = output_dir / "30-camera-live-preview.png"
    _capture_camera_entropy_preview_screen(preview_path, runtime)
    generated_files.append(preview_path)

    final_path = output_dir / "31-camera-final-image.png"
    _capture_camera_entropy_final_screen(final_path, runtime)
    generated_files.append(final_path)

    return generated_files


def _generate_contact_sheet(output_dir: Path, image_paths: list[Path]) -> Path:
    from PIL import Image, ImageDraw

    deduped = {path.name: path for path in image_paths if path.name != "_contact_sheet.png"}
    ordered_paths = [deduped[name] for name in sorted(deduped)]
    thumb_width = 180
    thumb_height = 180
    label_height = 28
    padding = 12
    columns = 4
    rows = (len(ordered_paths) + columns - 1) // columns
    canvas = Image.new(
        "RGB",
        (
            columns * (thumb_width + padding) + padding,
            rows * (thumb_height + label_height + padding) + padding,
        ),
        "#dbe3ea",
    )
    draw = ImageDraw.Draw(canvas)

    for index, image_path in enumerate(ordered_paths):
        row = index // columns
        col = index % columns
        x = padding + col * (thumb_width + padding)
        y = padding + row * (thumb_height + label_height + padding)
        image = Image.open(image_path).convert("RGB")
        image.thumbnail((thumb_width, thumb_height))
        thumb_x = x + (thumb_width - image.width) // 2
        thumb_y = y + (thumb_height - image.height) // 2
        canvas.paste(image, (thumb_x, thumb_y))
        draw.text((x, y + thumb_height + 4), image_path.name, fill="#0f172a")

    out_path = output_dir / "_contact_sheet.png"
    canvas.save(out_path)
    return out_path


def _capture_signed_summary_screens(output_dir: Path) -> list[Path]:
    from types import SimpleNamespace

    from seedsigner.gui.components import GUIConstants
    from seedsigner.gui.screens.screen import ButtonOption
    from seedsigner.gui.screens.tools_screens import ToolsScrollableTextScreen
    from seedsigner.models.encode_qr import GenericStaticQrEncoder
    from seedsigner.views.psbt_views import _build_signed_psbt_review_pages

    fake_parser = SimpleNamespace(
        num_inputs=4,
        num_destinations=1,
        spend_amount=18_938,
        fee_amount=158,
        change_amount=0,
        destination_addresses=["bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"],
        destination_amounts=[18_938],
    )
    qr_encoder = GenericStaticQrEncoder(
        data=f"btctx:{SIGNED_TX_SAMPLE_HEX}"
    )
    pages = _build_signed_psbt_review_pages(
        psbt_parser=fake_parser,
        signed_tx_hex=SIGNED_TX_SAMPLE_HEX,
        qr_encoder=qr_encoder,
        input_qr_type="psbt__bbqr",
    )

    summary_text = "\n\n".join(page for page in pages if str(page).strip())
    base_screen = ToolsScrollableTextScreen(
        title="签名结果摘要",
        text=summary_text,
        text_font_name=GUIConstants.get_body_font_name(),
        text_font_size=max(GUIConstants.get_body_font_size() + 1, 19),
        button_data=[ButtonOption("显示签名二维码")],
    )
    offsets = _spread_scroll_offsets(base_screen.text_component.max_vertical_scroll, 6)

    generated_files: list[Path] = []
    for index, scroll_y in enumerate(offsets, start=1):
        filename = f"{8 + index:02d}-signed-summary-{index}.png"
        out_path = output_dir / filename
        _capture_scrollable_screen(out_path, base_screen, scroll_y=scroll_y)
        generated_files.append(out_path)

    return generated_files


def _capture_satochip_verification_screens(output_dir: Path) -> list[Path]:
    from embit import bip32 as embit_bip32_mod
    from embit.networks import NETWORKS as EMBIT_NETWORKS
    from embit.util import secp256k1

    from seedsigner.gui.components import GUIConstants
    from seedsigner.gui.screens.screen import ButtonOption
    from seedsigner.gui.screens.tools_screens import ToolsScrollableTextScreen
    from seedsigner.helpers import embit_utils
    from seedsigner.models.seed import Seed
    from seedsigner.models.settings_definition import SettingsConstants

    def _chunk_status_text(text: str, width: int = 18) -> list[str]:
        value = str(text or "").strip()
        if not value:
            return ["-"]
        return [value[i:i + width] for i in range(0, len(value), width)] or ["-"]

    def _paginate_status_lines(lines: list[str], lines_per_page: int = 9) -> list[str]:
        cleaned = [str(line).rstrip() for line in lines]
        if not cleaned:
            return [""]
        pages: list[str] = []
        for start in range(0, len(cleaned), lines_per_page):
            page = "\n".join(cleaned[start:start + lines_per_page]).strip("\n")
            pages.append(page if page else " ")
        return pages

    def _status_mark(ok: bool) -> str:
        return "通过" if ok else "失败"

    class _FakeExtendedKey:
        def __init__(self, hdkey):
            self._hdkey = hdkey

        def get_public_key_bytes(self, compressed=True):
            if compressed:
                return self._hdkey.key.sec()
            return self._hdkey.key.sec(compressed=False)

    class _FakeSatochipImportConnector:
        def __init__(self, seed_bytes: bytes):
            self.seed_bytes = bytes(seed_bytes)
            self.parser = types.SimpleNamespace(authentikey=object())
            self._current_priv = None

        def card_get_status(self):
            return None, 0x90, 0x00, {"is_seeded": True}

        def _root(self, is_mainnet=True):
            embit_network = "main" if is_mainnet else "test"
            return embit_bip32_mod.HDKey.from_seed(
                self.seed_bytes,
                version=EMBIT_NETWORKS[embit_network]["xprv"],
            )

        def card_bip32_get_xpub(self, derivation_path, xtype, is_mainnet):
            root = self._root(is_mainnet=is_mainnet)
            if not derivation_path or derivation_path == "m":
                derived = root
            else:
                derived = root.derive(derivation_path)
            public = derived.to_public()
            version_key = {
                "standard": "xpub",
                "p2wpkh-p2sh": "ypub",
                "p2wpkh": "zpub",
            }[xtype]
            embit_network = "main" if is_mainnet else "test"
            return public.to_base58(version=EMBIT_NETWORKS[embit_network][version_key])

        def card_bip32_get_extendedkey(self, derivation_path):
            derived = self._root(is_mainnet=True)
            if derivation_path and derivation_path != "m":
                derived = derived.derive(derivation_path)
            self._current_priv = derived
            return _FakeExtendedKey(derived.to_public()), bytes(derived.chain_code)

        def card_sign_transaction_hash(self, keynbr, tx_hash, challenge):
            _ = keynbr
            _ = challenge
            sig = self._current_priv.key.sign(bytes(tx_hash)).serialize()
            return list(sig), 0x90, 0x00

    def _build_demo_verification(seed: Seed, connector: _FakeSatochipImportConnector) -> dict:
        network = SettingsConstants.MAINNET
        embit_network = embit_utils.get_embit_network_name(network) or "main"
        summary_lines = [
            "写卡后自动核验",
            "网络: 主网",
            "看到“通过”即可继续",
            "看到“失败”请停用此卡",
        ]
        failed_sections: list[list[str]] = []
        all_ok = True

        def add_check(label: str, ok: bool, detail_lines: list[str]) -> None:
            nonlocal all_ok
            all_ok = all_ok and ok
            summary_lines.append(f"{label}: {_status_mark(ok)}")
            if not ok:
                failed_sections.append(detail_lines)

        _resp, _sw1, _sw2, status = connector.card_get_status()
        seeded_ok = bool((status or {}).get("is_seeded"))
        add_check(
            "卡片状态",
            seeded_ok,
            [
                "核验项: 卡片状态",
                f"状态: {_status_mark(seeded_ok)}",
                f"is_seeded: {'是' if seeded_ok else '否'}",
            ],
        )

        card_master_xpub = connector.card_bip32_get_xpub("", "p2wpkh", True)
        card_fingerprint = embit_bip32_mod.HDKey.from_string(card_master_xpub).my_fingerprint.hex()
        local_fingerprint = seed.get_fingerprint(network)
        fingerprint_ok = local_fingerprint == card_fingerprint
        add_check(
            "主指纹",
            fingerprint_ok,
            [
                "核验项: 主指纹",
                f"状态: {_status_mark(fingerprint_ok)}",
                f"本地: {local_fingerprint}",
                f"卡片: {card_fingerprint}",
            ],
        )

        native_local_xpub = None
        profile_checks = [
            ("Legacy", SettingsConstants.LEGACY_P2PKH, "standard"),
            ("SegWit", SettingsConstants.NATIVE_SEGWIT, "p2wpkh"),
        ]
        for label, script_type, card_xtype in profile_checks:
            derivation_path = embit_utils.get_standard_derivation_path(
                network=network,
                wallet_type=SettingsConstants.SINGLE_SIG,
                script_type=script_type,
                account=0,
            )
            card_xpub_text = connector.card_bip32_get_xpub(derivation_path, card_xtype, True)
            card_xpub = embit_bip32_mod.HDKey.from_base58(card_xpub_text)
            local_xpub = seed.get_xpub(wallet_path=derivation_path, network=network)
            local_xpub_text = local_xpub.to_base58(version=card_xpub.version)
            xpub_ok = local_xpub_text == card_xpub_text

            local_receive = embit_utils.get_single_sig_address(
                xpub=local_xpub,
                script_type=script_type,
                index=0,
                is_change=False,
                embit_network=embit_network,
            )
            card_receive = embit_utils.get_single_sig_address(
                xpub=card_xpub,
                script_type=script_type,
                index=0,
                is_change=False,
                embit_network=embit_network,
            )
            local_change = embit_utils.get_single_sig_address(
                xpub=local_xpub,
                script_type=script_type,
                index=0,
                is_change=True,
                embit_network=embit_network,
            )
            card_change = embit_utils.get_single_sig_address(
                xpub=card_xpub,
                script_type=script_type,
                index=0,
                is_change=True,
                embit_network=embit_network,
            )

            if script_type == SettingsConstants.NATIVE_SEGWIT:
                native_local_xpub = local_xpub

            add_check(
                f"{label} xpub",
                xpub_ok,
                [
                    f"核验项: {label} xpub",
                    f"状态: {_status_mark(xpub_ok)}",
                    f"路径: {derivation_path}",
                    "本地:",
                    *_chunk_status_text(local_xpub_text),
                    "卡片:",
                    *_chunk_status_text(card_xpub_text),
                ],
            )
            add_check(
                f"{label} 收款0",
                local_receive == card_receive,
                [
                    f"核验项: {label} 收款地址 0",
                    f"状态: {_status_mark(local_receive == card_receive)}",
                    "本地:",
                    *_chunk_status_text(local_receive),
                    "卡片:",
                    *_chunk_status_text(card_receive),
                ],
            )
            add_check(
                f"{label} 找零0",
                local_change == card_change,
                [
                    f"核验项: {label} 找零地址 0",
                    f"状态: {_status_mark(local_change == card_change)}",
                    "本地:",
                    *_chunk_status_text(local_change),
                    "卡片:",
                    *_chunk_status_text(card_change),
                ],
            )

        sign_path = embit_utils.get_standard_derivation_path(
            network=network,
            wallet_type=SettingsConstants.SINGLE_SIG,
            script_type=SettingsConstants.NATIVE_SEGWIT,
            account=0,
        ) + "/0/0"
        _key, _chaincode = connector.card_bip32_get_extendedkey(sign_path)
        test_hash = __import__("hashlib").sha256(b"offline-signer-satochip-import-verify").digest()
        sig, sw1, sw2 = connector.card_sign_transaction_hash(0xFF, list(test_hash), None)
        verified = False
        if sw1 == 0x90 and sw2 == 0x00 and sig and native_local_xpub is not None:
            pubkey = native_local_xpub.derive([0, 0]).key.sec()
            sig_obj = secp256k1.ecdsa_signature_parse_der(bytes(sig))
            pubkey_obj = secp256k1.ec_pubkey_parse(pubkey)
            verified = bool(secp256k1.ecdsa_verify(sig_obj, test_hash, pubkey_obj))
        add_check(
            "测试签名验签",
            verified,
            [
                "核验项: 测试签名验签",
                f"状态: {_status_mark(verified)}",
                f"路径: {sign_path}",
                "固定测试哈希已通过本地验签" if verified else "固定测试哈希未通过本地验签",
            ],
        )

        summary_lines.extend(["", f"结论: {'可以继续使用' if all_ok else '请不要继续用这张卡保存资金'}"])
        pages = _paginate_status_lines(summary_lines, lines_per_page=7)
        for section in failed_sections:
            pages.extend(_paginate_status_lines(section, lines_per_page=7))
        return {"ok": all_ok, "pages": pages}

    mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split()
    seed = Seed(mnemonic=mnemonic)
    connector = _FakeSatochipImportConnector(seed.seed_bytes)
    verification = _build_demo_verification(seed=seed, connector=connector)
    pages = verification.get("pages", ["核验结果为空"])
    ok = bool(verification.get("ok"))

    summary_text = "\n\n".join(page for page in pages if str(page).strip())
    screen = ToolsScrollableTextScreen(
        title="写卡核验",
        text=summary_text,
        text_font_name=GUIConstants.get_body_font_name(),
        text_font_size=max(GUIConstants.BODY_FONT_MIN_SIZE, GUIConstants.get_body_font_size()),
        button_data=[ButtonOption("完成")],
    )
    offsets = _spread_scroll_offsets(screen.text_component.max_vertical_scroll, 3)

    generated_files: list[Path] = []
    for index, scroll_y in enumerate(offsets, start=1):
        filename = f"{22 + index:02d}-write-card-verify-{index}.png"
        out_path = output_dir / filename
        _capture_scrollable_screen(out_path, screen, scroll_y=scroll_y)
        generated_files.append(out_path)

    return generated_files


def generate_screenshots(output_dir: Path, venv_root: Path | None) -> list[Path]:
    runtime = _prepare_runtime(venv_root)

    from seedsigner.gui.components import GUIConstants
    from seedsigner.gui.screens.psbt_screens import PSBTFinalizeScreen, PSBTOverviewScreen
    from seedsigner.gui.screens import LargeIconStatusScreen
    from seedsigner.gui.screens.screen import ButtonListScreen, ButtonOption
    from seedsigner.gui.screens.seed_screens import SeedExportXpubDetailsScreen
    from seedsigner.gui.screens.tools_screens import ToolsFormattedTextScreen, ToolsScrollableTextScreen, ToolsTextQRTextEntryScreen
    from seedsigner.gui.screens import seed_screens
    from seedsigner.views.tp_views import _build_firmware_integrity_detail_pages

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_png in output_dir.glob("*.png"):
        stale_png.unlink()

    generated_files: list[Path] = []

    specs = [
        (
            "01-login-password.png",
            ToolsTextQRTextEntryScreen(
                title="设置登录密码",
                textToEncode="1234",
                initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__DIGITS_BUTTON_TEXT,
            ),
        ),
        (
            "02-home-menu.png",
            ButtonListScreen(
                title="离线签名器",
                is_button_text_centered=False,
                button_data=[
                    ButtonOption("扫码签名"),
                    ButtonOption("助记词工具"),
                    ButtonOption("智能卡工具"),
                    ButtonOption("固件自检"),
                ],
                show_back_button=False,
            ),
        ),
        (
            "15-bip39-check-menu.png",
            ButtonListScreen(
                title="BIP39 单词自检",
                is_button_text_centered=False,
                button_data=[
                    ButtonOption("输入单词查编号"),
                    ButtonOption("输入编号查单词"),
                ],
            ),
        ),
        (
            "05-smartcard-tools.png",
            ButtonListScreen(
                title="智能卡工具",
                is_button_text_centered=False,
                button_data=[
                    ButtonOption("Satochip 功能"),
                    ButtonOption("SeedKeeper 功能"),
                    ButtonOption("完整菜单"),
                ],
            ),
        ),
        (
            "04-xpub-details.png",
            SeedExportXpubDetailsScreen(
                fingerprint="A1B2C3D4",
                derivation_path="m/84'/0'/0'",
                xpub=(
                    "zpub6rS3yWb9YkW9Wkq8cC4k6U7H19dQd2t1f"
                    "zDpQh9Y4QnL7e4T2aX7xAz1h8f1J9mJb5G1z"
                ),
                button_label="显示二维码",
            ),
        ),
        (
            "16-loaded-seed-menu-1.png",
            ButtonListScreen(
                title="助记词 73c5da0a",
                is_button_text_centered=False,
                selected_button=0,
                button_data=[
                    ButtonOption("查看助记词"),
                    ButtonOption("查看原始熵"),
                    ButtonOption("按路径算地址"),
                    ButtonOption("导出 Blue zpub"),
                    ButtonOption("导出 Blue xpub"),
                    ButtonOption("BIP85 子助记词"),
                    ButtonOption("写入到 SeedKeeper"),
                    ButtonOption("写入到智能卡"),
                    ButtonOption("二次加密"),
                    ButtonOption("二次还原"),
                    ButtonOption("钢板数字"),
                    ButtonOption("删除助记词", button_label_color="red"),
                ],
            ),
        ),
        (
            "17-loaded-seed-menu-2.png",
            ButtonListScreen(
                title="助记词 73c5da0a",
                is_button_text_centered=False,
                selected_button=11,
                button_data=[
                    ButtonOption("查看助记词"),
                    ButtonOption("查看原始熵"),
                    ButtonOption("按路径算地址"),
                    ButtonOption("导出 Blue zpub"),
                    ButtonOption("导出 Blue xpub"),
                    ButtonOption("BIP85 子助记词"),
                    ButtonOption("写入到 SeedKeeper"),
                    ButtonOption("写入到智能卡"),
                    ButtonOption("二次加密"),
                    ButtonOption("二次还原"),
                    ButtonOption("钢板数字"),
                    ButtonOption("删除助记词", button_label_color="red"),
                ],
            ),
        ),
        (
            "06-review-psbt.png",
            PSBTOverviewScreen(
                spend_amount=18_938,
                change_amount=0,
                fee_amount=158,
                num_inputs=4,
                num_self_transfer_outputs=0,
                num_change_outputs=0,
                destination_addresses=["bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"],
                has_op_return=False,
            ),
        ),
        (
            "07-sign-psbt.png",
            PSBTFinalizeScreen(
                button_data=[ButtonOption("输入 PIN 并签名")],
            ),
        ),
        (
            "18-satochip-tools-1.png",
            ButtonListScreen(
                title="Satochip 功能",
                is_button_text_centered=False,
                selected_button=0,
                button_data=[
                    ButtonOption("按路径看地址"),
                    ButtonOption("导出 Blue zpub"),
                    ButtonOption("导出 Blue xpub"),
                    ButtonOption("写入助记词"),
                    ButtonOption("更改卡 PIN"),
                    ButtonOption("重置卡"),
                    ButtonOption("更多功能"),
                ],
            ),
        ),
        (
            "19-satochip-tools-2.png",
            ButtonListScreen(
                title="Satochip 功能",
                is_button_text_centered=False,
                selected_button=6,
                button_data=[
                    ButtonOption("按路径看地址"),
                    ButtonOption("导出 Blue zpub"),
                    ButtonOption("导出 Blue xpub"),
                    ButtonOption("写入助记词"),
                    ButtonOption("更改卡 PIN"),
                    ButtonOption("重置卡"),
                    ButtonOption("更多功能"),
                ],
            ),
        ),
        (
            "20-seedkeeper-tools-1.png",
            ButtonListScreen(
                title="SeedKeeper 功能",
                is_button_text_centered=False,
                selected_button=0,
                button_data=[
                    ButtonOption("卡上真随机创建"),
                    ButtonOption("写入到 SeedKeeper"),
                    ButtonOption("保存二次加密"),
                    ButtonOption("加载二次加密"),
                    ButtonOption("更改卡 PIN"),
                    ButtonOption("重置卡"),
                    ButtonOption("更多功能"),
                ],
            ),
        ),
        (
            "21-seedkeeper-tools-2.png",
            ButtonListScreen(
                title="SeedKeeper 功能",
                is_button_text_centered=False,
                selected_button=6,
                button_data=[
                    ButtonOption("卡上真随机创建"),
                    ButtonOption("写入到 SeedKeeper"),
                    ButtonOption("保存二次加密"),
                    ButtonOption("加载二次加密"),
                    ButtonOption("更改卡 PIN"),
                    ButtonOption("重置卡"),
                    ButtonOption("更多功能"),
                ],
            ),
        ),
        (
            "26-full-smartcard-menu.png",
            ButtonListScreen(
                title="智能卡工具",
                is_button_text_centered=False,
                button_data=[
                    ButtonOption("通用功能"),
                    ButtonOption("SeedKeeper 功能"),
                    ButtonOption("Satochip 功能"),
                ],
            ),
        ),
        (
            "27-common-smartcard-tools.png",
            ButtonListScreen(
                title="通用工具",
                is_button_text_centered=False,
                button_data=[
                    ButtonOption("设备筛选"),
                    ButtonOption("卡片信息"),
                    ButtonOption("真伪检查"),
                    ButtonOption("修改标签"),
                    ButtonOption("修改 NFC 策略"),
                ],
            ),
        ),
        (
            "28-firmware-self-check.png",
            ToolsFormattedTextScreen(
                title="固件完整性",
                text="固件完整性: 通过\n清单文件: 已找到\n运行时文件: 未发现异常\n建议: 可以继续使用",
                text_font_name=GUIConstants.get_body_font_name(),
                button_data=[ButtonOption("查看详情"), ButtonOption("重新自检"), ButtonOption("完成")],
            ),
        ),
        (
            "54-derive-path.png",
            ToolsTextQRTextEntryScreen(
                textToEncode="m/84'/0'/0'/0/0",
                title="派生路径",
                initial_keyboard=ToolsTextQRTextEntryScreen.KEYBOARD__DIGITS_BUTTON_TEXT,
            ),
        ),
        (
            "55-derived-address-1.png",
            ToolsScrollableTextScreen(
                title="派生地址",
                text="网络: 主网\n类型: Native SegWit\n\n路径:\nm/84'/0'/0'/0/0\n\nbc1qxy2kgdygjrsqtz\nq2n0yrf2493p83kkfj\nhx0wlh",
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size(), 18),
                button_data=[ButtonOption("显示二维码"), ButtonOption("完成")],
            ),
        ),
        (
            "56-derived-address-2.png",
            ToolsScrollableTextScreen(
                title="派生地址",
                text="网络: 主网\n类型: Native SegWit\n\n路径:\nm/84'/0'/0'/0/0\n\nbc1qxy2kgdygjrsqtz\nq2n0yrf2493p83kkfj\nhx0wlh",
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size(), 18),
                initial_text_scroll_y=88,
                button_data=[ButtonOption("显示二维码"), ButtonOption("完成")],
            ),
        ),
        (
            "57-bip85-num-words.png",
            ButtonListScreen(
                title="BIP85 词数",
                button_data=[
                    ButtonOption("12 个单词"),
                    ButtonOption("18 个单词"),
                    ButtonOption("24 个单词"),
                ],
            ),
        ),
        (
            "58-bip85-index-entry.png",
            seed_screens.SeedBIP85SelectChildIndexScreen(),
        ),
        (
            "59-bip85-backup-prompt.png",
            seed_screens.SeedWordsBackupTestPromptScreen(
                button_data=[
                    ButtonOption("验证备份"),
                    ButtonOption("重新查看"),
                    ButtonOption("跳过"),
                    ButtonOption("导入到树莓派"),
                ],
            ),
        ),
        (
            "60-satochip-more-menu.png",
            ButtonListScreen(
                title="Satochip",
                is_button_text_centered=False,
                button_data=[
                    ButtonOption("写入助记词"),
                    ButtonOption("导出公钥"),
                    ButtonOption("加载描述符"),
                    ButtonOption("加载 PSBT"),
                    ButtonOption("更改 PIN"),
                    ButtonOption("重置卡片"),
                    ButtonOption("高级功能"),
                ],
            ),
        ),
        (
            "61-seedkeeper-more-menu.png",
            ButtonListScreen(
                title="SeedKeeper",
                is_button_text_centered=False,
                button_data=[
                    ButtonOption("卡上真随机创建"),
                    ButtonOption("管理卡内助记词"),
                    ButtonOption("保存密码到卡片"),
                    ButtonOption("加载多签描述符"),
                    ButtonOption("保存多签描述符"),
                    ButtonOption("克隆卡内项目"),
                    ButtonOption("更改 PIN"),
                    ButtonOption("高风险：重置"),
                    ButtonOption("剩余空间"),
                ],
            ),
        ),
        (
            "62-smartcard-info.png",
            LargeIconStatusScreen(
                title="卡片信息",
                status_headline=None,
                text="卡型: SeedKeeper\nUID: a1b2c3d4e5\n版本: 2.1-0.2\nPIN 剩余: 5\n已初始化: 已完成\nNFC: 已启用",
                status_icon_name="",
                show_back_button=True,
            ),
        ),
        (
            "63-smartcard-genuine.png",
            LargeIconStatusScreen(
                title="真伪检查",
                status_headline=None,
                text="卡片验证通过",
                show_back_button=True,
            ),
        ),
        (
            "64-seedkeeper-free-space.png",
            LargeIconStatusScreen(
                title="剩余空间",
                status_headline=None,
                text="32768 字节可用\n(32.0 KiB)",
                show_back_button=True,
            ),
        ),
        (
            "69-steel-shift-review.png",
            ToolsScrollableTextScreen(
                title="检查运算",
                text=(
                    "01: +123\n02: -045\n03: +888\n04: （不变）\n05: +111\n06: -222\n"
                    "07: +333\n08: +444\n09: -555\n10: +666\n11: -777\n12: +999"
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size(), 18),
                button_data=[ButtonOption("重新输入"), ButtonOption("预览结果序号"), ButtonOption("确认执行")],
            ),
        ),
        (
            "70-steel-plate-review.png",
            ToolsScrollableTextScreen(
                title="检查数字",
                text=(
                    "01: 1 2 8 32\n\n02: 4 16 64 128\n\n03: 2 4 8 16 32\n\n04: 256 1024\n\n"
                    "05: 1 4 32 256\n\n06: 2 64 128\n\n07: 8 16 32 64\n\n08: 1 512 1024\n\n"
                    "09: 4 8 128 256\n\n10: 32 64 128\n\n11: 1 2 4 8 16\n\n12: 2 8 32 512"
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size(), 18),
                button_data=[ButtonOption("编辑词条"), ButtonOption("预览恢复序号"), ButtonOption("确认恢复")],
            ),
        ),
        (
            "71-steel-cipher-words.png",
            ToolsScrollableTextScreen(
                title="假助记词序号",
                text=(
                    "01  0000  abandon\n02  0001  ability\n03  0002  able\n04  0003  about\n"
                    "05  0004  above\n06  0005  absent\n07  0006  absorb\n08  0007  abstract\n"
                    "09  0008  absurd\n10  0009  abuse\n11  0010  access\n12  0011  accident"
                ),
                text_font_name=GUIConstants.FIXED_WIDTH_FONT_NAME,
                text_font_size=max(GUIConstants.get_body_font_size(), 18),
                button_data=[ButtonOption("完成")],
            ),
        ),
        (
            "72-steel-plate-words-1.png",
            ToolsScrollableTextScreen(
                title="打孔位",
                text=(
                    "01 词\n序号: 0000\n打孔位:\n无需打孔\n\n"
                    "02 词\n序号: 0001\n打孔位:\n1\n\n"
                    "03 词\n序号: 0002\n打孔位:\n2\n\n"
                    "04 词\n序号: 0003\n打孔位:\n1 2"
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size(), 18),
                button_data=[ButtonOption("查看 BIP39 序号"), ButtonOption("完成")],
            ),
        ),
        (
            "73-steel-plate-words-2.png",
            ToolsScrollableTextScreen(
                title="打孔位",
                text=(
                    "05 词\n序号: 0296\n打孔位:\n8 32\n256\n\n"
                    "06 词\n序号: 1024\n打孔位:\n1024\n\n"
                    "07 词\n序号: 1536\n打孔位:\n512 1024\n\n"
                    "08 词\n序号: 2047\n打孔位:\n1 2 4 8 16 32\n64 128 256 512 1024"
                ),
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size(), 18),
                button_data=[ButtonOption("查看 BIP39 序号"), ButtonOption("完成")],
            ),
        ),
    ]

    for filename, screen in specs:
        out_path = output_dir / filename
        _capture_static_screen(out_path, screen)
        generated_files.append(out_path)

    scan_path = output_dir / "05-scan-psbt.png"
    _capture_scan_screen(scan_path, runtime)
    generated_files.append(scan_path)

    generated_files.extend(_capture_signed_summary_screens(output_dir))
    generated_files.extend(_capture_satochip_verification_screens(output_dir))
    generated_files.extend(_build_seed_tools_screens(output_dir, runtime))

    firmware_detail_pages = _build_firmware_integrity_detail_pages(
        {
            "supported": True,
            "ok": True,
            "verified_file_count": 101,
            "repo_head": "930deeb9dc04d4fb8f85c907806171e7262c7376",
            "build_commit_time": "2026-04-09T02:10:00Z",
            "build_time_utc": "2026-04-09T03:15:00Z",
            "source_snapshot_tree_sha256": "98ce03bc4e0920e0ac555c851384d623fba9c09da9c19df531c575ac5a450023",
            "missing": [],
            "modified": [],
            "unexpected": [],
            "errors": [],
        }
    )
    firmware_screen = ToolsScrollableTextScreen(
        title="固件完整性",
        text="\n\n".join(page for page in firmware_detail_pages if str(page).strip()),
        text_font_name=GUIConstants.get_body_font_name(),
        button_data=[ButtonOption("返回")],
    )
    firmware_offsets = _spread_scroll_offsets(firmware_screen.text_component.max_vertical_scroll, 4)
    for page_index, scroll_y in enumerate(firmware_offsets, start=1):
        out_path = output_dir / f"{64 + page_index:02d}-firmware-detail-{page_index}.png"
        _capture_scrollable_screen(out_path, firmware_screen, scroll_y=scroll_y)
        generated_files.append(out_path)

    qr_path = output_dir / "08-signed-qr.png"
    _capture_qr_screen(qr_path, runtime)
    generated_files.append(qr_path)

    contact_sheet_path = _generate_contact_sheet(output_dir, generated_files)
    generated_files.append(contact_sheet_path)

    return generated_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate real firmware UI screenshots for docs.")
    parser.add_argument(
        "venv_root",
        nargs="?",
        help="Optional desktop smoke venv root (default: /tmp/satochip-desktop-smoke-venv)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory for generated screenshots (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    venv_root = Path(args.venv_root).resolve() if args.venv_root else None
    output_dir = Path(args.output_dir).resolve()

    generated_files = generate_screenshots(output_dir=output_dir, venv_root=venv_root)
    for file_path in generated_files:
        print(file_path.relative_to(REPO_ROOT))
    print(f"generated_real_ui_screenshots={len(generated_files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
