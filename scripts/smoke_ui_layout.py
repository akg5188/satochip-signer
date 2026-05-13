#!/usr/bin/env python3
"""Lightweight 240x240 UI layout checks for dense mnemonic/passphrase screens."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from threading import RLock

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = ROOT / "seedsigner-os" / "opt" / "rootfs-overlay" / "opt" / "src"
VENDOR = ROOT / "pi-signer-py" / "vendor"


def add_python_paths(extra_root: Path | None = None) -> None:
    sys.path.insert(0, str(REPO_SRC))
    if VENDOR.is_dir():
        sys.path.insert(0, str(VENDOR))

    candidates = [
        extra_root,
        ROOT / ".venv-desktop-smoke",
        ROOT / ".venv-smoke",
        ROOT / ".venv",
    ]
    for root in candidates:
        if root is None or not root.exists():
            continue
        for site_packages in root.glob("lib/python*/site-packages"):
            sys.path.insert(0, str(site_packages))


class FakeInputs:
    def wait_for(self, *args, **kwargs):
        return None


class FakeDisplay:
    def show_image(self, image, x_start=0, y_start=0):
        return None


class FakeRenderer:
    canvas_width = 240
    canvas_height = 240
    display_type = "st7789"

    def __init__(self):
        self.canvas = Image.new("RGB", (240, 240), "black")
        self.draw = ImageDraw.Draw(self.canvas)
        self.disp = FakeDisplay()
        self.lock = RLock()

    def show_image(self, image=None, *args, **kwargs):
        if image:
            self.canvas.paste(image)


def configure_runtime():
    from seedsigner.gui.renderer import Renderer
    from seedsigner.hardware.buttons import HardwareButtons
    from seedsigner.models.settings import Settings
    from seedsigner.models.settings_definition import SettingsConstants

    class FakeSettings:
        def __init__(self):
            self._data = {
                SettingsConstants.SETTING__LOCALE: SettingsConstants.LOCALE__CHINESE_SIMPLIFIED,
                SettingsConstants.SETTING__DISPLAY_CONFIGURATION: SettingsConstants.DISPLAY_CONFIGURATION__ST7789__240x240,
                SettingsConstants.SETTING__DISPLAY_COLOR_INVERTED: SettingsConstants.OPTION__DISABLED,
                SettingsConstants.SETTING__NETWORK: SettingsConstants.MAINNET,
                SettingsConstants.SETTING__BTC_DENOMINATION: SettingsConstants.BTC_DENOMINATION__THRESHOLD,
            }

        def get_value(self, key, default=None, default_if_none=False):
            value = self._data.get(key, default)
            if value is None and default_if_none:
                return default
            return value

    Settings._instance = FakeSettings()
    Renderer._instance = FakeRenderer()
    HardwareButtons._instance = FakeInputs()


def capture_screen(output_dir: Path, name: str, screen) -> None:
    from seedsigner.gui.renderer import Renderer

    renderer = Renderer.get_instance()
    renderer.canvas.paste("black", (0, 0, renderer.canvas_width, renderer.canvas_height))
    screen._render()
    renderer.canvas.save(output_dir / name)


def assert_no_vertical_overlap(label: str, top: int, bottom: int, next_top: int) -> None:
    if top < 0 or bottom < top:
        raise AssertionError(f"{label}: invalid bounds {top}-{bottom}")
    if bottom > next_top - 2:
        raise AssertionError(f"{label}: {top}-{bottom} overlaps next element at {next_top}")


def run(output_dir: Path) -> None:
    from seedsigner.gui.screens.screen import ButtonListScreen, ButtonOption, WarningScreen
    from seedsigner.gui.screens import seed_screens

    output_dir.mkdir(parents=True, exist_ok=True)

    finalize = seed_screens.SeedFinalizeScreen(
        fingerprint="fb1be1f9",
        button_data=[
            ButtonOption("完成"),
            ButtonOption("查看 BIP39 序号"),
            ButtonOption("输入密码短语"),
            ButtonOption("扫描密码短语"),
            ButtonOption("加载密码短语"),
        ],
    )
    capture_screen(output_dir, "seed-finalize-passphrase.png", finalize)

    review = seed_screens.SeedReviewPassphraseScreen(
        fingerprint_without="fb1be1f9",
        fingerprint_with="8a2c6e0d",
        passphrase="secret phrase demo",
        button_data=[ButtonOption("完成"), ButtonOption("重新输入")],
    )
    capture_screen(output_dir, "seed-review-passphrase.png", review)

    capture_screen(
        output_dir,
        "seed-add-passphrase.png",
        seed_screens.SeedAddPassphraseScreen(title="BIP39 密码短语", passphrase="secret phrase"),
    )
    capture_screen(
        output_dir,
        "loaded-seed-options.png",
        ButtonListScreen(
            title="助记词 fb1be1f9",
            is_button_text_centered=False,
            button_data=[
                ButtonOption("查看助记词"),
                ButtonOption("按路径算地址"),
                ButtonOption("设置密码短语"),
                ButtonOption("查看原始熵"),
                ButtonOption("二次加密"),
                ButtonOption("二次还原"),
                ButtonOption("钢板数字"),
                ButtonOption("写入到智能卡"),
                ButtonOption("删除助记词"),
            ],
        ),
    )
    capture_screen(
        output_dir,
        "clear-passphrase-warning.png",
        WarningScreen(
            title="清除密码短语？",
            status_headline=None,
            status_icon_size=42,
            text="清除后会恢复为无 BIP39 密码短语的钱包。\n恢复时只需要助记词。",
            show_back_button=True,
            button_data=[ButtonOption("保留密码短语"), ButtonOption("确认清除")],
        ),
    )

    finalize_fp_top = finalize.fingerprint_icontl.screen_y
    finalize_fp_bottom = finalize_fp_top + finalize.fingerprint_icontl.height
    if finalize_fp_top < finalize.top_nav.height:
        raise AssertionError("seed finalize fingerprint starts inside top nav")
    assert_no_vertical_overlap(
        "seed finalize fingerprint",
        finalize_fp_top,
        finalize_fp_bottom,
        finalize.buttons[0].screen_y,
    )
    if finalize.num_display_buttons != 3 or not finalize.has_scroll_arrows:
        raise AssertionError("seed finalize dense menu should show 3 visible rows with scroll arrows")

    review_fingerprint = review.components[1]
    assert_no_vertical_overlap(
        "passphrase review fingerprint",
        review_fingerprint.screen_y,
        review_fingerprint.screen_y + review_fingerprint.height,
        review.buttons[0].screen_y,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("venv", nargs="?", type=Path, help="Optional desktop smoke venv root")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "logs" / "ui-layout-check",
        help="Directory for rendered check images.",
    )
    args = parser.parse_args()

    add_python_paths(args.venv)
    configure_runtime()
    run(args.output_dir)
    print(f"ui_layout_ok: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
