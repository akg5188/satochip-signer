#!/usr/bin/env python3
import base64
import json
import os
import sys
import tempfile
import time
import types
import uuid
import zlib
from pathlib import Path
from PIL import Image, ImageDraw
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = ROOT / "seedsigner-os/opt/rootfs-overlay/opt/src"
VENDOR = ROOT / "pi-signer-py/vendor"
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
sys.path.insert(0, str(REPO_SRC))
sys.path.insert(0, str(VENDOR))


def add_optional_site_packages() -> None:
    candidates: list[Path] = []

    env_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    if env_path is not None:
        candidates.append(env_path)

    candidates.extend(
        [
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


add_optional_site_packages()


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
    pyzbar_mod.decode = lambda *a, **k: []

    class _FakeZBarSymbol:
        QRCODE = "QRCODE"

    pyzbar_mod.ZBarSymbol = _FakeZBarSymbol
    pyzbar_pkg.pyzbar = pyzbar_mod
    sys.modules["pyzbar"] = pyzbar_pkg
    sys.modules["pyzbar.pyzbar"] = pyzbar_mod


class _FakeStorage:
    def __init__(self):
        self.seeds = []
        self.pending_seed = None
        self._pending_mnemonic = []
        self._steel = []
        self._steel_indices = []
        self._plate = []

    def has_steel_encrypted_mnemonic(self):
        return bool(self._steel)

    def get_steel_encrypted_mnemonic(self):
        return list(self._steel)

    def set_steel_encrypted_mnemonic(self, words, bip39_indices=None, **kwargs):
        self._steel = list(words)
        self._steel_indices = list(bip39_indices or [])

    def get_steel_bip39_indices(self):
        return list(self._steel_indices)

    def set_steel_plate_groups(self, groups):
        self._plate = list(groups)

    def get_steel_plate_groups(self):
        return list(self._plate)

    def clear_steel_cache(self):
        self._steel = []
        self._steel_indices = []
        self._plate = []

    def set_pending_seed(self, seed):
        self.pending_seed = seed

    def get_pending_seed(self):
        return self.pending_seed

    @property
    def pending_mnemonic(self):
        return list(self._pending_mnemonic)

    def discard_pending_mnemonic(self):
        self._pending_mnemonic = []

    def init_pending_mnemonic(self, num_words=12, **kwargs):
        self._pending_mnemonic = [None] * num_words

    @property
    def pending_mnemonic_length(self):
        return len(self._pending_mnemonic)

    def update_pending_mnemonic(self, word, index):
        self._pending_mnemonic[index] = word

    def get_pending_mnemonic_word(self, index):
        if index < len(self._pending_mnemonic):
            return self._pending_mnemonic[index]
        return None

    def finalize_pending_seed(self):
        if self.pending_seed in self.seeds:
            index = self.seeds.index(self.pending_seed)
        else:
            self.seeds.append(self.pending_seed)
            index = len(self.seeds) - 1
        self.pending_seed = None
        return index


class _FakeController:
    def __init__(self):
        self.storage = _FakeStorage()

    def get_seed(self, seed_num):
        return self.storage.seeds[seed_num]


class _FakeSettings:
    def get_value(self, key):
        key_str = str(key).lower()
        if "seed_word_lengths" in key_str:
            return [12, 24]
        if "wordlist_language" in key_str:
            return "en"
        if "smartcard_support" in key_str or "bip85_child_seeds" in key_str:
            return "E"
        return "M"


class _FakeRenderer:
    canvas_width = 240
    canvas_height = 240


class _FakeLoadingScreenThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        return None

    def stop(self):
        return None


def main() -> int:
    install_import_stubs()

    from seedsigner.views import view as view_mod

    orig_init = view_mod.View._initialize

    def fake_init(self):
        self.controller = _FakeController()
        self.settings = _FakeSettings()
        self.renderer = _FakeRenderer()
        self.canvas_width = 240
        self.canvas_height = 240
        self.screen = None
        self._redirect = None

    view_mod.View._initialize = fake_init

    try:
        from seedsigner.gui.screens import RET_CODE__BACK_BUTTON
        import seedsigner.gui.screens.screen as screen_mod
        from seedsigner.views.seed_views import (
            LoadSeedView,
            SaveToSeedkeeperView,
            SeedKeeperSelectView,
            SeedMnemonicIndexEntryView,
            SeedMnemonicRawReviewView,
            SeedFinalizeView,
            SeedExportXpubWarningView,
            SeedWordIndexView,
            SeedWordsView,
            SeedsMenuView,
            SeedWordsBackupTestPromptView,
        )
        from seedsigner.views.tp_views import (
            TP_STEEL_SECRET_PREFIX,
            WEB3_WALLET_PROFILE_BITGET,
            WEB3_WALLET_PROFILE_OKX,
            ToolsTpLoadedSeedOptionsView,
            ToolsTpSeedPassphraseView,
            ToolsTpSatochipToolsView,
            ToolsTpSignerQrView,
            TpRequestQrDecoder,
            ToolsTpSignerPsbtQrView,
            ToolsTpSignerPsbtRunView,
            ToolsTpSteelCipherOptionsView,
            ToolsTpSeedkeeperLoadSteelCipherView,
            ToolsTpSeedkeeperSelectLoadedSeedView,
            ToolsTpSeedkeeperToolsView,
            ToolsTpSeedToolsView,
            ToolsTpSteelPlateReviewView,
            ToolsTpSteelPlateWordsView,
            ToolsTpSteelShiftInputView,
            ToolsTpSteelShiftReviewView,
            ToolsTpSmartcardToolsView,
            ToolsTpUiLockView,
            _canonicalize_bip39_words,
            _build_web3_account_export_response,
            _build_web3_connect_qr_pages,
            _extract_web3_export_request,
            _export_web3_account_from_seed,
            _format_number_groups,
            _store_restored_steel_cipher,
            _decode_seedkeeper_text_payload,
            _parse_seedkeeper_steel_payload,
            _parse_seedkeeper_steel_words,
        )
        from seedsigner.helpers.seedkeeper_utils import (
            decode_seedkeeper_tp_steel_payload,
            encode_seedkeeper_tp_steel_payload,
        )
        from seedsigner.helpers import mnemonic_generation
        from seedsigner.models.mnemonic_steel import (
            indices_to_words,
            indices_to_plate_groups,
            parse_restore_indices,
            shift_mnemonic,
            words_to_indices,
            words_to_plate_groups,
        )
        from seedsigner.models.seed import Seed, TransientWordSeed
        from seedsigner.models.decode_qr import DecodeQR, DecodeQRStatus, SeedQrDecoder
        from seedsigner.models.qr_type import QRType
        from seedsigner.models.settings import SettingsConstants
        from seedsigner.models.seed_storage import SeedStorage
        from seedsigner.models.threads import ThreadsafeCounter
        import seedsigner.helpers.qr as qr_helper
        from seedsigner.helpers.ur2.ur_decoder import URDecoder
        from seedsigner.models.encode_qr import GenericStaticQrEncoder
        from seedsigner.hardware import buttons as buttons_mod
        from seedsigner.hardware.buttons import HardwareButtons
        from seedsigner.gui.screens.seed_screens import _normalize_review_mnemonic_id
        from seedsigner.views.tools_views import (
            ToolsMenuView,
            ToolsCardEntropyEntryView,
            ToolsImageEntropyMnemonicLengthView,
            ToolsCardEntropyReviewView,
            ToolsHexEntropyEntryView,
            ToolsHexEntropyReviewView,
            ToolsSatochipView,
            ToolsSatochipImportSeedView,
            ToolsSatochipImportVerificationView,
            ToolsSeedkeeperView,
            ToolsSeedkeeperViewSecretsView,
            ToolsSmartcardMenuView,
            ToolsSatochipFactoryResetView,
            ToolsSatochipDIYView,
            SatochipExportXpubWarningView,
            _format_seedkeeper_generation_complete_text,
            _seedkeeper_build_entries,
            _seedkeeper_decode_secret_detail,
        )
        from seedsigner.gui.components import GUIConstants, ScrollableTextArea, reflow_text_into_pages
        from seedsigner.gui.keyboard import Keyboard
        from seedsigner.gui.screens.tools_screens import ToolsScrollableTextScreen
        import seedsigner.views.seed_views as seed_views_mod
        import seedsigner.views.psbt_views as psbt_views_mod
        import seedsigner.views.tools_views as tools_views_mod
        import seedsigner.views.tp_views as tp_views_mod
        import seedsigner.gui.renderer as renderer_mod
        import seedsigner.models.encode_qr as encode_qr_mod
        import seedsigner.models.settings as settings_mod

        tp_views_mod.LoadingScreenThread = _FakeLoadingScreenThread
        screen_mod.LoadingScreenThread = _FakeLoadingScreenThread

        def _build_web3_eth_sign_request_ur(
            *,
            request_id: str | None,
            sign_data: bytes,
            data_type: int,
            chain_id: int,
            derivation_path: str,
            address: str | None = None,
            origin: str | None = None,
        ) -> str:
            encoder = tp_views_mod.CBOREncoder()
            field_count = 3  # signData, dataType, derivationPath
            if request_id:
                field_count += 1
            if chain_id is not None:
                field_count += 1
            if address:
                field_count += 1
            if origin:
                field_count += 1

            encoder.encodeMapSize(field_count)
            if request_id:
                encoder.encodeUnsigned(1)
                encoder.encodeTagAndValue(tp_views_mod.Tag_Major_semantic, 37)
                encoder.encodeBytes(uuid.UUID(request_id).bytes)
            encoder.encodeUnsigned(2)
            encoder.encodeBytes(bytes(sign_data))
            encoder.encodeUnsigned(3)
            encoder.encodeUnsigned(int(data_type))
            if chain_id is not None:
                encoder.encodeUnsigned(4)
                encoder.encodeUnsigned(int(chain_id))
            encoder.encodeUnsigned(5)
            encoder.encodeTagAndValue(tp_views_mod.Tag_Major_semantic, 304)
            encoder.buf += tp_views_mod._encode_web3_keypath_bytes(derivation_path)
            if address:
                encoder.encodeUnsigned(6)
                encoder.encodeBytes(bytes.fromhex(address[2:] if address.lower().startswith("0x") else address))
            if origin:
                encoder.encodeUnsigned(7)
                encoder.encodeText(origin)
            return tp_views_mod.UREncoder.encode(tp_views_mod.UR("eth-sign-request", encoder.get_bytes()))

        bip39_words = Seed.get_wordlist(SettingsConstants.WORDLIST_LANGUAGE__ENGLISH)
        valid_upper_mnemonic = ("ABANDON " * 11 + "ABOUT").strip()
        assert DecodeQR.detect_segment_type(
            valid_upper_mnemonic,
            wordlist_language_code=SettingsConstants.WORDLIST_LANGUAGE__ENGLISH,
        ) == QRType.SEED__MNEMONIC
        assert Seed(valid_upper_mnemonic.split()).mnemonic_list[0] == "abandon"

        decoder = SeedQrDecoder(SettingsConstants.WORDLIST_LANGUAGE__ENGLISH)
        assert decoder.add(valid_upper_mnemonic, QRType.SEED__MNEMONIC) == DecodeQRStatus.COMPLETE
        assert decoder.seed_phrase[0] == "abandon"

        numeric_decoder = SeedQrDecoder(SettingsConstants.WORDLIST_LANGUAGE__ENGLISH)
        assert numeric_decoder.add("0000" * 12, QRType.SEED__SEEDQR) == DecodeQRStatus.COMPLETE
        assert numeric_decoder.seed_phrase[0] == bip39_words[0]
        assert numeric_decoder.seed_phrase[0] is not bip39_words[0]

        real_storage = SeedStorage()
        real_storage.init_pending_mnemonic(12)
        real_storage.update_pending_mnemonic(bip39_words[0], 0)
        assert real_storage.get_pending_mnemonic_word(0) == bip39_words[0]
        assert real_storage.get_pending_mnemonic_word(0) is not bip39_words[0]

        class _FakePin:
            def __init__(self, values):
                self.values = list(values)

            def read(self):
                return self.values.pop(0)

            def close(self):
                return None

        orig_using_gpio = buttons_mod.USING_GPIO
        buttons_mod.USING_GPIO = True
        try:
            key = HardwareButtons.KEY1_PIN
            hardware_buttons = object.__new__(HardwareButtons)
            hardware_buttons._gpio_pins = {key: _FakePin([False, False, True])}
            hardware_buttons._low_since_ms = {
                key: int(time.time() * 1000) - 20,
            }
            hardware_buttons.debounce_threshold_ms = 10
            hardware_buttons.last_input_time = 0
            assert hardware_buttons.check_for_low(keys=[key]) is True
            assert hardware_buttons._low_since_ms[key] is not None
            assert hardware_buttons.check_for_low(keys=[key]) is True
            assert hardware_buttons.check_for_low(keys=[key]) is False
            assert hardware_buttons._low_since_ms[key] is None
        finally:
            buttons_mod.USING_GPIO = orig_using_gpio

        assert ToolsTpSmartcardToolsView.SATOCHIP_TOOLS.button_label == "Satochip 功能"
        assert ToolsTpSmartcardToolsView.SEEDKEEPER_TOOLS.button_label == "SeedKeeper 功能"
        assert "/mnt/microsd" not in str(tp_views_mod._tp_ui_lock_path())
        assert ToolsTpSatochipToolsView.IMPORT_LOADED_SEED.button_label == "写入助记词"
        assert ToolsTpSeedkeeperToolsView.GENERATE_MNEMONIC.button_label == "智能卡创建"
        assert ToolsTpSeedkeeperToolsView.SAVE_STEEL_CIPHER.button_label == "保存二次加密"
        assert ToolsTpSeedkeeperToolsView.LOAD_STEEL_CIPHER.button_label == "加载二次加密"
        assert not hasattr(ToolsTpSeedToolsView, "STEEL_RESTORE")
        assert not hasattr(ToolsTpSeedToolsView, "STEEL_SCAN")
        assert ToolsTpSeedToolsView.CREATE_MNEMONIC.button_label == "创建助记词"
        assert tp_views_mod.ToolsTpSeedCreateMnemonicView.CARD_CREATE.button_label == "扑克牌创建"
        assert tp_views_mod.ToolsTpSeedCreateMnemonicView.HEX_CREATE.button_label == "16进制创建"
        assert tp_views_mod.ToolsTpSeedCreateMnemonicView.DICE_CREATE.button_label == "骰子创建"
        assert tp_views_mod.ToolsTpSeedCreateMnemonicView.CAMERA_CREATE.button_label == "拍照创建"
        assert tp_views_mod.ToolsTpSeedCreateMnemonicView.SEEDKEEPER_CREATE.button_label == "智能卡创建"
        assert tp_views_mod.ToolsTpHomeView.CONNECT_WALLET.button_label == "连接钱包"
        assert tp_views_mod.ToolsTpConnectWalletMenuView.WEB3.button_label == "Web3钱包"
        assert tp_views_mod.ToolsTpConnectWalletMenuView.BTC.button_label == "比特币钱包"
        assert tp_views_mod.ToolsTpWeb3WalletProfileSelectView.TOKENPOCKET.button_label == "TokenPocket"
        assert tp_views_mod.ToolsTpWeb3WalletProfileSelectView.IMTOKEN.button_label == "imToken"
        assert tp_views_mod._web3_wallet_profile("imToken") == tp_views_mod.WEB3_WALLET_PROFILE_IMTOKEN
        assert tp_views_mod._web3_wallet_meta("imToken") == ("IMTOKEN", "imToken")
        assert tp_views_mod.WEB3_KEYSTONE_DEVICE_VERSION == "1.0.4"
        assert tp_views_mod.ToolsTpBtcConnectTypeView.ZPUB.button_label == "BlueWallet zpub"
        assert tp_views_mod.ToolsTpBtcConnectTypeView.XPUB.button_label == "BlueWallet xpub"
        assert URDecoder().expected_part_count() == 0

        class _FakeWeb3UrDecoder:
            def receive_part(self, _text):
                return True

            def expected_part_count(self):
                return None

            def received_part_indexes(self):
                return None

            def is_complete(self):
                return False

        web3_qr_decoder = TpRequestQrDecoder()
        web3_qr_decoder._web3_ur_decoder = _FakeWeb3UrDecoder()
        assert web3_qr_decoder.add_data("ur:eth-sign-request/placeholder") == DecodeQRStatus.PART_COMPLETE
        assert web3_qr_decoder.total_segments == 1
        assert web3_qr_decoder.collected_segments == 1
        assert ToolsTpLoadedSeedOptionsView.VIEW_WORDS.button_label == "查看助记词"
        assert ToolsTpLoadedSeedOptionsView.SAVE_TO_SEEDKEEPER.button_label == "写入到 SeedKeeper"
        assert ToolsTpLoadedSeedOptionsView.IMPORT_TO_SMARTCARD.button_label == "写入到智能卡"
        assert LoadSeedView.TYPE_STEEL_RESTORE.button_label == "从钢板数字恢复"
        assert ToolsTpUiLockView.SETUP.button_label == "设置登录密码"
        assert ToolsTpUiLockView.UNLOCK.button_label == "输入登录密码"
        assert ToolsMenuView.CARDS.button_label == "扑克牌创建"
        assert ToolsMenuView.HEX.button_label == "16进制创建"
        assert ToolsSeedkeeperView.VIEW_SECRETS.button_label == "管理卡内助记词"
        assert ToolsSeedkeeperView.VIEW_FREE_SPACE.button_label == "剩余空间"
        assert ToolsSeedkeeperView.CHANGE_PIN.button_label == "更改 PIN"
        assert ToolsSeedkeeperView.FACTORY_RESET.button_label == "高风险：重置"
        assert ToolsSatochipView.IMPORT_SEED.button_label == "写入助记词"
        assert ToolsSatochipView.EXPORT_XPUB.button_label == "导出公钥"
        assert ToolsSatochipView.LOAD_DESCRIPTOR.button_label == "加载描述符"
        assert ToolsSatochipView.CHANGE_PIN.button_label == "更改 PIN"
        assert ToolsSatochipView.FACTORY_RESET.button_label == "重置卡片"
        assert not hasattr(ToolsSmartcardMenuView, "Satochip_DIY")
        assert ToolsSatochipFactoryResetView.LEGACY_RESET.button_label == "拔插卡恢复出厂（推荐）"
        assert ToolsSatochipFactoryResetView.BLOCKING_RESET.button_label == "锁死 PIN/PUK 恢复出厂"
        assert ToolsSatochipDIYView.MANAGE_KEYS.button_label == "管理卡默认密钥"
        assert ToolsSatochipDIYView.BUILD_APPLETS.button_label == "编译 CAP 安装包"
        assert ToolsSatochipDIYView.INSTALL_APPLET.button_label == "安装卡片程序"
        assert ToolsSatochipDIYView.UNINSTALL_APPLET.button_label == "卸载卡片程序"
        relay_payload = "ethereum:signTransaction-?chain_id=1&requestId=okx-smoke&data=%7B%7D"
        relay_envelope = json.dumps(
            {
                "version": 1,
                "wallet": "OKX",
                "wallet_name": "OKX Wallet",
                "format": "Ethereum URI",
                "qr_type": "-",
                "action": "EVM 签名请求",
                "payload": relay_payload,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        relay_encoded = base64.urlsafe_b64encode(zlib.compress(relay_envelope.encode("utf-8"))).decode("ascii").rstrip("=")
        relay_crc = str(zlib.crc32(relay_encoded.encode("utf-8")) & 0xFFFFFFFF)
        relay_chunks = [relay_encoded[:56], relay_encoded[56:]]
        relay_decoder = TpRequestQrDecoder()
        assert relay_decoder.add_data(f"w3r1:1/2.{relay_crc}.{relay_chunks[0]}") == DecodeQRStatus.PART_COMPLETE
        assert relay_decoder.add_data(f"w3r1:2/2.{relay_crc}.{relay_chunks[1]}") == DecodeQRStatus.COMPLETE
        assert relay_decoder.get_text() == relay_payload

        native_envelope = json.dumps(
            {
                "version": 1,
                "wallet": "BITGET",
                "wallet_name": "Bitget Wallet",
                "qr_type": "eth-sign-request",
                "action": "EVM 签名请求",
                "payload": relay_payload,
                "response_protocol": "eth-signature",
                "request_id": "123e4567-e89b-12d3-a456-426614174000",
                "origin": "Bitkeep",
                "data_type": "PERSONAL_MESSAGE",
                "chain_id": "1",
                "address": "0x1111111111111111111111111111111111111111",
                "address_path": "m/44'/60'/0'/0/0",
                "expected_address": "0x1111111111111111111111111111111111111111",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        native_encoded = base64.urlsafe_b64encode(zlib.compress(native_envelope.encode("utf-8"))).decode("ascii").rstrip("=")
        native_crc = str(zlib.crc32(native_encoded.encode("utf-8")) & 0xFFFFFFFF)
        native_decoder = TpRequestQrDecoder()
        assert native_decoder.add_data(f"w3r1:1/1.{native_crc}.{native_encoded}") == DecodeQRStatus.COMPLETE
        native_request = tp_views_mod._extract_web3_native_relay_request(native_decoder.get_text())
        assert native_request["wallet_name"] == "Bitget Wallet"
        assert native_request["response_protocol"] == "eth-signature"
        assert native_request["payload"] == relay_payload
        assert native_request["derivation_path"] == "m/44'/60'/0'/0/0"

        assert _normalize_review_mnemonic_id("") == "（空）"
        assert _normalize_review_mnemonic_id(None) == "（空）"
        assert _normalize_review_mnemonic_id("  ab  cd  ") == "\u2589\u2589ab\u2589\u2589cd\u2589\u2589"
        assert reflow_text_into_pages("abc", width=40, height=1, font_name="Inconsolata-SemiBold", font_size=18) == ["abc"]
        assert _canonicalize_bip39_words([" Enjoy ", "ABILITY"]) == ["enjoy", "ability"]
        assert mnemonic_generation.parse_card_entropy_events("ah qs 9dtc") == ["AH", "QS", "9D", "TC"]
        assert mnemonic_generation.normalize_cards_for_iancoleman("ahqs9dtc") == "AH QS 9D TC"
        assert mnemonic_generation.format_cards_for_iancoleman_hash("ah qs 9dtc") == "A\u2665 Q\u2660 9\u2666 T\u2663"
        assert mnemonic_generation.normalize_hex_for_iancoleman("60 55 17 82 11 46 41 6f") == "605517821146416F"
        assert mnemonic_generation.format_hex_for_iancoleman_hash("60 55 17 82 11 46 41 6F") == "605517821146416f"
        assert mnemonic_generation.hex_entropy_bit_length("605517821146416F") == 64
        assert mnemonic_generation.hex_entropy_matches_word_length("00000000000000000000000000000000", 12)
        assert mnemonic_generation.generate_mnemonic_from_hex("f2a83b9c7d4e1a0b5f6e9d8c7b6a5f4e", 12) == (
            "huge protect deal panel bullet during fog annual crew cattle anchor rival".split()
        )
        tp_loaded_seed = Seed(
            mnemonic="abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split(),
            wordlist_language_code="en",
        )
        seed_btc_view = tp_views_mod.ToolsTpSeedBtcXpubQrView(seed_num=0, xtype="zpub", return_to_connect_wallet=True)
        seed_btc_view.controller.storage.seeds.append(tp_loaded_seed)
        seed_btc_capture = {}

        def _seed_btc_run_screen(*args, **kwargs):
            screen_name = getattr(args[0], "__name__", str(args[0])) if args else ""
            seed_btc_capture.setdefault("screens", []).append(screen_name)
            if screen_name == "QRDisplayScreen":
                seed_btc_capture["encoder"] = kwargs["qr_encoder"]
            return 0

        seed_btc_view.run_screen = _seed_btc_run_screen
        dest = seed_btc_view.run()
        assert dest.View_cls == tp_views_mod.ToolsTpConnectWalletMenuView
        assert seed_btc_capture["screens"] == ["WarningScreen", "QRDisplayScreen"]

        def _run_review_chain(view, run_screen, max_steps=8):
            controller = view.controller
            settings = view.settings
            renderer = view.renderer
            current = view
            for _ in range(max_steps):
                current.controller = controller
                current.settings = settings
                current.renderer = renderer
                current.canvas_width = renderer.canvas_width
                current.canvas_height = renderer.canvas_height
                current.run_screen = run_screen
                dest = current.run()
                if hasattr(dest, "View_cls") and dest.View_cls == current.__class__:
                    next_view = dest.View_cls(**(dest.view_args or {}))
                    next_view.controller = controller
                    next_view.settings = settings
                    next_view.renderer = renderer
                    next_view.canvas_width = renderer.canvas_width
                    next_view.canvas_height = renderer.canvas_height
                    current = next_view
                    continue
                return dest
            raise AssertionError("review chain did not terminate")

        from embit import bip32 as embit_bip32_mod
        from embit.networks import NETWORKS as EMBIT_NETWORKS
        from pysatochip.CardDataParser import CardDataParser

        web3_expected_address = "0x1111111111111111111111111111111111111111"
        web3_data = json.dumps(
            {
                "address": web3_expected_address,
                "expectedAddress": web3_expected_address,
                "path": "m/44'/60'/0'/0/0",
                "purpose": "web3-bridge",
            },
            separators=(",", ":"),
        )
        web3_payload = (
            "tp:exportWeb3Account-version=1.0&protocol=ArbitrumWallet&network=evm&chain_id=42161"
            "&requestId=web3-smoke&path=m%2F44%27%2F60%27%2F0%27%2F0%2F0&data="
            + quote(web3_data, safe="")
        )
        web3_request = _extract_web3_export_request(web3_payload)
        assert web3_request["expected_address"].lower() == web3_expected_address.lower()
        web3_account = {
            "address": web3_expected_address,
            "addressPath": web3_request["derivation_path"],
            "accountPath": "m/44'/60'/0'",
            "masterFingerprint": "f23f9fd2",
            "compressedPubKeyHex": "02" + "11" * 32,
            "chainCodeHex": "22" * 32,
            "xpub": "xpub-smoke",
            "sourceLabel": "smoke",
            "importedAt": 1,
            "label": "Web3 账户",
            "childrenPath": "0/*",
        }
        web3_response = _build_web3_account_export_response(web3_request, web3_account)
        assert web3_response.startswith("tp:exportWeb3AccountResult-")
        seed_web3_account = _export_web3_account_from_seed(Seed(valid_upper_mnemonic.split()), web3_request["derivation_path"])
        seed_web3_okx_pages = _build_web3_connect_qr_pages(seed_web3_account, WEB3_WALLET_PROFILE_OKX)
        seed_web3_bitget_pages = _build_web3_connect_qr_pages(seed_web3_account, WEB3_WALLET_PROFILE_BITGET)
        seed_web3_metamask_pages = _build_web3_connect_qr_pages(seed_web3_account, tp_views_mod.WEB3_WALLET_PROFILE_METAMASK)
        seed_web3_rabby_pages = _build_web3_connect_qr_pages(seed_web3_account, tp_views_mod.WEB3_WALLET_PROFILE_RABBY)
        seed_web3_tp_pages = _build_web3_connect_qr_pages(seed_web3_account, tp_views_mod.WEB3_WALLET_PROFILE_TOKENPOCKET)
        seed_web3_imtoken_pages = _build_web3_connect_qr_pages(seed_web3_account, tp_views_mod.WEB3_WALLET_PROFILE_IMTOKEN)
        assert seed_web3_okx_pages
        assert seed_web3_bitget_pages
        assert seed_web3_metamask_pages
        assert seed_web3_rabby_pages
        assert seed_web3_tp_pages
        assert seed_web3_imtoken_pages
        assert seed_web3_okx_pages[0].lower().startswith("ur:crypto-multi-accounts")
        assert seed_web3_bitget_pages[0].lower().startswith("ur:crypto-multi-accounts")
        assert seed_web3_metamask_pages[0].lower().startswith("ur:crypto-hdkey")
        assert seed_web3_rabby_pages[0].lower().startswith("ur:crypto-hdkey")
        assert seed_web3_tp_pages[0].lower().startswith("ur:crypto-hdkey")
        assert seed_web3_imtoken_pages[0].lower().startswith("ur:crypto-hdkey")
        assert len(seed_web3_okx_pages) > 1
        assert len(seed_web3_bitget_pages) == 1
        assert len(seed_web3_metamask_pages) == 1
        assert len(seed_web3_rabby_pages) == 1
        assert len(seed_web3_tp_pages) == 1
        assert len(seed_web3_imtoken_pages) == 1
        assert all(page == page.upper() for page in seed_web3_okx_pages)
        assert seed_web3_bitget_pages[0] == seed_web3_bitget_pages[0].upper()
        assert seed_web3_metamask_pages[0] == seed_web3_metamask_pages[0].upper()
        assert seed_web3_rabby_pages[0] == seed_web3_rabby_pages[0].upper()
        assert seed_web3_tp_pages[0] == seed_web3_tp_pages[0].upper()
        assert seed_web3_imtoken_pages[0] == seed_web3_imtoken_pages[0].upper()
        assert all(qr_helper._normalize_qr_render_data(page) == page for page in seed_web3_okx_pages)
        assert qr_helper._normalize_qr_render_data(seed_web3_bitget_pages[0]) == seed_web3_bitget_pages[0]
        assert seed_web3_account["keystoneKeys"]["standard"]["coinType"] == tp_views_mod.WEB3_ETH_COIN_TYPE
        assert seed_web3_account["keystoneKeys"]["standard"]["network"] == tp_views_mod.WEB3_MAINNET_NETWORK
        okx_ledger_live_entries = seed_web3_account["keystoneKeys"].get("okxLedgerLive", [])
        assert len(okx_ledger_live_entries) == tp_views_mod.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT
        assert len(seed_web3_account["keystoneKeys"]["okxBitcoin"]) == len(tp_views_mod.WEB3_OKX_BTC_ACCOUNT_PATHS)
        assert [entry["originPath"] for entry in seed_web3_account["keystoneKeys"]["okxBitcoin"]] == list(tp_views_mod.WEB3_OKX_BTC_ACCOUNT_PATHS)
        if tp_views_mod.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT:
            assert okx_ledger_live_entries[0]["originPath"] == "m/44'/60'/0'/0/0"
            assert okx_ledger_live_entries[-1]["originPath"] == f"m/44'/60'/{tp_views_mod.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT - 1}'/0/0"
            assert all(entry["note"] == "account.ledger_live" for entry in okx_ledger_live_entries)
            assert all(entry["originDepth"] == 5 for entry in okx_ledger_live_entries)
            assert all(entry["chainCodeHex"] == "" for entry in okx_ledger_live_entries)
            assert all(entry["parentFingerprint"] == "" for entry in okx_ledger_live_entries)

        okx_multi_decoder = URDecoder()
        for page in seed_web3_okx_pages:
            assert okx_multi_decoder.receive_part(page)
        assert okx_multi_decoder.is_complete()
        okx_multi_root = tp_views_mod._decode_cbor_root_map(okx_multi_decoder.result_message().cbor)
        assert sorted(okx_multi_root.keys()) == [1, 2, 3, 4, 5]
        assert okx_multi_root[3] == tp_views_mod.WEB3_OKX_DEVICE_TYPE
        assert okx_multi_root[4] == tp_views_mod._web3_device_id(seed_web3_account, tp_views_mod.WEB3_WALLET_PROFILE_OKX)
        assert okx_multi_root[5] == tp_views_mod.WEB3_KEYSTONE_DEVICE_VERSION
        assert len(okx_multi_root[4]) == 40
        assert len(okx_multi_root[2]) == 1 + tp_views_mod.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT + len(tp_views_mod.WEB3_OKX_BTC_ACCOUNT_PATHS)
        okx_standard_hdkey = tp_views_mod._tagged_value(okx_multi_root[2][0], expected_tag=303)
        okx_first_ledger_live_hdkey = None
        if tp_views_mod.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT:
            okx_first_ledger_live_hdkey = tp_views_mod._tagged_value(okx_multi_root[2][1], expected_tag=303)
        okx_first_btc_hdkey = tp_views_mod._tagged_value(
            okx_multi_root[2][1 + tp_views_mod.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT],
            expected_tag=303,
        )
        assert tp_views_mod._tagged_value(okx_standard_hdkey[5], expected_tag=305) == {
            1: tp_views_mod.WEB3_ETH_COIN_TYPE,
            2: tp_views_mod.WEB3_MAINNET_NETWORK,
        }
        assert tp_views_mod._web3_keypath_to_bip32_path(okx_standard_hdkey[6]) == "m/44'/60'/0'"
        assert tp_views_mod._web3_keypath_to_bip32_path(okx_standard_hdkey[7]) == "m/0/*"
        assert 3 not in tp_views_mod._tagged_value(okx_standard_hdkey[6], expected_tag=304)
        assert 3 not in tp_views_mod._tagged_value(okx_standard_hdkey[7], expected_tag=304)
        if tp_views_mod.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT:
            assert tp_views_mod._web3_keypath_to_bip32_path(okx_first_ledger_live_hdkey[6]) == "m/44'/60'/0'/0/0"
            assert 3 not in tp_views_mod._tagged_value(okx_first_ledger_live_hdkey[6], expected_tag=304)
            assert 4 not in okx_first_ledger_live_hdkey
            assert 5 not in okx_first_ledger_live_hdkey
            assert 7 not in okx_first_ledger_live_hdkey
            assert 8 not in okx_first_ledger_live_hdkey
        assert tp_views_mod._tagged_value(okx_first_btc_hdkey[5], expected_tag=305) == {
            1: tp_views_mod.WEB3_BTC_COIN_TYPE,
            2: tp_views_mod.WEB3_MAINNET_NETWORK,
        }
        assert tp_views_mod._web3_keypath_to_bip32_path(okx_first_btc_hdkey[6]) == tp_views_mod.WEB3_OKX_BTC_ACCOUNT_PATHS[0]
        assert tp_views_mod._tagged_value(okx_first_btc_hdkey[6], expected_tag=304)[3] == 3

        bitget_multi_decoder = URDecoder()
        for page in seed_web3_bitget_pages:
            assert bitget_multi_decoder.receive_part(page)
        assert bitget_multi_decoder.is_complete()
        bitget_multi_root = tp_views_mod._decode_cbor_root_map(bitget_multi_decoder.result_message().cbor)
        assert sorted(bitget_multi_root.keys()) == [1, 2, 3]
        assert bitget_multi_root[3] == "Keystone"
        assert len(bitget_multi_root[2]) == 1 + len(tp_views_mod.WEB3_BITKEEP_BTC_ACCOUNT_PATHS)
        try:
            _build_web3_account_export_response(
                web3_request,
                dict(web3_account, address="0x2222222222222222222222222222222222222222"),
            )
            raise AssertionError("Web3 观察地址不一致时必须拒绝导出")
        except ValueError as exc:
            assert "不一致" in str(exc)

        class _FakeExtendedKey:
            def __init__(self, hdkey):
                self._hdkey = hdkey

            def get_public_key_bytes(self, compressed=True):
                _ = compressed
                return self._hdkey.key.sec()

        class _FakeSatochipImportConnector:
            def __init__(self):
                self.seed_bytes = None
                self.parser = CardDataParser()
                self.parser.authentikey = object()
                self._current_priv = None
                self._pin = None

            def card_bip32_import_seed(self, seed_bytes):
                self.seed_bytes = bytes(seed_bytes)

            def card_get_status(self):
                return None, 0x90, 0x00, {"is_seeded": self.seed_bytes is not None}

            def set_pin(self, pin_nbr, pin):
                _ = pin_nbr
                self._pin = list(pin)

            def card_verify_PIN(self):
                return [], 0x90, 0x00

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

        import_seed_view = ToolsSatochipImportSeedView(
            preferred_seed_num=0,
            return_destination=view_mod.Destination(view_mod.BackStackView),
        )
        import_seed_view.controller = _FakeController()
        import_seed_view.settings = _FakeSettings()
        import_seed_view.renderer = _FakeRenderer()
        import_seed_view.canvas_width = 240
        import_seed_view.canvas_height = 240
        import_seed_view.run_screen = lambda *args, **kwargs: 0
        import_seed_view.controller.storage.seeds.append(tp_loaded_seed)
        verify_dest = import_seed_view._import_loaded_seed(_FakeSatochipImportConnector(), tp_loaded_seed)
        assert verify_dest.View_cls == ToolsSatochipImportVerificationView
        assert verify_dest.view_args["ok"] is True
        assert any("主指纹: 通过" in page for page in verify_dest.view_args["pages"])
        assert any("测试签名验签: 通过" in page for page in verify_dest.view_args["pages"])

        verify_view = ToolsSatochipImportVerificationView(**verify_dest.view_args)
        verify_view.controller = import_seed_view.controller
        verify_view.settings = import_seed_view.settings
        verify_view.renderer = import_seed_view.renderer
        verify_view.canvas_width = 240
        verify_view.canvas_height = 240
        verify_capture = {}

        def _verify_run_screen(*args, **kwargs):
            screen_name = getattr(args[0], "__name__", str(args[0])) if args else ""
            verify_capture.setdefault("screens", []).append(screen_name)
            if screen_name in {"ToolsFormattedTextScreen", "ToolsScrollableTextScreen"}:
                verify_capture.setdefault("titles", []).append(kwargs["title"])
                verify_capture.setdefault("texts", []).append(kwargs["text"])
                return len(kwargs["button_data"]) - 1
            return 0

        verify_dest_done = _run_review_chain(verify_view, _verify_run_screen, max_steps=40)
        assert "ToolsScrollableTextScreen" in verify_capture["screens"]
        assert any(title.startswith("写卡核验") for title in verify_capture["titles"])
        assert any("Legacy xpub" in text for text in verify_capture["texts"])
        assert verify_dest_done.View_cls == view_mod.BackStackView

        import embit.psbt as embit_psbt_mod

        original_tp_psbt_from_base64 = embit_psbt_mod.PSBT.from_base64
        original_tp_build_signed = encode_qr_mod.build_signed_psbt_qr_encoder
        original_tp_home_destination = tp_views_mod._tp_home_destination
        original_tp_bbqr_text_qr_encoder = encode_qr_mod.BbqrTextQrEncoder

        class _FakeSignedPsbt:
            pass

        class _FakeQrEncoder:
            def seq_len(self):
                return 1

            def restart(self):
                return None

            def next_part(self):
                return "ur:crypto-psbt/part"

        signed_capture = {}

        def _fake_tp_psbt_from_base64(raw):
            signed_capture["psbt_base64"] = raw
            return _FakeSignedPsbt()

        def _fake_tp_build_signed(psbt, qr_density, input_qr_type):
            signed_capture["encoder_args"] = (psbt, qr_density, input_qr_type)
            return _FakeQrEncoder()

        embit_psbt_mod.PSBT.from_base64 = staticmethod(_fake_tp_psbt_from_base64)
        encode_qr_mod.build_signed_psbt_qr_encoder = _fake_tp_build_signed
        tp_views_mod._tp_home_destination = lambda: object()
        try:
            signed_view = ToolsTpSignerPsbtQrView(
                psbt_base64="cHNidP8BAHECAAAAAQ==",
                input_qr_type=QRType.PSBT__BBQR,
                tx_hex=SIGNED_TX_SAMPLE_HEX,
            )
            screen_capture = {}

            def _signed_run_screen(*args, **kwargs):
                screen_name = getattr(args[0], "__name__", str(args[0])) if args else ""
                screen_capture.setdefault("screens", []).append(screen_name)
                if screen_name in {"ToolsFormattedTextScreen", "ToolsScrollableTextScreen"}:
                    screen_capture.setdefault("review_titles", []).append(kwargs["title"])
                    screen_capture.setdefault("review_texts", []).append(kwargs["text"])
                    return len(kwargs["button_data"]) - 1
                screen_capture["encoder"] = kwargs["qr_encoder"]
                return 0

            dest = _run_review_chain(signed_view, _signed_run_screen)
            assert signed_capture["psbt_base64"] == "cHNidP8BAHECAAAAAQ=="
            assert signed_capture["encoder_args"][2] == QRType.PSBT__BBQR
            assert "ToolsScrollableTextScreen" in screen_capture["screens"]
            assert "QRDisplayScreen" in screen_capture["screens"]
            assert any("结果: 可直接广播的交易" in text for text in screen_capture["review_texts"])
            assert any("扫码方式: 单张二维码" in text for text in screen_capture["review_texts"])
            assert any("随机数重复: 未发现" in text for text in screen_capture["review_texts"])
            assert all("回传格式:" not in text for text in screen_capture["review_texts"])
            assert all("帧数:" not in text for text in screen_capture["review_texts"])
            assert all("RawTx 预览" not in text for text in screen_capture["review_texts"])
            assert isinstance(screen_capture["encoder"], _FakeQrEncoder)
            assert dest is not None

            tx_only_capture = {}

            class _FakeBbqrTextEncoder:
                def __init__(self, **kwargs):
                    tx_only_capture["encoder_kwargs"] = kwargs

            encode_qr_mod.BbqrTextQrEncoder = _FakeBbqrTextEncoder
            tx_only_view = ToolsTpSignerPsbtQrView(
                psbt_base64="",
                input_qr_type=None,
                tx_hex=SIGNED_TX_SAMPLE_HEX,
            )

            def _tx_only_run_screen(*args, **kwargs):
                screen_name = getattr(args[0], "__name__", str(args[0])) if args else ""
                tx_only_capture.setdefault("screens", []).append(screen_name)
                if screen_name in {"ToolsFormattedTextScreen", "ToolsScrollableTextScreen"}:
                    tx_only_capture.setdefault("review_texts", []).append(kwargs["text"])
                    return len(kwargs["button_data"]) - 1
                tx_only_capture["encoder"] = kwargs["qr_encoder"]
                return 0

            tx_only_dest = _run_review_chain(tx_only_view, _tx_only_run_screen)
            assert "ToolsScrollableTextScreen" in tx_only_capture["screens"]
            assert "QRDisplayScreen" in tx_only_capture["screens"]
            assert any("结果: 可直接广播的交易" in text for text in tx_only_capture["review_texts"])
            assert any("随机数重复: 未发现" in text for text in tx_only_capture["review_texts"])
            assert isinstance(tx_only_capture["encoder"], _FakeBbqrTextEncoder)
            assert tx_only_capture["encoder_kwargs"]["text"] == SIGNED_TX_SAMPLE_HEX
            assert tx_only_dest is not None

            generic_capture = {}
            generic_view = ToolsTpSignerQrView(response_text=f"btctx:{SIGNED_TX_SAMPLE_HEX}")

            def _generic_run_screen(*args, **kwargs):
                screen_name = getattr(args[0], "__name__", str(args[0])) if args else ""
                generic_capture.setdefault("screens", []).append(screen_name)
                if screen_name in {"ToolsFormattedTextScreen", "ToolsScrollableTextScreen"}:
                    generic_capture.setdefault("review_texts", []).append(kwargs["text"])
                    return len(kwargs["button_data"]) - 1
                generic_capture["encoder"] = kwargs["qr_encoder"]
                return 0

            generic_dest = _run_review_chain(generic_view, _generic_run_screen)
            assert "ToolsScrollableTextScreen" in generic_capture["screens"]
            assert "QRDisplayScreen" in generic_capture["screens"]
            assert any("手机扫回后可直接广播" in text for text in generic_capture["review_texts"])
            assert any("随机数重复: 未发现" in text for text in generic_capture["review_texts"])
            assert all("回传类型:" not in text for text in generic_capture["review_texts"])
            assert all("RawTx 预览" not in text for text in generic_capture["review_texts"])
            assert generic_dest is not None

            original_psbt_signed_qr_display = psbt_views_mod.PSBTSignedQRDisplayView
            psbt_capture = {}
            psbt_view = original_psbt_signed_qr_display()
            psbt_view.controller.psbt = object()
            psbt_view.controller.psbt_seed = object()
            psbt_view.controller.signed_tx_hex = SIGNED_TX_SAMPLE_HEX
            psbt_view.controller.psbt_microsd_save_path = None
            psbt_view.controller.psbt_from_microsd = False
            psbt_view.controller.psbt_microsd_seed_warning_shown = False
            psbt_view.controller.psbt_parser = types.SimpleNamespace(
                num_inputs=4,
                num_destinations=2,
                spend_amount=12000,
                fee_amount=150,
                change_amount=300,
                destination_addresses=["bc1qexampleaddress0000000000000000000000000"],
            )

            def _psbt_run_screen(*args, **kwargs):
                screen_name = getattr(args[0], "__name__", str(args[0])) if args else ""
                psbt_capture.setdefault("screens", []).append(screen_name)
                if screen_name in {"ToolsFormattedTextScreen", "ToolsScrollableTextScreen"}:
                    psbt_capture.setdefault("review_texts", []).append(kwargs["text"])
                    return len(kwargs["button_data"]) - 1
                psbt_capture["encoder"] = kwargs["qr_encoder"]
                return 0

            psbt_dest = _run_review_chain(psbt_view, _psbt_run_screen)
            assert "ToolsScrollableTextScreen" in psbt_capture["screens"]
            assert "QRDisplayScreen" in psbt_capture["screens"]
            assert any("矿工费: 150 sats" in text for text in psbt_capture["review_texts"])
            assert any("结果: 可直接广播的交易" in text for text in psbt_capture["review_texts"])
            assert any("扫码方式: 单张二维码" in text for text in psbt_capture["review_texts"])
            assert any("随机数重复: 未发现" in text for text in psbt_capture["review_texts"])
            assert all("回传格式:" not in text for text in psbt_capture["review_texts"])
            assert all("RawTx 预览" not in text for text in psbt_capture["review_texts"])
            assert isinstance(psbt_capture["encoder"], _FakeQrEncoder)
            assert psbt_dest is not None

            original_generic_string_encoder = encode_qr_mod.GenericStringEncoder
            btctx_capture = {}

            class _FakeGenericStringEncoder:
                def __init__(self, text):
                    self.text = text
                    btctx_capture["text"] = text

                def seq_len(self):
                    return 1

            encode_qr_mod.GenericStringEncoder = _FakeGenericStringEncoder
            try:
                btctx_psbt_view = original_psbt_signed_qr_display()
                btctx_psbt_view.controller.psbt = object()
                btctx_psbt_view.controller.psbt_seed = tp_loaded_seed
                btctx_psbt_view.controller.psbt_response_mode = "btctx"
                btctx_psbt_view.controller.signed_tx_hex = SIGNED_TX_SAMPLE_HEX
                btctx_psbt_view.controller.psbt_microsd_save_path = None
                btctx_psbt_view.controller.psbt_from_microsd = False
                btctx_psbt_view.controller.psbt_microsd_seed_warning_shown = False
                btctx_psbt_view.controller.psbt_parser = types.SimpleNamespace(
                    num_inputs=1,
                    num_destinations=1,
                    spend_amount=12000,
                    fee_amount=150,
                    change_amount=0,
                    destination_addresses=["bc1qexampleaddress0000000000000000000000000"],
                )

                def _btctx_run_screen(*args, **kwargs):
                    screen_name = getattr(args[0], "__name__", str(args[0])) if args else ""
                    btctx_capture.setdefault("screens", []).append(screen_name)
                    if screen_name in {"ToolsFormattedTextScreen", "ToolsScrollableTextScreen"}:
                        return len(kwargs["button_data"]) - 1
                    btctx_capture["encoder"] = kwargs["qr_encoder"]
                    return 0

                btctx_dest = _run_review_chain(btctx_psbt_view, _btctx_run_screen)
                assert btctx_capture["text"] == f"btctx:{SIGNED_TX_SAMPLE_HEX}"
                assert "QRDisplayScreen" in btctx_capture["screens"]
                assert isinstance(btctx_capture["encoder"], _FakeGenericStringEncoder)
                assert btctx_dest is not None
            finally:
                encode_qr_mod.GenericStringEncoder = original_generic_string_encoder
        finally:
            embit_psbt_mod.PSBT.from_base64 = original_tp_psbt_from_base64
            encode_qr_mod.build_signed_psbt_qr_encoder = original_tp_build_signed
            tp_views_mod._tp_home_destination = original_tp_home_destination
            encode_qr_mod.BbqrTextQrEncoder = original_tp_bbqr_text_qr_encoder
        original_bbqr_from_payload = encode_qr_mod.BBQrParts.from_payload
        bbqr_retry_calls = []

        def _fake_bbqr_from_payload(
            cls,
            raw,
            file_type="P",
            *,
            encoding_preference="auto",
            min_version=5,
            max_version=40,
            min_split=1,
            max_split=1295,
        ):
            bbqr_retry_calls.append((min_version, max_version))
            if (min_version, max_version) != (5, 40):
                raise ValueError("BBQr payload does not fit the requested QR settings")
            return types.SimpleNamespace(parts=["B$2P0100TEST"])

        class _FakePsbt:
            def serialize(self):
                return b"psbt"

        encode_qr_mod.BBQrParts.from_payload = classmethod(_fake_bbqr_from_payload)
        try:
            bbqr_encoder = encode_qr_mod.build_bbqr_psbt_qr_encoder(
                psbt=_FakePsbt(),
                qr_density=SettingsConstants.DENSITY__LOW,
            )
            assert bbqr_encoder.parts == ["B$2P0100TEST"]
            assert bbqr_retry_calls == [(5, 15), (5, 40)]
        finally:
            encode_qr_mod.BBQrParts.from_payload = original_bbqr_from_payload

        original_build_bbqr_psbt_qr_encoder = encode_qr_mod.build_bbqr_psbt_qr_encoder
        original_base43_psbt_qr_encoder = encode_qr_mod.Base43PsbtQrEncoder
        original_base64_psbt_qr_encoder = encode_qr_mod.Base64PsbtQrEncoder
        original_specter_psbt_qr_encoder = encode_qr_mod.SpecterPsbtQrEncoder
        original_ur_psbt_qr_encoder = encode_qr_mod.UrPsbtQrEncoder
        signed_route_capture = []

        def _fake_encoder_ctor(name):
            class _FakeEncoder:
                def __init__(self, **kwargs):
                    self.name = name
                    self.kwargs = kwargs
                    signed_route_capture.append((name, kwargs))

                def seq_len(self):
                    return 1

            return _FakeEncoder

        def _fake_build_bbqr_signed(psbt, qr_density):
            signed_route_capture.append(("bbqr", {"psbt": psbt, "qr_density": qr_density}))
            return "bbqr-encoder"

        class _FakeUrPsbtQrEncoder:
            def __init__(self, psbt, qr_density):
                self.psbt = psbt
                self.qr_density = qr_density
                signed_route_capture.append(("ur", {"psbt": psbt, "qr_density": qr_density}))
            def seq_len(self):
                return 8
        encode_qr_mod.build_bbqr_psbt_qr_encoder = _fake_build_bbqr_signed
        encode_qr_mod.Base43PsbtQrEncoder = _fake_encoder_ctor("base43")
        encode_qr_mod.Base64PsbtQrEncoder = _fake_encoder_ctor("base64")
        encode_qr_mod.SpecterPsbtQrEncoder = _fake_encoder_ctor("specter")
        encode_qr_mod.UrPsbtQrEncoder = _FakeUrPsbtQrEncoder
        try:
            base43_signed_encoder = encode_qr_mod.build_signed_psbt_qr_encoder(
                psbt=_FakePsbt(),
                qr_density=SettingsConstants.DENSITY__LOW,
                input_qr_type=QRType.PSBT__BASE43,
            )
            assert getattr(base43_signed_encoder, "name", "") == "base43"
            base64_signed_encoder = encode_qr_mod.build_signed_psbt_qr_encoder(
                psbt=_FakePsbt(),
                qr_density=SettingsConstants.DENSITY__LOW,
                input_qr_type=QRType.PSBT__BASE64,
            )
            assert getattr(base64_signed_encoder, "name", "") == "base64"
            bbqr_signed_encoder = encode_qr_mod.build_signed_psbt_qr_encoder(
                psbt=_FakePsbt(),
                qr_density=SettingsConstants.DENSITY__LOW,
                input_qr_type=QRType.PSBT__BBQR,
            )
            assert bbqr_signed_encoder == "bbqr-encoder"
            assert signed_route_capture[-1][0] == "bbqr"
            specter_signed_encoder = encode_qr_mod.build_signed_psbt_qr_encoder(
                psbt=_FakePsbt(),
                qr_density=SettingsConstants.DENSITY__LOW,
                input_qr_type=QRType.PSBT__SPECTER,
            )
            assert getattr(specter_signed_encoder, "name", "") == "specter"
            ur_signed_encoder = encode_qr_mod.build_signed_psbt_qr_encoder(
                psbt=_FakePsbt(),
                qr_density=SettingsConstants.DENSITY__LOW,
                input_qr_type=QRType.PSBT__UR2,
            )
            assert isinstance(ur_signed_encoder, _FakeUrPsbtQrEncoder)
            assert ur_signed_encoder.qr_density == SettingsConstants.DENSITY__LOW
        finally:
            encode_qr_mod.build_bbqr_psbt_qr_encoder = original_build_bbqr_psbt_qr_encoder
            encode_qr_mod.Base43PsbtQrEncoder = original_base43_psbt_qr_encoder
            encode_qr_mod.Base64PsbtQrEncoder = original_base64_psbt_qr_encoder
            encode_qr_mod.SpecterPsbtQrEncoder = original_specter_psbt_qr_encoder
            encode_qr_mod.UrPsbtQrEncoder = original_ur_psbt_qr_encoder

        original_renderer_get_instance = renderer_mod.Renderer.get_instance
        original_settings_get_instance = settings_mod.Settings.get_instance
        original_screen_sleep = screen_mod.time.sleep

        class _FakeLock:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class _FakeThreadRenderer:
            def __init__(self, width: int, height: int):
                self.canvas_width = width
                self.canvas_height = height
                self.lock = _FakeLock()
                self.thread = None

            def show_image(self, image):
                if self.thread is not None:
                    self.thread.keep_running = False

        class _FakeBrightnessSettings:
            def __init__(self, enabled: bool):
                self.enabled = enabled

            def get_value(self, key):
                if self.enabled:
                    return SettingsConstants.OPTION__ENABLED
                return SettingsConstants.OPTION__DISABLED

        class _FakeScreenEncoder:
            def __init__(self):
                self.calls = []
                self.restart_count = 0

            def cur_part(self):
                return "part"

            def part_to_image(self, part, width, height, border=0, background_color=None):
                self.calls.append(("part_to_image", width, height, border, background_color))
                return Image.new("RGB", (width, height))

            def next_part_image(self, width, height, border=0, background_color=None):
                self.calls.append(("next_part_image", width, height, border, background_color))
                return Image.new("RGB", (width, height))

            def restart(self):
                self.restart_count += 1

        try:
            screen_mod.time.sleep = lambda _: None

            tip_renderer = _FakeThreadRenderer(320, 180)
            renderer_mod.Renderer.get_instance = classmethod(lambda cls: tip_renderer)
            settings_mod.Settings.get_instance = classmethod(lambda cls: _FakeBrightnessSettings(True))
            tip_encoder = _FakeScreenEncoder()
            tip_thread = screen_mod.QRDisplayScreen.QRDisplayThread(
                qr_encoder=tip_encoder,
                qr_brightness=ThreadsafeCounter(initial_value=255),
                tips_start_time=ThreadsafeCounter(initial_value=time.time_ns()),
            )
            tip_renderer.thread = tip_thread
            tip_thread.render_brightness_tip = lambda image: None
            tip_thread.keep_running = True
            tip_thread.run()
            assert tip_encoder.calls[0] == ("part_to_image", 320, 180, 2, "ffffff")

            normal_renderer = _FakeThreadRenderer(320, 180)
            renderer_mod.Renderer.get_instance = classmethod(lambda cls: normal_renderer)
            settings_mod.Settings.get_instance = classmethod(lambda cls: _FakeBrightnessSettings(False))
            normal_encoder = _FakeScreenEncoder()
            normal_thread = screen_mod.QRDisplayScreen.QRDisplayThread(
                qr_encoder=normal_encoder,
                qr_brightness=ThreadsafeCounter(initial_value=255),
                tips_start_time=ThreadsafeCounter(initial_value=0),
            )
            normal_renderer.thread = normal_thread
            normal_thread.keep_running = True
            normal_thread.run()
            assert normal_encoder.calls[0] == ("next_part_image", 320, 180, 2, "ffffff")
        finally:
            renderer_mod.Renderer.get_instance = original_renderer_get_instance
            settings_mod.Settings.get_instance = original_settings_get_instance
            screen_mod.time.sleep = original_screen_sleep

        original_tp_resolve_signer_bin = tp_views_mod._resolve_signer_bin
        original_tp_subprocess_run = tp_views_mod.subprocess.run
        original_tp_loading_screen = tp_views_mod.LoadingScreenThread
        original_tp_default_reader_hint = tp_views_mod.DEFAULT_READER_HINT
        original_tp_masked_error_destination = tp_views_mod._masked_error_destination
        original_tp_debug_error_destination = tp_views_mod._debug_error_destination
        original_tp_extract_error = tp_views_mod._extract_error
        original_tp_map_signer_error_code = tp_views_mod._map_signer_error_code
        original_tp_home_destination = tp_views_mod._tp_home_destination
        tp_views_mod.LoadingScreenThread = _FakeLoadingScreenThread
        tp_views_mod.DEFAULT_READER_HINT = None
        tp_views_mod._masked_error_destination = lambda code: types.SimpleNamespace(kind="masked", code=code)
        tp_views_mod._debug_error_destination = lambda code, detail: types.SimpleNamespace(kind="debug", code=code, detail=detail)
        tp_views_mod._extract_error = lambda stdout, stderr, fallback: fallback
        tp_views_mod._map_signer_error_code = lambda detail: "32"
        tp_views_mod._tp_home_destination = lambda: object()
        with tempfile.TemporaryDirectory(prefix="tp-smoke-signer-") as signer_tmpdir:
            signer_path = Path(signer_tmpdir) / "satochip-signer"
            signer_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            tp_views_mod._resolve_signer_bin = lambda: signer_path

            def _fake_psbt_signer_run(cmd, **kwargs):
                out_psbt = Path(cmd[cmd.index("--out-psbt-base64") + 1])
                out_tx = Path(cmd[cmd.index("--out-tx") + 1])
                out_psbt.write_text("c2lnbmVkLXBzYnQ=", encoding="utf-8")
                out_tx.write_text("deadbeef", encoding="utf-8")
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")

            tp_views_mod.subprocess.run = _fake_psbt_signer_run
            try:
                legacy_payload = "tp:signPsbt-requestId=req-1&data=" + quote(json.dumps({"psbt": "dW5zaWduZWQtcHNidA=="}))
                legacy_view = ToolsTpSignerPsbtRunView(payload=legacy_payload, pin="1234")
                legacy_dest = legacy_view.run()
                assert legacy_view.legacy_tp_request is True
                assert legacy_view.response_mode == "btctx"
                assert legacy_dest.View_cls.__name__ == "ToolsTpSignerQrView"
                assert legacy_dest.view_args["response_text"] == "btctx:deadbeef"

                compat_view = ToolsTpSignerPsbtRunView(
                    psbt_base64="dW5zaWduZWQtcHNidA==",
                    pin="1234",
                    response_mode="btctx",
                )
                compat_dest = compat_view.run()
                assert compat_dest.View_cls.__name__ == "ToolsTpSignerQrView"
                assert compat_dest.view_args["response_text"] == "btctx:deadbeef"

                animated_view = ToolsTpSignerPsbtRunView(
                    psbt_base64="dW5zaWduZWQtcHNidA==",
                    pin="1234",
                    psbt_input_qr_type=QRType.PSBT__BBQR,
                    response_mode="ur",
                )
                animated_dest = animated_view.run()
                assert animated_dest.View_cls.__name__ == "ToolsTpSignerPsbtQrView"
                assert animated_dest.view_args["psbt_base64"] == "c2lnbmVkLXBzYnQ="
                assert animated_dest.view_args["input_qr_type"] == QRType.PSBT__BBQR
                assert animated_dest.view_args["tx_hex"] == "deadbeef"
            finally:
                tp_views_mod._resolve_signer_bin = original_tp_resolve_signer_bin
                tp_views_mod.subprocess.run = original_tp_subprocess_run
                tp_views_mod.LoadingScreenThread = original_tp_loading_screen
                tp_views_mod.DEFAULT_READER_HINT = original_tp_default_reader_hint
                tp_views_mod._masked_error_destination = original_tp_masked_error_destination
                tp_views_mod._debug_error_destination = original_tp_debug_error_destination
                tp_views_mod._extract_error = original_tp_extract_error
                tp_views_mod._map_signer_error_code = original_tp_map_signer_error_code
                tp_views_mod._tp_home_destination = original_tp_home_destination

        personal_payload_address = tp_views_mod._derive_evm_address_from_seed(
            tp_loaded_seed,
            "m/44'/60'/0'/0/0",
        )["address"]
        personal_payload = (
            "tp:personalSign-version=1.0&protocol=TokenPocket&network=ethereum"
            "&chain_id=1&requestId=req-1&data="
            + quote(json.dumps(
                {"message": "hello", "address": personal_payload_address},
                ensure_ascii=False,
                separators=(",", ":"),
            ))
        )

        method_smartcard_view = tp_views_mod.ToolsTpSignerMethodSelectView(payload=personal_payload)
        method_smartcard_capture = {}

        def _method_smartcard_run_screen(*args, **kwargs):
            method_smartcard_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
            return method_smartcard_capture["labels"].index("智能卡签名")

        method_smartcard_view.run_screen = _method_smartcard_run_screen
        dest = method_smartcard_view.run()
        assert method_smartcard_capture["labels"] == ["智能卡签名", "已加载助记词签名"]
        assert dest.View_cls.__name__ == "ToolsTpSignerPinEntryView"
        assert dest.view_args["payload"] == personal_payload

        method_seed_view = tp_views_mod.ToolsTpSignerMethodSelectView(payload=personal_payload)
        method_seed_view.run_screen = lambda *args, **kwargs: next(
            i for i, button in enumerate(kwargs["button_data"])
            if button.button_label == "已加载助记词签名"
        )
        dest = method_seed_view.run()
        assert dest.View_cls.__name__ == "ToolsTpSignerSeedSelectView"
        assert dest.view_args["payload"] == personal_payload

        legacy_seed_method_view = tp_views_mod.ToolsTpSignerMethodSelectView(
            payload="tp:signPsbt-requestId=req-1&data="
            + quote(json.dumps({"psbt": "dW5zaWduZWQtcHNidA=="}, separators=(",", ":")))
        )
        legacy_seed_method_view.run_screen = lambda *args, **kwargs: next(
            i for i, button in enumerate(kwargs["button_data"])
            if button.button_label == "已加载助记词签名"
        )
        dest = legacy_seed_method_view.run()
        assert dest.View_cls.__name__ == "ToolsTpSignerPsbtSeedSelectView"
        assert dest.view_args["psbt_base64"] == "dW5zaWduZWQtcHNidA=="
        assert dest.view_args["response_mode"] == "btctx"

        seed_select_view = tp_views_mod.ToolsTpSignerSeedSelectView(payload=personal_payload)
        seed_select_view.controller.storage.seeds = [
            TransientWordSeed(tp_loaded_seed.mnemonic_display_list),
            tp_loaded_seed,
        ]
        seed_select_capture = {}

        def _seed_select_run_screen(*args, **kwargs):
            seed_select_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
            return 0

        seed_select_view.run_screen = _seed_select_run_screen
        dest = seed_select_view.run()
        assert seed_select_capture["labels"] == [
            f"2. {tp_loaded_seed.get_fingerprint(seed_select_view.settings.get_value(SettingsConstants.SETTING__NETWORK))[:8]}"
        ]
        assert dest.View_cls.__name__ == "ToolsTpSignerSeedRunView"
        assert dest.view_args["seed_num"] == 1

        psbt_seed_select_view = tp_views_mod.ToolsTpSignerPsbtSeedSelectView(
            psbt_base64="dW5zaWduZWQtcHNidA==",
            psbt_input_qr_type=QRType.PSBT__BBQR,
            response_mode="btctx",
        )
        psbt_seed_select_view.controller.psbt = object()
        psbt_seed_select_view.controller.storage.seeds = [tp_loaded_seed]
        psbt_seed_select_view.run_screen = lambda *args, **kwargs: 0
        dest = psbt_seed_select_view.run()
        assert dest.View_cls.__name__ == "PSBTOverviewView"
        assert psbt_seed_select_view.controller.psbt_seed is tp_loaded_seed
        assert psbt_seed_select_view.controller.psbt_input_qr_type == QRType.PSBT__BBQR
        assert psbt_seed_select_view.controller.psbt_response_mode == "btctx"
        assert psbt_seed_select_view.controller.psbt_sign_with_satochip is False
        assert psbt_seed_select_view.controller.psbt_external_signer_flow is False

        original_tp_resolve_signer_bin = tp_views_mod._resolve_signer_bin
        original_tp_preview_module = tp_views_mod._SIGNER_PREVIEW_MODULE
        original_tp_microsd_dir = tp_views_mod.MicroSD.get_microsd_dir
        try:
            tp_views_mod._resolve_signer_bin = lambda: ROOT / "pi-signer-py/bin/pi-signer"
            tp_views_mod._SIGNER_PREVIEW_MODULE = None
            debug_microsd_dir = Path(tempfile.mkdtemp(prefix="tp-okx-debug-"))
            tp_views_mod.MicroSD.get_microsd_dir = staticmethod(lambda: debug_microsd_dir)
            tp_views_mod._WEB3_ETH_SIGNATURE_DEBUG_CACHE.clear()
            seed_sign_outcome = tp_views_mod._sign_tp_payload_with_seed(
                personal_payload,
                tp_loaded_seed,
                "m/44'/60'/0'/0/0",
            )
            response_data = json.loads(seed_sign_outcome.response_payload.split("data=", 1)[1])
            assert seed_sign_outcome.signer_address.lower() == personal_payload_address.lower()
            assert response_data["address"].lower() == personal_payload_address.lower()
            assert response_data["signature"].startswith("0x")
            assert len(response_data["signature"]) == 132
            assert seed_sign_outcome.digest_label == "消息哈希"

            native_wrapper_payload = tp_views_mod._build_web3_native_relay_payload(
                personal_payload,
                {
                    "version": 1,
                    "wallet": "OKX",
                    "wallet_name": "OKX Wallet",
                    "format": "Keystone / AirGap UR",
                    "qr_type": "eth-sign-request",
                    "action": "EVM 签名请求",
                    "response_protocol": "eth-signature",
                    "request_id": "123e4567-e89b-12d3-a456-426614174000",
                    "origin": "OKX Wallet",
                    "data_type": "PERSONAL_MESSAGE",
                    "chain_id": "1",
                    "address": personal_payload_address,
                    "address_path": "m/44'/60'/0'/0/0",
                    "expected_address": personal_payload_address,
                },
            )
            native_outcome = tp_views_mod._sign_tp_payload_with_seed(
                native_wrapper_payload,
                tp_loaded_seed,
                "m/44'/60'/0'/0/0",
            )
            assert native_outcome.response_payload.startswith("ur:eth-signature/")
            native_decoder = URDecoder()
            assert native_decoder.receive_part(native_outcome.response_payload)
            assert native_decoder.is_complete()
            native_root = tp_views_mod._decode_cbor_root_map(native_decoder.result_message().cbor)
            assert native_root[3] == "OKX Wallet"
            assert len(native_root[2]) == 65
            imtoken_request_id_bytes = b"97437vfuqqh6d2o87jeaqrjf78h1wai8ud1p"
            imtoken_response = tp_views_mod._build_eth_signature_ur(
                None,
                bytes(range(65)),
                origin="imToken",
                request_id_cbor={"tag": 37, "value": imtoken_request_id_bytes},
            )
            imtoken_decoder = URDecoder()
            assert imtoken_decoder.receive_part(imtoken_response)
            assert imtoken_decoder.is_complete()
            imtoken_root = tp_views_mod._decode_cbor_root_map(imtoken_decoder.result_message().cbor)
            assert imtoken_root[1] == {"tag": 37, "value": imtoken_request_id_bytes}
            assert imtoken_root[3] == "imToken"
            imtoken_string_request_id = "97437vfuqqh6d2o87jeaqrjf78h1wai8ud1p"
            imtoken_string_response = tp_views_mod._build_eth_signature_ur(
                imtoken_string_request_id,
                bytes(range(65)),
                origin="imToken",
            )
            imtoken_string_decoder = URDecoder()
            assert imtoken_string_decoder.receive_part(imtoken_string_response)
            assert imtoken_string_decoder.is_complete()
            imtoken_string_root = tp_views_mod._decode_cbor_root_map(
                imtoken_string_decoder.result_message().cbor
            )
            assert imtoken_string_root[1] == {
                "tag": 37,
                "value": imtoken_string_request_id.encode("ascii"),
            }
            native_qr_view = tp_views_mod.ToolsTpSignerQrView(response_text=native_outcome.response_payload)
            native_qr_encoder = native_qr_view._get_qr_encoder()
            native_snapshot = tp_views_mod._ensure_eth_signature_debug_snapshot(
                native_outcome.response_payload,
                qr_encoder=native_qr_encoder,
            )
            native_title, native_pages = tp_views_mod._build_tp_signed_response_review_pages(
                native_outcome.response_payload,
                qr_encoder=native_qr_encoder,
            )
            assert native_title == "原生签名结果"
            assert any("不需要再扫回手机" in page for page in native_pages)
            assert all("协议诊断" not in page for page in native_pages)
            assert isinstance(native_qr_encoder, tp_views_mod.ToolsTpEthSignatureQrEncoder)
            assert native_qr_encoder.seq_len() == 1
            assert native_qr_encoder.display_border_modules == 5
            assert native_qr_encoder.display_image_size == (236, 236)
            assert native_qr_encoder.display_min_background_brightness == 240
            assert native_qr_encoder.display_background_color == "ffffff"
            assert qr_helper._normalize_qr_render_data(native_outcome.response_payload) == native_outcome.response_payload.upper()
            assert native_snapshot["request_id"] == "123e4567-e89b-12d3-a456-426614174000"
            assert native_snapshot["cbor_keys"] == [1, 2, 3]
            assert native_snapshot["origin"] == "OKX Wallet"
            assert native_snapshot["signature_len"] == 65
            assert native_snapshot["transaction_type"] == "message"
            assert native_snapshot["request_address"] == personal_payload_address
            assert native_snapshot["derivation_path"] == "m/44'/60'/0'/0/0"
            assert native_snapshot["digest_hex"]
            assert native_snapshot["recovered_address"].lower() == personal_payload_address.lower()
            assert native_snapshot["recovered_matches_request"] is True
            assert native_snapshot["v"] in (0, 1)
            assert native_snapshot["recovery_id"] == native_snapshot["v"]
            assert native_snapshot["signature_output_byte"] == native_snapshot["recovery_id"]
            assert native_snapshot["fragment_count"] == native_qr_encoder.seq_len()
            assert native_snapshot["frame_repeat"] == tp_views_mod.WEB3_ETH_SIGNATURE_QR_FRAME_REPEAT
            assert native_snapshot["frame_char_lengths"] == [len(native_outcome.response_payload)]
            assert native_snapshot["first_frame"] == native_outcome.response_payload
            assert native_snapshot["last_frame"] == native_outcome.response_payload

            no_origin_ur = tp_views_mod._build_eth_signature_ur(
                "123e4567-e89b-12d3-a456-426614174001",
                bytes(range(65)),
                origin=None,
            )
            no_origin_decoder = URDecoder()
            assert no_origin_decoder.receive_part(no_origin_ur)
            assert no_origin_decoder.is_complete()
            no_origin_root = tp_views_mod._decode_cbor_root_map(no_origin_decoder.result_message().cbor)
            assert 3 not in no_origin_root

            legacy_native_tp_payload = tp_views_mod._build_tp_sign_transaction_request(
                address=personal_payload_address,
                tx_data={
                    "to": "0x1111111111111111111111111111111111111111",
                    "value": "0",
                    "data": "0x",
                    "gasLimit": "21000",
                    "nonce": "0",
                    "gasPrice": "1000000000",
                    "type": 0,
                },
                chain_id=1,
                request_id="123e4567-e89b-12d3-a456-426614174002",
                derivation_path="m/44'/60'/0'/0/0",
            )
            legacy_native_wrapper = tp_views_mod._build_web3_native_relay_payload(
                legacy_native_tp_payload,
                {
                    "version": 1,
                    "wallet": "OKX",
                    "wallet_name": "OKX Wallet",
                    "format": "Keystone / AirGap UR",
                    "qr_type": "eth-sign-request",
                    "action": "EVM 签名请求",
                    "response_protocol": "eth-signature",
                    "request_id": "123e4567-e89b-12d3-a456-426614174002",
                    "origin": "OKX Wallet",
                    "data_type": "TRANSACTION",
                    "chain_id": "1",
                    "address": personal_payload_address,
                    "address_path": "m/44'/60'/0'/0/0",
                    "expected_address": personal_payload_address,
                },
            )
            legacy_outcome = tp_views_mod._sign_tp_payload_with_seed(
                legacy_native_wrapper,
                tp_loaded_seed,
                "m/44'/60'/0'/0/0",
            )
            legacy_qr_view = tp_views_mod.ToolsTpSignerQrView(response_text=legacy_outcome.response_payload)
            legacy_encoder = legacy_qr_view._get_qr_encoder()
            legacy_snapshot = tp_views_mod._ensure_eth_signature_debug_snapshot(
                legacy_outcome.response_payload,
                qr_encoder=legacy_encoder,
            )
            assert isinstance(legacy_encoder, tp_views_mod.ToolsTpEthSignatureQrEncoder)
            assert legacy_encoder.seq_len() == 1
            assert legacy_snapshot["request_id"] == "123e4567-e89b-12d3-a456-426614174002"
            assert legacy_snapshot["cbor_keys"] == [1, 2, 3]
            assert legacy_snapshot["origin"] == "OKX Wallet"
            assert legacy_snapshot["transaction_type"] == "legacy"
            assert legacy_snapshot["chain_id"] == 1
            assert legacy_snapshot["request_address"] == personal_payload_address
            assert legacy_snapshot["derivation_path"] == "m/44'/60'/0'/0/0"
            assert legacy_snapshot["digest_hex"]
            assert legacy_snapshot["recovered_address"].lower() == personal_payload_address.lower()
            assert legacy_snapshot["recovered_matches_request"] is True
            assert legacy_snapshot["v"] in (37, 38)
            assert legacy_snapshot["recovery_id"] in (0, 1)
            assert legacy_snapshot["y_parity"] is None
            assert legacy_snapshot["legacy_v_mode"] == "eip155_v"
            assert legacy_snapshot["signature_output_byte"] == legacy_snapshot["v"]
            assert legacy_snapshot["fragment_count"] == legacy_encoder.seq_len()
            assert legacy_snapshot["frame_char_lengths"] == [len(legacy_outcome.response_payload)]
            assert legacy_snapshot["first_frame"] == legacy_outcome.response_payload
            assert legacy_snapshot["last_frame"] == legacy_outcome.response_payload

            arbitrum_legacy_native_tp_payload = tp_views_mod._build_tp_sign_transaction_request(
                address=personal_payload_address,
                tx_data={
                    "to": "0x1111111111111111111111111111111111111111",
                    "value": "0",
                    "data": "0x",
                    "gasLimit": "21000",
                    "nonce": "0",
                    "gasPrice": "1000000000",
                    "type": 0,
                },
                chain_id=42161,
                request_id="123e4567-e89b-12d3-a456-4266141740aa",
                derivation_path="m/44'/60'/0'/0/0",
            )
            arbitrum_legacy_wrapper = tp_views_mod._build_web3_native_relay_payload(
                arbitrum_legacy_native_tp_payload,
                {
                    "version": 1,
                    "wallet": "BITGET",
                    "wallet_name": "Bitget Wallet",
                    "format": "Keystone / AirGap UR",
                    "qr_type": "eth-sign-request",
                    "action": "EVM 签名请求",
                    "response_protocol": "eth-signature",
                    "request_id": "123e4567-e89b-12d3-a456-4266141740aa",
                    "origin": "Bitkeep",
                    "data_type": "TRANSACTION",
                    "chain_id": "42161",
                    "address": personal_payload_address,
                    "address_path": "m/44'/60'/0'/0/0",
                    "expected_address": personal_payload_address,
                },
            )
            arbitrum_legacy_outcome = tp_views_mod._sign_tp_payload_with_seed(
                arbitrum_legacy_wrapper,
                tp_loaded_seed,
                "m/44'/60'/0'/0/0",
            )
            arbitrum_legacy_qr_view = tp_views_mod.ToolsTpSignerQrView(response_text=arbitrum_legacy_outcome.response_payload)
            arbitrum_legacy_encoder = arbitrum_legacy_qr_view._get_qr_encoder()
            arbitrum_legacy_snapshot = tp_views_mod._ensure_eth_signature_debug_snapshot(
                arbitrum_legacy_outcome.response_payload,
                qr_encoder=arbitrum_legacy_encoder,
            )
            assert isinstance(arbitrum_legacy_encoder, tp_views_mod.ToolsTpEthSignatureQrEncoder)
            assert arbitrum_legacy_encoder.seq_len() == 1
            assert arbitrum_legacy_snapshot["transaction_type"] == "legacy"
            assert arbitrum_legacy_snapshot["chain_id"] == 42161
            assert arbitrum_legacy_snapshot["origin"] == "Bitkeep"
            assert arbitrum_legacy_snapshot["signature_len"] == 67
            assert arbitrum_legacy_snapshot["v"] == 84358
            assert arbitrum_legacy_snapshot["recovery_id"] == 1
            assert arbitrum_legacy_snapshot["legacy_v_mode"] == "eip155_v"
            assert arbitrum_legacy_snapshot["signature_output_byte"] == 84358
            assert arbitrum_legacy_snapshot["recovered_address"].lower() == personal_payload_address.lower()
            assert arbitrum_legacy_snapshot["recovered_matches_request"] is True
            assert arbitrum_legacy_snapshot["frame_char_lengths"] == [len(arbitrum_legacy_outcome.response_payload)]
            assert arbitrum_legacy_snapshot["first_frame"] == arbitrum_legacy_outcome.response_payload
            assert arbitrum_legacy_snapshot["last_frame"] == arbitrum_legacy_outcome.response_payload

            typed_native_tp_payload = tp_views_mod._build_tp_sign_transaction_request(
                address=personal_payload_address,
                tx_data={
                    "to": "0x1111111111111111111111111111111111111111",
                    "value": "0",
                    "data": "0x",
                    "gasLimit": "21000",
                    "nonce": "1",
                    "maxFeePerGas": "1000000000",
                    "maxPriorityFeePerGas": "100000000",
                    "type": 2,
                },
                chain_id=1,
                request_id="123e4567-e89b-12d3-a456-426614174003",
                derivation_path="m/44'/60'/0'/0/0",
            )
            typed_native_wrapper = tp_views_mod._build_web3_native_relay_payload(
                typed_native_tp_payload,
                {
                    "version": 1,
                    "wallet": "OKX",
                    "wallet_name": "OKX Wallet",
                    "format": "Keystone / AirGap UR",
                    "qr_type": "eth-sign-request",
                    "action": "EVM 签名请求",
                    "response_protocol": "eth-signature",
                    "request_id": "123e4567-e89b-12d3-a456-426614174003",
                    "origin": "OKX Wallet",
                    "data_type": "TYPED_TRANSACTION",
                    "chain_id": "1",
                    "address": personal_payload_address,
                    "address_path": "m/44'/60'/0'/0/0",
                    "expected_address": personal_payload_address,
                },
            )
            typed_outcome = tp_views_mod._sign_tp_payload_with_seed(
                typed_native_wrapper,
                tp_loaded_seed,
                "m/44'/60'/0'/0/0",
            )
            typed_qr_view = tp_views_mod.ToolsTpSignerQrView(response_text=typed_outcome.response_payload)
            typed_encoder = typed_qr_view._get_qr_encoder()
            typed_snapshot = tp_views_mod._ensure_eth_signature_debug_snapshot(
                typed_outcome.response_payload,
                qr_encoder=typed_encoder,
            )
            assert isinstance(typed_encoder, tp_views_mod.ToolsTpEthSignatureQrEncoder)
            assert typed_encoder.seq_len() == 1
            assert typed_snapshot["transaction_type"] == "eip-1559"
            assert typed_snapshot["chain_id"] == 1
            assert typed_snapshot["cbor_keys"] == [1, 2, 3]
            assert typed_snapshot["origin"] == "OKX Wallet"
            assert typed_snapshot["request_address"] == personal_payload_address
            assert typed_snapshot["derivation_path"] == "m/44'/60'/0'/0/0"
            assert typed_snapshot["digest_hex"]
            assert typed_snapshot["recovered_address"].lower() == personal_payload_address.lower()
            assert typed_snapshot["recovered_matches_request"] is True
            assert typed_snapshot["y_parity"] in (0, 1)
            assert typed_snapshot["v"] is None
            assert typed_snapshot["recovery_id"] is None
            assert typed_snapshot["signature_output_byte"] == typed_snapshot["y_parity"]
            assert typed_snapshot["fragment_count"] == typed_encoder.seq_len()
            assert typed_snapshot["frame_char_lengths"] == [len(typed_outcome.response_payload)]
            assert typed_snapshot["first_frame"] == typed_outcome.response_payload
            assert typed_snapshot["last_frame"] == typed_outcome.response_payload

            raw_request_type_id, raw_request_sign_data = tp_views_mod._derive_web3_native_request_sign_data(
                typed_native_tp_payload
            )
            assert raw_request_type_id == 4
            assert isinstance(raw_request_sign_data, (bytes, bytearray)) and raw_request_sign_data
            raw_request_id = "123e4567-e89b-12d3-a456-426614174004"
            raw_request_ur = _build_web3_eth_sign_request_ur(
                request_id=raw_request_id,
                sign_data=bytes(raw_request_sign_data),
                data_type=raw_request_type_id,
                chain_id=1,
                derivation_path="m/44'/60'/0'/0/0",
                address=personal_payload_address,
                origin="OKX Wallet",
            )
            raw_request_decoder = TpRequestQrDecoder()
            assert raw_request_decoder.add_data(raw_request_ur) == DecodeQRStatus.COMPLETE
            assert raw_request_decoder.get_text().startswith("ur:eth-sign-request/")
            raw_request = tp_views_mod._parse_web3_eth_sign_request_from_payload(raw_request_ur)
            assert raw_request.request_id == raw_request_id
            assert raw_request.data_type == 4
            assert raw_request.chain_id == 1
            assert raw_request.derivation_path == "m/44'/60'/0'/0/0"
            assert raw_request.address.lower() == personal_payload_address.lower()
            assert raw_request.origin == "OKX Wallet"
            assert qr_helper._normalize_qr_render_data(raw_request_ur) == raw_request_ur
            assert tp_views_mod._is_supported_sign_scan_payload(raw_request_ur) is True
            assert tp_views_mod._extract_requested_derivation_path(raw_request_ur) == "m/44'/60'/0'/0/0"
            assert tp_views_mod._resolve_sign_execution_payload(raw_request_ur).startswith("tp:signTransaction-")
            raw_review_title, raw_review_pages = tp_views_mod._build_tp_request_review_pages(raw_request_ur)
            assert raw_review_title == "交易核对"
            assert any("回传格式: eth-signature" in page for page in raw_review_pages)
            raw_outcome = tp_views_mod._sign_tp_payload_with_seed(
                raw_request_ur,
                tp_loaded_seed,
                "m/44'/60'/999'/9/9",
            )
            assert raw_outcome.response_payload.startswith("ur:eth-signature/")
            raw_encoder = GenericStaticQrEncoder(data=raw_outcome.response_payload)
            raw_snapshot = tp_views_mod._ensure_eth_signature_debug_snapshot(
                raw_outcome.response_payload,
                qr_encoder=raw_encoder,
            )
            assert raw_snapshot["request_id"] == raw_request_id
            assert raw_snapshot["cbor_keys"] == [1, 2, 3]
            assert raw_snapshot["origin"] == "OKX Wallet"
            assert raw_snapshot["transaction_type"] == "eip-1559"
            assert raw_snapshot["chain_id"] == 1
            assert raw_snapshot["request_address"].lower() == personal_payload_address.lower()
            assert raw_snapshot["derivation_path"] == "m/44'/60'/0'/0/0"
            assert raw_snapshot["digest_hex"]
            assert raw_snapshot["recovered_address"].lower() == personal_payload_address.lower()
            assert raw_snapshot["recovered_matches_request"] is True
            assert raw_snapshot["y_parity"] in (0, 1)
            assert raw_snapshot["v"] is None
            assert raw_snapshot["signature_output_byte"] == raw_snapshot["y_parity"]

            original_init_satochip = tp_views_mod.seedkeeper_utils.init_satochip
            try:
                web3_card_connector = _FakeSatochipImportConnector()
                web3_card_connector.card_bip32_import_seed(tp_loaded_seed.seed_bytes)
                tp_views_mod.seedkeeper_utils.init_satochip = lambda *args, **kwargs: web3_card_connector

                legacy_sign_data = bytes.fromhex("dc80018252089411111111111111111111111111111111111111118080")
                legacy_web3_request_ur = _build_web3_eth_sign_request_ur(
                    request_id="123e4567-e89b-12d3-a456-4266141740bb",
                    sign_data=legacy_sign_data,
                    data_type=1,
                    chain_id=42161,
                    derivation_path="m/44'/60'/0'/0/0",
                    address=personal_payload_address,
                    origin="Bitkeep",
                )
                parsed_legacy_request = tp_views_mod._parse_web3_eth_sign_request_from_payload(legacy_web3_request_ur)
                legacy_tp_payload = tp_views_mod._build_tp_payload_from_web3_request(parsed_legacy_request)
                legacy_derived_type_id, legacy_derived_sign_data = tp_views_mod._derive_web3_native_request_sign_data(
                    legacy_tp_payload
                )
                assert legacy_derived_type_id == 1
                assert legacy_derived_sign_data != legacy_sign_data

                legacy_native_from_ur = tp_views_mod._build_web3_native_payload_from_ur_text(legacy_web3_request_ur)
                legacy_native_meta = tp_views_mod._extract_web3_native_relay_request(legacy_native_from_ur)
                assert legacy_native_meta["request_data_type_id"] == "1"
                assert legacy_native_meta["request_sign_data_hex"] == legacy_sign_data.hex()

                smartcard_dest = tp_views_mod.ToolsTpSignerRunView(
                    payload=legacy_web3_request_ur,
                    pin="1234",
                ).run()
                assert smartcard_dest.View_cls == tp_views_mod.ToolsTpSignerQrView
                smartcard_response = smartcard_dest.view_args["response_text"]
                smartcard_qr_view = tp_views_mod.ToolsTpSignerQrView(response_text=smartcard_response)
                smartcard_encoder = smartcard_qr_view._get_qr_encoder()
                smartcard_snapshot = tp_views_mod._ensure_eth_signature_debug_snapshot(
                    smartcard_response,
                    qr_encoder=smartcard_encoder,
                )
                assert smartcard_snapshot["transaction_type"] == "legacy"
                assert smartcard_snapshot["chain_id"] == 42161
                assert smartcard_snapshot["origin"] == "Bitkeep"
                assert smartcard_snapshot["signature_len"] == 67
                assert smartcard_snapshot["v"] in (84357, 84358)
                assert smartcard_snapshot["recovery_id"] in (0, 1)
                assert smartcard_snapshot["legacy_v_mode"] == "eip155_v"
                assert smartcard_snapshot["signature_output_byte"] == smartcard_snapshot["v"]
                assert smartcard_snapshot["recovered_address"].lower() == personal_payload_address.lower()
                assert smartcard_snapshot["recovered_matches_request"] is True

                smartcard_native_outcome = tp_views_mod._sign_tp_payload_with_satochip(
                    legacy_native_from_ur,
                    web3_card_connector,
                    "m/44'/60'/0'/0/0",
                )
                smartcard_native_qr_view = tp_views_mod.ToolsTpSignerQrView(
                    response_text=smartcard_native_outcome.response_payload
                )
                smartcard_native_snapshot = tp_views_mod._ensure_eth_signature_debug_snapshot(
                    smartcard_native_outcome.response_payload,
                    qr_encoder=smartcard_native_qr_view._get_qr_encoder(),
                )
                assert smartcard_native_snapshot["digest_hex"] == smartcard_snapshot["digest_hex"]
                assert smartcard_native_snapshot["signature_len"] == 67
                assert smartcard_native_snapshot["v"] == smartcard_snapshot["v"]
                assert smartcard_native_snapshot["signature_output_byte"] == smartcard_native_snapshot["v"]

                typed_smartcard_dest = tp_views_mod.ToolsTpSignerRunView(
                    payload=raw_request_ur,
                    pin="1234",
                ).run()
                assert typed_smartcard_dest.View_cls == tp_views_mod.ToolsTpSignerQrView
                typed_smartcard_snapshot = tp_views_mod._ensure_eth_signature_debug_snapshot(
                    typed_smartcard_dest.view_args["response_text"],
                    qr_encoder=tp_views_mod.ToolsTpSignerQrView(
                        response_text=typed_smartcard_dest.view_args["response_text"]
                    )._get_qr_encoder(),
                )
                assert typed_smartcard_snapshot["transaction_type"] == "eip-1559"
                assert typed_smartcard_snapshot["chain_id"] == 1
                assert typed_smartcard_snapshot["origin"] == "OKX Wallet"
                assert typed_smartcard_snapshot["signature_len"] == 65
                assert typed_smartcard_snapshot["y_parity"] in (0, 1)
                assert typed_smartcard_snapshot["signature_output_byte"] == typed_smartcard_snapshot["y_parity"]
            finally:
                tp_views_mod.seedkeeper_utils.init_satochip = original_init_satochip

            missing_address_tx_payload = tp_views_mod._build_tp_sign_transaction_request(
                address=None,
                tx_data={
                    "to": "0x1111111111111111111111111111111111111111",
                    "value": "0",
                    "data": "0x",
                    "gasLimit": "21000",
                    "nonce": "0",
                    "gasPrice": "1",
                    "type": 0,
                },
                chain_id=1,
                request_id="123e4567-e89b-12d3-a456-426614174000",
                derivation_path="m/44'/60'/0'/0/0",
            )
            missing_address_outcome = tp_views_mod._sign_tp_payload_with_seed(
                missing_address_tx_payload,
                tp_loaded_seed,
                "m/44'/60'/0'/0/0",
            )
            missing_address_response = json.loads(missing_address_outcome.response_payload.split("data=", 1)[1])
            assert missing_address_response["rawTransaction"].startswith("0x")
        finally:
            tp_views_mod._resolve_signer_bin = original_tp_resolve_signer_bin
            tp_views_mod._SIGNER_PREVIEW_MODULE = original_tp_preview_module
            tp_views_mod.MicroSD.get_microsd_dir = original_tp_microsd_dir

        finalize_view = psbt_views_mod.PSBTFinalizeView()
        finalize_view.controller.psbt = types.SimpleNamespace(serialize=lambda: b"psbt")
        finalize_view.controller.psbt_parser = object()
        finalize_view.controller.psbt_sign_with_satochip = False
        finalize_view.controller.psbt_external_signer_flow = True
        finalize_view.controller.psbt_input_qr_type = QRType.PSBT__BBQR
        finalize_view.controller.psbt_response_mode = "btctx"
        finalize_view.run_screen = lambda *args, **kwargs: 0
        dest = finalize_view.run()
        assert dest.View_cls.__name__ == "ToolsTpSignerMethodSelectView"
        assert dest.view_args["psbt_base64"] == "cHNidA=="
        assert dest.view_args["psbt_input_qr_type"] == QRType.PSBT__BBQR
        assert dest.view_args["response_mode"] == "btctx"

        keyboard = Keyboard(
            draw=ImageDraw.Draw(Image.new("RGB", (240, 240))),
            charset="".join(["23456789", "ATJQKCDHS"]),
            charset_rows=["23456789", "ATJQKCDHS"],
            selected_char="A",
            rows=2,
            cols=9,
            rect=(0, 40, 180, 120),
            additional_keys=[],
            render_now=False,
        )
        keyboard.set_selected_key_indices(8, 1)
        assert keyboard.get_selected_key().code == "S"
        assert keyboard.update_from_input(Keyboard.ENTER_TOP) == "9"
        assert keyboard.get_selected_key().code == "9"
        full_deck = " ".join(f"{value}{suit}" for suit in "CDHS" for value in "A23456789TJQK")
        assert mnemonic_generation.card_entropy_bit_length(full_deck) == 232
        assert not mnemonic_generation.card_entropy_is_sufficient("AH QS 9D TC", 12)
        assert mnemonic_generation.card_entropy_is_sufficient(full_deck, 21)
        expected_card_mnemonic = (
            "frost feature cover nurse robust exhibit metal earth link bless shallow "
            "chase trigger second improve main gown message prison column manual"
        ).split()
        assert mnemonic_generation.generate_mnemonic_from_cards(full_deck, 21) == expected_card_mnemonic

        tool_menu_view = ToolsMenuView(include_password_generator=False)
        tool_menu_view.run_screen = lambda *args, **kwargs: next(
            i for i, button in enumerate(kwargs["button_data"]) if button.button_label == "扑克牌创建"
        )
        dest = tool_menu_view.run()
        assert dest.View_cls.__name__ == "ToolsCardEntropyMnemonicLengthView"

        tool_menu_hex_view = ToolsMenuView(include_password_generator=False)
        tool_menu_hex_view.run_screen = lambda *args, **kwargs: next(
            i for i, button in enumerate(kwargs["button_data"]) if button.button_label == "16进制创建"
        )
        dest = tool_menu_hex_view.run()
        assert dest.View_cls.__name__ == "ToolsHexEntropyMnemonicLengthView"

        tp_seed_tools_order_view = ToolsTpSeedToolsView()
        tp_seed_tools_order_capture = {}

        def _tp_seed_tools_order_run_screen(*args, **kwargs):
            tp_seed_tools_order_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
            return 0

        tp_seed_tools_order_view.run_screen = _tp_seed_tools_order_run_screen
        dest = tp_seed_tools_order_view.run()
        assert tp_seed_tools_order_capture["labels"] == [
            "创建助记词",
            "导入助记词",
            "BIP39 查询",
            "管理助记词",
        ]
        assert dest.View_cls.__name__ == "ToolsTpSeedCreateMnemonicView"

        tp_seed_create_order_view = tp_views_mod.ToolsTpSeedCreateMnemonicView()
        tp_seed_create_order_capture = {}

        def _tp_seed_create_order_run_screen(*args, **kwargs):
            tp_seed_create_order_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
            return 0

        tp_seed_create_order_view.run_screen = _tp_seed_create_order_run_screen
        dest = tp_seed_create_order_view.run()
        assert tp_seed_create_order_capture["labels"] == [
            "扑克牌创建",
            "16进制创建",
            "骰子创建",
            "拍照创建",
            "智能卡创建",
        ]
        assert dest.View_cls.__name__ == "ToolsCardEntropyMnemonicLengthView"

        tp_seed_tools_view = tp_views_mod.ToolsTpSeedCreateMnemonicView()
        tp_seed_tools_view.run_screen = lambda *args, **kwargs: next(
            i for i, button in enumerate(kwargs["button_data"]) if button.button_label == "扑克牌创建"
        )
        dest = tp_seed_tools_view.run()
        assert dest.View_cls.__name__ == "ToolsCardEntropyMnemonicLengthView"

        tp_seed_tools_hex_view = tp_views_mod.ToolsTpSeedCreateMnemonicView()
        tp_seed_tools_hex_view.run_screen = lambda *args, **kwargs: next(
            i for i, button in enumerate(kwargs["button_data"]) if button.button_label == "16进制创建"
        )
        dest = tp_seed_tools_hex_view.run()
        assert dest.View_cls.__name__ == "ToolsHexEntropyMnemonicLengthView"

        tp_seed_tools_smartcard_view = tp_views_mod.ToolsTpSeedCreateMnemonicView()
        tp_seed_tools_smartcard_view.run_screen = lambda *args, **kwargs: next(
            i for i, button in enumerate(kwargs["button_data"]) if button.button_label == "智能卡创建"
        )
        dest = tp_seed_tools_smartcard_view.run()
        assert dest.View_cls.__name__ == "ToolsSeedkeeperGenerateMnemonicView"
        assert dest.view_args["return_destination"].View_cls.__name__ == "ToolsTpSeedCreateMnemonicView"

        load_seed_view = LoadSeedView()
        load_seed_capture = {}

        def _load_seed_run_screen(*args, **kwargs):
            load_seed_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
            return RET_CODE__BACK_BUTTON

        load_seed_view.run_screen = _load_seed_run_screen
        dest = load_seed_view.run()
        assert "创建助记词" not in load_seed_capture["labels"]
        assert dest.View_cls.__name__ == "BackStackView"

        pending_storage = SeedStorage()
        canonical_source_words = [
            "ABANDON",
            "ABANDON",
            "ABANDON",
            "ABANDON",
            "ABANDON",
            "ABANDON",
            "ABANDON",
            "ABANDON",
            "ABANDON",
            "ABANDON",
            "ABANDON",
            "ABOUT",
        ]
        expected_canonical_words = [word.lower() for word in canonical_source_words]
        pending_storage.init_pending_mnemonic(num_words=len(canonical_source_words))
        for index, word in enumerate(canonical_source_words):
            pending_storage.update_pending_mnemonic(word, index)
        pending_storage.convert_pending_mnemonic_to_pending_seed()
        assert pending_storage.get_pending_seed().mnemonic_display_list == expected_canonical_words
        summary_text = _format_seedkeeper_generation_complete_text(
            word_count=12,
            label="BIP39-RNG-12w-demo",
            seed_fingerprint="1756f9d4",
            record_fingerprint="a8fe2d76",
        )
        assert "助记词指纹：1756f9d4" in summary_text
        assert "卡内记录指纹：a8fe2d76" in summary_text

        plain_words = (
            "abandon ability able about above absent "
            "absorb abstract absurd abuse access accident"
        )
        hex_payload = len(plain_words.encode("utf-8")).to_bytes(2, "big").hex() + plain_words.encode("utf-8").hex()
        text = _decode_seedkeeper_text_payload(hex_payload)
        words = _parse_seedkeeper_steel_words(text)
        assert len(words) == 12 and words[0] == "abandon" and words[-1] == "accident"
        payload_text = encode_seedkeeper_tp_steel_payload(words, list(range(12)))
        payload_words, payload_indices = decode_seedkeeper_tp_steel_payload(payload_text)
        assert payload_words == words
        assert payload_indices == list(range(12))
        parsed_words, parsed_indices = _parse_seedkeeper_steel_payload(payload_text)
        assert parsed_words == words
        assert parsed_indices == list(range(12))

        headers = [
            {
                "id": 1,
                "type": 0x10,
                "subtype": 0x01,
                "label": "BIP39-RNG-12w-20260405-0800",
                "export_rights": 0x01,
                "fingerprint": "abcd1234",
            },
            {
                "id": 2,
                "type": 0xC0,
                "subtype": 0x00,
                "label": TP_STEEL_SECRET_PREFIX + "demo-deadbeef",
                "export_rights": 0x01,
                "fingerprint": "deadbeef",
            },
        ]
        entries = _seedkeeper_build_entries(headers)
        assert entries[0]["display_label"].startswith("真随机 · ")
        assert entries[1]["display_label"] == "假助记词 · deadbeef"
        mnemonic_entries = _seedkeeper_build_entries(headers, mnemonic_only=True)
        assert len(mnemonic_entries) == 2
        assert mnemonic_entries[0]["display_label"].startswith("真随机 · ")
        assert mnemonic_entries[1]["display_label"] == "假助记词 · deadbeef"
        rng_secret_dict = {
            "type": 0x10,
            "subtype": 0x01,
            "secret": "00112233445566778899aabbccddeeff",
        }
        entropy = bytes.fromhex("00000000000000000000000000000000")
        wordlist_code = 0x00
        passphrase = b""
        payload = (
            bytes([len(entropy)])
            + entropy
            + bytes([wordlist_code])
            + bytes([len(entropy)])
            + entropy
            + bytes([len(passphrase)])
            + passphrase
        )
        rng_secret_dict["secret"] = payload.hex()
        detail = _seedkeeper_decode_secret_detail(entries[0], rng_secret_dict)
        assert detail["title"].startswith("真随机助记词")
        assert detail["words"][0] == "abandon"
        assert len(detail["words"]) == 12
        assert detail["qr_text"].startswith("abandon")
        steel_secret_text = encode_seedkeeper_tp_steel_payload(words, list(range(12)))
        steel_secret_dict = {
            "secret": len(steel_secret_text.encode("utf-8")).to_bytes(2, "big").hex()
            + steel_secret_text.encode("utf-8").hex()
        }
        steel_detail = _seedkeeper_decode_secret_detail(entries[1], steel_secret_dict)
        assert steel_detail["title"] == "假助记词"
        assert steel_detail["words"] == words
        assert steel_detail["bip39_indices"] == list(range(12))

        steel_groups = words_to_plate_groups(words)
        restored_indices = parse_restore_indices(",".join(steel_groups))
        assert restored_indices == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        assert ToolsTpSteelPlateReviewView.EDIT_PAGE.button_label == "编辑词条"
        assert _format_number_groups(steel_groups, 0, entries_per_page=1)[1] == 12
        fake_view = types.SimpleNamespace(controller=_FakeController())
        seed_num = _store_restored_steel_cipher(fake_view, words)
        assert seed_num == 0
        assert isinstance(fake_view.controller.storage.seeds[0], TransientWordSeed)
        assert fake_view.controller.storage.get_steel_encrypted_mnemonic() == words
        assert SeedsMenuView.get_seed_type_label(fake_view.controller.storage.seeds[0]) == "假助记词"

        restored_from_indices_view = types.SimpleNamespace(controller=_FakeController())
        restored_from_indices_words = indices_to_words(list(range(12)))
        seed_num = _store_restored_steel_cipher(
            restored_from_indices_view,
            ["坏词"] * 12,
            indices=list(range(12)),
        )
        assert seed_num == 0
        assert restored_from_indices_view.controller.storage.get_steel_encrypted_mnemonic() == restored_from_indices_words
        assert restored_from_indices_view.controller.storage.get_steel_bip39_indices() == list(range(12))
        assert isinstance(restored_from_indices_view.controller.storage.seeds[0], TransientWordSeed)

        class _FakeConnector:
            def card_get_status(self):
                return None, None, None, {"protocol_minor_version": 2}

            def make_header(self, stype, export_rights, label, subtype=0):
                return f"{stype}|{export_rights}|{label}|{subtype}"

        save_view = SaveToSeedkeeperView(
            words_override=words,
            bip39_indices_override=list(range(12)),
            label_prefix=TP_STEEL_SECRET_PREFIX,
        )
        assert save_view._finalize_label("demo", "deadbeef", prefix=TP_STEEL_SECRET_PREFIX) == "TP-STEEL:demo-deadbeef"
        assert save_view._finalize_label("deadbeef", "deadbeef") == "deadbeef"
        assert "deadbeef" in save_view._build_auto_label("deadbeef")
        secret_dic = save_view._build_text_secret_dic(
            _FakeConnector(),
            encode_seedkeeper_tp_steel_payload(words, list(range(12))),
            TP_STEEL_SECRET_PREFIX + "demo",
        )
        assert secret_dic["header"].startswith("Data|Plaintext export allowed|TP-STEEL:demo")
        stored_payload = bytes(secret_dic["secret_list"][2:]).decode("utf-8")
        decoded_words, decoded_indices = decode_seedkeeper_tp_steel_payload(stored_payload)
        assert decoded_words == words
        assert decoded_indices == list(range(12))
        assert SaveToSeedkeeperView(label_prefix=TP_STEEL_SECRET_PREFIX)._build_auto_label().startswith(TP_STEEL_SECRET_PREFIX)

        bip85_parent = Seed(
            "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split()
        )
        for child_words_len in (12, 18, 24):
            child_words = bip85_parent.get_bip85_child_mnemonic(0, child_words_len).split()
            assert len(child_words) == child_words_len
            assert all(word in bip85_parent.wordlist for word in child_words)

        seed_words_view = SeedWordsView.__new__(SeedWordsView)
        seed_words_view.controller = _FakeController()
        seed_words_view.settings = _FakeSettings()
        seed_words_view.renderer = _FakeRenderer()
        seed_words_view.canvas_width = 240
        seed_words_view.canvas_height = 240
        seed_words_view.controller.storage.seeds = [bip85_parent]
        seed_words_view.seed_num = 0
        seed_words_view.seed = bip85_parent
        seed_words_view.bip85_data = None
        seed_words_view.page_index = 0
        seed_words_view.share_index = None
        seed_words_capture = {}

        def _seed_words_run_screen(*args, **kwargs):
            seed_words_capture["screen_cls"] = getattr(args[0], "__name__", "")
            seed_words_capture["title"] = kwargs["title"]
            seed_words_capture["text"] = kwargs["text"]
            seed_words_capture["buttons"] = [button.button_label for button in kwargs["button_data"]]
            return 0

        seed_words_view.run_screen = _seed_words_run_screen
        dest = seed_words_view.run()
        assert seed_words_capture["screen_cls"] == "ToolsScrollableTextScreen"
        assert seed_words_capture["title"] == "BIP39 序号"
        assert "01. abandon  0000" in seed_words_capture["text"]
        assert seed_words_capture["text"].count("\n") >= 9
        assert seed_words_capture["buttons"] == ["完成"]
        assert dest.View_cls.__name__ == "SeedWordsBackupTestPromptView"

        invalid_seed_words_view = SeedWordsView.__new__(SeedWordsView)
        invalid_seed_words_view.controller = _FakeController()
        invalid_seed_words_view.settings = _FakeSettings()
        invalid_seed_words_view.renderer = _FakeRenderer()
        invalid_seed_words_view.canvas_width = 240
        invalid_seed_words_view.canvas_height = 240
        invalid_seed_words_view.controller.storage.seeds = [TransientWordSeed(["goood"] + words[1:])]
        invalid_seed_words_view.seed_num = 0
        invalid_seed_words_view.seed = invalid_seed_words_view.controller.storage.seeds[0]
        invalid_seed_words_view.bip85_data = None
        invalid_seed_words_view.page_index = 0
        invalid_seed_words_view.share_index = None
        invalid_seed_capture = {}

        def _invalid_seed_run_screen(*args, **kwargs):
            invalid_seed_capture["screen_cls"] = getattr(args[0], "__name__", "")
            invalid_seed_capture["text"] = kwargs["text"]
            invalid_seed_capture["buttons"] = [button.button_label for button in kwargs["button_data"]]
            return 0

        invalid_seed_words_view.run_screen = _invalid_seed_run_screen
        dest = invalid_seed_words_view.run()
        assert invalid_seed_capture["screen_cls"] == "ToolsScrollableTextScreen"
        assert "01. goood" in invalid_seed_capture["text"]
        assert "0000" not in invalid_seed_capture["text"]
        assert invalid_seed_capture["text"].count("\n") >= 9
        assert invalid_seed_capture["buttons"] == ["完成"]
        assert dest.View_cls.__name__ == "SeedWordsBackupTestPromptView"

        indexed_transient_view = SeedWordsView.__new__(SeedWordsView)
        indexed_transient_view.controller = _FakeController()
        indexed_transient_view.settings = _FakeSettings()
        indexed_transient_view.renderer = _FakeRenderer()
        indexed_transient_view.canvas_width = 240
        indexed_transient_view.canvas_height = 240
        indexed_transient_view.controller.storage.seeds = [
            TransientWordSeed(
                ["Enjoy"] + words[1:],
                bip39_word_indices=words_to_indices(words),
            )
        ]
        indexed_transient_view.seed_num = 0
        indexed_transient_view.seed = indexed_transient_view.controller.storage.seeds[0]
        indexed_transient_view.bip85_data = None
        indexed_transient_view.page_index = 0
        indexed_transient_view.share_index = None
        indexed_transient_capture = {}

        def _indexed_transient_run_screen(*args, **kwargs):
            indexed_transient_capture["text"] = kwargs["text"]
            return 0

        indexed_transient_view.run_screen = _indexed_transient_run_screen
        dest = indexed_transient_view.run()
        assert "01. enjoy" in indexed_transient_capture["text"]
        assert "0000" in indexed_transient_capture["text"]
        assert indexed_transient_capture["text"].count("\n") >= 9
        assert dest.View_cls.__name__ == "SeedWordsBackupTestPromptView"

        transient_index_view = SeedWordIndexView(seed_num=0, title="假助记词序号")
        transient_index_view.controller.storage.seeds = [
            TransientWordSeed(
                ["enjoy", "nut", "repair"] + words[3:],
                bip39_word_indices=[11, 12, 13] + words_to_indices(words[3:]),
            )
        ]
        transient_index_capture = {}

        def _transient_index_run_screen(*args, **kwargs):
            transient_index_capture["text"] = kwargs["text"]
            return 0

        transient_index_view.run_screen = _transient_index_run_screen
        dest = transient_index_view.run()
        assert "01. enjoy" in transient_index_capture["text"]
        assert "0011" in transient_index_capture["text"]
        assert transient_index_capture["text"].count("\n") >= 9
        assert dest.View_cls.__name__ == "BackStackView"

        explicit_index_view = SeedWordIndexView(
            words=["goood", "journey", "repair"],
            indices=[11, 12, 13],
            title="显式序号",
        )
        explicit_index_capture = {}

        def _explicit_index_run_screen(*args, **kwargs):
            explicit_index_capture["text"] = kwargs["text"]
            return 0

        explicit_index_view.run_screen = _explicit_index_run_screen
        dest = explicit_index_view.run()
        assert "01. goood" in explicit_index_capture["text"]
        assert "0011" in explicit_index_capture["text"]
        assert dest.View_cls.__name__ == "BackStackView"

        raw_index_review_view = SeedMnemonicRawReviewView(page_index=0, entry_mode="index")
        raw_index_review_view.controller.storage._pending_mnemonic = list(words)
        raw_index_review_capture = {}

        def _raw_index_review_run_screen(*args, **kwargs):
            raw_index_review_capture["screen_cls"] = getattr(args[0], "__name__", "")
            raw_index_review_capture["title"] = kwargs["title"]
            raw_index_review_capture["text"] = kwargs["text"]
            raw_index_review_capture["buttons"] = [button.button_label for button in kwargs["button_data"]]
            return next(i for i, button in enumerate(kwargs["button_data"]) if button.button_label == "按原样导入")

        raw_index_review_view.run_screen = _raw_index_review_run_screen
        dest = raw_index_review_view.run()
        assert raw_index_review_capture["screen_cls"] == "ToolsScrollableTextScreen"
        assert raw_index_review_capture["title"] == "检查 BIP39 序号"
        assert "01. abandon" in raw_index_review_capture["text"]
        assert "0000" in raw_index_review_capture["text"]
        assert raw_index_review_capture["text"].count("\n") >= 9
        assert raw_index_review_capture["buttons"] == ["重新输入", "按原样导入"]
        assert dest.View_cls.__name__ == "SeedsMenuView"

        class _FakeIndexEntryScreen:
            KEYBOARD__DIGITS_BUTTON_TEXT = object()
            responses = iter(["0", "1", "2", "3", "4"])

            def __init__(self, *args, **kwargs):
                pass

            def display(self):
                return {"textToEncode": next(self.responses)}

        orig_index_entry_screen = seed_views_mod.ToolsTextQRTextEntryScreen
        seed_views_mod.ToolsTextQRTextEntryScreen = _FakeIndexEntryScreen
        index_entry_controller = _FakeController()
        index_entry_controller.storage.init_pending_mnemonic(num_words=12)
        try:
            for cur_word_index in range(5):
                index_entry_view = SeedMnemonicIndexEntryView(cur_word_index=cur_word_index)
                index_entry_view.controller = index_entry_controller
                index_entry_view.settings = _FakeSettings()
                index_entry_view.renderer = _FakeRenderer()
                index_entry_view.cur_word_index = cur_word_index
                index_entry_view.wordlist = Seed.get_wordlist(
                    wordlist_language_code=index_entry_view.settings.get_value("wordlist_language")
                )
                index_entry_view.cur_word = index_entry_controller.storage.get_pending_mnemonic_word(cur_word_index)
                index_entry_view.run_screen = lambda *args, **kwargs: 0
                dest = index_entry_view.run()
                assert dest.View_cls.__name__ == "SeedMnemonicIndexEntryView"
                assert dest.view_args["cur_word_index"] == cur_word_index + 1
            assert index_entry_controller.storage.pending_mnemonic[:5] == [Seed.get_wordlist()[i] for i in range(5)]
        finally:
            seed_views_mod.ToolsTextQRTextEntryScreen = orig_index_entry_screen

        class _FakeSeedWordsBackupTestPromptScreen:
            def __init__(self, *args, **kwargs):
                self.button_data = kwargs["button_data"]
                _FakeSeedWordsBackupTestPromptScreen.labels = [button.button_label for button in self.button_data]

            def display(self):
                return 3

        original_prompt_screen = seed_views_mod.seed_screens.SeedWordsBackupTestPromptScreen
        seed_views_mod.seed_screens.SeedWordsBackupTestPromptScreen = _FakeSeedWordsBackupTestPromptScreen
        try:
            prompt_view = SeedWordsBackupTestPromptView(seed_num=0, bip85_data=dict(child_index=0, num_words=12))
            prompt_view.controller.storage.seeds = [bip85_parent]
            dest = prompt_view.run()
            assert "导入到树莓派" in _FakeSeedWordsBackupTestPromptScreen.labels
            assert dest.View_cls.__name__ == "SeedFinalizeView"
            assert prompt_view.controller.storage.pending_seed.mnemonic_display_str.split()[0] in bip85_parent.wordlist
        finally:
            seed_views_mod.seed_screens.SeedWordsBackupTestPromptScreen = original_prompt_screen

        original_offline_signer_mode = os.environ.get("OFFLINE_SIGNER_MODE")
        original_tp_only_mode = os.environ.get("TP_ONLY_MODE")
        try:
            os.environ["OFFLINE_SIGNER_MODE"] = "1"
            os.environ["TP_ONLY_MODE"] = "1"
            finalize_controller = _FakeController()
            finalize_controller.storage.set_pending_seed(Seed(expected_canonical_words))
            finalize_controller.resume_main_flow = False
            finalize_view = SeedFinalizeView.__new__(SeedFinalizeView)
            finalize_view.controller = finalize_controller
            finalize_view.settings = _FakeSettings()
            finalize_view.renderer = _FakeRenderer()
            finalize_view.canvas_width = 240
            finalize_view.canvas_height = 240
            finalize_view.seed = finalize_controller.storage.get_pending_seed()
            finalize_view.fingerprint = finalize_view.seed.get_fingerprint()
            finalize_capture = {}

            def _finalize_run_screen(*args, **kwargs):
                finalize_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
                return finalize_capture["labels"].index("输入密码短语")

            finalize_view.run_screen = _finalize_run_screen
            dest = finalize_view.run()
            assert "输入密码短语" in finalize_capture["labels"]
            assert "扫描密码短语" in finalize_capture["labels"]
            assert dest.View_cls.__name__ == "SeedAddPassphraseView"
        finally:
            if original_offline_signer_mode is None:
                os.environ.pop("OFFLINE_SIGNER_MODE", None)
            else:
                os.environ["OFFLINE_SIGNER_MODE"] = original_offline_signer_mode
            if original_tp_only_mode is None:
                os.environ.pop("TP_ONLY_MODE", None)
            else:
                os.environ["TP_ONLY_MODE"] = original_tp_only_mode

        transient_seed = TransientWordSeed(words)
        loaded_seed_view = ToolsTpLoadedSeedOptionsView.__new__(ToolsTpLoadedSeedOptionsView)
        loaded_seed_view.controller = _FakeController()
        loaded_seed_view.settings = _FakeSettings()
        loaded_seed_view.renderer = _FakeRenderer()
        loaded_seed_view.canvas_width = 240
        loaded_seed_view.canvas_height = 240
        loaded_seed_view.controller.storage.seeds = [transient_seed]
        loaded_seed_view.seed_num = 0
        loaded_seed_view.seed = transient_seed
        loaded_seed_buttons = {}

        def _loaded_seed_run_screen(*args, **kwargs):
            loaded_seed_buttons["labels"] = [button.button_label for button in kwargs["button_data"]]
            return next(
                i for i, button in enumerate(kwargs["button_data"])
                if button.button_label == "写入到 SeedKeeper"
            )

        loaded_seed_view.run_screen = _loaded_seed_run_screen
        dest = loaded_seed_view.run()
        assert dest.View_cls.__name__ == "SaveToSeedkeeperView"
        assert dest.view_args["label_prefix"] == TP_STEEL_SECRET_PREFIX
        assert dest.view_args["words_override"] == words
        assert dest.view_args["bip39_indices_override"] == words_to_indices(words)
        assert "查看助记词" in loaded_seed_buttons["labels"]
        assert "设置密码短语" not in loaded_seed_buttons["labels"]

        bip39_loaded_seed = Seed(expected_canonical_words)
        bip39_loaded_seed_view = ToolsTpLoadedSeedOptionsView.__new__(ToolsTpLoadedSeedOptionsView)
        bip39_loaded_seed_view.controller = _FakeController()
        bip39_loaded_seed_view.settings = _FakeSettings()
        bip39_loaded_seed_view.renderer = _FakeRenderer()
        bip39_loaded_seed_view.canvas_width = 240
        bip39_loaded_seed_view.canvas_height = 240
        bip39_loaded_seed_view.controller.storage.seeds = [bip39_loaded_seed]
        bip39_loaded_seed_view.seed_num = 0
        bip39_loaded_seed_view.seed = bip39_loaded_seed
        bip39_loaded_seed_buttons = {}

        def _bip39_loaded_seed_run_screen(*args, **kwargs):
            bip39_loaded_seed_buttons["labels"] = [button.button_label for button in kwargs["button_data"]]
            return bip39_loaded_seed_buttons["labels"].index("设置密码短语")

        bip39_loaded_seed_view.run_screen = _bip39_loaded_seed_run_screen
        dest = bip39_loaded_seed_view.run()
        assert "设置密码短语" in bip39_loaded_seed_buttons["labels"]
        assert dest.View_cls.__name__ == "ToolsTpSeedPassphraseView"

        passphrase_view = ToolsTpSeedPassphraseView.__new__(ToolsTpSeedPassphraseView)
        passphrase_view.controller = _FakeController()
        passphrase_view.settings = _FakeSettings()
        passphrase_view.renderer = _FakeRenderer()
        passphrase_view.canvas_width = 240
        passphrase_view.canvas_height = 240
        passphrase_seed = Seed(expected_canonical_words)
        passphrase_view.controller.storage.seeds = [passphrase_seed]
        passphrase_view.seed_num = 0
        passphrase_view.seed = passphrase_seed
        passphrase_view.clear_passphrase = False
        passphrase_capture = {"screens": []}

        def _passphrase_run_screen(screen_cls, **kwargs):
            passphrase_capture["screens"].append(getattr(screen_cls, "__name__", ""))
            if getattr(screen_cls, "__name__", "") == "SeedAddPassphraseScreen":
                return {"passphrase": "secret"}
            if getattr(screen_cls, "__name__", "") == "SeedReviewPassphraseScreen":
                return 0
            return 0

        passphrase_view.run_screen = _passphrase_run_screen
        old_fingerprint = passphrase_seed.get_fingerprint()
        dest = passphrase_view.run()
        assert passphrase_seed.passphrase == "secret"
        assert passphrase_seed.get_fingerprint() != old_fingerprint
        assert "SeedReviewPassphraseScreen" in passphrase_capture["screens"]
        assert dest.View_cls.__name__ == "ToolsTpLoadedSeedOptionsView"

        passphrase_loaded_seed_view = ToolsTpLoadedSeedOptionsView.__new__(ToolsTpLoadedSeedOptionsView)
        passphrase_loaded_seed_view.controller = _FakeController()
        passphrase_loaded_seed_view.settings = _FakeSettings()
        passphrase_loaded_seed_view.renderer = _FakeRenderer()
        passphrase_loaded_seed_view.canvas_width = 240
        passphrase_loaded_seed_view.canvas_height = 240
        passphrase_loaded_seed_view.controller.storage.seeds = [passphrase_seed]
        passphrase_loaded_seed_view.seed_num = 0
        passphrase_loaded_seed_view.seed = passphrase_seed
        passphrase_loaded_seed_buttons = {}

        def _passphrase_loaded_seed_run_screen(*args, **kwargs):
            passphrase_loaded_seed_buttons["labels"] = [button.button_label for button in kwargs["button_data"]]
            return passphrase_loaded_seed_buttons["labels"].index("清除密码短语")

        passphrase_loaded_seed_view.run_screen = _passphrase_loaded_seed_run_screen
        dest = passphrase_loaded_seed_view.run()
        assert "修改密码短语" in passphrase_loaded_seed_buttons["labels"]
        assert "清除密码短语" in passphrase_loaded_seed_buttons["labels"]
        assert dest.View_cls.__name__ == "ToolsTpSeedPassphraseView"
        assert dest.view_args["clear_passphrase"] is True

        clear_view = ToolsTpSeedPassphraseView.__new__(ToolsTpSeedPassphraseView)
        clear_view.controller = passphrase_loaded_seed_view.controller
        clear_view.settings = _FakeSettings()
        clear_view.renderer = _FakeRenderer()
        clear_view.canvas_width = 240
        clear_view.canvas_height = 240
        clear_view.seed_num = 0
        clear_view.seed = passphrase_seed
        clear_view.clear_passphrase = True
        clear_view.run_screen = lambda *args, **kwargs: 1 if kwargs.get("button_data") else 0
        dest = clear_view.run()
        assert passphrase_seed.passphrase == ""
        assert dest.View_cls.__name__ == "ToolsTpLoadedSeedOptionsView"

        card_entropy_seed = Seed(
            expected_card_mnemonic,
            entropy_source_label="扑克牌",
            entropy_input_format_label="Card",
            entropy_display_text="AH QS 9D TC 4H 8S KD 2C",
            entropy_qr_text="AH QS 9D TC 4H 8S KD 2C",
            entropy_transform_label="SHA256 后截位",
        )
        entropy_info = card_entropy_seed.get_entropy_display_info()
        assert entropy_info["source_label"] == "扑克牌"
        assert entropy_info["input_format_label"] == "Card"
        assert entropy_info["entropy_bits"] == 224
        assert entropy_info["search_space_label"] == "2^224"
        assert entropy_info["strength_label"] == "很高"

        entropy_info, entropy_pages = seed_views_mod._build_seed_entropy_pages(card_entropy_seed)
        assert entropy_pages[0]["title"] == "熵详情"
        assert "来源: 扑克牌" in entropy_pages[0]["text"]
        assert "难度: 2^224" in entropy_pages[0]["text"]
        assert entropy_pages[1]["title"] == "牌序"
        assert "AH QS 9D TC" in entropy_pages[1]["text"]

        fallback_entropy_seed = Seed("abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split())
        fallback_info = fallback_entropy_seed.get_entropy_display_info()
        assert fallback_info["source_label"] == "从助记词还原"
        assert fallback_info["input_format_label"] == "Hex"
        assert fallback_info["transform_label"] == "BIP39 反推"

        orig_button_list_screen = tools_views_mod.ButtonListScreen
        orig_derive_camera_entropy = tools_views_mod._derive_camera_entropy_bytes
        try:
            class _FixedButtonListScreen:
                def __init__(self, *args, **kwargs):
                    self.button_data = kwargs.get("button_data", [])

                def display(self):
                    return 0

            tools_views_mod.ButtonListScreen = _FixedButtonListScreen
            tools_views_mod._derive_camera_entropy_bytes = (
                lambda previews, final: bytes.fromhex(
                    "00112233445566778899AABBCCDDEEFF00112233445566778899AABBCCDDEEFF"
                )
            )

            camera_entropy_view = ToolsImageEntropyMnemonicLengthView()
            camera_entropy_view.controller.image_entropy_preview_frames = [object(), object()]
            camera_entropy_view.controller.image_entropy_final_image = object()
            camera_entropy_view.controller.create_slip39 = False
            dest = camera_entropy_view.run()
            assert dest.View_cls.__name__ == "SeedWordsWarningView"
            pending_camera_seed = camera_entropy_view.controller.storage.get_pending_seed()
            assert pending_camera_seed is not None
            camera_entropy_info = pending_camera_seed.get_entropy_display_info()
            assert camera_entropy_info["source_label"] == "拍照随机源"
            assert camera_entropy_info["input_format_label"] == "Hex"
            assert camera_entropy_info["transform_label"] == "直接作为随机数"
            assert camera_entropy_info["display_text"] == "00 11 22 33 44 55 66 77 88 99 AA BB CC DD EE FF"
            assert camera_entropy_info["qr_text"] == "00112233445566778899AABBCCDDEEFF"
            assert camera_entropy_view.controller.image_entropy_preview_frames is None
            assert camera_entropy_view.controller.image_entropy_final_image is None
        finally:
            tools_views_mod.ButtonListScreen = orig_button_list_screen
            tools_views_mod._derive_camera_entropy_bytes = orig_derive_camera_entropy

        scroll_canvas = Image.new("RGB", (240, 240), "black")
        scroll_draw = ImageDraw.Draw(scroll_canvas)
        scroll_text = "\n".join(
            f"{index:02d}. abandon  0000" for index in range(1, 25)
        )
        original_renderer_instance = renderer_mod.Renderer._instance
        try:
            renderer_mod.Renderer._instance = types.SimpleNamespace(
                canvas_width=240,
                canvas_height=240,
                draw=scroll_draw,
                canvas=scroll_canvas,
            )
            scrollable_text = ScrollableTextArea(
                image_draw=scroll_draw,
                canvas=scroll_canvas,
                text=scroll_text,
                width=208,
                height=112,
                screen_x=16,
                screen_y=16,
                font_name=GUIConstants.FIXED_WIDTH_FONT_NAME,
                font_size=19,
                background_color="black",
                font_color="white",
                is_text_centered=False,
            )
            assert scrollable_text.max_vertical_scroll > 0
            assert scrollable_text.scroll_surface.height >= (
                scrollable_text.rendered_text_img.height + GUIConstants.COMPONENT_PADDING
            )
            scrollable_text.set_vertical_scroll_y(scrollable_text.max_vertical_scroll)
            assert scrollable_text.vertical_scroll_y == scrollable_text.max_vertical_scroll
            scrollable_text.render()

            expected_top_padding = max(8, max(4, int(GUIConstants.COMPONENT_PADDING / 2)) + 2)
            original_hw_buttons_get_instance = screen_mod.HardwareButtons.get_instance
            screen_mod.HardwareButtons.get_instance = classmethod(lambda cls: types.SimpleNamespace())
            try:
                scrollable_screen = ToolsScrollableTextScreen(
                    title="BIP39 序号",
                    text=scroll_text,
                    text_font_name=GUIConstants.FIXED_WIDTH_FONT_NAME,
                    text_font_size=19,
                )
                assert scrollable_screen.text_component.screen_y - scrollable_screen.body_box[1] == expected_top_padding
                assert scrollable_screen.text_component.height == (
                    scrollable_screen.body_box[3] - scrollable_screen.body_box[1] - expected_top_padding
                )
            finally:
                screen_mod.HardwareButtons.get_instance = original_hw_buttons_get_instance
        finally:
            renderer_mod.Renderer._instance = original_renderer_instance

        steel_cipher_view = ToolsTpSteelCipherOptionsView()
        steel_cipher_view.controller.storage.set_steel_encrypted_mnemonic(words)
        steel_cipher_buttons = {}

        def _steel_cipher_run_screen(*args, **kwargs):
            steel_cipher_buttons["labels"] = [button.button_label for button in kwargs["button_data"]]
            return 0

        steel_cipher_view.run_screen = _steel_cipher_run_screen
        dest = steel_cipher_view.run()
        assert "查看二次加密单词" in steel_cipher_buttons["labels"]
        assert dest.View_cls.__name__ == "ToolsTpSteelCipherWordsView"

        seedkeeper_select_view = ToolsTpSeedkeeperSelectLoadedSeedView()
        seedkeeper_select_view.controller.storage.seeds = [transient_seed]
        seedkeeper_select_view.run_screen = lambda *args, **kwargs: 0
        dest = seedkeeper_select_view.run()
        assert dest.View_cls.__name__ == "SaveToSeedkeeperView"
        assert dest.view_args["label_prefix"] == TP_STEEL_SECRET_PREFIX
        assert dest.view_args["words_override"] == words
        assert dest.view_args["bip39_indices_override"] == words_to_indices(words)

        class _LoadConnector:
            def seedkeeper_list_secret_headers(self):
                return [{"id": 7, "label": TP_STEEL_SECRET_PREFIX + "demo-deadbeef"}]

            def seedkeeper_export_secret(self, sid, _):
                assert sid == 7
                return {
                    "secret": len(payload_text.encode("utf-8")).to_bytes(2, "big").hex()
                    + payload_text.encode("utf-8").hex()
                }

        expected_rng_fingerprint = Seed(
            "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split()
        ).get_fingerprint()

        orig_card_entry_screen = tools_views_mod.ToolsTextQRTextEntryScreen

        class _FakeCardEntryScreen:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs
                _FakeCardEntryScreen.last_kwargs = kwargs

            def display(self):
                return {"textToEncode": full_deck.replace(" ", "")}

        tools_views_mod.ToolsTextQRTextEntryScreen = _FakeCardEntryScreen
        try:
            card_view = ToolsCardEntropyEntryView(word_length=21, initial_value=full_deck)
            dest = card_view.run()
            assert dest.View_cls.__name__ == "ToolsCardEntropyReviewView"
            assert dest.view_args["card_text"] == full_deck
            assert _FakeCardEntryScreen.last_kwargs["quick_space_backspace"] is True
            assert _FakeCardEntryScreen.last_kwargs["custom_charset_rows"] == ["23456789", "ATJQKCDHS"]
            assert _FakeCardEntryScreen.last_kwargs["custom_selected_char"] == "A"

            review_view = ToolsCardEntropyReviewView(
                word_length=21,
                card_text=dest.view_args["card_text"],
                page_num=99,
            )
            expected_review_text = "\n\n".join(review_view._prepare_pages())
            review_capture = {}

            def _review_run_screen(*args, **kwargs):
                review_capture["title"] = kwargs["title"]
                review_capture["text"] = kwargs["text"]
                review_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
                return next(i for i, button in enumerate(kwargs["button_data"]) if button.button_label == "确认生成")

            review_view.run_screen = _review_run_screen
            dest = review_view.run()
            assert review_capture["title"] == "核对牌序"
            assert review_capture["text"] == expected_review_text
            assert "确认生成" in review_capture["labels"]
            assert "继续编辑" in review_capture["labels"]
            assert dest.View_cls.__name__ == "SeedWordsWarningView"
            assert review_view.controller.storage.pending_seed.mnemonic_display_list == expected_card_mnemonic
        finally:
            tools_views_mod.ToolsTextQRTextEntryScreen = orig_card_entry_screen

        class _FakeHexEntryScreen:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs
                _FakeHexEntryScreen.last_kwargs = kwargs

            def display(self):
                return {"textToEncode": "f2a83b9c7d4e1a0b5f6e9d8c7b6a5f4e"}

        tools_views_mod.ToolsTextQRTextEntryScreen = _FakeHexEntryScreen
        try:
            hex_view = ToolsHexEntropyEntryView(word_length=12, initial_value="")
            hex_view.run_screen = lambda *args, **kwargs: 0
            dest = hex_view.run()
            assert dest.View_cls.__name__ == "ToolsHexEntropyReviewView"
            assert dest.view_args["hex_text"] == "F2 A8 3B 9C 7D 4E 1A 0B 5F 6E 9D 8C 7B 6A 5F 4E"
            assert _FakeHexEntryScreen.last_kwargs["quick_space_backspace"] is True
            assert _FakeHexEntryScreen.last_kwargs["custom_charset_rows"] == ["0123456789", "ABCDEF"]
            assert _FakeHexEntryScreen.last_kwargs["custom_selected_char"] == "0"

            hex_review_view = ToolsHexEntropyReviewView(
                word_length=12,
                hex_text=dest.view_args["hex_text"],
                page_num=99,
            )
            expected_hex_review_text = "\n\n".join(hex_review_view._prepare_pages())
            review_capture = {}

            def _hex_review_run_screen(*args, **kwargs):
                review_capture["title"] = kwargs["title"]
                review_capture["text"] = kwargs["text"]
                review_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
                return next(i for i, button in enumerate(kwargs["button_data"]) if button.button_label == "确认生成")

            hex_review_view.run_screen = _hex_review_run_screen
            dest = hex_review_view.run()
            assert review_capture["title"] == "核对 Hex"
            assert review_capture["text"] == expected_hex_review_text
            assert "确认生成" in review_capture["labels"]
            assert "继续编辑" in review_capture["labels"]
            assert dest.View_cls.__name__ == "SeedWordsWarningView"
            assert hex_review_view.controller.storage.pending_seed.mnemonic_display_list == (
                "huge protect deal panel bullet during fog annual crew cattle anchor rival".split()
            )
        finally:
            tools_views_mod.ToolsTextQRTextEntryScreen = orig_card_entry_screen

        orig_init_satochip = tp_views_mod.seedkeeper_utils.init_satochip
        orig_ui_lock_path = tp_views_mod._tp_ui_lock_path
        tmp_lock_dir = Path(tempfile.mkdtemp(prefix="tp-ui-lock-"))

        tp_views_mod.seedkeeper_utils.init_satochip = lambda *a, **k: _LoadConnector()
        tp_views_mod._tp_ui_lock_path = lambda: tmp_lock_dir / "offline-signer-login.json"
        try:
            load_view = ToolsTpSeedkeeperLoadSteelCipherView()
            load_capture = {}

            def _load_run_screen(*args, **kwargs):
                if args and getattr(args[0], "__name__", "") == "ButtonListScreen":
                    load_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
                return 0

            load_view.run_screen = _load_run_screen
            dest = load_view.run()
            assert load_capture["labels"] == ["假助记词 · demo-deadbeef"]
            assert load_view.controller.storage.get_steel_encrypted_mnemonic() == words
            assert load_view.controller.storage.get_steel_bip39_indices() == list(range(12))
            assert any(isinstance(seed, TransientWordSeed) for seed in load_view.controller.storage.seeds)
            assert dest.View_cls.__name__ == "ToolsTpLoadedSeedOptionsView"

            class _SeedKeeperSelectConnector:
                def seedkeeper_list_secret_headers(self):
                    return [
                        {
                            "id": 9,
                            "label": TP_STEEL_SECRET_PREFIX + "demo",
                            "type": 0xC0,
                            "subtype": 0x00,
                            "export_rights": 0x01,
                        }
                    ]

                def seedkeeper_export_secret(self, sid, _):
                    assert sid == 9
                    return {
                        "type": 0xC0,
                        "secret": len(payload_text.encode("utf-8")).to_bytes(2, "big").hex()
                        + payload_text.encode("utf-8").hex(),
                    }

            expected_steel_fingerprint = TransientWordSeed(
                words,
                bip39_word_indices=list(range(12)),
            ).get_fingerprint()

            orig_seed_views_init_satochip = seed_views_mod.seedkeeper_utils.init_satochip
            seed_views_mod.seedkeeper_utils.init_satochip = lambda *a, **k: _SeedKeeperSelectConnector()
            try:
                import_label_capture = {}
                import_view = SeedKeeperSelectView.__new__(SeedKeeperSelectView)
                import_view.controller = _FakeController()
                import_view.settings = _FakeSettings()
                import_view.renderer = _FakeRenderer()
                import_view.canvas_width = 240
                import_view.canvas_height = 240
                import_view.seed = None
                def _import_view_run_screen(*args, **kwargs):
                    if args and getattr(args[0], "__name__", "") == "ButtonListScreen":
                        import_label_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
                        return RET_CODE__BACK_BUTTON
                    return 0
                import_view.run_screen = _import_view_run_screen
                dest = import_view.run()
                assert import_label_capture["labels"] == [f"假助记词 · {expected_steel_fingerprint}"]
                assert dest.View_cls.__name__ == "BackStackView"
            finally:
                seed_views_mod.seedkeeper_utils.init_satochip = orig_seed_views_init_satochip

            class _SeedKeeperSelectFingerprintConnector:
                def seedkeeper_list_secret_headers(self):
                    return [
                        {
                            "id": 1,
                            "label": "BIP39-RNG-12w-demo",
                            "type": 0x10,
                            "subtype": 0x01,
                            "export_rights": 0x01,
                        }
                    ]

                def seedkeeper_export_secret(self, sid, _):
                    assert sid == 1
                    return rng_secret_dict

            seed_views_mod.seedkeeper_utils.init_satochip = lambda *a, **k: _SeedKeeperSelectFingerprintConnector()
            try:
                import_label_capture = {}
                import_view = SeedKeeperSelectView.__new__(SeedKeeperSelectView)
                import_view.controller = _FakeController()
                import_view.settings = _FakeSettings()
                import_view.renderer = _FakeRenderer()
                import_view.canvas_width = 240
                import_view.canvas_height = 240
                import_view.seed = None

                def _import_rng_run_screen(*args, **kwargs):
                    if args and getattr(args[0], "__name__", "") == "ButtonListScreen":
                        import_label_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
                        return RET_CODE__BACK_BUTTON
                    return 0

                import_view.run_screen = _import_rng_run_screen
                dest = import_view.run()
                assert import_label_capture["labels"] == [f"真随机 · {expected_rng_fingerprint}"]
                assert dest.View_cls.__name__ == "BackStackView"
            finally:
                seed_views_mod.seedkeeper_utils.init_satochip = orig_seed_views_init_satochip

            class _MnemonicConnector:
                def __init__(self):
                    self.deleted = []

                def card_get_status(self):
                    return None, None, None, {"protocol_minor_version": 2}

                def seedkeeper_list_secret_headers(self):
                    return headers

                def seedkeeper_export_secret(self, sid, _):
                    assert sid == 1
                    return rng_secret_dict

                def seedkeeper_reset_secret(self, sid):
                    self.deleted.append(sid)

            mnemonic_connector = _MnemonicConnector()
            import seedsigner.views.tools_views as tools_views_mod

            orig_tools_init_satochip = tools_views_mod.seedkeeper_utils.init_satochip
            tools_views_mod.seedkeeper_utils.init_satochip = lambda *a, **k: mnemonic_connector
            try:
                response_queue = iter([0, RET_CODE__BACK_BUTTON, RET_CODE__BACK_BUTTON])
                mnemonic_label_capture = {}

                def _run_screen(*args, **kwargs):
                    if args and getattr(args[0], "__name__", "") == "ButtonListScreen":
                        mnemonic_label_capture["labels"] = [button.button_label for button in kwargs["button_data"]]
                    if args and getattr(args[0], "__name__", "") == "QRDisplayScreen":
                        return 0
                    return next(response_queue)

                view = ToolsSeedkeeperViewSecretsView()
                view.run_screen = _run_screen
                dest = view.run()
                assert mnemonic_label_capture["labels"][0] == f"真随机 · {expected_rng_fingerprint}"
                assert dest.View_cls.__name__ == "BackStackView"
                assert mnemonic_connector.deleted == []
            finally:
                tools_views_mod.seedkeeper_utils.init_satochip = orig_tools_init_satochip

            tp_views_mod._save_tp_ui_password("246824")
            assert tp_views_mod._verify_tp_ui_password("246824") is True
            assert tp_views_mod._verify_tp_ui_password("135790") is False
            assert oct((tmp_lock_dir / "offline-signer-login.json").stat().st_mode & 0o777) == "0o600"
            (tmp_lock_dir / "offline-signer-login.json").unlink()
            assert tp_views_mod._verify_tp_ui_password("246824") is True
        finally:
            tp_views_mod.seedkeeper_utils.init_satochip = orig_init_satochip
            tp_views_mod._tp_ui_lock_path = orig_ui_lock_path

        raw_review_words = [
            " Enjoy ",
            "ABILITY",
            "able",
            "about",
            "above",
            "absent",
            "absorb",
            "abstract",
            "absurd",
            "abuse",
            "access",
            "accident",
        ]
        raw_review_view = SeedMnemonicRawReviewView(page_index=2, entry_mode="word")
        raw_review_view.controller.storage._pending_mnemonic = list(raw_review_words)

        class _FakeRawReviewScreen:
            def __init__(self, *args, **kwargs):
                self.button_data = kwargs["button_data"]

            def display(self):
                return next(
                    index for index, button in enumerate(self.button_data)
                    if button.button_label == "按原样导入"
                )

        raw_review_capture = {}

        def _raw_review_run_screen(*args, **kwargs):
            raw_review_capture["screen_cls"] = getattr(args[0], "__name__", "")
            raw_review_capture["text"] = kwargs["text"]
            return next(
                index for index, button in enumerate(kwargs["button_data"])
                if button.button_label == "按原样导入"
            )

        raw_review_view.run_screen = _raw_review_run_screen
        dest = raw_review_view.run()
        assert raw_review_capture["screen_cls"] == "ToolsScrollableTextScreen"
        assert "09. absurd" in raw_review_capture["text"]
        assert "0008" in raw_review_capture["text"]
        assert dest.View_cls.__name__ == "SeedsMenuView"
        assert raw_review_view.controller.storage.seeds[0].mnemonic_display_list[:2] == ["enjoy", "ability"]
        assert raw_review_view.controller.storage.seeds[0].get_bip39_word_indices()[:2] == words_to_indices(["enjoy", "ability"])
        assert raw_review_view.controller.storage.pending_mnemonic == []

        valid_words = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split()
        shift_values = [8, 7, 6, 7, 6, 7, 7, 3, 5, 2, 4, 2]
        shift_entries = [f"+{value}" for value in shift_values]
        reverse_shift_entries = [f"-{value}" for value in shift_values]
        encrypted_words = shift_mnemonic(valid_words, shift_values, encrypt=True, operators=["+"] * len(valid_words))

        raw_shift_source_view = ToolsTpSteelShiftReviewView(mode="decrypt_seed", entries=shift_entries, seed_num=0, page_index=2)
        raw_shift_source_view.controller.storage.seeds = [TransientWordSeed(["Enjoy"] + encrypted_words[1:])]
        assert raw_shift_source_view._source_words()[0] == "enjoy"

        literal_preview_view = ToolsTpSteelShiftReviewView(mode="decrypt_seed", entries=shift_entries, seed_num=0, page_index=0)
        literal_preview_view.controller.storage.seeds = [TransientWordSeed(valid_words, bip39_word_indices=words_to_indices(valid_words))]
        literal_preview_view.run_screen = lambda *args, **kwargs: next(
            index for index, button in enumerate(kwargs["button_data"])
            if button.button_label == "预览结果序号"
        )
        dest = literal_preview_view.run()
        assert dest.View_cls.__name__ == "SeedWordIndexView"
        assert dest.view_args["indices"][0] == 8

        decrypt_view = ToolsTpSteelShiftReviewView(mode="decrypt_seed", entries=reverse_shift_entries, seed_num=0, page_index=2)
        decrypt_view.controller.storage.seeds = [TransientWordSeed(encrypted_words)]
        decrypt_view.run_screen = lambda *args, **kwargs: next(
            index for index, button in enumerate(kwargs["button_data"])
            if button.button_label == "确认执行"
        )
        dest = decrypt_view.run()
        assert dest.View_cls.__name__ == "ToolsTpLoadedSeedOptionsView"
        assert decrypt_view.controller.storage.seeds[-1].mnemonic_display_list == valid_words

        indexed_decrypt_view = ToolsTpSteelShiftReviewView(mode="decrypt_seed", entries=reverse_shift_entries, seed_num=0, page_index=2)
        indexed_decrypt_view.controller.storage.seeds = [
            TransientWordSeed(
                ["goood"] + encrypted_words[1:],
                bip39_word_indices=words_to_indices(encrypted_words),
            )
        ]
        indexed_decrypt_view.run_screen = lambda *args, **kwargs: next(
            index for index, button in enumerate(kwargs["button_data"])
            if button.button_label == "确认执行"
        )
        dest = indexed_decrypt_view.run()
        assert dest.View_cls.__name__ == "ToolsTpLoadedSeedOptionsView"
        assert indexed_decrypt_view.controller.storage.seeds[-1].mnemonic_display_list == valid_words

        steel_plate_words_view = ToolsTpSteelPlateWordsView(page_index=0)
        fake_plate_words = ["goood"] + words[1:]
        fake_plate_indices = words_to_indices(words)
        steel_plate_words_view.controller.storage.set_steel_encrypted_mnemonic(
            fake_plate_words,
            bip39_indices=fake_plate_indices,
        )
        steel_plate_words_view.controller.storage.set_steel_plate_groups(
            indices_to_plate_groups(fake_plate_indices)
        )
        steel_plate_capture = {}

        def _steel_plate_run_screen(*args, **kwargs):
            steel_plate_capture["text"] = kwargs["text"]
            steel_plate_capture["title"] = kwargs["title"]
            return next(
                i for i, button in enumerate(kwargs["button_data"])
                if button.button_label == "完成"
            )

        steel_plate_words_view.run_screen = _steel_plate_run_screen
        dest = steel_plate_words_view.run()
        assert steel_plate_capture["title"] == "打孔位"
        assert "01 词" in steel_plate_capture["text"]
        assert "序号: 0000" in steel_plate_capture["text"]
        assert "无需打孔" in steel_plate_capture["text"]
        assert "○" not in steel_plate_capture["text"]
        assert dest.View_cls.__name__ == "ToolsTpSteelCipherOptionsView"

        plate_title, plate_text = tp_views_mod._format_plate_word_page(
            ["demo"],
            ["8 32 256"],
            0,
            indices=[296],
        )
        assert plate_title == "01 词"
        assert "序号: 0296" in plate_text
        assert "打孔位:" in plate_text
        assert "8 32" in plate_text
        assert "256" in plate_text
        assert "○" not in plate_text

        class _FakeShiftEntryScreen:
            KEYBOARD__DIGITS_BUTTON_TEXT = object()

            def __init__(self, *args, **kwargs):
                pass

            def display(self):
                return {"is_back_button": True}

        orig_shift_entry_screen = tp_views_mod.ToolsTextQRTextEntryScreen
        tp_views_mod.ToolsTextQRTextEntryScreen = _FakeShiftEntryScreen
        invalid_source_view = ToolsTpSteelShiftInputView(mode="decrypt_seed", seed_num=0, entries=["+1"] * 12, word_index=0)
        invalid_source_view.controller.storage.seeds = [TransientWordSeed(["goood"] + valid_words[1:])]
        try:
            invalid_source_view.run_screen = lambda *args, **kwargs: 0
            dest = invalid_source_view.run()
            assert dest.View_cls.__name__ == "ToolsTpLoadedSeedOptionsView"
        finally:
            tp_views_mod.ToolsTextQRTextEntryScreen = orig_shift_entry_screen

    finally:
        view_mod.View._initialize = orig_init

    print("smoke_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
