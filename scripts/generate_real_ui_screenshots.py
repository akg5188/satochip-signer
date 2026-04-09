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
        system_mod = types.ModuleType("smartcard.System")
        exceptions_mod = types.ModuleType("smartcard.Exceptions")
        util_mod = types.ModuleType("smartcard.util")

        class CardConnectionException(Exception):
            pass

        class NoReadersException(Exception):
            pass

        system_mod.readers = lambda: []
        exceptions_mod.CardConnectionException = CardConnectionException
        exceptions_mod.NoReadersException = NoReadersException
        util_mod.toHexString = lambda data: " ".join(f"{byte:02X}" for byte in data)

        smartcard_mod.System = system_mod
        smartcard_mod.Exceptions = exceptions_mod
        smartcard_mod.util = util_mod

        sys.modules["smartcard"] = smartcard_mod
        sys.modules["smartcard.System"] = system_mod
        sys.modules["smartcard.Exceptions"] = exceptions_mod
        sys.modules["smartcard.util"] = util_mod

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
    screen._render()
    screen.renderer.canvas.save(path)


def _capture_live_display(path: Path, runtime, starter) -> None:
    renderer = runtime["renderer"]
    original_show_image = renderer.disp.show_image
    last_image = {"image": None}

    def wrapped_show_image(image, x_start=0, y_start=0):
        last_image["image"] = image.copy()
        return original_show_image(image, x_start, y_start)

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
    from seedsigner.gui.screens.screen import QRDisplayScreen
    from seedsigner.models.encode_qr import GenericStaticQrEncoder

    def starter():
        screen = QRDisplayScreen(
            qr_encoder=GenericStaticQrEncoder(
                data=(
                    "btctx:02000000000101888a1c65d1a90971cb53"
                    "67af2f1f3c58f71e40d4a4d9b2d7f6a7e4e6d52f0000000000ffffffff"
                )
            )
        )
        qr_thread = screen.threads[-1]
        qr_thread.start()
        time.sleep(0.18)
        qr_thread.stop()
        while qr_thread.is_alive():
            time.sleep(0.01)

    _capture_live_display(path, runtime, starter)


def generate_screenshots(output_dir: Path, venv_root: Path | None) -> list[Path]:
    runtime = _prepare_runtime(venv_root)

    from seedsigner.gui.screens.psbt_screens import PSBTFinalizeScreen, PSBTOverviewScreen
    from seedsigner.gui.screens.screen import ButtonListScreen, ButtonOption
    from seedsigner.gui.screens.seed_screens import SeedExportXpubDetailsScreen
    from seedsigner.gui.screens.tools_screens import ToolsTextQRTextEntryScreen

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
                    ButtonOption("固件完整性自检"),
                    ButtonOption("智能卡工具"),
                ],
                show_back_button=False,
            ),
        ),
        (
            "03-seed-tools.png",
            ButtonListScreen(
                title="助记词工具",
                is_button_text_centered=False,
                button_data=[
                    ButtonOption("智能卡真随机创建助记词"),
                    ButtonOption("导入助记词"),
                    ButtonOption("BIP39 单词自检"),
                    ButtonOption("已加载助记词"),
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
    ]

    for filename, screen in specs:
        out_path = output_dir / filename
        _capture_static_screen(out_path, screen)
        generated_files.append(out_path)

    scan_path = output_dir / "05-scan-psbt.png"
    _capture_scan_screen(scan_path, runtime)
    generated_files.append(scan_path)

    qr_path = output_dir / "08-signed-qr.png"
    _capture_qr_screen(qr_path, runtime)
    generated_files.append(qr_path)

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
