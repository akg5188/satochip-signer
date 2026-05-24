#!/usr/bin/env python3
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageFilter, ImageOps

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    import zxingcpp  # type: ignore
except Exception as error:  # pragma: no cover
    zxingcpp = None
    _ZXINGCPP_IMPORT_ERROR = error
else:
    _ZXINGCPP_IMPORT_ERROR = None

try:
    import cv2  # type: ignore
except Exception as error:  # pragma: no cover
    cv2 = None
    _OPENCV_IMPORT_ERROR = error
else:
    _OPENCV_IMPORT_ERROR = None

try:
    from picamera2 import Picamera2
except Exception as error:  # pragma: no cover
    Picamera2 = None
    _PICAMERA_IMPORT_ERROR = error
else:
    _PICAMERA_IMPORT_ERROR = None

try:
    from picamera import PiCamera
    from picamera.array import PiRGBArray
except Exception as error:  # pragma: no cover
    PiCamera = None
    PiRGBArray = None
    _LEGACY_PICAMERA_IMPORT_ERROR = error
else:
    _LEGACY_PICAMERA_IMPORT_ERROR = None

try:
    from pyzbar.pyzbar import decode as zbar_decode
except Exception as error:  # pragma: no cover
    zbar_decode = None
    _PYZBAR_IMPORT_ERROR = error
else:
    _PYZBAR_IMPORT_ERROR = None

try:
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    _SEEDSIGNER_SRC = _REPO_ROOT / "seedsigner-os" / "opt" / "rootfs-overlay" / "opt" / "src"
    if _SEEDSIGNER_SRC.exists() and str(_SEEDSIGNER_SRC) not in sys.path:
        sys.path.insert(0, str(_SEEDSIGNER_SRC))
    from seedsigner.models.decode_qr import DecodeQR, QR_ROI_HINT_MAX_MISSES  # type: ignore
except Exception as error:  # pragma: no cover
    DecodeQR = None
    _SEEDSIGNER_DECODE_IMPORT_ERROR = error
else:
    _SEEDSIGNER_DECODE_IMPORT_ERROR = None


OPENCV_QR_MAX_CANDIDATES = 16
OPENCV_QR_MAX_SIZE = 960
OPENCV_QR_ROI_MAX_REGIONS = 3
OPENCV_QR_ROI_MIN_SIZE = 384
OPENCV_QR_ROI_MAX_SIZE = 960
OPENCV_QR_ROI_BORDER = 24
WECHAT_QR_MODEL_DIR = Path(__file__).resolve().parent / "wechat_qrcode"
WECHAT_QR_MODEL_FILES = (
    "detect.prototxt",
    "detect.caffemodel",
    "sr.prototxt",
    "sr.caffemodel",
)


class CameraScanner:
    _opencv_detector = None
    _wechat_detector = None

    def __init__(
        self,
        preview_size: Tuple[int, int] = (960, 720),
        rotate: int = 0,
    ) -> None:
        self.preview_size = preview_size
        self.fallback_preview_sizes: Tuple[Tuple[int, int], ...] = ((960, 720), (640, 480))
        self.rotate = rotate % 360
        self._camera: Optional[Picamera2] = None
        self._legacy_camera: Optional[PiCamera] = None
        self._legacy_raw = None
        self._scan_attempt_count = 0
        self._qr_roi_hint = None
        self._qr_roi_misses = 0

    def _preview_size_candidates(self) -> Tuple[Tuple[int, int], ...]:
        candidates: List[Tuple[int, int]] = [self.preview_size]
        for size in self.fallback_preview_sizes:
            if size not in candidates:
                candidates.append(size)
        return tuple(candidates)

    def start(self) -> None:
        if zbar_decode is None and zxingcpp is None and cv2 is None and DecodeQR is None:
            raise RuntimeError(
                "扫码解码器不可用: "
                f"pyzbar={_PYZBAR_IMPORT_ERROR}; zxingcpp={_ZXINGCPP_IMPORT_ERROR}; "
                f"opencv={_OPENCV_IMPORT_ERROR}; seedsigner={_SEEDSIGNER_DECODE_IMPORT_ERROR}"
            )

        if Picamera2 is not None:
            self._camera = Picamera2()
            cfg = None
            last_error = None
            for candidate_size in self._preview_size_candidates():
                try:
                    cfg = self._camera.create_preview_configuration(
                        main={"size": candidate_size, "format": "RGB888"}
                    )
                    self.preview_size = candidate_size
                    break
                except Exception as error:
                    last_error = error
            if cfg is None:
                raise RuntimeError(f"无法创建相机预览配置: {last_error}")
            self._camera.configure(cfg)
            self._camera.start()
            self._apply_picamera2_scan_controls()
            return

        if PiCamera is not None and PiRGBArray is not None:
            self._legacy_camera = PiCamera()
            last_error = None
            for candidate_size in self._preview_size_candidates():
                try:
                    self._legacy_camera.resolution = candidate_size
                    self.preview_size = candidate_size
                    last_error = None
                    break
                except Exception as error:
                    last_error = error
            if last_error is not None:
                raise RuntimeError(f"无法设置相机分辨率: {last_error}")
            self._legacy_camera.framerate = 24
            self._legacy_raw = PiRGBArray(self._legacy_camera, size=self.preview_size)
            time.sleep(0.25)
            self._apply_legacy_picamera_scan_controls()
            return

        raise RuntimeError(
            "picamera2/picamera 都不可用: "
            f"picamera2={_PICAMERA_IMPORT_ERROR}; picamera={_LEGACY_PICAMERA_IMPORT_ERROR}"
        )

    def _apply_picamera2_scan_controls(self) -> None:
        if self._camera is None:
            return
        time.sleep(0.30)
        controls = {"AeEnable": False, "AwbEnable": False}
        try:
            metadata = self._camera.capture_metadata()
        except Exception:
            metadata = {}
        if isinstance(metadata, dict):
            exposure_time = metadata.get("ExposureTime")
            analogue_gain = metadata.get("AnalogueGain")
            colour_gains = metadata.get("ColourGains")
            if exposure_time is not None:
                controls["ExposureTime"] = exposure_time
            if analogue_gain is not None:
                controls["AnalogueGain"] = analogue_gain
            if colour_gains is not None:
                controls["ColourGains"] = colour_gains
        for control_set in (
            controls,
            {"AeEnable": False},
            {"AwbEnable": False},
        ):
            try:
                self._camera.set_controls(control_set)
            except Exception:
                pass

    def _apply_legacy_picamera_scan_controls(self) -> None:
        if self._legacy_camera is None:
            return
        try:
            exposure_speed = self._legacy_camera.exposure_speed
        except Exception:
            exposure_speed = None
        try:
            awb_gains = self._legacy_camera.awb_gains
        except Exception:
            awb_gains = None
        try:
            if exposure_speed is not None and exposure_speed > 0:
                self._legacy_camera.shutter_speed = exposure_speed
            self._legacy_camera.exposure_mode = "off"
        except Exception:
            pass
        try:
            self._legacy_camera.awb_mode = "off"
        except Exception:
            pass
        if awb_gains is not None:
            try:
                self._legacy_camera.awb_gains = awb_gains
            except Exception:
                pass

    @staticmethod
    def _get_opencv_detector():
        if cv2 is None:
            return None
        try:
            if CameraScanner._opencv_detector is None:
                detector = cv2.QRCodeDetector()
                for setter_name, value in (("setEpsX", 0.2), ("setEpsY", 0.2)):
                    try:
                        setter = getattr(detector, setter_name, None)
                        if setter is not None:
                            setter(value)
                    except Exception:
                        pass
                CameraScanner._opencv_detector = detector
            return CameraScanner._opencv_detector
        except Exception:
            return None

    @staticmethod
    def _get_wechat_detector():
        if cv2 is None:
            return None

        if CameraScanner._wechat_detector is not None:
            return CameraScanner._wechat_detector

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

        CameraScanner._wechat_detector = detector
        return detector

    @staticmethod
    def _otsu_threshold(gray_image: Image.Image) -> Optional[int]:
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
    def _iter_qr_point_sets(points) -> Tuple:
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
    def _roi_hint_from_points(points, width: int, height: int):
        rect = CameraScanner._order_qr_points(points)
        if rect is None:
            return None
        try:
            left = max(0, float(np.min(rect[:, 0])))
            top = max(0, float(np.min(rect[:, 1])))
            right = min(float(width), float(np.max(rect[:, 0])))
            bottom = min(float(height), float(np.max(rect[:, 1])))
            if right - left < 32 or bottom - top < 32:
                return None
            margin = max(right - left, bottom - top) * 0.22
            return (
                max(0, int(left - margin)),
                max(0, int(top - margin)),
                min(width, int(right + margin)),
                min(height, int(bottom + margin)),
            )
        except Exception:
            return None

    @staticmethod
    def _add_roi_hint_candidates(candidates: List[Image.Image], gray: Image.Image, roi_hint) -> None:
        if not roi_hint:
            return
        try:
            left, top, right, bottom = [int(value) for value in roi_hint]
        except Exception:
            return
        left = max(0, min(left, gray.width - 1))
        top = max(0, min(top, gray.height - 1))
        right = max(left + 1, min(right, gray.width))
        bottom = max(top + 1, min(bottom, gray.height))
        if right - left < 48 or bottom - top < 48:
            return
        try:
            crop = gray.crop((left, top, right, bottom))
            target_size = max(OPENCV_QR_ROI_MIN_SIZE, min(OPENCV_QR_ROI_MAX_SIZE, max(crop.size) * 2))
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
            threshold = CameraScanner._otsu_threshold(roi)
            if threshold is not None:
                candidates.append(roi.point(lambda value: 255 if value > threshold else 0, mode="L"))
        except Exception:
            pass

    @staticmethod
    def _rectified_qr_region_candidates(gray: Image.Image, points) -> tuple[List[Image.Image], Optional[tuple[int, int, int, int]]]:
        if cv2 is None or np is None:
            return [], None

        rect = CameraScanner._order_qr_points(points)
        if rect is None:
            return [], None

        try:
            width_a = np.linalg.norm(rect[2] - rect[3])
            width_b = np.linalg.norm(rect[1] - rect[0])
            height_a = np.linalg.norm(rect[1] - rect[2])
            height_b = np.linalg.norm(rect[0] - rect[3])
            qr_edge = max(width_a, width_b, height_a, height_b)
            if qr_edge < 32:
                return []

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
            source = np.asarray(gray, dtype="uint8")
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
            return [], None

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
            threshold = CameraScanner._otsu_threshold(rectified)
            if threshold is not None:
                thresholded = rectified.point(lambda value: 255 if value > threshold else 0, mode="L")
                candidates.append(thresholded)
                candidates.append(ImageOps.expand(thresholded, border=OPENCV_QR_ROI_BORDER, fill=255))
        except Exception:
            pass
        return candidates, CameraScanner._roi_hint_from_points(rect, gray.width, gray.height)

    @staticmethod
    def _opencv_rectified_candidates(gray: Image.Image) -> tuple[List[Image.Image], Optional[tuple[int, int, int, int]]]:
        if cv2 is None or np is None:
            return [], None

        detector = CameraScanner._get_opencv_detector()
        if detector is None:
            return [], None

        try:
            image_array = np.asarray(gray, dtype="uint8")
        except Exception:
            return [], None

        point_sets = []
        try:
            detected, points = detector.detect(image_array)
            if detected:
                point_sets.extend(CameraScanner._iter_qr_point_sets(points))
        except Exception:
            pass
        if hasattr(detector, "detectMulti"):
            try:
                detected, points = detector.detectMulti(image_array)
                if detected:
                    point_sets.extend(CameraScanner._iter_qr_point_sets(points))
            except Exception:
                pass

        candidates: List[Image.Image] = []
        seen = set()
        regions_added = 0
        roi_hint = None
        for point_set in point_sets:
            rect = CameraScanner._order_qr_points(point_set)
            if rect is None:
                continue
            key = tuple(int(round(value / 4.0)) for value in rect.reshape((8,)))
            if key in seen:
                continue
            seen.add(key)
            region_candidates, rect_roi_hint = CameraScanner._rectified_qr_region_candidates(gray, rect)
            if not region_candidates:
                continue
            candidates.extend(region_candidates)
            if roi_hint is None:
                roi_hint = rect_roi_hint
            regions_added += 1
            if regions_added >= OPENCV_QR_ROI_MAX_REGIONS:
                break
        return candidates, roi_hint

    @staticmethod
    def _center_crop_candidates(
        img: Image.Image,
        roi_hint=None,
        dense_scan_mode: bool = False,
    ) -> tuple[List[Image.Image], Optional[tuple[int, int, int, int]]]:
        gray = img if img.mode == "L" else img.convert("L")
        min_dim = min(gray.size)
        candidates: List[Image.Image] = [img, gray]

        CameraScanner._add_roi_hint_candidates(candidates, gray, roi_hint)
        try:
            if roi_hint is None or not dense_scan_mode:
                candidates.append(ImageOps.autocontrast(gray, cutoff=2))
        except Exception:
            pass
        rectified_candidates, new_roi_hint = CameraScanner._opencv_rectified_candidates(gray)
        candidates.extend(rectified_candidates)

        if dense_scan_mode and roi_hint is not None:
            return candidates, new_roi_hint

        for ratio in (0.72, 0.58, 0.46, 0.36, 0.28, 0.22):
            crop_size = int(min_dim * ratio)
            if crop_size < 96 or crop_size >= min_dim - 8:
                continue
            left = (gray.width - crop_size) // 2
            top = (gray.height - crop_size) // 2
            crop = gray.crop((left, top, left + crop_size, top + crop_size))
            resized = crop.resize((min_dim, min_dim), Image.Resampling.NEAREST)
            candidates.append(resized)
            try:
                candidates.append(ImageOps.autocontrast(resized, cutoff=2))
            except Exception:
                pass
            try:
                candidates.append(resized.filter(ImageFilter.SHARPEN))
            except Exception:
                pass
            if ratio <= 0.36:
                try:
                    candidates.append(resized.filter(ImageFilter.MinFilter(3)))
                except Exception:
                    pass
                try:
                    thresholded = resized.point(lambda value: 255 if value > 160 else 0, mode="L")
                    candidates.append(thresholded)
                except Exception:
                    pass

        return candidates, new_roi_hint

    @staticmethod
    def _decode_with_zxingcpp(candidates: List[Image.Image]) -> List[str]:
        if zxingcpp is None:
            return []
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

        values: List[str] = []
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
                text = getattr(barcode, "text", "")
                if text and text not in values:
                    values.append(text)
                raw = getattr(barcode, "bytes", None)
                if raw:
                    try:
                        decoded = bytes(raw).decode("utf-8", errors="strict")
                    except Exception:
                        continue
                    if decoded not in values:
                        values.append(decoded)
            if values:
                break
        return values

    @staticmethod
    def _decode_with_wechat(candidates: List[Image.Image]) -> List[str]:
        if cv2 is None or np is None:
            return []

        detector = CameraScanner._get_wechat_detector()
        if detector is None:
            return []

        values: List[str] = []
        for candidate in candidates[:OPENCV_QR_MAX_CANDIDATES]:
            if max(candidate.size) > OPENCV_QR_MAX_SIZE:
                continue
            try:
                decoded = detector.detectAndDecode(np.asarray(candidate.convert("RGB"), dtype="uint8"))
            except Exception:
                continue

            texts = decoded[0] if isinstance(decoded, tuple) else decoded
            if isinstance(texts, str):
                texts = (texts,)
            try:
                iterator = iter(texts)
            except Exception:
                continue

            for text in iterator:
                if text and text not in values:
                    values.append(text)
            if values:
                break
        return values

    @staticmethod
    def _decode_with_pyzbar(candidates: List[Image.Image]) -> List[str]:
        if zbar_decode is None:
            return []
        values: List[str] = []
        for candidate in candidates:
            try:
                decoded_items = zbar_decode(candidate)
            except Exception:
                continue
            for item in decoded_items:
                try:
                    text = item.data.decode("utf-8", errors="strict")
                except Exception:
                    continue
                if text not in values:
                    values.append(text)
            if values:
                break
        return values

    @staticmethod
    def _decode_with_opencv(candidates: List[Image.Image]) -> List[str]:
        if cv2 is None or np is None:
            return []
        try:
            detector = CameraScanner._get_opencv_detector()
            if detector is None:
                return []
        except Exception:
            return []

        values: List[str] = []
        for candidate in candidates[:OPENCV_QR_MAX_CANDIDATES]:
            if max(candidate.size) > OPENCV_QR_MAX_SIZE:
                continue
            try:
                gray = candidate if candidate.mode == "L" else candidate.convert("L")
                image_array = np.asarray(gray, dtype="uint8")
                if hasattr(detector, "detectAndDecodeMulti"):
                    detected, decoded_info, _points, _straight = detector.detectAndDecodeMulti(image_array)
                    if detected:
                        for data in decoded_info:
                            if data and data not in values:
                                values.append(data)
                        if values:
                            break
                data, _points, _straight = detector.detectAndDecode(image_array)
            except Exception:
                continue
            if data and data not in values:
                values.append(data)
                break
        return values

    @classmethod
    def _decode_image(
        cls,
        img: Image.Image,
        roi_hint=None,
        include_wechat: bool = True,
        dense_scan_mode: bool = False,
    ) -> tuple[List[str], Optional[tuple[int, int, int, int]]]:
        candidates, new_roi_hint = cls._center_crop_candidates(
            img,
            roi_hint=roi_hint,
            dense_scan_mode=dense_scan_mode,
        )
        values: List[str] = []
        for decoder in (
            cls._decode_with_zxingcpp,
            cls._decode_with_pyzbar,
            cls._decode_with_wechat if include_wechat else None,
            cls._decode_with_opencv,
        ):
            if decoder is None:
                continue
            for value in decoder(candidates):
                if value not in values:
                    values.append(value)
            if values:
                break
        return values, new_roi_hint

    def _scan_hint_every_n(self) -> int:
        return 4 if self._scan_attempt_count <= 2 else 6

    def stop(self) -> None:
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception:
                pass
            try:
                self._camera.close()
            except Exception:
                pass
            self._camera = None
        if self._legacy_camera is not None:
            try:
                self._legacy_camera.close()
            except Exception:
                pass
            self._legacy_camera = None
            self._legacy_raw = None

    def capture(self) -> Tuple[Image.Image, List[str]]:
        self._scan_attempt_count += 1
        frame = None
        if self._camera is not None:
            frame = self._camera.capture_array("main")
        elif self._legacy_camera is not None and self._legacy_raw is not None:
            self._legacy_raw.truncate(0)
            self._legacy_camera.capture(self._legacy_raw, format="rgb", use_video_port=True)
            frame = self._legacy_raw.array
        else:
            raise RuntimeError("camera not started")

        if frame is None:
            raise RuntimeError("无法从相机采集画面")

        img = Image.fromarray(frame.astype("uint8"), mode="RGB")
        if self.rotate:
            if np is not None:
                frame = np.rot90(frame, k=self.rotate // 90)
                img = Image.fromarray(frame.astype("uint8"), mode="RGB")
            else:
                img = img.rotate(self.rotate, expand=True)
        qr_values: List[str] = []

        include_wechat = self._scan_attempt_count <= 2 or self._scan_attempt_count % self._scan_hint_every_n() == 0
        qr_values, roi_hint = self._decode_image(
            img,
            roi_hint=self._qr_roi_hint,
            include_wechat=include_wechat,
            dense_scan_mode=True,
        )
        if roi_hint is not None:
            self._qr_roi_hint = roi_hint

        if not qr_values and DecodeQR is not None:
            for aggressive in (False, True):
                try:
                    decoded, roi_hint = DecodeQR.extract_qr_data_with_hint(
                        img,
                        is_binary=True,
                        aggressive=aggressive,
                        include_fast_candidates=not aggressive and self._qr_roi_hint is None,
                        include_wechat=include_wechat,
                        roi_hint=self._qr_roi_hint,
                        dense_scan_mode=True,
                    )
                except Exception:
                    decoded = None
                    roi_hint = None
                if roi_hint is not None:
                    self._qr_roi_hint = roi_hint
                if decoded is None:
                    continue
                if isinstance(decoded, bytes):
                    try:
                        qr_values.append(decoded.decode("utf-8", errors="strict"))
                    except Exception:
                        pass
                else:
                    qr_values.append(str(decoded))
                if qr_values:
                    break

        if qr_values:
            self._qr_roi_misses = 0
        elif self._qr_roi_hint is not None:
            self._qr_roi_misses += 1
            if self._qr_roi_misses >= QR_ROI_HINT_MAX_MISSES:
                self._qr_roi_hint = None
                self._qr_roi_misses = 0

        return img, qr_values
