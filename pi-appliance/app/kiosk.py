#!/usr/bin/env python3
import hashlib
import hmac
import logging
import os
import re
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

try:
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
except Exception:  # pragma: no cover
    AES = None
    get_random_bytes = None

try:
    from camera_scanner import CameraScanner
except Exception as error:  # pragma: no cover
    CameraScanner = None
    _CAMERA_IMPORT_ERROR = error
else:
    _CAMERA_IMPORT_ERROR = None
from controls import HardwareKeys, KeyEvent
from st7789 import ST7789Display
from tp_fragment import FragmentParseError, MultiFragmentAssembler, parse_tp_multi_fragment


APP_DIR = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get("OFFLINE_SIGNER_KIOSK_WORK_DIR", os.environ.get("TP_KIOSK_WORK_DIR", "/run/offline-signer-kiosk")))
WORK_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = WORK_DIR / "kiosk.log"

PI_SIGNER_BIN = Path(
    os.environ.get(
        "OFFLINE_SIGNER_BIN",
        os.environ.get("TP_PI_SIGNER_BIN", "/opt/offline-signer/bin/offline-signer"),
    )
)
DERIVATION_PATH = os.environ.get("TP_DERIVATION_PATH", "m/44'/60'/0'/0/0")
DEFAULT_READER_HINT = os.environ.get("TP_READER_HINT", "ACR39")
BOOT_UNLOCK_SHA256 = os.environ.get("TP_BOOT_UNLOCK_SHA256", "").strip().lower()

SCREEN_W = 240
SCREEN_H = 240
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BOOT_LOCK_FILENAME = "tp-lock.dat"
BOOT_LOCK_MAGIC = b"TPSL1"
BOOT_LOCK_KEY_CONTEXT = b"tp-signer-lock-v1"
BOOT_MOUNT_POINT = Path("/mnt/boot")

logger = logging.getLogger(__name__)


def normalize_hash(value: str) -> str:
    value = value.strip().lower()
    if SHA256_RE.fullmatch(value):
        return value
    return ""


class BootLockStore:
    def __init__(self, mount_point: Path = BOOT_MOUNT_POINT) -> None:
        self.mount_point = mount_point

    def load_hash(self, fallback_hash: str) -> Tuple[str, str]:
        key = self._derive_key()
        if key is None:
            return fallback_hash, "AES密钥不可用，使用内置开机密码"

        mount_path, mounted_here = self._resolve_boot_mount(read_only=True)
        if mount_path is None:
            return fallback_hash, "未检测到启动分区，使用内置开机密码"

        try:
            cfg = mount_path / BOOT_LOCK_FILENAME
            if not cfg.exists():
                return fallback_hash, ""
            blob = cfg.read_bytes()
            plain = self._decrypt_blob(key, blob)
            if plain is None:
                locked = hashlib.sha256((self._read_cpu_serial() + "::boot-lock").encode("utf-8")).hexdigest()
                return locked, "开机密码配置解密失败，已进入保护锁定"
            loaded = self._parse_hash_from_text(plain)
            if loaded:
                return loaded, ""
            locked = hashlib.sha256((self._read_cpu_serial() + "::boot-lock").encode("utf-8")).hexdigest()
            return locked, "开机密码配置内容无效，已进入保护锁定"
        except Exception as error:
            return fallback_hash, f"读取开机密码配置失败: {error}"
        finally:
            if mounted_here:
                self._safe_unmount(mount_path)

    def save_hash(self, new_hash: str) -> Tuple[bool, str]:
        if not normalize_hash(new_hash):
            return False, "新开机密码哈希格式错误"

        key = self._derive_key()
        if key is None:
            return False, "AES密钥不可用，无法保存开机密码"

        mount_path, mounted_here = self._resolve_boot_mount(read_only=False)
        if mount_path is None:
            return False, "未检测到可写启动分区，无法保存开机密码"

        try:
            payload = f"TP_BOOT_UNLOCK_SHA256={new_hash}\n".encode("utf-8")
            blob = self._encrypt_blob(key, payload)
            if blob is None:
                return False, "AES加密不可用，无法保存开机密码"
            cfg = mount_path / BOOT_LOCK_FILENAME
            tmp = mount_path / f"{BOOT_LOCK_FILENAME}.tmp"
            tmp.write_bytes(blob)
            os.replace(tmp, cfg)
            return True, "开机密码已保存"
        except Exception as error:
            return False, f"保存开机密码失败: {error}"
        finally:
            if mounted_here:
                self._safe_unmount(mount_path)

    def _parse_hash_from_text(self, text: bytes) -> str:
        try:
            content = text.decode("utf-8", errors="strict")
        except Exception:
            return ""
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "TP_BOOT_UNLOCK_SHA256":
                return normalize_hash(value.strip())
        return ""

    def _read_cpu_serial(self) -> str:
        try:
            data = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
        for line in data.splitlines():
            if line.lower().startswith("serial"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip().lower()
        return ""

    def _derive_key(self) -> Optional[bytes]:
        serial = self._read_cpu_serial()
        if not serial:
            return None
        return hashlib.sha256(BOOT_LOCK_KEY_CONTEXT + serial.encode("utf-8")).digest()

    def _encrypt_blob(self, key: bytes, plain: bytes) -> Optional[bytes]:
        if AES is None or get_random_bytes is None:
            return None
        nonce = get_random_bytes(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
        ciphertext, tag = cipher.encrypt_and_digest(plain)
        return BOOT_LOCK_MAGIC + nonce + tag + ciphertext

    def _decrypt_blob(self, key: bytes, blob: bytes) -> Optional[bytes]:
        if AES is None:
            return None
        if not blob.startswith(BOOT_LOCK_MAGIC):
            return None
        if len(blob) < len(BOOT_LOCK_MAGIC) + 12 + 16 + 1:
            return None
        offset = len(BOOT_LOCK_MAGIC)
        nonce = blob[offset : offset + 12]
        tag = blob[offset + 12 : offset + 28]
        ciphertext = blob[offset + 28 :]
        try:
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
            return cipher.decrypt_and_verify(ciphertext, tag)
        except Exception:
            return None

    def _resolve_boot_mount(self, read_only: bool) -> Tuple[Optional[Path], bool]:
        existing = self._find_existing_boot_mount()
        if existing is not None:
            return existing, False

        self.mount_point.mkdir(parents=True, exist_ok=True)
        options = "ro,noatime" if read_only else "rw,noatime"
        for dev in ("/dev/mmcblk0p1", "/dev/disk/by-label/TPSIGNEROS"):
            if not Path(dev).exists():
                continue
            cmd = ["mount", "-t", "vfat", "-o", options, dev, str(self.mount_point)]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc.returncode == 0:
                return self.mount_point, True
        return None, False

    def _find_existing_boot_mount(self) -> Optional[Path]:
        try:
            mounts = Path("/proc/mounts").read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return None
        for line in mounts:
            cols = line.split()
            if len(cols) < 3:
                continue
            dev, mountpoint, fstype = cols[0], cols[1], cols[2]
            if fstype != "vfat":
                continue
            if dev.endswith("mmcblk0p1") or "TPSIGNEROS" in dev.upper():
                return Path(mountpoint.replace("\\040", " "))
            if mountpoint in ("/boot", "/boot/firmware", "/mnt/boot"):
                return Path(mountpoint)
        return None

    def _safe_unmount(self, mount_path: Path) -> None:
        subprocess.run(["umount", str(mount_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class App:
    def __init__(self) -> None:
        self.running = True
        self.display = ST7789Display(width=SCREEN_W, height=SCREEN_H, rotation=0)
        self.keys = HardwareKeys()
        self.camera: Optional[Any] = None
        self.boot_store = BootLockStore()

        self.font = ImageFont.load_default()

        self.pin = ""
        self.path = DERIVATION_PATH
        self.address = ""
        self.status = "请先扫码交易二维码"
        self.error = ""
        loaded_hash, load_note = self.boot_store.load_hash(BOOT_UNLOCK_SHA256)
        self.boot_unlock_hash = normalize_hash(loaded_hash)
        self.boot_unlock_code = ""
        self.settings_cursor = 0
        self.change_step = ""
        self.change_input = ""
        self.change_new_plain = ""
        self.load_note = load_note

        self.state = "scan"
        self.last_frame = 0.0

        self.keypad = [
            ["1", "2", "3"],
            ["4", "5", "6"],
            ["7", "8", "9"],
            ["DEL", "0", "OK"],
        ]
        self.cursor = [0, 0]

        self.assembler = MultiFragmentAssembler()
        self.fragment_seen = set()
        self.pending_payload = ""
        self.scan_status = "对准 TP 二维码"
        self.response_qr: Optional[Image.Image] = None
        self.preview_image: Optional[Image.Image] = None
        self._pending_scan_start = False

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        if self.boot_unlock_hash:
            self.state = "boot_lock"
            self.status = "输入开机密码解锁"
            if self.load_note:
                self.error = self.load_note
        else:
            self.state = "busy"
            self.status = "系统启动中，正在准备扫码..."
            self._pending_scan_start = True

    def _on_signal(self, *_args) -> None:
        self.running = False

    def close(self) -> None:
        try:
            self._stop_camera()
        finally:
            self.keys.close()
            self.display.close()

    def run(self) -> None:
        try:
            while self.running:
                self._render()
                if self._pending_scan_start:
                    self._pending_scan_start = False
                    self._start_scan()
                events = self.keys.poll()
                self._handle_events(events)
                time.sleep(0.04)
        finally:
            self.close()

    def _handle_events(self, events: List[KeyEvent]) -> None:
        if self.state == "boot_lock":
            self._handle_boot_lock_events(events)
            return
        if self.state == "settings":
            self._handle_settings_events(events)
            return
        if self.state == "change_lock":
            self._handle_change_lock_events(events)
            return
        if self.state == "pin":
            self._handle_pin_events(events)
            return
        if self.state == "scan":
            self._handle_scan_events(events)
            return
        if self.state == "show_qr":
            self._handle_qr_events(events)
            return
        if self.state == "busy":
            return

    def _handle_boot_lock_events(self, events: List[KeyEvent]) -> None:
        for event in events:
            if event.name in ("up", "down", "left", "right"):
                self._move_cursor(event.name)
                continue

            if event.name in ("press", "key2"):
                self._activate_boot_unlock_cell()
                continue

            if event.name == "key1":
                self.boot_unlock_code = self.boot_unlock_code[:-1]
                continue

            if event.name == "key3":
                self._try_boot_unlock()

    def _handle_settings_events(self, events: List[KeyEvent]) -> None:
        for event in events:
            if event.name in ("up", "down"):
                if event.name == "up":
                    self.settings_cursor = max(0, self.settings_cursor - 1)
                else:
                    self.settings_cursor = min(1, self.settings_cursor + 1)
                continue
            if event.name in ("press", "key2", "key3"):
                if self.settings_cursor == 0:
                    self._begin_change_lock()
                else:
                    self._start_scan()
                return

    def _handle_change_lock_events(self, events: List[KeyEvent]) -> None:
        for event in events:
            if event.name in ("up", "down", "left", "right"):
                self._move_cursor(event.name)
                continue

            if event.name in ("press", "key2"):
                self._activate_change_lock_cell()
                continue

            if event.name == "key1":
                self.change_input = self.change_input[:-1]
                continue

            if event.name == "key3":
                self._submit_change_lock()

    def _handle_pin_events(self, events: List[KeyEvent]) -> None:
        for event in events:
            if event.name in ("up", "down", "left", "right"):
                self._move_cursor(event.name)
                continue

            if event.name in ("press", "key2"):
                self._activate_keypad_cell()
                continue

            if event.name == "key1":
                self.pin = self.pin[:-1]

            if event.name == "key3":
                self._try_sign_with_card()

    def _handle_scan_events(self, events: List[KeyEvent]) -> None:
        for event in events:
            if event.name == "key1":
                self._enter_settings()
                return
            if event.name == "key3":
                self.pending_payload = ""
                self.error = ""
                self.scan_status = "已清空，重新扫码"
                self.assembler.reset()
                self.fragment_seen.clear()
                return
            if event.name == "key2":
                self._start_scan()
                return

        now = time.monotonic()
        if now - self.last_frame < 0.16:
            return
        self.last_frame = now

        if self.camera is None:
            return

        try:
            preview, values = self.camera.capture()
        except Exception as error:
            logger.exception("camera capture failed")
            self.error = f"相机采集失败: {error}"
            self._stop_camera()
            self.state = "scan"
            self.scan_status = "相机异常，按 KEY2 重试"
            return

        self.preview_image = preview
        for value in values:
            text = value.strip()
            if not text:
                continue
            if text in self.fragment_seen:
                continue
            self.fragment_seen.add(text)

            if text.lower().startswith("tp:multifragment-"):
                try:
                    fragment = parse_tp_multi_fragment(text)
                except FragmentParseError as error:
                    self.error = str(error)
                    continue

                state, detail = self.assembler.accept(fragment)
                if state == "progress":
                    self.scan_status = detail or "分片接收中"
                elif state == "error":
                    self.error = detail or "分片处理失败"
                elif state == "complete":
                    self._on_payload_scanned(detail or "")
                    return
                continue

            self._on_payload_scanned(text)
            return

    def _handle_qr_events(self, events: List[KeyEvent]) -> None:
        for event in events:
            if event.name in ("key3", "press", "key2"):
                self.response_qr = None
                self.error = ""
                self.status = "请先扫码交易二维码"
                self._start_scan()

    def _move_cursor(self, direction: str) -> None:
        row, col = self.cursor
        if direction == "up":
            row = max(0, row - 1)
        elif direction == "down":
            row = min(len(self.keypad) - 1, row + 1)
        elif direction == "left":
            col = max(0, col - 1)
        elif direction == "right":
            col = min(len(self.keypad[0]) - 1, col + 1)
        self.cursor = [row, col]

    def _enter_settings(self) -> None:
        self._stop_camera()
        self.settings_cursor = 0
        self.error = ""
        self.state = "settings"

    def _begin_change_lock(self) -> None:
        self.change_input = ""
        self.change_new_plain = ""
        self.cursor = [0, 0]
        self.error = ""
        if self.boot_unlock_hash:
            self.change_step = "verify"
            self.status = "输入当前开机密码"
        else:
            self.change_step = "new"
            self.status = "设置新的开机密码"
        self.state = "change_lock"

    def _activate_keypad_cell(self) -> None:
        label = self.keypad[self.cursor[0]][self.cursor[1]]
        if label == "DEL":
            self.pin = self.pin[:-1]
            return
        if label == "OK":
            self._try_sign_with_card()
            return
        if label.isdigit() and len(self.pin) < 16:
            self.pin += label

    def _activate_change_lock_cell(self) -> None:
        label = self.keypad[self.cursor[0]][self.cursor[1]]
        if label == "DEL":
            self.change_input = self.change_input[:-1]
            return
        if label == "OK":
            self._submit_change_lock()
            return
        if label.isdigit() and len(self.change_input) < 16:
            self.change_input += label

    def _submit_change_lock(self) -> None:
        if self.change_step == "verify":
            if len(self.change_input) < 4:
                self.error = "当前密码至少 4 位"
                return
            digest = hashlib.sha256(self.change_input.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(digest, self.boot_unlock_hash):
                self.change_input = ""
                self.error = "当前密码错误"
                return
            self.change_input = ""
            self.change_step = "new"
            self.status = "输入新的开机密码"
            self.error = ""
            return

        if self.change_step == "new":
            if len(self.change_input) < 4:
                self.error = "新密码至少 4 位"
                return
            self.change_new_plain = self.change_input
            self.change_input = ""
            self.change_step = "confirm"
            self.status = "再次输入新密码确认"
            self.error = ""
            return

        if self.change_step == "confirm":
            if self.change_input != self.change_new_plain:
                self.change_input = ""
                self.change_new_plain = ""
                self.change_step = "new"
                self.status = "两次不一致，请重输新密码"
                self.error = "两次输入不一致"
                return
            new_hash = hashlib.sha256(self.change_input.encode("utf-8")).hexdigest()
            ok, message = self.boot_store.save_hash(new_hash)
            if not ok:
                self.error = message
                return
            self.boot_unlock_hash = new_hash
            self.change_input = ""
            self.change_new_plain = ""
            self.change_step = ""
            self.error = ""
            self.status = message
            self.scan_status = "开机密码已更新，继续扫码"
            self._start_scan()

    def _activate_boot_unlock_cell(self) -> None:
        label = self.keypad[self.cursor[0]][self.cursor[1]]
        if label == "DEL":
            self.boot_unlock_code = self.boot_unlock_code[:-1]
            return
        if label == "OK":
            self._try_boot_unlock()
            return
        if label.isdigit() and len(self.boot_unlock_code) < 16:
            self.boot_unlock_code += label

    def _try_boot_unlock(self) -> None:
        if not self.boot_unlock_hash:
            self._start_scan()
            return
        if len(self.boot_unlock_code) < 4:
            self.error = "密码至少 4 位"
            return

        digest = hashlib.sha256(self.boot_unlock_code.encode("utf-8")).hexdigest()
        if hmac.compare_digest(digest, self.boot_unlock_hash):
            self.boot_unlock_code = ""
            self.error = ""
            self.status = "系统已解锁"
            self.cursor = [0, 0]
            self._start_scan()
            return

        self.boot_unlock_code = ""
        self.error = "开机密码错误"

    def _try_sign_with_card(self) -> None:
        payload = self.pending_payload.strip()
        if not payload:
            self.error = "还没有扫码交易"
            self.status = "请先扫码 TP 二维码"
            self._start_scan()
            return

        if len(self.pin) < 4:
            self.error = "PIN 至少 4 位"
            return

        self.state = "busy"
        self.status = "请插卡，检测到后自动解锁并签名..."
        self.error = ""
        self._render()

        req_file = WORK_DIR / "request.txt"
        out_file = WORK_DIR / "response.txt"
        qr_file = WORK_DIR / "response.png"
        req_file.write_text(payload + "\n", encoding="utf-8")

        cmd = [
            str(PI_SIGNER_BIN),
            "sign",
            "--pin",
            self.pin,
            "--path",
            self.path,
            "--payload-file",
            str(req_file),
            "--out",
            str(out_file),
            "--qr",
            str(qr_file),
            "--timeout-sec",
            "120",
        ]
        if DEFAULT_READER_HINT:
            cmd += ["--reader", DEFAULT_READER_HINT]

        rc, out, err = run_cmd(cmd, timeout=150)
        if rc != 0:
            self.state = "pin"
            self.error = extract_error(out, err, "签名失败")
            self.status = "可直接重试，插卡后会自动签名"
            return

        if not qr_file.exists():
            self.state = "pin"
            self.error = "签名成功但未生成二维码文件"
            self.status = "按 OK 或 KEY3 重试"
            return

        address = parse_signer_address(out)
        if address:
            self.address = address

        self.response_qr = Image.open(qr_file).convert("RGB")
        self.state = "show_qr"
        self.status = "TP 扫描此二维码"
        self.error = ""
        self.pin = ""

    def _start_scan(self) -> None:
        self.pending_payload = ""
        self.scan_status = "正在启动相机..."
        self.error = ""
        self.pin = ""
        self.preview_image = None
        self.assembler.reset()
        self.fragment_seen.clear()

        if CameraScanner is None:
            self.error = f"相机模块加载失败: {_CAMERA_IMPORT_ERROR}"
            self.state = "scan"
            self.scan_status = "相机不可用，按 KEY2 重试"
            return

        if self.camera is None:
            self.camera = CameraScanner(preview_size=(640, 480), rotate=0)
            try:
                self.camera.start()
            except Exception as error:
                logger.exception("camera start failed")
                self.camera = None
                self.error = f"相机启动失败: {error}"
                self.state = "scan"
                self.scan_status = "相机不可用，按 KEY2 重试"
                return

        self.state = "scan"
        self.scan_status = "对准 TP 二维码"
        self.last_frame = 0.0

    def _stop_camera(self) -> None:
        if self.camera is not None:
            try:
                self.camera.stop()
            finally:
                self.camera = None
        self.preview_image = None

    def _on_payload_scanned(self, payload: str) -> None:
        payload = payload.strip()
        if not payload:
            self.error = "扫码内容为空"
            self._start_scan()
            return

        self.pending_payload = payload
        self._stop_camera()
        self.state = "pin"
        self.cursor = [0, 0]
        self.pin = ""
        self.status = "扫码完成，输入 PIN 后按 OK"
        self.error = ""

    def _render(self) -> None:
        if self.state == "scan":
            if self.preview_image is None:
                img = self._base_canvas("扫码")
                self._draw_text_block(img, self.scan_status, y=40)
                if self.error:
                    self._draw_error(img, self.error)
                self.display.show_image(img)
            else:
                self._render_scan_preview(self.preview_image)
            return

        if self.state == "boot_lock":
            img = self._base_canvas("系统锁定")
            self._draw_boot_lock_screen(img)
            self.display.show_image(img)
            return

        if self.state == "settings":
            img = self._base_canvas("设置")
            self._draw_settings_screen(img)
            self.display.show_image(img)
            return

        if self.state == "change_lock":
            img = self._base_canvas("修改开机密码")
            self._draw_change_lock_screen(img)
            self.display.show_image(img)
            return

        if self.state == "pin":
            img = self._base_canvas("输入 PIN")
            self._draw_pin_screen(img)
            self.display.show_image(img)
            return

        if self.state == "busy":
            img = self._base_canvas("处理中")
            self._draw_text_block(img, self.status, y=88)
            if self.error:
                self._draw_error(img, self.error)
            self.display.show_image(img)
            return

        if self.state == "show_qr":
            img = self._base_canvas("签名二维码")
            self._draw_qr_screen(img)
            self.display.show_image(img)

    def _render_scan_preview(self, preview: Image.Image) -> None:
        img = self._base_canvas("扫码中")
        preview = preview.resize((220, 160), Image.Resampling.BILINEAR)
        img.paste(preview, (10, 24))
        self._draw_text_line(img, self.scan_status, 10, 190)
        if self.error:
            self._draw_error(img, self.error)
        else:
            self._draw_text_line(img, "KEY1 设置 KEY2重扫 KEY3清空", 10, 210)
        self.display.show_image(img)

    def _base_canvas(self, title: str) -> Image.Image:
        img = Image.new("RGB", (SCREEN_W, SCREEN_H), (245, 247, 250))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, SCREEN_W, 20), fill=(21, 101, 192))
        draw.text((6, 5), title, fill=(255, 255, 255), font=self.font)
        return img

    def _draw_boot_lock_screen(self, img: Image.Image) -> None:
        draw = ImageDraw.Draw(img)
        masked = "*" * len(self.boot_unlock_code)
        draw.text((8, 28), f"密码: {masked}", fill=(0, 0, 0), font=self.font)
        draw.text((8, 44), "输入开机密码后进入系统", fill=(60, 60, 60), font=self.font)
        self._draw_numeric_keypad(draw)
        draw.text((8, 222), "KEY3 或 OK 提交", fill=(80, 80, 80), font=self.font)
        if self.error:
            self._draw_error(img, self.error)

    def _draw_settings_screen(self, img: Image.Image) -> None:
        draw = ImageDraw.Draw(img)
        options = ["修改开机密码", "返回扫码"]
        draw.text((8, 30), "KEY1 从扫码页进入设置", fill=(60, 60, 60), font=self.font)
        for idx, label in enumerate(options):
            y0 = 66 + idx * 44
            y1 = y0 + 34
            selected = idx == self.settings_cursor
            fill = (255, 241, 118) if selected else (255, 255, 255)
            draw.rectangle((12, y0, 228, y1), outline=(50, 50, 50), fill=fill, width=2)
            draw.text((20, y0 + 10), label, fill=(0, 0, 0), font=self.font)
        draw.text((8, 222), "上下选择，OK确认", fill=(80, 80, 80), font=self.font)
        if self.error:
            self._draw_error(img, self.error)

    def _draw_change_lock_screen(self, img: Image.Image) -> None:
        draw = ImageDraw.Draw(img)
        masked = "*" * len(self.change_input)
        draw.text((8, 28), f"密码: {masked}", fill=(0, 0, 0), font=self.font)
        tip = "输入密码"
        if self.change_step == "verify":
            tip = "输入当前密码"
        elif self.change_step == "new":
            tip = "输入新密码"
        elif self.change_step == "confirm":
            tip = "再次输入新密码"
        draw.text((8, 44), tip, fill=(60, 60, 60), font=self.font)
        self._draw_numeric_keypad(draw)
        draw.text((8, 222), "KEY3 或 OK 提交", fill=(80, 80, 80), font=self.font)
        if self.error:
            self._draw_error(img, self.error)

    def _draw_pin_screen(self, img: Image.Image) -> None:
        draw = ImageDraw.Draw(img)
        masked = "*" * len(self.pin)
        draw.text((8, 28), f"PIN: {masked}", fill=(0, 0, 0), font=self.font)
        draw.text((8, 44), "已扫码, 输入PIN后按OK", fill=(60, 60, 60), font=self.font)
        self._draw_numeric_keypad(draw)
        draw.text((8, 222), "KEY3 也可直接提交", fill=(80, 80, 80), font=self.font)

        if self.status:
            self._draw_text_line(img, self.status, 8, 206)
        if self.error:
            self._draw_error(img, self.error)

    def _draw_numeric_keypad(self, draw: ImageDraw.ImageDraw) -> None:
        cell_w = 66
        cell_h = 34
        start_x = 14
        start_y = 66

        for r, row in enumerate(self.keypad):
            for c, label in enumerate(row):
                x0 = start_x + c * (cell_w + 7)
                y0 = start_y + r * (cell_h + 7)
                x1 = x0 + cell_w
                y1 = y0 + cell_h

                selected = (r == self.cursor[0] and c == self.cursor[1])
                fill = (255, 241, 118) if selected else (255, 255, 255)
                draw.rectangle((x0, y0, x1, y1), outline=(50, 50, 50), fill=fill, width=2)

                tw, th = draw.textbbox((0, 0), label, font=self.font)[2:]
                draw.text((x0 + (cell_w - tw) / 2, y0 + (cell_h - th) / 2), label, fill=(0, 0, 0), font=self.font)

    def _draw_qr_screen(self, img: Image.Image) -> None:
        draw = ImageDraw.Draw(img)
        if self.response_qr is not None:
            qr = self.response_qr.resize((198, 198), Image.Resampling.NEAREST)
            img.paste(qr, (21, 24))

        draw.rectangle((0, 224, SCREEN_W, SCREEN_H), fill=(236, 239, 241))
        draw.text((8, 228), "KEY3 返回 / KEY2 重扫", fill=(0, 0, 0), font=self.font)
        if self.error:
            self._draw_error(img, self.error)

    def _draw_text_block(self, img: Image.Image, text: str, y: int) -> None:
        draw = ImageDraw.Draw(img)
        self._draw_wrapped(draw, text, x=8, y=y, width=224, line_h=14, fill=(0, 0, 0))

    def _draw_text_line(self, img: Image.Image, text: str, x: int, y: int) -> None:
        draw = ImageDraw.Draw(img)
        draw.text((x, y), text[:36], fill=(0, 0, 0), font=self.font)

    def _draw_error(self, img: Image.Image, text: str) -> None:
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 206, SCREEN_W, SCREEN_H), fill=(255, 235, 238))
        self._draw_wrapped(draw, f"错误: {text}", x=8, y=209, width=224, line_h=12, fill=(183, 28, 28))

    def _draw_wrapped(self, draw: ImageDraw.ImageDraw, text: str, x: int, y: int, width: int, line_h: int, fill: Tuple[int, int, int]) -> None:
        words = text.split()
        if not words:
            return
        line = ""
        y_pos = y
        for word in words:
            candidate = f"{line} {word}".strip()
            box = draw.textbbox((0, 0), candidate, font=self.font)
            if box[2] - box[0] <= width:
                line = candidate
                continue

            if line:
                draw.text((x, y_pos), line, fill=fill, font=self.font)
                y_pos += line_h
            line = word

        if line:
            draw.text((x, y_pos), line, fill=fill, font=self.font)


def run_cmd(cmd: List[str], timeout: int) -> Tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        text=True,
        encoding="utf-8",
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def parse_signer_address(stdout: str) -> str:
    for line in stdout.splitlines():
        m = re.search(r"(?:签名地址|地址):\s*(0x[0-9a-fA-F]{40})", line)
        if m:
            return m.group(1).lower()
    return ""


def extract_error(stdout: str, stderr: str, fallback: str) -> str:
    lines = []
    if stderr:
        lines.extend(stderr.splitlines())
    if stdout:
        lines.extend(stdout.splitlines())
    for line in reversed(lines):
        text = line.strip()
        if text:
            return text[:120]
    return fallback


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stderr)],
    )

    if not PI_SIGNER_BIN.exists():
        print(f"离线签名器可执行文件不存在: {PI_SIGNER_BIN}", file=sys.stderr)
        return 1

    try:
        app = App()
        app.run()
        return 0
    except Exception:
        logger.exception("kiosk fatal error")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
