#!/usr/bin/env python3
import hashlib
import os
import shutil
import sys
import types
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = ROOT / "seedsigner-os/opt/rootfs-overlay/opt/src"
VENDOR = ROOT / "pi-signer-py/vendor"
sys.path.insert(0, str(REPO_SRC))
sys.path.insert(0, str(VENDOR))

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


def add_optional_site_packages() -> None:
    candidates: list[Path] = []

    env_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    if env_path is not None:
        candidates.append(env_path)

    candidates.extend(
        [
            ROOT / ".venv-desktop-smoke",
            Path("/tmp/satochip-desktop-smoke-venv"),
            ROOT / ".venv",
            ROOT / ".venv-smoke",
            Path("/tmp/satochip-smoketest-venv"),
        ]
    )

    for base in candidates:
        if not base.exists():
            continue
        for site_packages in base.glob("lib/python*/site-packages"):
            sys.path.insert(0, str(site_packages))


def install_import_stubs() -> None:
    smartcard = types.ModuleType("smartcard")
    smartcard.__path__ = []
    smartcard.CardType = types.ModuleType("smartcard.CardType")
    smartcard.CardType.AnyCardType = object
    smartcard.CardRequest = types.ModuleType("smartcard.CardRequest")
    smartcard.CardRequest.CardRequest = object
    smartcard.CardConnectionObserver = types.ModuleType("smartcard.CardConnectionObserver")
    smartcard.CardConnectionObserver.CardConnectionObserver = object
    smartcard.CardMonitoring = types.ModuleType("smartcard.CardMonitoring")
    smartcard.CardMonitoring.CardMonitor = object
    smartcard.CardMonitoring.CardObserver = object
    smartcard.Exceptions = types.ModuleType("smartcard.Exceptions")
    smartcard.Exceptions.CardConnectionException = Exception
    smartcard.Exceptions.NoCardException = Exception
    smartcard.Exceptions.CardRequestTimeoutException = Exception
    smartcard.System = types.ModuleType("smartcard.System")
    smartcard.System.readers = lambda: []
    smartcard.util = types.ModuleType("smartcard.util")
    smartcard.util.toHexString = lambda data: ""
    smartcard.util.toBytes = lambda data: []
    smartcard.sw = types.ModuleType("smartcard.sw")
    smartcard.sw.__path__ = []
    smartcard.sw.SWExceptions = types.ModuleType("smartcard.sw.SWExceptions")
    smartcard.sw.SWExceptions.SWException = Exception

    for name, module in {
        "smartcard": smartcard,
        "smartcard.CardType": smartcard.CardType,
        "smartcard.CardRequest": smartcard.CardRequest,
        "smartcard.CardConnectionObserver": smartcard.CardConnectionObserver,
        "smartcard.CardMonitoring": smartcard.CardMonitoring,
        "smartcard.Exceptions": smartcard.Exceptions,
        "smartcard.System": smartcard.System,
        "smartcard.util": smartcard.util,
        "smartcard.sw": smartcard.sw,
        "smartcard.sw.SWExceptions": smartcard.sw.SWExceptions,
    }.items():
        sys.modules[name] = module

    pyzbar_pkg = types.ModuleType("pyzbar")
    pyzbar_mod = types.ModuleType("pyzbar.pyzbar")
    pyzbar_mod.decode = lambda *args, **kwargs: []

    class _FakeZBarSymbol:
        QRCODE = "QRCODE"

    pyzbar_mod.ZBarSymbol = _FakeZBarSymbol
    pyzbar_pkg.pyzbar = pyzbar_mod
    sys.modules["pyzbar"] = pyzbar_pkg
    sys.modules["pyzbar.pyzbar"] = pyzbar_mod


def _reset_singletons() -> None:
    from seedsigner.models.settings import Settings
    from seedsigner.gui.renderer import Renderer
    from seedsigner.hardware.buttons import HardwareButtons
    from seedsigner.hardware.camera import Camera

    Settings._instance = None
    Renderer._instance = None
    HardwareButtons._instance = None
    Camera._instance = None


def _test_renderer_desktop_modes():
    import pygame

    from seedsigner.gui.renderer import Renderer
    import seedsigner.models.settings as settings_mod
    from seedsigner.models.settings_definition import SettingsConstants

    class _FakeSettings:
        def __init__(self, display_config: str):
            self.display_config = display_config

        def get_value(self, key, default_if_none=False):
            if key == SettingsConstants.SETTING__DISPLAY_CONFIGURATION:
                return self.display_config
            if key == SettingsConstants.SETTING__DISPLAY_COLOR_INVERTED:
                return SettingsConstants.OPTION__DISABLED
            raise AssertionError(f"unexpected settings lookup: {key}")

    original_settings_get_instance = settings_mod.Settings.get_instance
    try:
        for display_config, expected_size in (
            (SettingsConstants.DISPLAY_CONFIGURATION__DESKTOP__240x240, (240, 240)),
            (SettingsConstants.DISPLAY_CONFIGURATION__DESKTOP__320x240, (320, 240)),
        ):
            _reset_singletons()
            settings_mod.Settings.get_instance = classmethod(lambda cls, cfg=display_config: _FakeSettings(cfg))
            Renderer.configure_instance()
            renderer = Renderer.get_instance()
            assert (renderer.canvas_width, renderer.canvas_height) == expected_size
            renderer.show_image(Image.new("RGB", expected_size, "white"))
            renderer.display_blank_screen()
            close_fn = getattr(renderer.disp, "close", None)
            if callable(close_fn):
                close_fn()
            Renderer._instance = None
    finally:
        settings_mod.Settings.get_instance = original_settings_get_instance
        pygame.display.quit()
        pygame.quit()


def _test_desktop_buttons():
    import pygame

    import seedsigner.hardware.buttons as buttons_mod
    from seedsigner.hardware.buttons import HardwareButtons, HardwareButtonsConstants
    import seedsigner.controller as controller_mod

    class _FakeController:
        screensaver_activation_ms = 60_000
        is_screensaver_running = False

        def start_screensaver(self):
            raise AssertionError("desktop button smoke should not trigger screensaver")

    original_get_instance = controller_mod.Controller.get_instance
    original_using_gpio = buttons_mod.USING_GPIO
    original_pygame = getattr(buttons_mod, "pygame", None)
    try:
        _reset_singletons()
        buttons_mod.USING_GPIO = False
        buttons_mod.pygame = pygame
        controller_mod.Controller.get_instance = classmethod(lambda cls: _FakeController())
        buttons = HardwareButtons.get_instance()

        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
        assert buttons.wait_for([HardwareButtons.KEY_RIGHT_PIN]) == HardwareButtons.KEY_RIGHT_PIN
        pygame.event.post(pygame.event.Event(pygame.KEYUP, key=pygame.K_RIGHT))

        key1_rect = buttons.button_rects[HardwareButtons.KEY1_PIN]
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=key1_rect.center))
        assert buttons.wait_for([HardwareButtons.KEY1_PIN]) == HardwareButtons.KEY1_PIN
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=key1_rect.center))

        HardwareButtonsConstants.release_lock = True
    finally:
        controller_mod.Controller.get_instance = original_get_instance
        buttons_mod.USING_GPIO = original_using_gpio
        buttons_mod.pygame = original_pygame
        HardwareButtons._instance = None
        pygame.display.quit()
        pygame.quit()


def _test_desktop_camera():
    from PIL import Image as PILImage

    import seedsigner.models.settings as settings_mod
    import seedsigner.hardware.pivideostream as pivideostream_mod
    from seedsigner.hardware.camera import Camera
    from seedsigner.models.settings_definition import SettingsConstants

    class _FakeSettings:
        def get_value(self, key, default_if_none=False):
            if key == SettingsConstants.SETTING__CAMERA_ROTATION:
                return 0
            if key == SettingsConstants.SETTING__CAMERA_DEVICE:
                return 0
            raise AssertionError(f"unexpected settings lookup: {key}")

    class _FakeVideoStream:
        def __init__(self, *args, **kwargs):
            self.started = False

        def start(self):
            self.started = True

        def read(self, preview=False, display=False):
            return PILImage.new("RGB", (320, 240), "white")

        def stop(self):
            self.started = False

    original_settings_get_instance = settings_mod.Settings.get_instance
    original_video_stream = pivideostream_mod.VideoStream
    try:
        _reset_singletons()
        settings_mod.Settings.get_instance = classmethod(lambda cls: _FakeSettings())
        pivideostream_mod.VideoStream = _FakeVideoStream
        camera = Camera.get_instance()
        camera.start_video_stream_mode(resolution=(320, 240), framerate=12)
        frame = camera.read_video_stream(as_image=True, preview=True)
        assert isinstance(frame, PILImage.Image)
        assert frame.size == (320, 240)
        assert frame.mode == "RGB"
        camera.stop_video_stream_mode()
    finally:
        settings_mod.Settings.get_instance = original_settings_get_instance
        pivideostream_mod.VideoStream = original_video_stream
        Camera._instance = None


def _test_desktop_microsd():
    from seedsigner.hardware.microsd import MicroSD

    microsd_dir = MicroSD.get_microsd_dir()
    assert MicroSD.is_desktop_mode() is True
    assert microsd_dir.name == "microsd"
    assert microsd_dir.is_dir()


def _test_main_startup_routes():
    import main as app_main

    class _FakeController:
        def __init__(self):
            self.calls = []

        def start(self, **kwargs):
            self.calls.append(kwargs)

    fake_controller = _FakeController()
    original_get_instance = app_main.Controller.get_instance
    original_tp_only_mode = os.environ.get("TP_ONLY_MODE")
    original_offline_signer_mode = os.environ.get("OFFLINE_SIGNER_MODE")
    try:
        app_main.Controller.get_instance = classmethod(lambda cls: fake_controller)

        app_main.main([])
        default_call = fake_controller.calls[-1]
        assert default_call["initial_destination"].View_cls.__name__ == "ToolsTpUiLockView"
        assert default_call["skip_startup_interstitials"] is True
        assert os.environ.get("OFFLINE_SIGNER_MODE") == "1"
        assert os.environ.get("TP_ONLY_MODE") == "1"

        app_main.main(["--iotest"])
        iotest_call = fake_controller.calls[-1]
        assert iotest_call["initial_destination"].View_cls.__name__ == "IOTestView"
        assert iotest_call["skip_startup_interstitials"] is True
    finally:
        app_main.Controller.get_instance = original_get_instance
        if original_tp_only_mode is None:
            os.environ.pop("TP_ONLY_MODE", None)
        else:
            os.environ["TP_ONLY_MODE"] = original_tp_only_mode
        if original_offline_signer_mode is None:
            os.environ.pop("OFFLINE_SIGNER_MODE", None)
        else:
            os.environ["OFFLINE_SIGNER_MODE"] = original_offline_signer_mode


def _decode_qr_image(image: Image.Image) -> str:
    from seedsigner.models.decode_qr import DecodeQR, DecodeQRStatus

    extracted = DecodeQR.extract_qr_data(image, is_binary=False)
    if isinstance(extracted, bytes):
        return extracted.decode("utf-8")
    if extracted:
        return str(extracted)

    import cv2
    import numpy as np

    detector = cv2.QRCodeDetector()
    for scale in (1, 2, 3):
        candidate = image
        if scale != 1:
            candidate = image.resize(
                (image.width * scale, image.height * scale),
                Image.Resampling.NEAREST,
            )
        data, _points, _ = detector.detectAndDecode(
            np.array(candidate.convert("RGB"))
        )
        if data:
            return data

    raise AssertionError("OpenCV failed to decode QR image")


def _build_sample_psbt(input_count: int, output_count: int) -> "PSBT":
    from embit.psbt import PSBT
    from embit.script import Script
    from embit.transaction import Transaction, TransactionInput, TransactionOutput

    vin = []
    for index in range(input_count):
        txid = hashlib.sha256(f"desktop-smoke-input-{index}".encode("utf-8")).digest()
        vin.append(TransactionInput(txid, index))

    vout = []
    for index in range(output_count):
        keyhash = hashlib.sha256(f"desktop-smoke-output-{index}".encode("utf-8")).digest()[:20]
        vout.append(
            TransactionOutput(
                1_000 + index,
                Script(bytes.fromhex("0014") + keyhash),
            )
        )

    return PSBT(Transaction(version=2, vin=vin, vout=vout))


def _assert_psbt_round_trip(encoder, expected_base64: str, *, qr_size: int = 320, max_frames: int | None = None):
    from seedsigner.models.decode_qr import DecodeQR, DecodeQRStatus

    decoder = DecodeQR()
    frame_budget = max_frames if max_frames is not None else encoder.seq_len()

    for _ in range(frame_budget):
        part = encoder.next_part()
        image = encoder.part_to_image(part, qr_size, qr_size)
        decoder.add_data(_decode_qr_image(image))
        if decoder.complete:
            break

    assert decoder.complete is True
    assert decoder.get_base64_psbt() == expected_base64


def _test_qr_round_trip():
    import qrcode

    from seedsigner.helpers.bbqr import decode_bbqr_data, parse_bbqr_header
    from seedsigner.models.decode_qr import DecodeQR, DecodeQRStatus
    from seedsigner.models.encode_qr import (
        Base64PsbtQrEncoder,
        BbqrTextQrEncoder,
        GenericStringEncoder,
        SpecterPsbtQrEncoder,
        UrPsbtQrEncoder,
        build_bbqr_psbt_qr_encoder,
    )
    from seedsigner.models.settings_definition import SettingsConstants

    tx_hex = "btctx:" + ("deadbeef" * 8)
    generic_encoder = GenericStringEncoder(tx_hex)
    generic_image = generic_encoder.part_to_image(generic_encoder.next_part(), 320, 320)
    assert _decode_qr_image(generic_image) == tx_hex

    dense_payload = "UR:ETH-SIGN-REQUEST/" + ("ABCDEFGHIJKLMNOPQRSTUVWX0123456789" * 18)
    dense_qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        border=3,
        box_size=2,
    )
    dense_qr.add_data(dense_payload)
    dense_qr.make(fit=True)
    dense_square = dense_qr.make_image(fill_color="black", back_color="white").convert("RGB")
    dense_square = dense_square.resize((160, 160), Image.Resampling.NEAREST)
    assert DecodeQR.extract_qr_data(dense_square, is_binary=False, aggressive=False) == dense_payload
    phone_frame = Image.new("RGB", (480, 480), "white")
    phone_frame.paste(
        dense_square.resize((132, 132), Image.Resampling.NEAREST),
        ((phone_frame.width - 132) // 2, (phone_frame.height - 132) // 2),
    )
    assert DecodeQR.extract_qr_data(phone_frame, is_binary=False) == dense_payload
    low_contrast_frame = ImageOps.colorize(
        phone_frame.convert("L"),
        black="#3c3c3c",
        white="#dadada",
    )
    assert DecodeQR.extract_qr_data(low_contrast_frame, is_binary=False) == dense_payload
    camera_like_source = dense_square.resize((320, 320), Image.Resampling.NEAREST)
    camera_like_frame = Image.new("RGB", (480, 480), "white")
    camera_like_frame.paste(
        camera_like_source.resize((112, 112), Image.Resampling.BILINEAR),
        ((camera_like_frame.width - 112) // 2, (camera_like_frame.height - 112) // 2),
    )
    assert DecodeQR.extract_qr_data(camera_like_frame, is_binary=False, aggressive=False) == dense_payload

    try:
        from qrcode.image.styledpil import StyledPilImage
        from qrcode.image.styles.moduledrawers import CircleModuleDrawer
    except Exception:
        StyledPilImage = None
        CircleModuleDrawer = None
    if StyledPilImage is not None and CircleModuleDrawer is not None:
        dense_circle = dense_qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=CircleModuleDrawer(),
            fill_color="black",
            back_color="white",
        ).convert("RGB")
        dense_circle = dense_circle.resize((160, 160), Image.Resampling.NEAREST)
        staged_decoder = DecodeQR()
        assert staged_decoder.add_image(dense_circle) == DecodeQRStatus.COMPLETE
        assert DecodeQR.extract_qr_data(dense_circle, is_binary=False) == dense_payload

    static_psbt = _build_sample_psbt(input_count=2, output_count=1)
    _assert_psbt_round_trip(
        Base64PsbtQrEncoder(psbt=static_psbt),
        static_psbt.to_base64(),
    )

    animated_psbt = _build_sample_psbt(input_count=20, output_count=2)
    specter_encoder = SpecterPsbtQrEncoder(
        psbt=animated_psbt,
        qr_density=SettingsConstants.DENSITY__MEDIUM,
    )
    assert specter_encoder.seq_len() > 1
    _assert_psbt_round_trip(specter_encoder, animated_psbt.to_base64())

    bbqr_psbt_encoder = build_bbqr_psbt_qr_encoder(
        psbt=animated_psbt,
        qr_density=SettingsConstants.DENSITY__LOW,
    )
    assert bbqr_psbt_encoder.seq_len() > 1
    _assert_psbt_round_trip(bbqr_psbt_encoder, animated_psbt.to_base64())

    ur_encoder = UrPsbtQrEncoder(
        psbt=animated_psbt,
        qr_density=SettingsConstants.DENSITY__HIGH,
    )
    assert ur_encoder.seq_len() > 1
    if shutil.which("qrencode") is not None:
        _assert_psbt_round_trip(
            ur_encoder,
            animated_psbt.to_base64(),
            max_frames=ur_encoder.seq_len() * 2,
        )

    text_payload = "".join(f"{value:02x}" for value in range(120))
    bbqr_text_encoder = BbqrTextQrEncoder(
        text=text_payload,
        min_version=4,
        max_version=4,
    )
    assert bbqr_text_encoder.seq_len() > 1

    segments = {}
    total = None
    encoding = None
    for _ in range(bbqr_text_encoder.seq_len()):
        part = _decode_qr_image(
            bbqr_text_encoder.part_to_image(bbqr_text_encoder.next_part(), 320, 320)
        ).upper()
        encoding, file_type, total, index = parse_bbqr_header(part)
        assert file_type == "U"
        segments[index] = part[8:]

    assert total is not None
    assert len(segments) == total
    decoded_text = decode_bbqr_data(
        "".join(segments[index] for index in range(total)),
        encoding,
    ).decode("utf-8")
    assert decoded_text == text_payload


def main() -> int:
    add_optional_site_packages()
    install_import_stubs()

    try:
        __import__("pygame")
        __import__("cv2")
        __import__("embit")
        __import__("qrcode")
        __import__("shamir_mnemonic")
        __import__("urtypes")
    except Exception as exc:
        print(f"desktop_smoke_missing_dependency: {exc}", file=sys.stderr)
        return 2

    _test_renderer_desktop_modes()
    _test_desktop_buttons()
    _test_desktop_camera()
    _test_desktop_microsd()
    _test_main_startup_routes()
    _test_qr_round_trip()
    print("desktop_smoke_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
