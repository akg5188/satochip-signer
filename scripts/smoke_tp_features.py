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
        self._steel = []
        self._plate = []

    def has_steel_encrypted_mnemonic(self):
        return bool(self._steel)

    def get_steel_encrypted_mnemonic(self):
        return list(self._steel)

    def set_steel_encrypted_mnemonic(self, words, **kwargs):
        self._steel = list(words)

    def set_steel_plate_groups(self, groups):
        self._plate = list(groups)


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
        from seedsigner.views.seed_views import SaveToSeedkeeperView
        from seedsigner.views.tp_views import (
            TP_STEEL_SECRET_PREFIX,
            ToolsTpSatochipToolsView,
            ToolsTpSeedkeeperLoadSteelCipherView,
            ToolsTpSeedkeeperToolsView,
            ToolsTpSmartcardToolsView,
            ToolsTpUiLockView,
            _decode_seedkeeper_text_payload,
            _parse_seedkeeper_steel_words,
        )
        import seedsigner.views.tp_views as tp_views_mod

        tp_views_mod.LoadingScreenThread = _FakeLoadingScreenThread

        assert ToolsTpSmartcardToolsView.SATOCHIP_TOOLS.button_label == "Satochip 功能"
        assert ToolsTpSmartcardToolsView.SEEDKEEPER_TOOLS.button_label == "SeedKeeper 功能"
        assert ToolsTpSatochipToolsView.IMPORT_LOADED_SEED.button_label == "写入已加载助记词到 Satochip"
        assert ToolsTpSeedkeeperToolsView.GENERATE_MNEMONIC.button_label == "卡上真随机创建助记词"
        assert ToolsTpSeedkeeperToolsView.SAVE_STEEL_CIPHER.button_label == "保存二次加密助记词到 SeedKeeper"
        assert ToolsTpSeedkeeperToolsView.LOAD_STEEL_CIPHER.button_label == "从 SeedKeeper 加载二次加密助记词"
        assert ToolsTpUiLockView.SETUP.button_label == "设置登录密码"
        assert ToolsTpUiLockView.UNLOCK.button_label == "输入登录密码"

        plain_words = (
            "abandon ability able about above absent "
            "absorb abstract absurd abuse access accident"
        )
        hex_payload = len(plain_words.encode("utf-8")).to_bytes(2, "big").hex() + plain_words.encode("utf-8").hex()
        text = _decode_seedkeeper_text_payload(hex_payload)
        words = _parse_seedkeeper_steel_words(text)
        assert len(words) == 12 and words[0] == "abandon" and words[-1] == "accident"

        class _FakeConnector:
            def card_get_status(self):
                return None, None, None, {"protocol_minor_version": 2}

            def make_header(self, stype, export_rights, label, subtype=0):
                return f"{stype}|{export_rights}|{label}|{subtype}"

        save_view = SaveToSeedkeeperView(words_override=words, label_prefix=TP_STEEL_SECRET_PREFIX)
        secret_dic = save_view._build_text_secret_dic(_FakeConnector(), " ".join(words), TP_STEEL_SECRET_PREFIX + "demo")
        assert secret_dic["header"].startswith("Data|Plaintext export allowed|TP-STEEL:demo")
        assert bytes(secret_dic["secret_list"][2:]).decode("utf-8") == " ".join(words)

        class _LoadConnector:
            def seedkeeper_list_secret_headers(self):
                return [{"id": 7, "label": TP_STEEL_SECRET_PREFIX + "demo"}]

            def seedkeeper_export_secret(self, sid, _):
                assert sid == 7
                return {"secret": hex_payload}

        orig_init_satochip = tp_views_mod.seedkeeper_utils.init_satochip
        orig_ui_lock_path = tp_views_mod._tp_ui_lock_path
        tmp_lock_dir = Path(tempfile.mkdtemp(prefix="tp-ui-lock-"))

        tp_views_mod.seedkeeper_utils.init_satochip = lambda *a, **k: _LoadConnector()
        tp_views_mod._tp_ui_lock_path = lambda: tmp_lock_dir / "offline-signer-login.json"
        try:
            load_view = ToolsTpSeedkeeperLoadSteelCipherView()
            load_view.run_screen = lambda *args, **kwargs: 0
            dest = load_view.run()
            assert load_view.controller.storage.get_steel_encrypted_mnemonic() == words
            assert dest.View_cls.__name__ == "ToolsTpSteelCipherOptionsView"

            tp_views_mod._save_tp_ui_password("246824")
            assert tp_views_mod._verify_tp_ui_password("246824") is True
            assert tp_views_mod._verify_tp_ui_password("135790") is False
        finally:
            tp_views_mod.seedkeeper_utils.init_satochip = orig_init_satochip
            tp_views_mod._tp_ui_lock_path = orig_ui_lock_path
    finally:
        view_mod.View._initialize = orig_init

    print("smoke_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
