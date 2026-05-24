import base64
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from binascii import a2b_base64, b2a_base64
from enum import IntEnum
from PIL import Image, ImageFilter, ImageOps
from embit import psbt, bip39, ec, bip32
from urtypes.crypto import PSBT as UR_PSBT
from urtypes.crypto import Account, Output
from urtypes.bytes import Bytes

try:
    from pyzbar import pyzbar
    from pyzbar.pyzbar import ZBarSymbol
except Exception:  # pragma: no cover - optional dependency in desktop smoke envs
    pyzbar = None
    ZBarSymbol = None

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency in some smoke envs
    cv2 = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency in some smoke envs
    np = None

try:
    import zxingcpp  # type: ignore
except Exception:  # pragma: no cover - optional dependency in some firmware builds
    zxingcpp = None

from seedsigner.helpers.bbqr import decode_bbqr_data, parse_bbqr_header
from seedsigner.helpers.ur2.ur_decoder import URDecoder
from seedsigner.models.qr_type import QRType
from seedsigner.models.seed import Seed
from seedsigner.models.aezeed import has_valid_checksum as aezeed_has_valid_checksum
from seedsigner.models.settings import SettingsConstants

logger = logging.getLogger(__name__)

FAST_QR_FALLBACK_INTERVAL = 4
MULTIPART_QR_FALLBACK_INTERVAL = 3
DENSE_QR_FALLBACK_INTERVAL = 2
FAST_QR_INITIAL_AGGRESSIVE_TRIES = 1
FAST_CENTER_CROP_RATIOS = (0.58, 0.46, 0.40, 0.24)
CENTER_CROP_RATIOS = (0.86, 0.72, 0.58, 0.46, 0.40, 0.36, 0.30, 0.26, 0.24, 0.20)
OPENCV_QR_MAX_CANDIDATES = 16
OPENCV_QR_MAX_SIZE = 960
OPENCV_QR_ROI_MAX_REGIONS = 3
OPENCV_QR_ROI_MIN_SIZE = 384
OPENCV_QR_ROI_MAX_SIZE = 960
OPENCV_QR_ROI_BORDER = 24
QR_ROI_HINT_MARGIN_RATIO = 0.22
QR_ROI_HINT_MAX_MISSES = 5
WECHAT_QR_FALLBACK_INTERVAL = 4
WECHAT_QR_MODEL_DIR = Path(__file__).resolve().parent.parent / "resources" / "wechat_qrcode"
WECHAT_QR_MODEL_FILES = (
    "detect.prototxt",
    "detect.caffemodel",
    "sr.prototxt",
    "sr.caffemodel",
)



class DecodeQRStatus(IntEnum):
    """
        Used in DecodeQR to communicate status of adding qr frame/segment
    """
    PART_COMPLETE = 1
    PART_EXISTING = 2
    COMPLETE = 3
    FALSE = 4
    INVALID = 5
    WRONG_KEY = 6



class DecodeQR:
    """
        Used to process images or string data from animated qr codes.
    """
    def __init__(self, wordlist_language_code: str = SettingsConstants.WORDLIST_LANGUAGE__ENGLISH, is_passphrase: bool = False,
                                                                                                   is_encryptionkey: bool = False,
                                                                                                   is_text: bool = False):
        self.wordlist_language_code = wordlist_language_code
        self.complete = False
        self.qr_type = None
        self.decoder = None
        self.is_passphrase = is_passphrase
        self.is_encryptionkey = is_encryptionkey
        self.is_text = is_text
        self.is_nonUTF8 = False
        self._scan_attempt_count = 0
        self._dense_scan_mode = False
        self._qr_roi_hint = None
        self._qr_roi_misses = 0


    def set_dense_scan_mode(self, enabled: bool):
        self._dense_scan_mode = bool(enabled)


    def add_image(self, image):
        self._scan_attempt_count += 1
        data, roi_hint = DecodeQR.extract_qr_data_with_hint(
            image,
            is_binary=True,
            aggressive=False,
            include_fast_candidates=self._qr_roi_hint is None,
            dense_scan_mode=self._dense_scan_mode,
            roi_hint=self._qr_roi_hint,
        )
        if data is None and self._should_run_aggressive_fallback():
            data, roi_hint = DecodeQR.extract_qr_data_with_hint(
                image,
                is_binary=True,
                aggressive=True,
                include_fast_candidates=False,
                include_wechat=self._should_run_wechat_fallback(),
                dense_scan_mode=self._dense_scan_mode,
                roi_hint=self._qr_roi_hint,
            )
        if roi_hint is not None:
            self._qr_roi_hint = roi_hint
        if data is None:
            if self._qr_roi_hint is not None:
                self._qr_roi_misses += 1
                if self._qr_roi_misses >= QR_ROI_HINT_MAX_MISSES:
                    self._qr_roi_hint = None
                    self._qr_roi_misses = 0
            return DecodeQRStatus.FALSE

        self._qr_roi_misses = 0
        return self.add_data(data)


    def add_data(self, data):
        if data == None:
            return DecodeQRStatus.FALSE

        if self.is_passphrase:
            qr_type = QRType.PASSPHRASE
        elif self.is_encryptionkey:
            qr_type = QRType.ENCRYPTION_KEY
        elif self.is_text:
            qr_type = QRType.TEXT
        else:
            qr_type = DecodeQR.detect_segment_type(data, wordlist_language_code=self.wordlist_language_code)

        if self.qr_type == None:
            self.qr_type = qr_type

            if self.qr_type in [QRType.PSBT__UR2, QRType.OUTPUT__UR, QRType.ACCOUNT__UR, QRType.BYTES__UR]:
                self.decoder = URDecoder() # BCUR Decoder

            elif self.qr_type == QRType.PSBT__BBQR:
                self.decoder = BbqrPsbtQrDecoder()

            elif self.qr_type == QRType.PSBT__SPECTER:
                self.decoder = SpecterPsbtQrDecoder() # Specter Desktop PSBT QR base64 decoder

            elif self.qr_type == QRType.PSBT__BASE64:
                self.decoder = Base64PsbtQrDecoder() # Single Segments Base64

            elif self.qr_type == QRType.PSBT__BASE43:
                self.decoder = Base43PsbtQrDecoder() # Single Segment Base43

            elif self.qr_type in [QRType.SEED__SEEDQR, QRType.SEED__COMPACTSEEDQR, QRType.SEED__MNEMONIC, QRType.SEED__FOUR_LETTER_MNEMONIC, QRType.SEED__UR2]:
                self.decoder = SeedQrDecoder(wordlist_language_code=self.wordlist_language_code)

            elif self.qr_type == QRType.SEED__SLIP39:
                self.decoder = Slip39ShareDecoder()

            elif self.qr_type == QRType.SEED__XPRV:
                self.decoder = XprvQrDecoder()

            elif self.qr_type == QRType.SETTINGS:
                self.decoder = SettingsQrDecoder()  # Settings config

            elif self.qr_type == QRType.BITCOIN_ADDRESS:
                self.decoder = BitcoinAddressQrDecoder() # Single Segment bitcoin address

            elif self.qr_type == QRType.SIGN_MESSAGE:
                self.decoder = SignMessageQrDecoder() # Single Segment sign message request

            elif self.qr_type == QRType.WALLET__SPECTER:
                self.decoder = SpecterWalletQrDecoder() # Specter Desktop Wallet Export decoder

            elif self.qr_type == QRType.WALLET__GENERIC:
                self.decoder = GenericWalletQrDecoder()
                
            elif self.qr_type == QRType.WALLET__CONFIGFILE:
                self.decoder = MultiSigConfigFileQRDecoder()

            elif self.qr_type == QRType.PASSPHRASE:
                self.decoder = PassphraseQrDecoder() # BIP39 passphrase

            elif self.qr_type == QRType.SEED__ENCRYPTEDQR:
                self.decoder = EncryptedQrDecoder()

            elif self.qr_type == QRType.ENCRYPTION_KEY:
                self.decoder = EncryptionKeyQrDecoder()

            elif self.qr_type == QRType.WIF:
                self.decoder = WifQrDecoder()

            elif self.qr_type == QRType.BIP38:
                self.decoder = Bip38QrDecoder()

            elif self.qr_type == QRType.SET_TIME:
                self.decoder = TimeQrDecoder()

            elif self.qr_type == QRType.TEXT:
                self.decoder = TextQrDecoder()

        elif self.qr_type != qr_type:
            raise Exception('QR Fragment Unexpected Type Change')
        
        if not self.decoder:
            # Did not find any recognizable format
            return DecodeQRStatus.INVALID

        # Process the binary formats first
        if self.qr_type in [QRType.SEED__COMPACTSEEDQR, QRType.SEED__ENCRYPTEDQR]:
            rt = self.decoder.add(data, self.qr_type)
            if rt == DecodeQRStatus.COMPLETE:
                self.complete = True
            elif rt == DecodeQRStatus.WRONG_KEY:
                self.wrong_key = True
            return rt

        # Convert to string data
        if type(data) == bytes:
            # Should always be bytes, but the test suite has some manual datasets that
            # are strings.
            # TODO: Convert the test suite rather than handle here?
            try:
                qr_str = data.decode('utf-8')
            except UnicodeDecodeError:
                self.is_nonUTF8 = True
                return DecodeQRStatus.INVALID
        else:
            # it's already str data
            qr_str = data

        if self.qr_type in [QRType.PSBT__UR2, QRType.OUTPUT__UR, QRType.ACCOUNT__UR, QRType.BYTES__UR]:
            added_part = self.decoder.receive_part(qr_str)
            if self.decoder.is_complete():
                self.complete = True
                return DecodeQRStatus.COMPLETE
            if added_part:
                return DecodeQRStatus.PART_COMPLETE
            else:
                return DecodeQRStatus.PART_EXISTING

        else:
            # All other formats use the same method signature
            rt = self.decoder.add(qr_str, self.qr_type)
            if rt == DecodeQRStatus.COMPLETE:
                self.complete = True
            return rt


    def _should_run_aggressive_fallback(self) -> bool:
        if self._scan_attempt_count <= FAST_QR_INITIAL_AGGRESSIVE_TRIES:
            return True

        if self._dense_scan_mode:
            interval = DENSE_QR_FALLBACK_INTERVAL
        elif self.qr_type in [QRType.PSBT__UR2, QRType.OUTPUT__UR, QRType.ACCOUNT__UR, QRType.BYTES__UR]:
            interval = MULTIPART_QR_FALLBACK_INTERVAL
        elif self.qr_type in [QRType.PSBT__SPECTER, QRType.PSBT__BBQR]:
            interval = FAST_QR_FALLBACK_INTERVAL
        else:
            interval = FAST_QR_FALLBACK_INTERVAL

        return self._scan_attempt_count % interval == 0


    def _should_run_wechat_fallback(self) -> bool:
        if self._scan_attempt_count <= FAST_QR_INITIAL_AGGRESSIVE_TRIES:
            return True
        return self._scan_attempt_count % WECHAT_QR_FALLBACK_INTERVAL == 0


    # TODO: Refactor all of these specific `get_` to just something generic like
    #   `get_data` and let each QRDecoder class return whatever it needs to as a
    #   str, tuple, dict, etc?
    def get_psbt(self):
        if self.complete:
            data = self.get_data_psbt()
            if data != None:
                try:
                    return psbt.PSBT.parse(data)
                except:
                    return None
        return None


    def get_data_psbt(self):
        if self.complete:
            if self.qr_type == QRType.PSBT__UR2:
                cbor = self.decoder.result_message().cbor
                return UR_PSBT.from_cbor(cbor).data

            else:
                # All the other psbt decoder types use the same method signature
                return self.decoder.get_data()

        return None


    def get_base64_psbt(self):
        if self.complete:
            data = self.get_data_psbt()
            b64_psbt = b2a_base64(data)

            if b64_psbt[-1:] == b"\n":
                b64_psbt = b64_psbt[:-1]

            return b64_psbt.decode("utf-8")
        return None


    def get_seed_phrase(self):
        if self.is_seed:
            return self.decoder.get_seed_phrase()

    def get_seed_type(self):
        if self.is_seed:
            return self.decoder.get_seed_type()

    def get_xprv(self):
        if self.is_xprv:
            return self.decoder.get_xprv()

    def get_slip39_share(self):
        if self.is_slip39_share:
            return self.decoder.get_share()


    def get_settings_data(self):
        if self.is_settings:
            return self.decoder.data


    def get_address(self):
        if self.is_address:
            return self.decoder.get_address()


    def get_address_type(self):
        if self.is_address:
            return self.decoder.get_address_type()

    def get_time(self):
        if self.is_time:
            return self.decoder.get_time()


    def get_passphrase(self):
        if self.is_passphrase:
            return self.decoder.get_passphrase()


    def get_encryption_key(self):
        if self.is_encryptionkey:
            return self.decoder.get_encryption_key()

    def get_wif(self):
        if self.is_wif:
            return self.decoder.get_wif()

    def get_bip38(self):
        if self.is_bip38:
            return self.decoder.get_bip38()


    def get_public_data(self):
        if self.is_encrypted_seedqr:
            return self.decoder.get_public_data()


    def get_text(self):
        if self.is_text:
            return self.decoder.get_text()


    def get_qr_data(self) -> dict:
        """
        This provides a single access point for external code to retrieve the QR data,
        regardless of which decoder is actually instantiated.
        """
        # TODO: Implement this approach across all decoders
        return self.decoder.get_qr_data()


    def get_wallet_descriptor(self):
        if self.is_wallet_descriptor:
            if self.qr_type in [QRType.OUTPUT__UR, QRType.ACCOUNT__UR, QRType.BYTES__UR]:
                cbor = self.decoder.result_message().cbor
                if self.qr_type == QRType.OUTPUT__UR:
                    return Output.from_cbor(cbor).descriptor()
                elif self.qr_type == QRType.ACCOUNT__UR:
                    return Account.from_cbor(cbor).output_descriptors[0].descriptor()
                elif self.qr_type == QRType.BYTES__UR:
                    raw = Bytes.from_cbor(cbor).data
                    descriptor = DecodeQR.multisig_setup_file_to_descriptor(raw.decode("utf-8"))
                    return descriptor
            else:
                # All the other wallet output descriptor decoder types use the same method signature
                return self.decoder.get_wallet_descriptor()


    def get_percent_complete(self, weight_mixed_frames: bool = False) -> int:
        if not self.decoder:
            return 0

        if self.qr_type in [QRType.PSBT__UR2, QRType.OUTPUT__UR, QRType.ACCOUNT__UR, QRType.BYTES__UR]:
            return int(self.decoder.estimated_percent_complete(weight_mixed_frames=weight_mixed_frames) * 100)

        elif self.qr_type in [QRType.PSBT__SPECTER, QRType.PSBT__BBQR]:
            if self.decoder.total_segments == None:
                return 0
            return int((self.decoder.collected_segments / self.decoder.total_segments) * 100)

        elif self.decoder.total_segments == 1:
            # The single frame QR formats are all or nothing
            if self.decoder.complete:
                return 100
            else:
                return 0

        else:
            return 0


    @property
    def is_complete(self) -> bool:
        return self.complete


    @property
    def is_invalid(self) -> bool:
        return self.qr_type == QRType.INVALID


    @property
    def is_psbt(self) -> bool:
        return self.qr_type in [
            QRType.PSBT__UR2,
            QRType.PSBT__BBQR,
            QRType.PSBT__SPECTER,
            QRType.PSBT__BASE64,
            QRType.PSBT__BASE43,
        ]


    @property
    def is_seed(self):
        return self.qr_type in [
            QRType.SEED__SEEDQR,
            QRType.SEED__COMPACTSEEDQR,
            QRType.SEED__UR2,
            QRType.SEED__MNEMONIC,
            QRType.SEED__FOUR_LETTER_MNEMONIC,
        ]

    @property
    def is_slip39_share(self) -> bool:
        return self.qr_type == QRType.SEED__SLIP39

    @property
    def is_xprv(self) -> bool:
        return self.qr_type == QRType.SEED__XPRV
    

    @property
    def is_json(self):
        return self.qr_type in [QRType.SETTINGS, QRType.JSON]
        

    @property
    def is_address(self):
        return self.qr_type == QRType.BITCOIN_ADDRESS
        

    @property
    def is_sign_message(self):
        return self.qr_type == QRType.SIGN_MESSAGE

    @property
    def is_time(self):
        return self.qr_type == QRType.SET_TIME

    @property
    def is_wif(self):
        return self.qr_type == QRType.WIF

    @property
    def is_bip38(self):
        return self.qr_type == QRType.BIP38
        

    @property
    def is_wallet_descriptor(self):
        check = self.qr_type in [QRType.WALLET__SPECTER, QRType.WALLET__UR, QRType.WALLET__CONFIGFILE, QRType.WALLET__GENERIC, QRType.OUTPUT__UR]
        
        if self.qr_type in [QRType.BYTES__UR]:
            cbor = self.decoder.result_message().cbor
            raw = Bytes.from_cbor(cbor).data
            data = raw.decode("utf-8").lower()
            check = 'policy:' in data and "format:" in data and "derivation:" in data
        
        return check

    @property
    def is_settings(self):
        return self.qr_type == QRType.SETTINGS


    @property
    def is_encrypted_seedqr(self) -> bool:
        return self.qr_type == QRType.SEED__ENCRYPTEDQR


    @staticmethod
    def _image_to_pil(image):
        if image is None:
            return None
        if isinstance(image, Image.Image):
            return image
        if np is None:
            return None
        try:
            array = np.asarray(image, dtype="uint8")
        except Exception:
            return None

        try:
            if getattr(array, "ndim", 0) == 2:
                return Image.fromarray(array, "L")
            if getattr(array, "ndim", 0) == 3:
                if array.shape[2] == 4:
                    return Image.fromarray(array[:, :, :4], "RGBA").convert("RGB")
                return Image.fromarray(array[:, :, :3], "RGB")
        except Exception:
            return None
        return None


    @staticmethod
    def _otsu_threshold(gray_image):
        try:
            histogram = gray_image.histogram()
        except Exception:
            return None

        total = sum(histogram)
        if total <= 0:
            return None

        sum_all = sum(level * count for level, count in enumerate(histogram))
        sum_background = 0
        weight_background = 0
        max_variance = -1
        threshold = 160

        for level, count in enumerate(histogram):
            weight_background += count
            if weight_background == 0:
                continue
            weight_foreground = total - weight_background
            if weight_foreground == 0:
                break

            sum_background += level * count
            mean_background = sum_background / weight_background
            mean_foreground = (sum_all - sum_background) / weight_foreground
            variance = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
            if variance > max_variance:
                max_variance = variance
                threshold = level

        return max(96, min(208, threshold))


    @staticmethod
    def _threshold_candidate(gray_image, threshold):
        return gray_image.point(lambda value: 255 if value > threshold else 0, mode="L")


    @staticmethod
    def _iter_qr_point_sets(points):
        if points is None or np is None:
            return tuple()
        try:
            point_array = np.asarray(points, dtype="float32")
            if point_array.size < 8:
                return tuple()
            return tuple(point_array.reshape((-1, 4, 2)))
        except Exception:
            return tuple()


    @staticmethod
    def _order_qr_points(points):
        if np is None:
            return None
        try:
            pts = np.asarray(points, dtype="float32").reshape((4, 2))
            rect = np.zeros((4, 2), dtype="float32")
            sums = pts.sum(axis=1)
            rect[0] = pts[np.argmin(sums)]
            rect[2] = pts[np.argmax(sums)]
            diffs = np.diff(pts, axis=1).reshape((4,))
            rect[1] = pts[np.argmin(diffs)]
            rect[3] = pts[np.argmax(diffs)]
            if not np.isfinite(rect).all():
                return None
            return rect
        except Exception:
            return None


    @staticmethod
    def _rectified_qr_region_candidates(gray_image, points):
        if cv2 is None or np is None:
            return tuple()

        rect = DecodeQR._order_qr_points(points)
        if rect is None:
            return tuple()

        try:
            width_a = np.linalg.norm(rect[2] - rect[3])
            width_b = np.linalg.norm(rect[1] - rect[0])
            height_a = np.linalg.norm(rect[1] - rect[2])
            height_b = np.linalg.norm(rect[0] - rect[3])
            qr_edge = max(width_a, width_b, height_a, height_b)
            if qr_edge < 32:
                return tuple()

            target_size = int(max(
                OPENCV_QR_ROI_MIN_SIZE,
                min(OPENCV_QR_ROI_MAX_SIZE, qr_edge * 2),
            ))
            destination = np.array(
                [
                    [0, 0],
                    [target_size - 1, 0],
                    [target_size - 1, target_size - 1],
                    [0, target_size - 1],
                ],
                dtype="float32",
            )
            matrix = cv2.getPerspectiveTransform(rect, destination)
            source = np.asarray(gray_image, dtype="uint8")
            warped = cv2.warpPerspective(
                source,
                matrix,
                (target_size, target_size),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=255,
            )
            rectified = Image.fromarray(warped, "L")
        except Exception:
            return tuple()

        candidates = [rectified]
        try:
            candidates.append(ImageOps.expand(rectified, border=OPENCV_QR_ROI_BORDER, fill=255))
        except Exception:
            pass
        try:
            candidates.append(ImageOps.autocontrast(rectified, cutoff=2))
        except Exception:
            pass
        try:
            candidates.append(rectified.filter(ImageFilter.SHARPEN))
        except Exception:
            pass
        try:
            threshold = DecodeQR._otsu_threshold(rectified)
            if threshold is not None:
                thresholded = DecodeQR._threshold_candidate(rectified, threshold)
                candidates.append(thresholded)
                candidates.append(ImageOps.expand(thresholded, border=OPENCV_QR_ROI_BORDER, fill=255))
        except Exception:
            pass
        return tuple(candidates)


    @staticmethod
    def _roi_hint_from_points(points, width: int, height: int):
        rect = DecodeQR._order_qr_points(points)
        if rect is None:
            return None
        try:
            left = max(0, float(np.min(rect[:, 0])))
            top = max(0, float(np.min(rect[:, 1])))
            right = min(float(width), float(np.max(rect[:, 0])))
            bottom = min(float(height), float(np.max(rect[:, 1])))
            if right - left < 32 or bottom - top < 32:
                return None
            margin = max(right - left, bottom - top) * QR_ROI_HINT_MARGIN_RATIO
            return (
                max(0, int(left - margin)),
                max(0, int(top - margin)),
                min(width, int(right + margin)),
                min(height, int(bottom + margin)),
            )
        except Exception:
            return None


    @staticmethod
    def _add_roi_hint_candidates(candidates, gray_image, roi_hint):
        if not roi_hint:
            return

        try:
            left, top, right, bottom = [int(value) for value in roi_hint]
        except Exception:
            return

        left = max(0, min(left, gray_image.width - 1))
        top = max(0, min(top, gray_image.height - 1))
        right = max(left + 1, min(right, gray_image.width))
        bottom = max(top + 1, min(bottom, gray_image.height))
        if right - left < 48 or bottom - top < 48:
            return

        try:
            crop = gray_image.crop((left, top, right, bottom))
            target_size = max(
                OPENCV_QR_ROI_MIN_SIZE,
                min(OPENCV_QR_ROI_MAX_SIZE, max(crop.size) * 2),
            )
            roi = ImageOps.pad(
                crop,
                (target_size, target_size),
                method=Image.Resampling.BILINEAR,
                color=255,
            )
            candidates.append(roi)
            candidates.append(ImageOps.expand(roi, border=OPENCV_QR_ROI_BORDER, fill=255))
            candidates.append(ImageOps.autocontrast(roi, cutoff=2))
            candidates.append(roi.filter(ImageFilter.SHARPEN))
            threshold = DecodeQR._otsu_threshold(roi)
            if threshold is not None:
                candidates.append(DecodeQR._threshold_candidate(roi, threshold))
        except Exception:
            pass


    @staticmethod
    def _add_opencv_rectified_candidates(candidates, gray_image):
        if cv2 is None or np is None:
            return None

        detector = DecodeQR._get_opencv_qr_detector()
        if detector is None:
            return None

        try:
            image_array = np.asarray(gray_image, dtype="uint8")
        except Exception:
            return None

        point_sets = []
        try:
            detected, points = detector.detect(image_array)
            if detected:
                point_sets.extend(DecodeQR._iter_qr_point_sets(points))
        except Exception:
            pass

        if hasattr(detector, "detectMulti"):
            try:
                detected, points = detector.detectMulti(image_array)
                if detected:
                    point_sets.extend(DecodeQR._iter_qr_point_sets(points))
            except Exception:
                pass

        seen = set()
        regions_added = 0
        roi_hint = None
        for point_set in point_sets:
            rect = DecodeQR._order_qr_points(point_set)
            if rect is None:
                continue
            key = tuple(int(round(value / 4.0)) for value in rect.reshape((8,)))
            if key in seen:
                continue
            seen.add(key)
            region_candidates = DecodeQR._rectified_qr_region_candidates(gray_image, rect)
            if not region_candidates:
                continue
            candidates.extend(region_candidates)
            if roi_hint is None:
                roi_hint = DecodeQR._roi_hint_from_points(rect, gray_image.width, gray_image.height)
            regions_added += 1
            if regions_added >= OPENCV_QR_ROI_MAX_REGIONS:
                break
        return roi_hint


    @staticmethod
    def _add_center_crop_candidates(candidates, gray_image, ratios, heavy: bool = False):
        min_dim = min(gray_image.width, gray_image.height)
        for crop_ratio in ratios:
            crop_size = int(min_dim * crop_ratio)
            if crop_size < 96 or crop_size >= min_dim - 8:
                continue
            left = max(0, (gray_image.width - crop_size) // 2)
            top = max(0, (gray_image.height - crop_size) // 2)
            try:
                center_crop = gray_image.crop((left, top, left + crop_size, top + crop_size))
                target_size = (min_dim, min_dim)
                centered = center_crop.resize(target_size, Image.Resampling.NEAREST)
                candidates.append(centered)
                candidates.append(ImageOps.autocontrast(centered, cutoff=2))
                candidates.append(centered.filter(ImageFilter.SHARPEN))
                if crop_ratio <= 0.30:
                    smoothed = center_crop.resize(target_size, Image.Resampling.BILINEAR)
                    candidates.append(smoothed)
                    candidates.append(smoothed.filter(ImageFilter.SHARPEN))
                    padded = ImageOps.expand(centered, border=16, fill=255)
                    candidates.append(padded)
                    candidates.append(padded.filter(ImageFilter.SHARPEN))
                if heavy:
                    candidates.append(centered.filter(ImageFilter.MinFilter(3)))
                    if crop_ratio <= 0.22:
                        candidates.append(center_crop.resize(
                            (target_size[0] * 2, target_size[1] * 2),
                            Image.Resampling.BILINEAR,
                        ))
                    centered_threshold = DecodeQR._otsu_threshold(centered)
                    if centered_threshold is not None:
                        candidates.append(DecodeQR._threshold_candidate(centered, centered_threshold))
            except Exception:
                pass


    @staticmethod
    def _qr_candidate_images(
        image,
        aggressive: bool = True,
        include_fast_candidates: bool = True,
        roi_hint=None,
        dense_scan_mode: bool = False,
    ):
        pil_image = DecodeQR._image_to_pil(image)
        if pil_image is None:
            return tuple(), None

        candidates = [pil_image]
        gray_image = pil_image if pil_image.mode == "L" else pil_image.convert("L")
        if gray_image is not pil_image:
            candidates.append(gray_image)

        DecodeQR._add_roi_hint_candidates(candidates, gray_image, roi_hint)
        try:
            if roi_hint is None or not dense_scan_mode:
                candidates.append(ImageOps.autocontrast(gray_image, cutoff=2))
        except Exception:
            pass
        new_roi_hint = None

        if include_fast_candidates and roi_hint is None:
            DecodeQR._add_center_crop_candidates(
                candidates,
                gray_image,
                FAST_CENTER_CROP_RATIOS,
                heavy=False,
            )

        if aggressive:
            new_roi_hint = DecodeQR._add_opencv_rectified_candidates(candidates, gray_image)

            if not (dense_scan_mode and roi_hint is not None):
                quiet_border = max(8, min(32, min(gray_image.width, gray_image.height) // 16))
                try:
                    candidates.append(ImageOps.expand(gray_image, border=quiet_border, fill=255))
                except Exception:
                    pass

                try:
                    candidates.append(DecodeQR._threshold_candidate(gray_image, 160))
                except Exception:
                    pass

                try:
                    otsu_threshold = DecodeQR._otsu_threshold(gray_image)
                    if otsu_threshold is not None:
                        candidates.append(DecodeQR._threshold_candidate(gray_image, otsu_threshold))
                except Exception:
                    pass

                try:
                    candidates.append(gray_image.filter(ImageFilter.SHARPEN))
                except Exception:
                    pass

                try:
                    dilated = gray_image.filter(ImageFilter.MinFilter(3))
                    candidates.append(dilated)
                    candidates.append(ImageOps.autocontrast(dilated, cutoff=2))
                except Exception:
                    pass

                if roi_hint is None:
                    DecodeQR._add_center_crop_candidates(
                        candidates,
                        gray_image,
                        CENTER_CROP_RATIOS,
                        heavy=True,
                    )

                    min_dim = min(gray_image.width, gray_image.height)
                    if min_dim <= 720:
                        scales = (2,) if min_dim > 360 else (2, 3)
                        for scale in scales:
                            enlarged = gray_image.resize(
                                (max(1, gray_image.width * scale), max(1, gray_image.height * scale)),
                                Image.Resampling.NEAREST,
                            )
                            candidates.append(enlarged)
                            try:
                                candidates.append(ImageOps.autocontrast(enlarged, cutoff=2))
                            except Exception:
                                pass

        return tuple(candidates), new_roi_hint


    @staticmethod
    def _decode_qr_with_pyzbar(candidates, is_binary: bool):
        if pyzbar is None or ZBarSymbol is None:
            return None

        for candidate in candidates:
            try:
                barcodes = pyzbar.decode(candidate, symbols=[ZBarSymbol.QRCODE], binary=is_binary)
            except Exception:
                continue
            for barcode in barcodes:
                return barcode.data
        return None


    @staticmethod
    def _decode_qr_with_zxingcpp(candidates, is_binary: bool):
        if zxingcpp is None:
            return None

        try:
            qr_format = zxingcpp.BarcodeFormat.QRCode
        except Exception:
            qr_format = None

        try:
            local_average = zxingcpp.Binarizer.LocalAverage
        except Exception:
            local_average = None

        try:
            fixed_threshold = zxingcpp.Binarizer.FixedThreshold
        except Exception:
            fixed_threshold = None

        for candidate in candidates:
            option_sets = (
                {
                    "formats": qr_format,
                    "try_rotate": False,
                    "try_downscale": False,
                    "binarizer": local_average,
                    "is_pure": False,
                },
                {
                    "formats": qr_format,
                    "try_rotate": False,
                    "try_downscale": False,
                    "binarizer": fixed_threshold,
                    "is_pure": True,
                },
                {"formats": qr_format},
            )
            barcodes = []
            for options in option_sets:
                try:
                    kwargs = {key: value for key, value in options.items() if value is not None}
                    if qr_format is None:
                        kwargs.pop("formats", None)
                    barcodes = zxingcpp.read_barcodes(candidate, **kwargs)
                except TypeError:
                    try:
                        if qr_format is None:
                            barcodes = zxingcpp.read_barcodes(candidate)
                        else:
                            barcodes = zxingcpp.read_barcodes(candidate, formats=qr_format)
                    except Exception:
                        barcodes = []
                except Exception:
                    barcodes = []
                if barcodes:
                    break
            for barcode in barcodes:
                if is_binary:
                    raw = getattr(barcode, "bytes", None)
                    if raw is not None:
                        return bytes(raw)
                    text = getattr(barcode, "text", "")
                    if text:
                        return text.encode("utf-8")
                    continue

                text = getattr(barcode, "text", "")
                if text:
                    return text
                raw = getattr(barcode, "bytes", None)
                if raw:
                    try:
                        return bytes(raw).decode("utf-8")
                    except Exception:
                        return bytes(raw).decode("utf-8", errors="ignore")
        return None


    @staticmethod
    def _get_wechat_qr_detector():
        if cv2 is None:
            return None

        detector = getattr(DecodeQR, "_wechat_qr_detector", None)
        if detector is not None:
            return detector

        wechat_module = getattr(cv2, "wechat_qrcode", None)
        detector_factory = getattr(wechat_module, "WeChatQRCode", None) if wechat_module else None
        if detector_factory is None:
            detector_factory = getattr(cv2, "wechat_qrcode_WeChatQRCode", None)
        if detector_factory is None:
            return None

        model_paths = [WECHAT_QR_MODEL_DIR / filename for filename in WECHAT_QR_MODEL_FILES]
        model_args = [str(path) for path in model_paths if path.exists()]
        try:
            detector = detector_factory(*model_args) if len(model_args) == len(model_paths) else detector_factory()
        except Exception:
            try:
                detector = detector_factory()
            except Exception:
                return None

        DecodeQR._wechat_qr_detector = detector
        return detector


    @staticmethod
    def _decode_qr_with_wechat(candidates, is_binary: bool):
        if cv2 is None or np is None:
            return None

        detector = DecodeQR._get_wechat_qr_detector()
        if detector is None:
            return None

        for candidate in candidates:
            try:
                if max(candidate.size) > OPENCV_QR_MAX_SIZE:
                    continue
                image_array = np.asarray(candidate.convert("RGB"), dtype="uint8")
                decoded = detector.detectAndDecode(image_array)
            except Exception:
                continue

            texts = None
            if isinstance(decoded, tuple):
                texts = decoded[0]
            else:
                texts = decoded
            if isinstance(texts, str):
                texts = (texts,)

            try:
                iterator = iter(texts)
            except Exception:
                continue

            for data in iterator:
                if data:
                    return data.encode("utf-8") if is_binary else data
        return None


    @staticmethod
    def _decode_qr_with_opencv(candidates, is_binary: bool):
        if cv2 is None or np is None:
            return None

        detector = DecodeQR._get_opencv_qr_detector()
        if detector is None:
            return None

        for candidate in candidates:
            try:
                gray_candidate = candidate if candidate.mode == "L" else candidate.convert("L")
                candidate_array = np.asarray(gray_candidate, dtype="uint8")
                if hasattr(detector, "detectAndDecodeMulti"):
                    detected, decoded_info, _points, _straight = detector.detectAndDecodeMulti(candidate_array)
                    if detected:
                        for data in decoded_info:
                            if data:
                                return data.encode("utf-8") if is_binary else data
                data, _points, _straight = detector.detectAndDecode(candidate_array)
                if not data and hasattr(detector, "detectAndDecodeCurved"):
                    data, _points, _straight = detector.detectAndDecodeCurved(candidate_array)
                if data:
                    return data.encode("utf-8") if is_binary else data
            except Exception:
                continue
        return None


    @staticmethod
    def _get_opencv_qr_detector():
        if cv2 is None:
            return None

        detector = getattr(DecodeQR, "_opencv_qr_detector", None)
        if detector is None:
            try:
                detector = cv2.QRCodeDetector()
            except Exception:
                return None
            for setter_name, value in (("setEpsX", 0.2), ("setEpsY", 0.2)):
                try:
                    setter = getattr(detector, setter_name, None)
                    if setter is not None:
                        setter(value)
                except Exception:
                    pass
            DecodeQR._opencv_qr_detector = detector
        return detector


    @staticmethod
    def extract_qr_data(
        image,
        is_binary: bool = False,
        aggressive: bool = True,
        include_fast_candidates: bool = True,
        include_wechat: bool = True,
        roi_hint=None,
        dense_scan_mode: bool = False,
    ) -> bytes | str | None:
        data, _roi_hint = DecodeQR.extract_qr_data_with_hint(
            image,
            is_binary=is_binary,
            aggressive=aggressive,
            include_fast_candidates=include_fast_candidates,
            include_wechat=include_wechat,
            roi_hint=roi_hint,
            dense_scan_mode=dense_scan_mode,
        )
        return data


    @staticmethod
    def extract_qr_data_with_hint(
        image,
        is_binary: bool = False,
        aggressive: bool = True,
        include_fast_candidates: bool = True,
        include_wechat: bool = True,
        roi_hint=None,
        dense_scan_mode: bool = False,
    ):
        if image is None:
            return None, None

        candidates, new_roi_hint = DecodeQR._qr_candidate_images(
            image,
            aggressive=aggressive,
            include_fast_candidates=include_fast_candidates,
            roi_hint=roi_hint,
            dense_scan_mode=dense_scan_mode,
        )
        if not candidates:
            return None, new_roi_hint

        decoder_order = [
            DecodeQR._decode_qr_with_zxingcpp,
            DecodeQR._decode_qr_with_pyzbar,
        ]
        if aggressive:
            if include_wechat:
                decoder_order.append(DecodeQR._decode_qr_with_wechat)
            decoder_order.append(DecodeQR._decode_qr_with_opencv)

        for decoder in decoder_order:
            decoder_candidates = candidates
            if decoder in (DecodeQR._decode_qr_with_wechat, DecodeQR._decode_qr_with_opencv):
                decoder_candidates = tuple(
                    candidate
                    for candidate in candidates[:OPENCV_QR_MAX_CANDIDATES]
                    if max(candidate.size) <= OPENCV_QR_MAX_SIZE
                )
                if not decoder_candidates:
                    continue
            data = decoder(decoder_candidates, is_binary=is_binary)
            if data is not None:
                return data, new_roi_hint

        return None, new_roi_hint


    @staticmethod
    def detect_segment_type(s, wordlist_language_code=None):
        # print("-------------- DecodeQR.detect_segment_type --------------")
        # print(type(s))
        # print(len(s))

        try:
            # Convert to str data
            if type(s) == bytes:
                # Should always be bytes, but the test suite has some manual datasets that
                # are strings.
                # TODO: Convert the test suite rather than handle here?
                s = s.decode('utf-8')

            # PSBT
            if re.search("^UR:CRYPTO-PSBT/", s, re.IGNORECASE):
                return QRType.PSBT__UR2

            elif re.search("^UR:CRYPTO-OUTPUT/", s, re.IGNORECASE):
                return QRType.OUTPUT__UR

            elif re.search("^UR:CRYPTO-ACCOUNT/", s, re.IGNORECASE):
                return QRType.ACCOUNT__UR

            elif re.search(r'^p(\d+)of(\d+) ([A-Za-z0-9+\/=]+$)', s, re.IGNORECASE): #must be base64 characters only in segment
                return QRType.PSBT__SPECTER

            elif re.search("^UR:BYTES/", s, re.IGNORECASE):
                return QRType.BYTES__UR

            elif s.upper().startswith("B$"):
                try:
                    _, file_type, _, _ = parse_bbqr_header(s.upper())
                    if file_type == "P":
                        return QRType.PSBT__BBQR
                except Exception:
                    pass

            elif DecodeQR.is_base64_psbt(s):
                return QRType.PSBT__BASE64

            # Wallet Descriptor
            desc_str = s.replace("\n","").replace(" ","")
            if re.search(r'^p(\d+)of(\d+) ', s, re.IGNORECASE):
                # when not a SPECTER Base64 PSBT from above, assume it's json
                return QRType.WALLET__SPECTER

            elif re.search(r'^\{\"label\".*\"descriptor\"\:.*', desc_str, re.IGNORECASE):
                # if json starting with label and contains descriptor, assume specter wallet json
                return QRType.WALLET__SPECTER

            elif "multisig setup file" in s.lower():
                return QRType.WALLET__CONFIGFILE

            elif "sortedmulti" in s:
                return QRType.WALLET__GENERIC

            # Seed
            if re.search(r'\d{48,96}', s):
                return QRType.SEED__SEEDQR

            # Bitcoin Address
            elif DecodeQR.is_bitcoin_address(s):
                return QRType.BITCOIN_ADDRESS

            # message signing
            elif s.startswith("signmessage"):
                return QRType.SIGN_MESSAGE

            # config data
            if s.startswith("settings::"):
                return QRType.SETTINGS

            # GoPro Labs precision time command
            if re.match(r'^oT(\d{12}(\.\d{2})?|0)$', s):
                return QRType.SET_TIME

            # Seed
            # create 4 letter wordlist only if not PSBT (performance gain)
            wordlist = Seed.get_wordlist(wordlist_language_code)
            try:
                _4LETTER_WORDLIST = [word[:4].strip() for word in wordlist]
            except:
                _4LETTER_WORDLIST = []

            from importlib import import_module
            slip39_wordlist = import_module("shamir_mnemonic.wordlist").WORDLIST

            if all(x in wordlist for x in s.strip().lower().split()):
                # checks if all words in list are in bip39 word list
                return QRType.SEED__MNEMONIC

            elif all(x in _4LETTER_WORDLIST for x in s.strip().lower().split()):
                # checks if all 4 letter words are in list are in 4 letter bip39 word list
                return QRType.SEED__FOUR_LETTER_MNEMONIC

            elif all(x in slip39_wordlist for x in s.strip().lower().split()):
                return QRType.SEED__SLIP39

            elif DecodeQR.is_base43_psbt(s):
                return QRType.PSBT__BASE43

            # WIF private key
            try:
                ec.PrivateKey.from_wif(s.strip())
                return QRType.WIF
            except Exception:
                pass

            try:
                hdkey = bip32.HDKey.from_string(s.strip())
                if hdkey.is_private:
                    return QRType.SEED__XPRV
            except Exception:
                pass

            # BIP38 encrypted key
            try:
                from seedsigner.models.bip38 import BIP38Key
                BIP38Key(s.strip())
                return QRType.BIP38
            except Exception:
                pass

        except UnicodeDecodeError:
            # Probably this isn't meant to be string data; check if it's valid byte data
            # below.
            pass

        # Is it byte data?
        if not isinstance(s, bytes):
            try:
                # TODO: remove this check & conversion once above cast to str is removed
                s = s.encode()
            except UnicodeError:
                # Couldn't convert back to bytes; shouldn't happen
                raise Exception("Conversion to bytes failed")

        # Byte lengths for CompactSeedQR entropy:
        #   32 bytes for 24-word
        #   28 bytes for 21-word
        #   24 bytes for 18-word
        #   20 bytes for 15-word
        #   16 bytes for 12-word
        if len(s) in (16, 20, 24, 28, 32):
            try:
                bitstream = ""
                for b in s:
                    bitstream += bin(b).lstrip('0b').zfill(8)
                # print(bitstream)

                return QRType.SEED__COMPACTSEEDQR
            except Exception as e:
                # Couldn't extract byte data; assume it's not a byte format
                pass

        else:
            from seedsigner.models.encryption import EncryptedQRCode
            from seedsigner.helpers.base43 import base43_decode
            encrypted_qr = EncryptedQRCode()
            public_data = None
            try:  # Try to decode base43 data
                if isinstance(s, bytes):
                    s = s.decode('utf-8')
                data_bytes = base43_decode(s)
                public_data = encrypted_qr.public_data(data_bytes)
            except:
                pass
            if not public_data:  # Failed to decode and parse base43
                public_data = encrypted_qr.public_data(s)
            if public_data:
                from seedsigner.models.encryptedqr import EncryptedQR
                encryptedqr = EncryptedQR(encrypted_qr=encrypted_qr, public_data=public_data)
                from seedsigner.controller import Controller
                Controller.get_instance().storage2.set_encryptedqr(encryptedqr)
                return QRType.SEED__ENCRYPTEDQR

        return QRType.INVALID


    @staticmethod   
    def is_base64(s):
        try:
            return base64.b64encode(base64.b64decode(s)) == s.encode('ascii')
        except Exception:
            return False


    @staticmethod   
    def is_base64_psbt(s):
        try:
            if DecodeQR.is_base64(s):
                psbt.PSBT.parse(a2b_base64(s))
                return True
        except Exception:
            return False
        return False


    @staticmethod
    def is_base43_psbt(s):
        try:
            psbt.PSBT.parse(DecodeQR.base43_decode(s))
            return True
        except Exception:
            return False


    @staticmethod
    def base43_decode(s):
        chars = b'0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ$*+-./:' #base43 chars

        if isinstance(s, bytes):
            v = s
        if isinstance(s, str):
            v = s.encode('ascii')
        elif isinstance(s, bytearray):
            v = bytes(s)
            
        long_value = 0
        power_of_base = 1
        for c in v[::-1]:
            digit = chars.find(bytes([c]))
            if digit == -1:
                raise Exception('Forbidden character {} for base {}'.format(c, 43))
            # naive but slow variant:   long_value += digit * (base**i)
            long_value += digit * power_of_base
            power_of_base *= 43
        result = bytearray()
        while long_value >= 256:
            div, mod = divmod(long_value, 256)
            result.append(mod)
            long_value = div
        result.append(long_value)
        nPad = 0
        for c in v:
            if c == chars[0]:
                nPad += 1
            else:
                break
        result.extend(b'\x00' * nPad)
        result.reverse()
        return bytes(result)


    @staticmethod
    def is_bitcoin_address(s):
        if re.search(r'^bitcoin\:.*', s, re.IGNORECASE):
            return True
        elif re.search(r'^((bc1|tb1|bcr|[123]|[mn])[a-zA-HJ-NP-Z0-9]{25,62})$', s, re.IGNORECASE):
            return True
        else:
            return False


    @staticmethod
    def multisig_setup_file_to_descriptor(text) -> str:
        # sample text file, parse the contents and create descriptor
        """
        Name: SeedSigner Dev Funds
        Policy: 4 of 6
        Derivation: m/48'/0'/0'/2'
        Format: P2WSH
        
        E0811B6B: xpub6E8v7uy63pCeJvHe5W8ea8zTnCtKMFgMRb5bueWWcUFMw6sWmUwTqxM8cFiKQRWkA2Fxth9HJZufJwjWTTvU1UGZNpTrh9khrswYMgeHiCt
        852B308F: xpub6ErhgAWfnEqW7xDBm1iLq5JjNyUS65YUFnjHLrRv9zmdDEtuE75bpWQ8o6bSBnpT6AkrrsA8eA5SmEFArZn11KEPaZJzx9mHTXPWZCsxLyh
        7EDF9C59: xpub6DaFfKoe7WpofrbYeNo3Wv2AiLUMeyrPwotXfukFxUHbK4JxaLHTd5394QtH5wnjFzBgr2YnJpHhXv25Zsqv2APmMFvH1DsKHj5LCr3pmXs
        B433E095: xpub6EF51itHko2YhGTjVeuYbBgJjVbTzzpYzn2a3JwZHpDrMePRVgXGBHMx2Yv1KwgLsUn9i7ExcAo8uqMx4pDjVRY9J7qnceFAwRRj16dd5AS
        184D07EB: xpub6EEoTpcQu7N4R8D84pJjZ69j3minevnYLDDoo2HBzYBXTQ4rGVf4XGTyCYFwJuZdsF9MyFYJNzYEjg5LGMA1ubTGWuDnjHAZz6ficVRDTSy
        3E451EFE: xpub6ExQPvQxGBMaPxr8Fv7Vq91ztJFFX3VWvtpvex6UPZ1AptTeuAiJGCtKkgwJkrwpMZMagh9ex6rL4sM8axfFcdQbERoFCRUKTJxrBkJh56g
        """
        
        lines = text.split('\n')
        
        m = 0
        n = 0
        xpubs = []
        x = 0
        derivation = ''
        descriptor = ''
        
        lines = text.split('\n')
        
        for l in lines:
            if l.find('#') == 0:
                # skip comments
                continue
        
            l = l.strip()
        
            if ':' not in l:
                # when label/value divider not found, skip line
                continue
                        
            label, value = l.split(':', 1)
            label = label.strip().lower()
            value = value.strip()
        
            if label == 'policy':
                try:
                    match = re.search(r'(\d+)\D*(\d+)', value)
                    m = int(match.group(1))
                    n = int(match.group(2))
                except:
                    raise Exception(f"Policy line not supported")
            elif label == 'derivation':
                derivation = value
            elif label == 'format':
                if value.lower() in ['p2wsh', 'p2sh-p2wsh', 'p2wsh-p2sh']:
                    script_type = value.lower()
            elif len(label) == 8:
                if len(xpubs) == 0:
                    xpubs = [None] * n
        
                xpubs[x] = {'xfp': label, 'key': value}
                x += 1
        
        if None in xpubs or len(xpubs) != n:
            raise Exception(f"bad or missing xpub")
        
        if m <= 0 or m > 9 or n <= 0 or n > 9:
            raise Exception(f"bad or missing policy")
        
        if len(derivation) == 0:
            raise Exception(f"bad or missing derivation path")
        
        if script_type not in ['p2wsh', 'p2sh-p2wsh', 'p2wsh-p2sh']:
            raise Exception(f"bad or missing script format")
        
        # create descriptor string
        
        if script_type == "p2wsh":
            script_open = "wsh(sortedmulti(" + str(m)
            script_close = "))"
        elif script_type in ["p2sh-p2wsh", 'p2wsh-p2sh']:
            script_open = "sh(wsh(sortedmulti(" + str(m)
            script_close = ")))"
        
        descriptor = script_open
        
        for x in xpubs:
            if derivation[0] == 'm':
                derivation = derivation[1:]
            derivation = derivation.replace("'", "h")
            descriptor += ',[' + x['xfp'] + derivation + "]" + x['key'] + "/{0,1}/*"
        
        descriptor += script_close

        return descriptor



class BaseQrDecoder:
    def __init__(self):
        self.total_segments = None
        self.collected_segments = 0
        self.complete = False

    @property
    def is_complete(self) -> bool:
        return self.complete

    def add(self, segment, qr_type):
        raise Exception("Not implemented in child class")
    
    def get_qr_data(self) -> dict:
        # TODO: standardize this approach across all decoders (example: SignMessageQrDecoder)
        raise Exception("get_qr_data must be implemented in decoder child class")



class BaseSingleFrameQrDecoder(BaseQrDecoder):
    def __init__(self):
        super().__init__()
        self.total_segments = 1



class BaseAnimatedQrDecoder(BaseQrDecoder):
    def __init__(self):
        super().__init__()
        self.segments = []

    def current_segment_num(self, segment) -> int:
        raise Exception("Not implemented in child class")

    def total_segment_nums(self, segment) -> int:
        raise Exception("Not implemented in child class")

    def parse_segment(self, segment) -> str:
        raise Exception("Not implemented in child class")
    
    @property
    def is_valid(self) -> bool:
        return True

    def add(self, segment, qr_type=None):
        if self.total_segments == None:
            self.total_segments = self.total_segment_nums(segment)
            self.segments = [None] * self.total_segments
        elif self.total_segments != self.total_segment_nums(segment):
            raise Exception('Segment total changed unexpectedly')

        if self.segments[self.current_segment_num(segment) - 1] == None:
            self.segments[self.current_segment_num(segment) - 1] = self.parse_segment(segment)
            self.collected_segments += 1
            if self.total_segments == self.collected_segments:
                if self.is_valid:
                    self.complete = True
                    return DecodeQRStatus.COMPLETE
                else:
                    return DecodeQRStatus.INVALID
            return DecodeQRStatus.PART_COMPLETE # new segment added

        return DecodeQRStatus.PART_EXISTING # segment not added because it's already been added



class SpecterPsbtQrDecoder(BaseAnimatedQrDecoder):
    """
        Used to decode Specter Desktop Animated QR PSBT encoding.
    """
    def get_base64_data(self) -> str:
        base64 = "".join(self.segments)
        if self.complete and DecodeQR.is_base64(base64):
            return base64

        return None


    def get_data(self):
        base64 = self.get_base64_data()
        if base64 != None:
            return a2b_base64(base64)

        return None


    def current_segment_num(self, segment) -> int:
        if re.search(r'^p(\d+)of(\d+) ', segment, re.IGNORECASE) != None:
            return int(re.search(r'^p(\d+)of(\d+) ', segment, re.IGNORECASE).group(1))


    def total_segment_nums(self, segment) -> int:
        if re.search(r'^p(\d+)of(\d+) ', segment, re.IGNORECASE) != None:
            return int(re.search(r'^p(\d+)of(\d+) ', segment, re.IGNORECASE).group(2))


    def parse_segment(self, segment) -> str:
        return segment.split(" ")[-1].strip()



class BbqrPsbtQrDecoder(BaseAnimatedQrDecoder):
    """
        Used to decode BlueWallet/Coinkite BBQr animated PSBT encoding.
    """
    def __init__(self):
        super().__init__()
        self.encoding = None
        self.file_type = None

    def _parse_header(self, segment: str) -> tuple[str, str, int, int]:
        encoding, file_type, total, index = parse_bbqr_header(segment.strip().upper())
        if self.encoding is None:
            self.encoding = encoding
            self.file_type = file_type
        elif self.encoding != encoding or self.file_type != file_type:
            raise Exception("BBQr header changed unexpectedly")
        return encoding, file_type, total, index

    def current_segment_num(self, segment) -> int:
        _, _, _, index = self._parse_header(segment)
        return index + 1

    def total_segment_nums(self, segment) -> int:
        _, _, total, _ = self._parse_header(segment)
        return total

    def parse_segment(self, segment) -> str:
        self._parse_header(segment)
        return segment.strip().upper()[8:]

    @property
    def is_valid(self) -> bool:
        return self.file_type == "P" and self.encoding is not None

    def get_data(self):
        if not self.complete or not self.is_valid:
            return None
        return decode_bbqr_data("".join(self.segments), self.encoding)


class Base64PsbtQrDecoder(BaseSingleFrameQrDecoder):
    """
        Decodes single frame base64 encoded qr image.
        Does not support animated qr because no indicator of segments or their order
    """
    def add(self, segment, qr_type=QRType.PSBT__BASE64):
        if DecodeQR.is_base64(segment):
            self.complete = True
            self.data = segment
            self.collected_segments = 1
            return DecodeQRStatus.COMPLETE

        return DecodeQRStatus.INVALID


    def get_base64_data(self) -> str:
        return self.data


    def get_data(self):
        base64 = self.get_base64_data()
        if base64 != None:
            return a2b_base64(base64)

        return None



class Base43PsbtQrDecoder(BaseSingleFrameQrDecoder):
    """
        Decodes single frame base43 encoded qr image.
        Does not support animated qr because no indicator of segments or their order
    """
    def add(self, segment, qr_type=QRType.PSBT__BASE43):
        if DecodeQR.is_base43_psbt(segment):
            self.complete = True
            self.data = DecodeQR.base43_decode(segment)
            self.collected_segments = 1
            return DecodeQRStatus.COMPLETE

        return DecodeQRStatus.INVALID


    def get_data(self):
        return self.data



class SeedQrDecoder(BaseSingleFrameQrDecoder):
    """
        Decodes a single frame representing a BIP39 seed.
        Supports SeedSigner SeedQR numeric (wordlist indices) representation of a seed.
        Supports SeedSigner CompactSeedQR entropy byte representation of a seed.
        Supports mnemonic seed phrase string data.
    """
    def __init__(self, wordlist_language_code):
        super().__init__()
        self.seed_phrase = []
        self.wordlist_language_code = wordlist_language_code
        self.wordlist = Seed.get_wordlist(wordlist_language_code)
        self.word_to_index = {word: idx for idx, word in enumerate(self.wordlist)}
        self.seed_type = "bip39"


    def add(self, segment, qr_type=QRType.SEED__SEEDQR):
        # `segment` data will either be bytes or str, depending on the qr_type
        if qr_type == QRType.SEED__SEEDQR:
            try:
                self.seed_phrase = []

                if len(segment) % 4 != 0:
                    return DecodeQRStatus.INVALID

                num_words = int(len(segment) / 4)
                for i in range(0, num_words):
                    index = int(segment[i * 4: (i*4) + 4])
                    word = self.wordlist[index]
                    # Keep a private string copy so secure wiping decoded words
                    # cannot mutate shared global wordlist string objects.
                    self.seed_phrase.append("".join(word))
                if len(self.seed_phrase) > 0:
                    if not self.has_valid_word_count():
                        return DecodeQRStatus.INVALID
                    self.seed_type = "bip39"
                    self.complete = True
                    self.collected_segments = 1
                    return DecodeQRStatus.COMPLETE
                else:
                    return DecodeQRStatus.INVALID
            except Exception as e:
                return DecodeQRStatus.INVALID

        if qr_type == QRType.SEED__COMPACTSEEDQR:
            logging.info("Trying CompactSeedQR")
            try:
                self.seed_phrase = bip39.mnemonic_from_bytes(segment).split()
                if not self.has_valid_word_count():
                    return DecodeQRStatus.INVALID
                self.seed_type = "bip39"
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception as e:
                logger.exception(repr(e))
                return DecodeQRStatus.INVALID

        elif qr_type == QRType.SEED__MNEMONIC:
            try:
                seed_phrase_list = self.seed_phrase = segment.strip().lower().split()
                if not self.has_valid_word_count():
                    return DecodeQRStatus.INVALID

                is_valid_bip39 = False
                try:
                    Seed(seed_phrase_list, passphrase="", wordlist_language_code=self.wordlist_language_code)
                    is_valid_bip39 = True
                except Exception:
                    is_valid_bip39 = False

                is_valid_aezeed = len(seed_phrase_list) == 24 and aezeed_has_valid_checksum(seed_phrase_list, self.word_to_index)

                if is_valid_aezeed and is_valid_bip39:
                    self.seed_type = "ambiguous"
                elif is_valid_aezeed:
                    self.seed_type = "aezeed"
                elif is_valid_bip39:
                    self.seed_type = "bip39"
                else:
                    return DecodeQRStatus.INVALID

                self.seed_phrase = seed_phrase_list
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception:
                return DecodeQRStatus.INVALID

        elif qr_type == QRType.SEED__FOUR_LETTER_MNEMONIC:
            try:
                seed_phrase_list = segment.strip().lower().split()
                words = []
                for s in seed_phrase_list:
                    # TODO: Pre-calculate this once on startup
                    _4LETTER_WORDLIST = [word[:4].strip() for word in self.wordlist]
                    # Keep a private string copy so secure wiping decoded words
                    # cannot mutate shared global wordlist string objects.
                    words.append("".join(self.wordlist[_4LETTER_WORDLIST.index(s)]))

                # embit mnemonic code to validate
                seed = Seed(words, passphrase="", wordlist_language_code=self.wordlist_language_code)
                if not seed:
                    return DecodeQRStatus.INVALID
                self.seed_phrase = words
                if not self.has_valid_word_count():
                    return DecodeQRStatus.INVALID
                self.seed_type = "bip39"
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception as e:
                return DecodeQRStatus.INVALID

        else:
            return DecodeQRStatus.INVALID

    def get_seed_phrase(self):
        if self.complete:
            return self.seed_phrase[:]
        return []

    def get_seed_type(self):
        if self.complete:
            return self.seed_type
        return None

    def has_valid_word_count(self):
        return len(self.seed_phrase) in (12, 15, 18, 21, 24)


class Slip39ShareDecoder(BaseSingleFrameQrDecoder):
    """Decodes a single-frame SLIP-39 share"""
    def __init__(self):
        super().__init__()
        self.share = None

    def add(self, segment, qr_type=QRType.SEED__SLIP39):
        if qr_type == QRType.SEED__SLIP39:
            try:
                if isinstance(segment, bytes):
                    segment = segment.decode("utf-8")
                segment = segment.lower()
                from shamir_mnemonic import Share as Slip39Share
                Slip39Share.from_mnemonic(segment)
                self.share = segment
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception:
                pass
        return DecodeQRStatus.INVALID

    def get_share(self):
        return self.share


class XprvQrDecoder(BaseSingleFrameQrDecoder):
    def __init__(self):
        super().__init__()
        self.xprv = None

    def add(self, segment, qr_type=QRType.SEED__XPRV):
        if qr_type == QRType.SEED__XPRV:
            try:
                key = bip32.HDKey.from_string(segment.strip())
                if not key.is_private:
                    return DecodeQRStatus.INVALID
                self.xprv = segment.strip()
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception:
                return DecodeQRStatus.INVALID
        return DecodeQRStatus.INVALID

    def get_xprv(self):
        return self.xprv



class SettingsQrDecoder(BaseSingleFrameQrDecoder):
    """
        Decodes settings data from the SettingsQR Generator.
    """
    def __init__(self):
        super().__init__()
        self.data = None


    def add(self, segment, qr_type=QRType.SETTINGS):
        """
            * Ignores unrecognized settings options.
            * Raises an Exception if a settings value is invalid.

            See `Settings.update()` for info on settings validation, especially for
            missing settings.
        """
        if not segment.startswith("settings::"):
            raise Exception("Invalid SettingsQR data")
        
        # Leave any other parsing or validation up to the Settings class itself.
        # SettingsQR are just ascii data to hand it over as-is.
        self.data = segment

        self.complete = True
        self.collected_segments = 1
        return DecodeQRStatus.COMPLETE



class SignMessageQrDecoder(BaseSingleFrameQrDecoder):
    def __init__(self):
        super().__init__()
        self.message = None
        self.derivation_path = None


    def add(self, segment, qr_type=QRType.SIGN_MESSAGE):
        """
            Expected QR data format:

            signmessage {derivation_path} ascii:{message}
        """
        parts = segment.split()
        self.derivation_path = parts[1].replace("h", "'")
        fmt = parts[2].split(":")[0]
        self.message = segment.split(f"{fmt}:")[1]

        # TODO: support formats other than ascii?
        if fmt != "ascii":
            logger.info(f"Sign message: Unsupported format: {fmt}")
            return DecodeQRStatus.INVALID

        self.complete = True
        self.collected_segments = 1

        return DecodeQRStatus.COMPLETE


    def get_qr_data(self) -> dict:
        return dict(derivation_path=self.derivation_path, message=self.message)



class BitcoinAddressQrDecoder(BaseSingleFrameQrDecoder):
    """
        Decodes single frame representing a bitcoin address
    """
    def __init__(self):
        super().__init__()
        self.address = None
        self.address_type = None


    def add(self, segment, qr_type=QRType.BITCOIN_ADDRESS):
        """
            Input may be prefixed with "bitcoin:" but will be ignored.

            RegEx searches for a recognizable bitcoin address.
                * The `^` ensures that the specified address prefixes can only match at
                    the beginning of the address.

            Result will yield the following match groups:
                * group 1: complete address
                * group 2: address prefix
        """
        address_match = re.search(r'^((bc1q|tb1q|bcrt1q|bc1p|tb1p|bcrt1p|[123]|[mn])[a-zA-HJ-NP-Z0-9]{25,64})', segment.split(":")[-1], re.IGNORECASE)
        if address_match != None:
            self.address = address_match.group(1)
            self.complete = True
            self.collected_segments = 1
            
            # Have to handle wallets that uppercase bech32 addresses.
            # Note that it's safe to lowercase the prefix for ALL addr formats.
            addr_prefix = address_match.group(2).lower()
            
            if addr_prefix == "1":
                # Legacy P2PKH. mainnet
                self.address_type = (SettingsConstants.LEGACY_P2PKH, SettingsConstants.MAINNET)

            elif addr_prefix in ["m", "n"]:
                self.address_type = (SettingsConstants.LEGACY_P2PKH, SettingsConstants.TESTNET)

            elif addr_prefix == "3":
                # Nested segwit single sig (p2sh-p2wpkh), nested segwit multisig (p2sh-p2wsh), or legacy multisig (p2sh); mainnet
                # TODO: Would be more correct to use a P2SH constant
                self.address_type = (SettingsConstants.NESTED_SEGWIT, SettingsConstants.MAINNET)

            elif addr_prefix == "2":
                # Nested segwit single sig (p2sh-p2wpkh), nested segwit multisig (p2sh-p2wsh), or legacy multisig (p2sh); testnet / regtest
                self.address_type = (SettingsConstants.NESTED_SEGWIT, SettingsConstants.TESTNET)

            elif addr_prefix == "bc1q":
                # Native Segwit (single sig or multisig), mainnet 
                self.address_type = (SettingsConstants.NATIVE_SEGWIT, SettingsConstants.MAINNET)

            elif addr_prefix == "tb1q":
                # Native Segwit (single sig or multisig), testnet
                self.address_type = (SettingsConstants.NATIVE_SEGWIT, SettingsConstants.TESTNET)

            elif addr_prefix == "bcrt1q":
                # Native Segwit (single sig or multisig), regtest
                self.address_type = (SettingsConstants.NATIVE_SEGWIT, SettingsConstants.REGTEST)

            elif addr_prefix == "bc1p":
                self.address_type = (SettingsConstants.TAPROOT, SettingsConstants.MAINNET)

            elif addr_prefix == "tb1p":
                self.address_type = (SettingsConstants.TAPROOT, SettingsConstants.TESTNET)

            elif addr_prefix == "bcrt1p":
                self.address_type = (SettingsConstants.TAPROOT, SettingsConstants.REGTEST)
            # Note: there is no final "else" here because the regex won't return any other matches.

            # If the addr type is case-insensitive, ensure we return it lowercase
            if self.address_type[0] in [SettingsConstants.NATIVE_SEGWIT, SettingsConstants.TAPROOT]:
                self.address = self.address.lower()

            return DecodeQRStatus.COMPLETE

        logger.debug(f"Invalid address: {segment}")
        return DecodeQRStatus.INVALID


    def get_address(self):
        if self.address != None:
            return self.address
        return None
        

    def get_address_type(self):
        if self.address != None:
            if self.address_type != None:
                return self.address_type
            else:
                return "Unknown"
        return None



class SpecterWalletQrDecoder(BaseAnimatedQrDecoder):
    """
        Decodes animated frames to get a wallet descriptor from Specter Desktop
    """
    def validate_json(self) -> str:
        try:
            j = "".join(self.segments)
            json.loads(j)
        except json.decoder.JSONDecodeError:
            return False
        return True


    @property
    def is_valid(self):
        if self.validate_json():
            j = "".join(self.segments)
            data = json.loads(j)
            if "descriptor" in data:
                return True
            return False


    def get_wallet_descriptor(self) -> str:
        if self.is_valid:
            j = "".join(self.segments)
            data = json.loads(j)
            return data['descriptor']
        return None


    def is_complete(self) -> bool:
        return self.complete and self.is_valid()


    def current_segment_num(self, segment) -> int:
        if re.search(r'^p(\d+)of(\d+) ', segment, re.IGNORECASE) != None:
            return int(re.search(r'^p(\d+)of(\d+) ', segment, re.IGNORECASE).group(1))
        else:
            return 1


    def total_segment_nums(self, segment) -> int:
        if re.search(r'^p(\d+)of(\d+) ', segment, re.IGNORECASE) != None:
            return int(re.search(r'^p(\d+)of(\d+) ', segment, re.IGNORECASE).group(2))
        else:
            return 1


    def parse_segment(self, segment) -> str:
        try:
            return re.search(r'^p(\d+)of(\d+) (.+$)', segment, re.IGNORECASE).group(3)
        except:
            return segment



class GenericWalletQrDecoder(BaseSingleFrameQrDecoder):
    def __init__(self):
        super().__init__()
        self.descriptor = None


    def add(self, segment, qr_type=QRType.WALLET__GENERIC):
        from embit.descriptor import Descriptor
        try:
            # Validate via embit
            Descriptor.from_string(segment)
            self.descriptor = segment
            self.complete = True
            return DecodeQRStatus.COMPLETE
        except Exception as e:
            logger.info(repr(e), exc_info=True)
        return DecodeQRStatus.INVALID
    

    def get_wallet_descriptor(self):
        return self.descriptor



class MultiSigConfigFileQRDecoder(GenericWalletQrDecoder):    
    def add(self, segment, qr_type=QRType.WALLET__CONFIGFILE):
        descriptor = DecodeQR.multisig_setup_file_to_descriptor(segment)
        return super().add(descriptor,qr_type=QRType.WALLET__CONFIGFILE)



class PassphraseQrDecoder(BaseSingleFrameQrDecoder):
    def __init__(self):
        super().__init__()
        self.passphrase = None


    def add(self, segment, qr_type=QRType.PASSPHRASE):
        if qr_type == QRType.PASSPHRASE:
            try:
                self.passphrase = segment
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception as e:
                logger.exception(repr(e))

        return DecodeQRStatus.INVALID


    def get_passphrase(self):
        return self.passphrase



class EncryptionKeyQrDecoder(BaseSingleFrameQrDecoder):
    """
        Decodes single frame representing an encyption key.
    """
    def __init__(self):
        super().__init__()
        self.encryption_key = None


    def add(self, segment, qr_type=QRType.ENCRYPTION_KEY):
        if qr_type == QRType.ENCRYPTION_KEY:
            try:
                self.encryption_key = segment
                from seedsigner.controller import Controller
                encryptedqr = Controller.get_instance().storage2.encryptedqr
                if encryptedqr:
                    encryptedqr.set_encryption_key(self.encryption_key)
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception as e:
                logger.exception(repr(e))

        return DecodeQRStatus.INVALID


    def get_encryption_key(self):
        return self.encryption_key


class WifQrDecoder(BaseSingleFrameQrDecoder):
    """Decodes single frame representing a WIF-encoded private key."""

    def __init__(self):
        super().__init__()
        self.wif = None

    def add(self, segment, qr_type=QRType.WIF):
        if qr_type == QRType.WIF:
            try:
                ec.PrivateKey.from_wif(segment)
                self.wif = segment
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception as e:
                logger.exception(repr(e))
        return DecodeQRStatus.INVALID

    def get_wif(self):
        return self.wif


class Bip38QrDecoder(BaseSingleFrameQrDecoder):
    """Decodes single frame representing a BIP38-encrypted private key."""

    def __init__(self):
        super().__init__()
        self.bip38 = None

    def add(self, segment, qr_type=QRType.BIP38):
        if qr_type == QRType.BIP38:
            try:
                from seedsigner.models.bip38 import BIP38Key
                BIP38Key(segment)
                self.bip38 = segment
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception as e:
                logger.exception(repr(e))
        return DecodeQRStatus.INVALID

    def get_bip38(self):
        return self.bip38



class EncryptedQrDecoder(BaseSingleFrameQrDecoder):
    """
        Decodes single frame representing an encypted seed.
    """
    def __init__(self):
        super().__init__()
        self.public_data = None
        self.seed_phrase = []
        self.xprv = None


    def add(self, segment, qr_type=QRType.SEED__ENCRYPTEDQR, encryption_key=None):
        if qr_type == QRType.SEED__ENCRYPTEDQR:
            try:
                from seedsigner.controller import Controller
                controller = Controller.get_instance()
                encryptedqr = controller.storage2.encryptedqr
                if encryptedqr:
                    encrypted_qr = encryptedqr.encrypted_qr
                    self.public_data = encryptedqr.public_data
                else:
                    from seedsigner.models.encryption import EncryptedQRCode
                    from seedsigner.helpers.base43 import base43_decode
                    encrypted_qr = EncryptedQRCode()
                    self.public_data = None
                    try:  # Try to decode base43 data
                        if isinstance(segment, bytes):
                            segment = segment.decode('utf-8')
                        data_bytes = base43_decode(segment)
                        self.public_data = encrypted_qr.public_data(data_bytes)
                    except:
                        pass
                    if not self.public_data:  # Failed to decode and parse base43
                        self.public_data = encrypted_qr.public_data(segment)
                    if not self.public_data:
                        raise Exception("Encrypted QR code is invalid.")
                    from seedsigner.models.encryptedqr import EncryptedQR
                    encryptedqr = EncryptedQR(encrypted_qr=encrypted_qr, public_data=self.public_data)
                    controller.storage2.set_encryptedqr(encryptedqr)

                if encryption_key:
                    word_bytes = encrypted_qr.decrypt(encryption_key)
                    if not word_bytes:
                        return DecodeQRStatus.WRONG_KEY
                    try:
                        self.seed_phrase = bip39.mnemonic_from_bytes(word_bytes).split()
                        self.xprv = None
                    except Exception:
                        candidate = word_bytes.decode("utf-8", errors="ignore").strip()
                        hdkey = bip32.HDKey.from_string(candidate)
                        if not hdkey.is_private:
                            return DecodeQRStatus.INVALID
                        self.seed_phrase = []
                        self.xprv = candidate
                else:
                    self.seed_phrase = []
                    self.xprv = None

                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE

            except Exception as e:
                logger.exception(repr(e))

        return DecodeQRStatus.INVALID


    def get_public_data(self):
        return self.public_data


    def get_seed_phrase(self):
        return self.seed_phrase[:]

    def get_xprv(self):
        return self.xprv



class TextQrDecoder(BaseSingleFrameQrDecoder):
    def __init__(self):
        super().__init__()
        self.text = None


    def add(self, segment, qr_type=QRType.TEXT):
        if qr_type == QRType.TEXT:
            try:
                self.text = segment
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception as e:
                logger.exception(repr(e))

        return DecodeQRStatus.INVALID


    def get_text(self):
        return self.text


class TimeQrDecoder(BaseSingleFrameQrDecoder):
    def __init__(self):
        super().__init__()
        self.time_str = None

    def add(self, segment, qr_type=QRType.SET_TIME):
        if qr_type == QRType.SET_TIME:
            try:
                self.time_str = segment
                self.complete = True
                self.collected_segments = 1
                return DecodeQRStatus.COMPLETE
            except Exception as e:
                logger.exception(repr(e))
        return DecodeQRStatus.INVALID

    def get_time(self):
        if self.time_str is None:
            return None
        # strip prefix 'oT'
        data = self.time_str[2:]
        if data == "0":
            return None
        if "." in data:
            data = data.split(".")[0]
        try:
            yy = int(data[0:2]) + 2000
            mm = int(data[2:4])
            dd = int(data[4:6])
            hh = int(data[6:8])
            mi = int(data[8:10])
            ss = int(data[10:12])
            return datetime(yy, mm, dd, hh, mi, ss)
        except Exception:
            return None
