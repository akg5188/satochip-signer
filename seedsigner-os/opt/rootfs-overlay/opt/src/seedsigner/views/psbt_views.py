import base64
from gettext import gettext as _

from binascii import hexlify
from binascii import hexlify

from embit import bip32
import logging

from seedsigner.helpers.signature_health import (
    analyze_psbt_signature_health,
    analyze_tx_signature_health,
    build_signature_health_lines,
)
from seedsigner.models.psbt_parser import PSBTParser
from seedsigner.models.settings import SettingsConstants
from seedsigner.gui.components import FontAwesomeIconConstants, GUIConstants, SeedSignerIconConstants
from seedsigner.gui.screens.screen import (
    RET_CODE__BACK_BUTTON,
    ButtonListScreen,
    ButtonOption,
    WarningScreen,
    DireWarningScreen,
    QRDisplayScreen,
    LargeIconStatusScreen,
)
from seedsigner.gui.screens.tools_screens import ToolsFormattedTextScreen, ToolsScrollableTextScreen
from seedsigner.views.view import BackStackView, MainMenuView, View, Destination
from seedsigner.hardware.microsd import MicroSD

logger = logging.getLogger(__name__)


def _chunk_review_text(text: str, width: int = 18) -> list[str]:
    value = str(text or "").strip()
    if not value:
        return ["-"]
    width = max(1, int(width))
    return [value[i:i + width] for i in range(0, len(value), width)] or ["-"]


def _paginate_review_lines(lines: list[str], lines_per_page: int = 9) -> list[str]:
    cleaned = [str(line).rstrip() for line in lines]
    if not cleaned:
        return [""]
    lines_per_page = max(1, int(lines_per_page))
    pages = []
    for start in range(0, len(cleaned), lines_per_page):
        page = "\n".join(cleaned[start:start + lines_per_page]).strip("\n")
        pages.append(page if page else " ")
    return pages


def _append_review_value(lines: list[str], label: str, value: str, width: int = 18) -> None:
    lines.append(label)
    lines.extend(_chunk_review_text(value, width=width))


def _format_review_sats(value: int | None) -> str:
    try:
        return f"{int(value):,} sats"
    except Exception:
        return "-"


def _friendly_signed_psbt_format_label(input_qr_type: str | None, signed_tx_hex: str | None) -> str:
    mapping = {
        "psbt__base43": "BASE43",
        "psbt__base64": "BASE64",
        "psbt__specter": "Specter",
        "psbt__ur2": "UR",
        "psbt__bbqr": "BBQr",
    }
    if input_qr_type in mapping:
        return mapping[input_qr_type]
    return "-"


def _describe_review_qr_delivery(qr_encoder) -> tuple[str, str]:
    frame_count = 1
    if qr_encoder is not None:
        try:
            frame_count = max(1, int(qr_encoder.seq_len()))
        except Exception:
            frame_count = 1
    if frame_count == 1:
        return "单张二维码", "下一步会显示 1 张二维码"
    return f"连续二维码（共 {frame_count} 张）", f"下一步会显示 {frame_count} 张连续二维码"


def _build_signed_psbt_review_pages(
    psbt_parser: PSBTParser | None,
    signed_tx_hex: str | None = None,
    signed_psbt_base64: str | None = None,
    qr_encoder=None,
    input_qr_type: str | None = None,
) -> list[str]:
    qr_style, qr_hint = _describe_review_qr_delivery(qr_encoder)
    result_label = "可直接广播的交易" if signed_tx_hex else "已签名 PSBT"
    pages: list[str] = []

    summary_lines = [
        "签名已完成",
        f"结果: {result_label}",
        f"扫码方式: {qr_style}",
        f"输入数: {psbt_parser.num_inputs if psbt_parser is not None else '-'}",
        f"金额: {_format_review_sats(psbt_parser.spend_amount if psbt_parser is not None else None)}",
        f"矿工费: {_format_review_sats(psbt_parser.fee_amount if psbt_parser is not None else None)}",
    ]
    if psbt_parser is not None and getattr(psbt_parser, "change_amount", 0):
        summary_lines.append(f"找零: {_format_review_sats(psbt_parser.change_amount)}")
    else:
        summary_lines.append("找零: 无")
    if psbt_parser is not None and getattr(psbt_parser, "num_destinations", 0) > 1:
        summary_lines.append(f"收款地址: {psbt_parser.num_destinations} 个")
    pages.append("\n".join(summary_lines))

    if psbt_parser is not None and psbt_parser.destination_addresses:
        address = psbt_parser.destination_addresses[0]
        address_lines = [
            "收款地址:",
        ]
        address_lines.extend(_chunk_review_text(address, width=18))
        if getattr(psbt_parser, "destination_amounts", None):
            address_lines.append(f"金额: {_format_review_sats(psbt_parser.destination_amounts[0])}")
        else:
            address_lines.append("金额: -")
        if psbt_parser.num_destinations > 1:
            address_lines.append(f"另有 {psbt_parser.num_destinations - 1} 个其他收款地址")
        pages.append("\n".join(address_lines))

    if signed_tx_hex:
        tx_hex = str(signed_tx_hex).strip()
        if tx_hex:
            pages.append(
                "\n".join(
                    [
                        f"交易大小: {len(tx_hex) // 2:,} 字节",
                        f"文本长度: {len(tx_hex):,} 个字符",
                        "这份结果可直接广播",
                    ]
                )
            )

    signature_health_report = None
    if signed_tx_hex:
        signature_health_report = analyze_tx_signature_health(signed_tx_hex)
    elif signed_psbt_base64:
        signature_health_report = analyze_psbt_signature_health(signed_psbt_base64)

    if signature_health_report is not None:
        pages.append("\n".join(build_signature_health_lines(signature_health_report)))

    pages.append(
        "\n".join(
            [
                qr_hint,
                "刚才确认过的金额和地址",
                "和下一步二维码是同一份结果",
                "确认没问题后再点",
                "“显示二维码”",
            ]
        )
    )
    return pages



class PSBTSelectSeedView(View):
    SCAN_SEED = ButtonOption("Scan a seed", SeedSignerIconConstants.QRCODE)
    SATOCHIP = ButtonOption("Use Satochip card", SeedSignerIconConstants.FINGERPRINT)
    TYPE_12WORD = ButtonOption("Enter 12-word seed", FontAwesomeIconConstants.KEYBOARD, return_data=12)
    TYPE_15WORD = ButtonOption("Enter 15-word seed", FontAwesomeIconConstants.KEYBOARD, return_data=15)
    TYPE_18WORD = ButtonOption("Enter 18-word seed", FontAwesomeIconConstants.KEYBOARD, return_data=18)
    TYPE_21WORD = ButtonOption("Enter 21-word seed", FontAwesomeIconConstants.KEYBOARD, return_data=21)
    TYPE_24WORD = ButtonOption("Enter 24-word seed", FontAwesomeIconConstants.KEYBOARD, return_data=24)
    TYPE_ELECTRUM = ButtonOption("Enter Electrum seed", FontAwesomeIconConstants.KEYBOARD)
    TYPE_WIF = ButtonOption("Enter WIF", FontAwesomeIconConstants.KEYBOARD)
    SCAN_WIF = ButtonOption("Scan WIF", SeedSignerIconConstants.QRCODE)
    TYPE_BIP38 = ButtonOption("Enter BIP38", FontAwesomeIconConstants.KEYBOARD)
    SCAN_BIP38 = ButtonOption("Scan BIP38", SeedSignerIconConstants.QRCODE)


    def run(self):
        from seedsigner.controller import Controller

        def ensure_microsd_seed_warning() -> bool:
            if not getattr(self.controller, "psbt_from_microsd", False):
                return True
            if getattr(self.controller, "psbt_microsd_seed_warning_shown", False):
                return True
            ret = self.run_screen(
                WarningScreen,
                title="WARNING",
                status_headline=None,
                text="These tools load data from the microSD card and may expose loaded secrets.",
                show_back_button=True,
                button_data=[ButtonOption("Continue")],
            )
            if ret == RET_CODE__BACK_BUTTON:
                return False
            self.controller.psbt_microsd_seed_warning_shown = True
            return True

        # Note: we can't just autoroute to the PSBT Overview because we might have a
        # multisig where we want to sign with more than one key on this device.
        if not self.controller.psbt:
            # Shouldn't be able to get here
            raise Exception("No PSBT currently loaded")

        if self.controller.psbt_seed:
             if PSBTParser.has_matching_input_fingerprint(psbt=self.controller.psbt, seed=self.controller.psbt_seed, network=self.settings.get_value(SettingsConstants.SETTING__NETWORK)):
                 # skip the seed prompt if a seed was previous selected and has matching input fingerprint
                 return Destination(PSBTOverviewView)

        seeds = self.controller.storage.seeds
        button_data = []
        for seed in seeds:
            button_str = seed.get_fingerprint(self.settings.get_value(SettingsConstants.SETTING__NETWORK))
            if not PSBTParser.has_matching_input_fingerprint(psbt=self.controller.psbt, seed=seed, network=self.settings.get_value(SettingsConstants.SETTING__NETWORK)):
                # Doesn't look like this seed can sign the current PSBT
                # TRANSLATOR_NOTE: Inserts fingerprint w/"?" to indicate that this seed can't sign the current PSBT
                button_str = _("{} (?)").format(button_str)

            button_data.append(ButtonOption(button_str, SeedSignerIconConstants.FINGERPRINT))

        button_data.append(self.SATOCHIP)
        button_data.append(self.SCAN_SEED)
        if self.settings.get_value(SettingsConstants.SETTING__WIF_KEYS) == SettingsConstants.OPTION__ENABLED:
            button_data.append(self.SCAN_WIF)
        if self.settings.get_value(SettingsConstants.SETTING__BIP38_KEYS) == SettingsConstants.OPTION__ENABLED:
            button_data.append(self.SCAN_BIP38)
        seed_lengths = self.settings.get_value(SettingsConstants.SETTING__SEED_WORD_LENGTHS)
        options = {
            12: self.TYPE_12WORD,
            15: self.TYPE_15WORD,
            18: self.TYPE_18WORD,
            21: self.TYPE_21WORD,
            24: self.TYPE_24WORD,
        }
        for l in seed_lengths:
            button_data.append(options[l])
        if self.settings.get_value(SettingsConstants.SETTING__ELECTRUM_SEEDS) == SettingsConstants.OPTION__ENABLED:
            button_data.append(self.TYPE_ELECTRUM)
        if self.settings.get_value(SettingsConstants.SETTING__WIF_KEYS) == SettingsConstants.OPTION__ENABLED:
            button_data.append(self.TYPE_WIF)
        if self.settings.get_value(SettingsConstants.SETTING__BIP38_KEYS) == SettingsConstants.OPTION__ENABLED:
            button_data.append(self.TYPE_BIP38)

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=_("Select Signer"),
            is_button_text_centered=False,
            button_data=button_data
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            if getattr(self.controller, "psbt_from_microsd", False):
                self.controller.psbt_from_microsd = False
                self.controller.psbt_microsd_save_path = None
                self.controller.psbt_microsd_seed_warning_shown = False
            return Destination(BackStackView)

        if len(seeds) > 0 and selected_menu_num < len(seeds):
            # User selected one of the n seeds
            if not ensure_microsd_seed_warning():
                return Destination(PSBTSelectSeedView)
            self.controller.psbt_seed = self.controller.get_seed(selected_menu_num)
            return Destination(PSBTOverviewView)

        # The remaining flows are a sub-flow; resume PSBT flow once the seed is loaded.
        self.controller.resume_main_flow = Controller.FLOW__PSBT

        if button_data[selected_menu_num] == self.SCAN_SEED:
            if not ensure_microsd_seed_warning():
                return Destination(PSBTSelectSeedView)
            from seedsigner.views.scan_views import ScanSeedQRView
            return Destination(ScanSeedQRView)

        elif button_data[selected_menu_num] == self.SCAN_WIF:
            if not ensure_microsd_seed_warning():
                return Destination(PSBTSelectSeedView)
            from seedsigner.views.scan_views import ScanWIFQRView
            return Destination(ScanWIFQRView)

        elif button_data[selected_menu_num] == self.SCAN_BIP38:
            if not ensure_microsd_seed_warning():
                return Destination(PSBTSelectSeedView)
            from seedsigner.views.scan_views import ScanBIP38QRView
            return Destination(ScanBIP38QRView)

        elif button_data[selected_menu_num] == self.SATOCHIP:
            from seedsigner.helpers import seedkeeper_utils
            from embit.bip32 import HDKey

            connector = seedkeeper_utils.init_satochip(self, init_card_filter=["satochip"])
            if not connector:
                return Destination(PSBTSelectSeedView, clear_history=True)

            psbt = self.controller.psbt
            is_multisig_psbt = False
            try:
                if psbt and psbt.inputs:
                    first_input = psbt.inputs[0]
                    if first_input.witness_utxo:
                        script_pubkey = first_input.witness_utxo.script_pubkey
                    elif first_input.non_witness_utxo:
                        script_pubkey = first_input.script_pubkey
                    else:
                        script_pubkey = None

                    if script_pubkey is not None:
                        policy = PSBTParser._get_policy(first_input, script_pubkey, psbt.xpubs)
                        is_multisig_psbt = isinstance(policy, dict) and "m" in policy
            except Exception as exc:
                logger.debug("Unable to determine PSBT policy", exc_info=exc)

            if is_multisig_psbt:
                try:
                    parser = PSBTParser(psbt)
                    parser.parse()
                except Exception as e:
                    logger.exception("Failed to parse PSBT with Satochip data")
                    self.run_screen(
                        WarningScreen,
                        title="Failed",
                        status_headline=None,
                        text=str(e),
                    )
                    return Destination(PSBTSelectSeedView, clear_history=True)

                self.controller.psbt_parser = parser
                self.controller.psbt_seed = None
                self.controller.psbt_sign_with_satochip = True
                return Destination(PSBTOverviewView)

            network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
            is_mainnet = network == SettingsConstants.MAINNET
            first_der = next(iter(self.controller.psbt.inputs[0].bip32_derivations.values())).derivation
            account_path = []
            HARDENED_INDEX = 0x80000000
            for idx in first_der:
                if idx & HARDENED_INDEX:
                    account_path.append(idx)
                else:
                    break

            account_path_str = "m"
            for i in account_path:
                hardened = bool(i & HARDENED_INDEX)
                index = i & 0x7FFFFFFF
                suffix = "'" if hardened else ""
                account_path_str += f"/{index}{suffix}"

            purpose = account_path[0] & 0x7FFFFFFF if account_path else 0
            xtype = {
                44: "standard",
                49: "p2wpkh-p2sh",
                84: "p2wpkh",
                48: "p2wsh-p2sh" if len(account_path) > 3 and (account_path[3] & 0x7FFFFFFF) == 1 else "p2wsh",
            }.get(purpose, "standard")

            from seedsigner.gui.screens.screen import LoadingScreenThread
            loading = LoadingScreenThread(text=_("Parsing PSBT..."))
            loading.start()
            loading_stopped = False
            try:
                try:
                    account_xpub = connector.card_bip32_get_xpub(account_path_str, xtype, is_mainnet)
                    master_xpub = connector.card_bip32_get_xpub("", xtype, is_mainnet)
                except Exception as e:
                    logger.exception("Failed to export xpub from Satochip card")
                    loading.stop()
                    loading_stopped = True
                    self.run_screen(
                        WarningScreen,
                        title="Failed",
                        status_headline=None,
                        text=str(e),
                    )
                    return Destination(PSBTSelectSeedView, clear_history=True)

                root_key = HDKey.from_base58(account_xpub)
                master_fp = HDKey.from_base58(master_xpub).my_fingerprint

                try:
                    self.controller.psbt_parser = PSBTParser(
                        self.controller.psbt,
                        seed=None,
                        root=root_key,
                        root_path=account_path,
                        master_fingerprint=master_fp,
                        network=network,
                    )
                except Exception as e:
                    logger.exception("Failed to parse PSBT with Satochip data")
                    loading.stop()
                    loading_stopped = True
                    self.run_screen(
                        WarningScreen,
                        title="Failed",
                        status_headline=None,
                        text=str(e),
                    )
                    return Destination(PSBTSelectSeedView, clear_history=True)

                card_fingerprints = {hexlify(master_fp).decode()}
                try:
                    card_fingerprints.add(hexlify(root_key.child(0).fingerprint).decode())
                except Exception:
                    pass

                psbt_fingerprints = set(PSBTParser.get_input_fingerprints(self.controller.psbt))
                if not card_fingerprints.intersection(psbt_fingerprints):
                    logger.warning(
                        "Satochip fingerprint mismatch: card %s vs psbt %s",
                        sorted(card_fingerprints),
                        sorted(psbt_fingerprints),
                    )
                    self.controller.psbt_parser = None
                    self.controller.psbt_sign_with_satochip = False
                    loading.stop()
                    loading_stopped = True
                    self.run_screen(
                        WarningScreen,
                        title=_("Fingerprint mismatch"),
                        status_icon_name=SeedSignerIconConstants.WARNING,
                        status_headline=_("Card cannot sign PSBT"),
                        text=_(
                            "Card fingerprint ({}) not in PSBT signers."
                        ).format(sorted(card_fingerprints)[0]),
                    )
                    return Destination(PSBTSelectSeedView, clear_history=True)
            finally:
                if not loading_stopped:
                    loading.stop()

            self.controller.psbt_seed = None
            self.controller.psbt_sign_with_satochip = True
            return Destination(PSBTOverviewView)

        elif button_data[selected_menu_num] in [self.TYPE_12WORD, self.TYPE_15WORD, self.TYPE_18WORD, self.TYPE_21WORD, self.TYPE_24WORD]:
            if not ensure_microsd_seed_warning():
                return Destination(PSBTSelectSeedView)
            from seedsigner.views.seed_views import SeedMnemonicEntryView
            self.controller.storage.init_pending_mnemonic(num_words=button_data[selected_menu_num].return_data)
            return Destination(SeedMnemonicEntryView)

        elif button_data[selected_menu_num] == self.TYPE_ELECTRUM:
            if not ensure_microsd_seed_warning():
                return Destination(PSBTSelectSeedView)
            from seedsigner.views.seed_views import SeedElectrumMnemonicStartView
            return Destination(SeedElectrumMnemonicStartView)

        elif button_data[selected_menu_num] == self.TYPE_WIF:
            if not ensure_microsd_seed_warning():
                return Destination(PSBTSelectSeedView)
            return Destination(PSBTWIFEntryView)

        elif button_data[selected_menu_num] == self.TYPE_BIP38:
            if not ensure_microsd_seed_warning():
                return Destination(PSBTSelectSeedView)
            return Destination(PSBTBIP38EntryView)



class PSBTWIFEntryView(View):
    def run(self):
        from seedsigner.gui.screens import seed_screens

        ret = self.run_screen(
            seed_screens.SeedAddPassphraseScreen,
            title=_("Private Key (WIF)"),
            passphrase="",
        )

        if "is_back_button" in ret:
            return Destination(BackStackView)

        wif = ret["passphrase"]
        from seedsigner.models.wif import WIFKey
        from seedsigner.models.seed import InvalidSeedException

        try:
            key = WIFKey(wif)
        except InvalidSeedException:
            self.run_screen(
                DireWarningScreen,
                status_headline=_("Invalid WIF!"),
                text=_("Not a valid WIF-encoded private key."),
                button_data=[ButtonOption("OK")],
                show_back_button=False,
            )
            return Destination(PSBTSelectSeedView)

        self.controller.psbt_seed = key
        return Destination(PSBTOverviewView)


class PSBTBIP38EntryView(View):
    def run(self):
        from seedsigner.gui.screens import seed_screens

        ret = self.run_screen(
            seed_screens.SeedAddPassphraseScreen,
            title=_("BIP38 Key"),
            passphrase="",
        )

        if "is_back_button" in ret:
            return Destination(BackStackView)

        bip38 = ret["passphrase"]
        return Destination(PSBTBIP38PassphraseView, view_args=dict(encrypted=bip38))


class PSBTBIP38PassphraseView(View):
    def __init__(self, encrypted: str):
        super().__init__()
        self.encrypted = encrypted

    def run(self):
        from seedsigner.gui.screens import seed_screens
        from seedsigner.models.bip38 import BIP38Key
        from seedsigner.models.seed import InvalidSeedException

        ret = self.run_screen(
            seed_screens.SeedAddPassphraseScreen,
            title=_("BIP38 Passphrase"),
            passphrase="",
        )

        if "is_back_button" in ret:
            return Destination(BackStackView)

        passphrase = ret["passphrase"]
        try:
            key = BIP38Key(self.encrypted).decrypt(passphrase, self.settings.get_value(SettingsConstants.SETTING__NETWORK))
        except InvalidSeedException:
            self.run_screen(
                DireWarningScreen,
                status_headline=_("Invalid BIP38!"),
                text=_("Could not decrypt BIP38 key."),
                button_data=[ButtonOption("OK")],
                show_back_button=False,
            )
            return Destination(PSBTSelectSeedView)

        self.controller.psbt_seed = key
        return Destination(PSBTOverviewView)

class PSBTOverviewView(View):
    def __init__(self):
        super().__init__()

        self.loading_screen = None

        if not self.controller.psbt_parser or self.controller.psbt_parser.seed != self.controller.psbt_seed:
            # The PSBTParser takes a while to read the PSBT. Run the loading screen while
            # we wait.
            from seedsigner.gui.screens.screen import LoadingScreenThread
            self.loading_screen = LoadingScreenThread(text=_("Parsing PSBT..."))
            self.loading_screen.start()
                
            try:
                self.controller.psbt_parser = PSBTParser(
                    self.controller.psbt,
                    seed=self.controller.psbt_seed,
                    network=self.settings.get_value(SettingsConstants.SETTING__NETWORK)
                )
            except Exception as e:
                self.loading_screen.stop()
                raise e


    def run(self):
        from seedsigner.gui.screens.psbt_screens import PSBTOverviewScreen
        psbt_parser = self.controller.psbt_parser

        change_data = psbt_parser.change_data
        """
            change_data = [
                {
                    'address': 'bc1q............', 
                    'amount': 397621401, 
                    'fingerprint': ['22bde1a9', '73c5da0a'], 
                    'derivation_path': ['m/48h/1h/0h/2h/1/0', 'm/48h/1h/0h/2h/1/0']
                }, {},
            ]
        """
        num_change_outputs = 0
        num_self_transfer_outputs = 0
        for change_output in change_data:
            path_ints = bip32.parse_path(change_output["derivation_path"][0])
            if len(path_ints) >= 2 and (path_ints[-2] & 0x7FFFFFFF) == 1:
                num_change_outputs += 1
            else:
                num_self_transfer_outputs += 1

        # Everything is set. Stop the loading screen
        if self.loading_screen:
            self.loading_screen.stop()

        # Run the overview screen
        selected_menu_num = self.run_screen(
            PSBTOverviewScreen,
            spend_amount=psbt_parser.spend_amount,
            change_amount=psbt_parser.change_amount,
            fee_amount=psbt_parser.fee_amount,
            num_inputs=psbt_parser.num_inputs,
            num_self_transfer_outputs=num_self_transfer_outputs,
            num_change_outputs=num_change_outputs,
            destination_addresses=psbt_parser.destination_addresses,
            has_op_return=psbt_parser.op_return_data is not None,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            self.controller.psbt_seed = None
            return Destination(BackStackView)

        # expecting p2sh (legacy multisig) and p2pkh to have no policy set
        # skip change warning and psbt math view
        if psbt_parser.policy == None:
            return Destination(PSBTUnsupportedScriptTypeWarningView)
        
        elif psbt_parser.change_amount == 0:
            return Destination(PSBTNoChangeWarningView)

        else:
            return Destination(PSBTMathView)



class PSBTUnsupportedScriptTypeWarningView(View):
    def run(self):
        selected_menu_num = WarningScreen(
            status_headline=_("Unsupported Script Type!"),
            text=_("PSBT has unsupported input script type, please verify your change addresses."),
            button_data=[ButtonOption("Continue")],
        ).display()
        
        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        
        # Only one exit point
        # skip PSBTMathView
        return Destination(
            PSBTAddressDetailsView, view_args={"address_num": 0},
            skip_current_view=True,  # Prevent going BACK to WarningViews
        )



class PSBTNoChangeWarningView(View):
    def run(self):
        selected_menu_num = WarningScreen(
            # TRANSLATOR_NOTE: User will receive no change back; the inputs to this transaction are fully spent
            status_headline=_("Full Spend!"),
            text=_("This PSBT spends its entire input value. No change is coming back to your wallet."),
            button_data=[ButtonOption("Continue")],
        ).display()

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        # Only one exit point
        return Destination(
            PSBTMathView,
            skip_current_view=True,  # Prevent going BACK to WarningViews
        )



class PSBTMathView(View):
    """
        Follows the Overview pictogram. Shows:
        + total input value
        - recipients' value
        - fees
        -------------------
        + change value
    """
    def run(self):
        from seedsigner.gui.screens.psbt_screens import PSBTMathScreen
        psbt_parser: PSBTParser = self.controller.psbt_parser
        if not psbt_parser:
            # Should not be able to get here
            return Destination(MainMenuView)
        
        selected_menu_num = self.run_screen(
            PSBTMathScreen,
            input_amount=psbt_parser.input_amount,
            num_inputs=psbt_parser.num_inputs,
            spend_amount=psbt_parser.spend_amount,
            num_recipients=psbt_parser.num_destinations,
            fee_amount=psbt_parser.fee_amount,
            change_amount=psbt_parser.change_amount,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        if len(psbt_parser.destination_addresses) > 0:
            return Destination(PSBTAddressDetailsView, view_args={"address_num": 0})
        else:
            # This is a self-transfer
            return Destination(PSBTChangeDetailsView, view_args={"change_address_num": 0})



class PSBTAddressDetailsView(View):
    """
        Shows the recipient's address and amount they will receive
    """
    def __init__(self, address_num):
        super().__init__()
        self.address_num = address_num


    def run(self):
        from seedsigner.gui.screens.psbt_screens import PSBTAddressDetailsScreen
        psbt_parser: PSBTParser = self.controller.psbt_parser

        if not psbt_parser:
            # Should not be able to get here
            raise Exception("Routing error")

        # TRANSLATOR_NOTE: Future-tense used to indicate that this transaction will send this amount, as opposed to "Send" on its own which could be misread as an instant command (e.g. "Send Now").
        title = _("Will Send")
        if psbt_parser.num_destinations > 1:
            title += f" (#{self.address_num + 1})"

        button_data = []
        if self.address_num < psbt_parser.num_destinations - 1:
            button_data.append(ButtonOption("Next Recipient"))
        else:
            # TRANSLATOR_NOTE: Short for "Next step"
            button_data.append(ButtonOption("Next"))

        selected_menu_num = self.run_screen(
            PSBTAddressDetailsScreen,
            title=title,
            button_data=button_data,
            address=psbt_parser.destination_addresses[self.address_num],
            amount=psbt_parser.destination_amounts[self.address_num],
        )
        
        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        if self.address_num < len(psbt_parser.destination_addresses) - 1:
            # Show the next receive addr
            return Destination(PSBTAddressDetailsView, view_args={"address_num": self.address_num + 1})

        elif psbt_parser.change_amount > 0:
            # Move on to display change
            return Destination(PSBTChangeDetailsView, view_args={"change_address_num": 0})

        elif psbt_parser.op_return_data:
            return Destination(PSBTOpReturnView)

        else:
            # There's no change output to verify. Move on to sign the PSBT.
            return Destination(PSBTFinalizeView)



class PSBTChangeDetailsView(View):
    NEXT = ButtonOption("Next")
    SKIP_VERIFICATION = ButtonOption("Skip Verification")
    VERIFY_MULTISIG = ButtonOption("Verify Multisig Change")

    def __init__(self, change_address_num):
        super().__init__()
        self.change_address_num = change_address_num


    def run(self):
        from seedsigner.gui.screens.psbt_screens import PSBTChangeDetailsScreen
        psbt_parser: PSBTParser = self.controller.psbt_parser

        if not psbt_parser:
            # Should not be able to get here
            return Destination(MainMenuView)

        # Can we verify this change addr?
        change_data = psbt_parser.get_change_data(change_num=self.change_address_num)
        """
            change_data:
            {
                'address': 'bc1q............', 
                'amount': 397621401, 
                'fingerprint': ['22bde1a9', '73c5da0a'], 
                'derivation_path': ['m/48h/1h/0h/2h/1/0', 'm/48h/1h/0h/2h/1/0']
            }
        """

        # Single-sig verification is easy. We expect to find a single fingerprint
        # and derivation path.
        fingerprints = change_data.get("fingerprint") or []
        derivation_paths = change_data.get("derivation_path") or []

        candidate_fingerprints = []
        if self.controller.psbt_seed:
            seed_fingerprint = self.controller.psbt_seed.get_fingerprint(
                self.settings.get_value(SettingsConstants.SETTING__NETWORK)
            )
            if seed_fingerprint:
                candidate_fingerprints.append(seed_fingerprint)
        else:
            master_fp = getattr(psbt_parser, "master_fingerprint", None)
            if master_fp:
                candidate_fingerprints.append(hexlify(master_fp).decode())

            # External signer flows can surface either the card's master fingerprint
            # or the account/root fingerprint in output derivation metadata.
            root = getattr(psbt_parser, "root", None)
            if root:
                try:
                    candidate_fingerprints.append(hexlify(root.child(0).fingerprint).decode())
                except Exception:
                    pass
                try:
                    candidate_fingerprints.append(hexlify(root.fingerprint).decode())
                except Exception:
                    pass

        candidate_fingerprints = [fp for i, fp in enumerate(candidate_fingerprints) if fp and fp not in candidate_fingerprints[:i]]

        seed_fingerprint = None
        index = None
        for candidate in candidate_fingerprints:
            if candidate in fingerprints:
                seed_fingerprint = candidate
                index = fingerprints.index(candidate)
                break

        if index is None:
            if fingerprints:
                index = 0
                seed_fingerprint = fingerprints[index]
                logger.warning(
                    "PSBT change fingerprint mismatch; falling back to first output derivation fingerprint. candidates=%s psbt=%s",
                    candidate_fingerprints,
                    fingerprints,
                )
            else:
                seed_fingerprint = candidate_fingerprints[0] if candidate_fingerprints else None

        derivation_path = ""
        if index is not None and index < len(derivation_paths):
            derivation_path = derivation_paths[index]

        # 'm/84h/1h/0h/1/0' would be a change addr while 'm/84h/1h/0h/0/0' is a self-receive
        if derivation_path:
            path_ints = bip32.parse_path(derivation_path)
        else:
            path_ints = []
        is_change_derivation_path = len(path_ints) >= 2 and (path_ints[-2] & 0x7FFFFFFF) == 1
        derivation_path_addr_index = path_ints[-1] & 0x7FFFFFFF if path_ints else 0

        if is_change_derivation_path:
            # TRANSLATOR_NOTE: The amount you're receiving back from the transaction
            title = _("Your Change")
        else:
            title = _("Self-Transfer")
            self.VERIFY_MULTISIG.button_label = _("Verify Multisig Addr")
        # if psbt_parser.num_change_outputs > 1:
        #     title += f" (#{self.change_address_num + 1})"

        is_change_addr_verified = False
        allow_unverified_change_display = bool(
            getattr(psbt_parser, "allow_unverified_single_sig_change", False)
            and not psbt_parser.is_multisig
            and self.controller.psbt_seed is None
            and getattr(psbt_parser, "root", None) is None
        )
        if psbt_parser.is_multisig:
            print("isMultisig")
            # if the known-good multisig descriptor is already onboard:
            if self.controller.multisig_wallet_descriptor:
                is_change_addr_verified = psbt_parser.verify_multisig_output(
                    self.controller.multisig_wallet_descriptor,
                    change_num=self.change_address_num,
                )
                if not is_change_addr_verified:
                    self.controller.multisig_wallet_descriptor = None
                    self.run_screen(
                        WarningScreen,
                        title=_("Descriptor mismatch"),
                        status_icon_name=SeedSignerIconConstants.WARNING,
                        status_headline=_("Descriptor cleared"),
                        text=_(
                            "Loaded multisig wallet descriptor does not match this PSBT. "
                            "Load the correct descriptor or skip verification to continue."
                        ),
                        show_back_button=False,
                        button_data=[ButtonOption(_("OK"))],
                    )
                    return Destination(
                        PSBTChangeDetailsView,
                        view_args={"change_address_num": self.change_address_num},
                        skip_current_view=True,
                    )

                button_data = [self.NEXT]

            else:
                # Have the Screen offer to load in the multisig descriptor.
                button_data = [self.VERIFY_MULTISIG, self.SKIP_VERIFICATION]

        else:
            # Single sig
            print("isSinglesig")
            if allow_unverified_change_display:
                button_data = [self.NEXT]
            else:
                try:
                    from embit import script
                    from embit.networks import NETWORKS

                    if is_change_derivation_path:
                        loading_screen_text = _("Verifying Change...")
                    else:
                        loading_screen_text = _("Verifying Self-Transfer...")
                    from seedsigner.gui.screens.screen import LoadingScreenThread
                    loading_screen = LoadingScreenThread(text=loading_screen_text)
                    loading_screen.start()

                    # convert change address to script pubkey to get script type
                    pubkey = script.address_to_scriptpubkey(change_data["address"])
                    script_type = pubkey.script_type()

                    # extract derivation path to get wallet and change derivation
                    change_path = bip32.path_to_str(path_ints[-2:])[2:] if len(path_ints) >= 2 else ""
                    wallet_path_list = path_ints[:-2]
                    wallet_path = bip32.path_to_str(wallet_path_list)

                    if self.controller.psbt_seed:
                        xpub = self.controller.psbt_seed.get_xpub(
                            wallet_path=wallet_path,
                            network=self.settings.get_value(SettingsConstants.SETTING__NETWORK)
                        )
                        xpub_key = xpub.derive(change_path).key
                    else:
                        rel_wallet_path_list = wallet_path_list[len(psbt_parser.root_path):]
                        rel_wallet_path = (
                            bip32.path_to_str(rel_wallet_path_list)[2:]
                            if rel_wallet_path_list
                            else ""
                        )
                        xpub = (
                            psbt_parser.root.derive(rel_wallet_path)
                            if rel_wallet_path
                            else psbt_parser.root
                        )
                        xpub_key = xpub.derive(change_path).key

                    network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
                    scriptcall = getattr(script, script_type)
                    if script_type == "p2sh":
                        # single sig only so p2sh is always p2sh-p2wpkh
                        calc_address = script.p2sh(script.p2wpkh(xpub_key)).address(
                            network=NETWORKS[SettingsConstants.map_network_to_embit(network)]
                        )
                    else:
                        # single sig so this handles p2wpkh and p2wpkh (and p2tr in the future)
                        calc_address = scriptcall(xpub_key).address(
                            network=NETWORKS[SettingsConstants.map_network_to_embit(network)]
                        )

                    if change_data["address"] == calc_address:
                        is_change_addr_verified = True
                        button_data = [self.NEXT]

                finally:
                    loading_screen.stop()

        if (
            is_change_addr_verified == False
            and not allow_unverified_change_display
            and (not psbt_parser.is_multisig or self.controller.multisig_wallet_descriptor is not None)
        ):
            return Destination(PSBTAddressVerificationFailedView, view_args=dict(is_change=is_change_derivation_path, is_multisig=psbt_parser.is_multisig), clear_history=True)

        selected_menu_num = self.run_screen(
            PSBTChangeDetailsScreen,
            title=title,
            button_data=button_data,
            address=change_data.get("address"),
            amount=change_data.get("amount"),
            is_multisig=psbt_parser.is_multisig,
            fingerprint=seed_fingerprint or "",
            derivation_path=derivation_path or "",
            is_change_derivation_path=is_change_derivation_path,
            derivation_path_addr_index=derivation_path_addr_index,
            is_change_addr_verified=is_change_addr_verified,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        elif button_data[selected_menu_num] == self.NEXT or button_data[selected_menu_num] == self.SKIP_VERIFICATION:
            if self.change_address_num < psbt_parser.num_change_outputs - 1:
                return Destination(PSBTChangeDetailsView, view_args={"change_address_num": self.change_address_num + 1})

            elif psbt_parser.op_return_data:
                return Destination(PSBTOpReturnView)

            else:
                # There's no more change to verify. Move on to sign the PSBT.
                return Destination(PSBTFinalizeView)
            
        elif button_data[selected_menu_num] == self.VERIFY_MULTISIG:
            from seedsigner.controller import Controller
            from seedsigner.views.seed_views import LoadMultisigWalletDescriptorView
            self.controller.resume_main_flow = Controller.FLOW__PSBT
            return Destination(LoadMultisigWalletDescriptorView)
            


class PSBTAddressVerificationFailedView(View):
    def __init__(self, is_change: bool = True, is_multisig: bool = False):
        super().__init__()
        self.is_change = is_change
        self.is_multisig = is_multisig


    def run(self):
        if self.is_multisig:
            # TRANSLATOR_NOTE: Variable is either "change" or "self-transfer".
            text = _("PSBT's {} address could not be verified from wallet descriptor.").format(_("change") if self.is_change else _("self-transfer"))
        else:
            # TRANSLATOR_NOTE: Variable is either "change" or "self-transfer".
            text = _("PSBT's {} address could not be generated from your seed.").format(_("change") if self.is_change else _("self-transfer"))
        
        DireWarningScreen(
            title=_("Suspicious PSBT"),
            status_headline=_("Address Verification Failed"),
            text=text,
            button_data=[ButtonOption("Discard PSBT")],
            show_back_button=False,
        ).display()

        # We're done with this PSBT. Route back to MainMenuView which always
        #   clears all ephemeral data (except in-memory seeds).
        return Destination(MainMenuView, clear_history=True)



class PSBTOpReturnView(View):
    """
        Shows the OP_RETURN data
    """
    def run(self):
        from seedsigner.gui.screens.psbt_screens import PSBTOpReturnScreen
        psbt_parser: PSBTParser = self.controller.psbt_parser

        if not psbt_parser:
            # Should not be able to get here
            raise Exception("Routing error")

        title = _("OP_RETURN")
        button_data = [ButtonOption("Next")]

        selected_menu_num = self.run_screen(
            PSBTOpReturnScreen,
            title=title,
            button_data=button_data,
            op_return_data=psbt_parser.op_return_data,
        )
        
        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        return Destination(PSBTFinalizeView)



class PSBTFinalizeView(View):
    """
    """
    APPROVE_PSBT = ButtonOption("Approve PSBT")

    
    def run(self):
        from embit.psbt import PSBT
        from seedsigner.gui.screens.psbt_screens import PSBTFinalizeScreen
        from seedsigner.models.wif import WIFKey
        from embit.finalizer import finalize_psbt

        psbt_parser: PSBTParser = self.controller.psbt_parser
        psbt: PSBT = self.controller.psbt

        if psbt is None:
            # Should not be able to get here
            return Destination(MainMenuView)

        if not self.controller.psbt_sign_with_satochip and psbt_parser is None:
            return Destination(MainMenuView)

        selected_menu_num = self.run_screen(
            PSBTFinalizeScreen,
            button_data=[self.APPROVE_PSBT]
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        if getattr(self.controller, "psbt_external_signer_flow", False):
            from seedsigner.views.tp_views import ToolsTpSignerPinEntryView

            try:
                unsigned_psbt_base64 = base64.b64encode(psbt.serialize()).decode("ascii")
            except Exception as exc:
                logger.exception("Failed to serialize PSBT for external signer flow", exc_info=exc)
                return Destination(PSBTFinalizeView)

            return Destination(
                ToolsTpSignerPinEntryView,
                view_args=dict(
                    psbt_base64=unsigned_psbt_base64,
                    psbt_input_qr_type=getattr(self.controller, "psbt_input_qr_type", None),
                    response_mode=getattr(self.controller, "psbt_response_mode", None),
                ),
                skip_current_view=True,
            )

        sig_cnt = PSBTParser.sig_count(psbt)

        connector = None
        if self.controller.psbt_sign_with_satochip:
            from seedsigner.helpers import seedkeeper_utils
            connector = seedkeeper_utils.init_satochip(self, init_card_filter=["satochip"])
            if not connector:
                return Destination(PSBTFinalizeView)

        from seedsigner.gui.screens.screen import LoadingScreenThread
        loading = LoadingScreenThread(text=_("Signing PSBT..."))
        loading.start()
        try:
            if self.controller.psbt_sign_with_satochip:
                from seedsigner.helpers.satochip_signer import sign_psbt_with_satochip
                sign_psbt_with_satochip(psbt, connector)
            else:
                psbt.sign_with(psbt_parser.root)
            if isinstance(self.controller.psbt_seed, WIFKey):
                tx = finalize_psbt(psbt)
                self.controller.signed_tx_hex = tx.serialize().hex() if tx else None
            else:
                self.controller.signed_tx_hex = None

            trimmed_psbt = PSBTParser.trim(psbt)
        except Exception:
            if self.controller.psbt_sign_with_satochip:
                logger.exception("Failed to sign PSBT with Satochip")
                return Destination(PSBTFinalizeView)
            raise
        finally:
            loading.stop()

        if sig_cnt == PSBTParser.sig_count(trimmed_psbt):
            if self.controller.psbt_sign_with_satochip:
                return Destination(PSBTFinalizeView)
            return Destination(PSBTSigningErrorView)

        self.controller.psbt = trimmed_psbt
        self.controller.psbt_sign_with_satochip = False
        return Destination(PSBTSignedQRDisplayView)



class PSBTSignedQRDisplayView(View):
    PREV = ButtonOption("上一页")
    NEXT = ButtonOption("下一页")
    SHOW_QR = ButtonOption("显示签名二维码")

    def __init__(self, page_num: int = 0, skip_review: bool = False):
        super().__init__()
        self.page_num = max(0, int(page_num))
        self.skip_review = bool(skip_review)

    def _reload_review(self, page_num: int, skip_review: bool = False) -> Destination:
        return Destination(
            PSBTSignedQRDisplayView,
            view_args=dict(page_num=page_num, skip_review=skip_review),
            clear_history=True,
        )

    def _qr_encoder_cache_key(self):
        return (
            id(getattr(self.controller, "psbt", None)),
            getattr(self.controller, "psbt_input_qr_type", None),
            getattr(self.controller, "signed_tx_hex", None),
            type(getattr(self.controller, "psbt_seed", None)).__name__,
        )

    def _get_qr_encoder(self):
        from seedsigner.models.encode_qr import build_signed_psbt_qr_encoder, GenericStringEncoder
        from seedsigner.models.wif import WIFKey
        from seedsigner.gui.screens.screen import LoadingScreenThread

        cache_key = self._qr_encoder_cache_key()
        if getattr(self.controller, "_psbt_signed_qr_encoder_cache_key", None) == cache_key:
            cached_encoder = getattr(self.controller, "_psbt_signed_qr_encoder", None)
            if cached_encoder is not None:
                return cached_encoder

        if isinstance(self.controller.psbt_seed, WIFKey) and getattr(self.controller, "signed_tx_hex", None):
            qr_encoder = GenericStringEncoder(self.controller.signed_tx_hex)
        else:
            loading = LoadingScreenThread(text=_("Encoding PSBT..."))
            loading.start()
            try:
                qr_encoder = build_signed_psbt_qr_encoder(
                    psbt=self.controller.psbt,
                    qr_density=self.settings.get_value(SettingsConstants.SETTING__QR_DENSITY),
                    input_qr_type=getattr(self.controller, "psbt_input_qr_type", None),
                )
            finally:
                loading.stop()

        self.controller._psbt_signed_qr_encoder_cache_key = cache_key
        self.controller._psbt_signed_qr_encoder = qr_encoder
        return qr_encoder

    def _clear_qr_encoder_cache(self) -> None:
        self.controller._psbt_signed_qr_encoder_cache_key = None
        self.controller._psbt_signed_qr_encoder = None

    def run(self):
        save_path = getattr(self.controller, "psbt_microsd_save_path", None)
        if save_path:
            signed_path = save_path.with_name(save_path.name + ".signed")
            try:
                signed_path.parent.mkdir(parents=True, exist_ok=True)
                signed_path.write_bytes(self.controller.psbt.serialize())
                try:
                    display_path = str(signed_path.relative_to(MicroSD.get_microsd_dir()))
                except ValueError:
                    display_path = signed_path.name
                self.run_screen(
                    LargeIconStatusScreen,
                    title=_("Success"),
                    status_headline=None,
                    text=_("Saved as {}.").format(display_path),
                    show_back_button=False,
                    button_data=[ButtonOption(_("Continue"))],
                )
            except Exception as e:
                logger.exception("Failed to save signed PSBT", exc_info=e)
                self.run_screen(
                    WarningScreen,
                    title=_("Error"),
                    status_headline=None,
                    text=_("Failed to save PSBT: {}").format(str(e)),
                    show_back_button=False,
                    button_data=[ButtonOption(_("OK"))],
                )
            finally:
                self.controller.psbt_microsd_save_path = None
                self.controller.psbt_from_microsd = False
                self.controller.psbt_microsd_seed_warning_shown = False

        qr_encoder = self._get_qr_encoder()
        signed_psbt_base64 = None
        try:
            if getattr(self.controller, "psbt", None) is not None:
                signed_psbt_base64 = base64.b64encode(self.controller.psbt.serialize()).decode("ascii")
        except Exception as exc:
            logger.warning("Failed to serialize signed PSBT for summary review: %s", exc)

        if not self.skip_review:
            pages = _build_signed_psbt_review_pages(
                psbt_parser=getattr(self.controller, "psbt_parser", None),
                signed_tx_hex=getattr(self.controller, "signed_tx_hex", None),
                signed_psbt_base64=signed_psbt_base64,
                qr_encoder=qr_encoder,
                input_qr_type=getattr(self.controller, "psbt_input_qr_type", None),
            )
            review_text = "\n\n".join(page for page in pages if str(page).strip())
            button_data = [self.SHOW_QR]

            selected_menu_num = self.run_screen(
                ToolsScrollableTextScreen,
                title="签名结果摘要",
                text=review_text,
                text_font_name=GUIConstants.get_body_font_name(),
                text_font_size=max(GUIConstants.get_body_font_size() + 1, 19),
                button_data=button_data,
            )

            if selected_menu_num == RET_CODE__BACK_BUTTON:
                self._clear_qr_encoder_cache()
                return Destination(MainMenuView, clear_history=True)

            return self._reload_review(0, skip_review=True)

        self.run_screen(QRDisplayScreen, qr_encoder=qr_encoder)
        self._clear_qr_encoder_cache()

        # We're done with this PSBT. Route back to MainMenuView which always
        #   clears all ephemeral data (except in-memory seeds).
        return Destination(MainMenuView, clear_history=True)



class PSBTSigningErrorView(View):
    SELECT_DIFF_SEED = ButtonOption("Select Diff Seed")
    
    def run(self):
        psbt_parser: PSBTParser = self.controller.psbt_parser
        if not psbt_parser:
            # Should not be able to get here
            return Destination(MainMenuView)

        # Just a WarningScreen here; only use DireWarningScreen for true security risks.
        selected_menu_num = self.run_screen(
            WarningScreen,
            title=_("PSBT Error"),
            status_icon_name=SeedSignerIconConstants.WARNING,
            status_headline=_("Signing Failed"),
            text=_("Signing with this seed did not add a valid signature."),
            button_data=[self.SELECT_DIFF_SEED]
        )

        if selected_menu_num == 0:
            # clear seed selected for psbt signing since it did not add a valid signature
            self.controller.psbt_seed = None
            return Destination(PSBTSelectSeedView, clear_history=True)

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
