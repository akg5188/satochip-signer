#!/usr/bin/env python3
import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = ROOT / "seedsigner-os/opt/rootfs-overlay/opt/src"
VENDOR = ROOT / "pi-signer-py/vendor"
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
            SeedWordIndexView,
            SeedWordsView,
            SeedsMenuView,
            SeedWordsBackupTestPromptView,
        )
        from seedsigner.views.tp_views import (
            TP_STEEL_SECRET_PREFIX,
            ToolsTpLoadedSeedOptionsView,
            ToolsTpSatochipToolsView,
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
        from seedsigner.models.mnemonic_steel import (
            indices_to_words,
            indices_to_plate_groups,
            parse_restore_indices,
            shift_mnemonic,
            words_to_indices,
            words_to_plate_groups,
        )
        from seedsigner.models.seed import Seed, TransientWordSeed
        from seedsigner.models.seed_storage import SeedStorage
        from seedsigner.gui.screens.seed_screens import _normalize_review_mnemonic_id
        from seedsigner.views.tools_views import (
            ToolsSeedkeeperView,
            ToolsSeedkeeperViewSecretsView,
            ToolsSmartcardMenuView,
            ToolsSatochipFactoryResetView,
            ToolsSatochipDIYView,
            _format_seedkeeper_generation_complete_text,
            _seedkeeper_build_entries,
            _seedkeeper_decode_secret_detail,
        )
        from seedsigner.gui.components import reflow_text_into_pages
        import seedsigner.views.seed_views as seed_views_mod
        import seedsigner.views.tp_views as tp_views_mod

        tp_views_mod.LoadingScreenThread = _FakeLoadingScreenThread
        screen_mod.LoadingScreenThread = _FakeLoadingScreenThread

        assert ToolsTpSmartcardToolsView.SATOCHIP_TOOLS.button_label == "Satochip 功能"
        assert ToolsTpSmartcardToolsView.SEEDKEEPER_TOOLS.button_label == "SeedKeeper 功能"
        assert "/mnt/microsd" not in str(tp_views_mod._tp_ui_lock_path())
        assert ToolsTpSatochipToolsView.IMPORT_LOADED_SEED.button_label == "写入已加载助记词到 Satochip"
        assert ToolsTpSeedkeeperToolsView.GENERATE_MNEMONIC.button_label == "卡上真随机创建助记词"
        assert ToolsTpSeedkeeperToolsView.SAVE_STEEL_CIPHER.button_label == "保存二次加密助记词到 SeedKeeper"
        assert ToolsTpSeedkeeperToolsView.LOAD_STEEL_CIPHER.button_label == "从 SeedKeeper 加载二次加密助记词"
        assert not hasattr(ToolsTpSeedToolsView, "STEEL_RESTORE")
        assert not hasattr(ToolsTpSeedToolsView, "STEEL_SCAN")
        assert LoadSeedView.TYPE_STEEL_RESTORE.button_label == "从钢板数字恢复二次助记词"
        assert ToolsTpUiLockView.SETUP.button_label == "设置登录密码"
        assert ToolsTpUiLockView.UNLOCK.button_label == "输入登录密码"
        assert ToolsSeedkeeperView.VIEW_SECRETS.button_label == "查看和管理卡内助记词"
        assert ToolsSeedkeeperView.FACTORY_RESET.button_label == "高风险：重置 SeedKeeper"
        assert not hasattr(ToolsSmartcardMenuView, "Satochip_DIY")
        assert ToolsSatochipFactoryResetView.LEGACY_RESET.button_label == "拔插卡恢复出厂（推荐）"
        assert ToolsSatochipFactoryResetView.BLOCKING_RESET.button_label == "锁死 PIN/PUK 恢复出厂"
        assert ToolsSatochipDIYView.MANAGE_KEYS.button_label == "管理卡默认密钥"
        assert ToolsSatochipDIYView.BUILD_APPLETS.button_label == "编译 CAP 安装包"
        assert ToolsSatochipDIYView.INSTALL_APPLET.button_label == "安装卡片程序"
        assert ToolsSatochipDIYView.UNINSTALL_APPLET.button_label == "卸载卡片程序"
        assert _normalize_review_mnemonic_id("") == "（空）"
        assert _normalize_review_mnemonic_id(None) == "（空）"
        assert _normalize_review_mnemonic_id("  ab  cd  ") == "\u2589\u2589ab\u2589\u2589cd\u2589\u2589"
        assert reflow_text_into_pages("abc", width=40, height=1, font_name="Inconsolata-SemiBold", font_size=18) == ["abc"]
        assert _canonicalize_bip39_words([" Enjoy ", "ABILITY"]) == ["enjoy", "ability"]
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
        assert ToolsTpSteelPlateReviewView.EDIT_PAGE.button_label == "编辑当前页"
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
        assert seed_words_capture["screen_cls"] == "ToolsFormattedTextScreen"
        assert seed_words_capture["title"] == "BIP39 序号：1/3"
        assert "01. abandon  0000" in seed_words_capture["text"]
        assert "04. abandon  0000" in seed_words_capture["text"]
        assert seed_words_capture["buttons"] == ["下一页"]
        assert dest.View_cls.__name__ == "SeedWordsView"
        assert dest.view_args["page_index"] == 1

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
        assert invalid_seed_capture["screen_cls"] == "ToolsFormattedTextScreen"
        assert "01. goood" in invalid_seed_capture["text"]
        assert "0000" not in invalid_seed_capture["text"]
        assert invalid_seed_capture["buttons"] == ["下一页"]
        assert dest.View_cls.__name__ == "SeedWordsView"
        assert dest.view_args["page_index"] == 1

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
        assert "01. Enjoy" in indexed_transient_capture["text"]
        assert "0000" in indexed_transient_capture["text"]
        assert dest.View_cls.__name__ == "SeedWordsView"
        assert dest.view_args["page_index"] == 1

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
        assert dest.View_cls.__name__ == "SeedWordIndexView"
        assert dest.view_args["page_index"] == 1

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
            return next(
                i for i, button in enumerate(kwargs["button_data"])
                if button.button_label == "下一页"
            )

        raw_index_review_view.run_screen = _raw_index_review_run_screen
        dest = raw_index_review_view.run()
        assert raw_index_review_capture["screen_cls"] == "ToolsFormattedTextScreen"
        assert raw_index_review_capture["title"] == "检查 BIP39 序号：1/3"
        assert "01. abandon" in raw_index_review_capture["text"]
        assert "0000" in raw_index_review_capture["text"]
        assert raw_index_review_capture["buttons"] == ["下一页"]
        assert dest.View_cls.__name__ == "SeedMnemonicRawReviewView"
        assert dest.view_args["page_index"] == 1

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
                if button.button_label == "写入当前助记词到 SeedKeeper"
            )

        loaded_seed_view.run_screen = _loaded_seed_run_screen
        dest = loaded_seed_view.run()
        assert dest.View_cls.__name__ == "SaveToSeedkeeperView"
        assert dest.view_args["label_prefix"] == TP_STEEL_SECRET_PREFIX
        assert dest.view_args["words_override"] == words
        assert dest.view_args["bip39_indices_override"] == words_to_indices(words)
        assert "查看 BIP39 序号" in loaded_seed_buttons["labels"]

        steel_cipher_view = ToolsTpSteelCipherOptionsView()
        steel_cipher_view.controller.storage.set_steel_encrypted_mnemonic(words)
        steel_cipher_buttons = {}

        def _steel_cipher_run_screen(*args, **kwargs):
            steel_cipher_buttons["labels"] = [button.button_label for button in kwargs["button_data"]]
            return 0

        steel_cipher_view.run_screen = _steel_cipher_run_screen
        dest = steel_cipher_view.run()
        assert "查看 BIP39 序号" in steel_cipher_buttons["labels"]
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
        assert raw_review_capture["screen_cls"] == "ToolsFormattedTextScreen"
        assert "09. absurd" in raw_review_capture["text"]
        assert "0008" in raw_review_capture["text"]
        assert dest.View_cls.__name__ == "SeedsMenuView"
        assert raw_review_view.controller.storage.seeds[0].mnemonic_display_list[:2] == ["Enjoy", "ABILITY"]
        assert raw_review_view.controller.storage.seeds[0].get_bip39_word_indices()[:2] == words_to_indices(["Enjoy", "ABILITY"])
        assert raw_review_view.controller.storage.pending_mnemonic == []

        valid_words = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split()
        shift_values = [8, 7, 6, 7, 6, 7, 7, 3, 5, 2, 4, 2]
        shift_entries = [f"+{value}" for value in shift_values]
        reverse_shift_entries = [f"-{value}" for value in shift_values]
        encrypted_words = shift_mnemonic(valid_words, shift_values, encrypt=True, operators=["+"] * len(valid_words))

        raw_shift_source_view = ToolsTpSteelShiftReviewView(mode="decrypt_seed", entries=shift_entries, seed_num=0, page_index=2)
        raw_shift_source_view.controller.storage.seeds = [TransientWordSeed(["Enjoy"] + encrypted_words[1:])]
        assert raw_shift_source_view._source_words()[0] == "Enjoy"

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
                if button.button_label == "下一页"
            )

        steel_plate_words_view.run_screen = _steel_plate_run_screen
        dest = steel_plate_words_view.run()
        assert steel_plate_capture["title"] == "打孔位：1/12"
        assert "序号 0000" in steel_plate_capture["text"]
        assert "无需打孔" in steel_plate_capture["text"]
        assert "○" not in steel_plate_capture["text"]
        assert "1 2 4 8 16 32" not in steel_plate_capture["text"]
        assert dest.View_cls.__name__ == "ToolsTpSteelPlateWordsView"
        assert dest.view_args["page_index"] == 1

        plate_title, plate_text = tp_views_mod._format_plate_word_page(
            ["demo"],
            ["8 32 256"],
            0,
            indices=[296],
        )
        assert plate_title == "第 01 词"
        assert "序号 0296" in plate_text
        assert "8 32" in plate_text
        assert "256" in plate_text
        assert "○" not in plate_text
        assert "1 2 4 8 16 32" not in plate_text

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
