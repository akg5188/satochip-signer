"""
Minimal BBQr encoder/decoder support for PSBT exchange.

The format is documented by Coinkite and used by BlueWallet. The reference
TypeScript implementation is public domain; this Python port keeps only the
pieces needed by the firmware's PSBT QR flow.
"""

from __future__ import annotations

import base64
import zlib
from dataclasses import dataclass


HEADER_LEN = 8
VALID_ENCODINGS = {"H", "Z", "2"}
ENCODING_SPLIT_MOD = {
    "H": 2,
    "Z": 8,
    "2": 8,
}
ALNUM_QR_CAPACITY_L = (
    25,
    47,
    77,
    114,
    154,
    195,
    224,
    279,
    335,
    395,
    468,
    535,
    619,
    667,
    758,
    854,
    938,
    1046,
    1153,
    1249,
    1352,
    1460,
    1588,
    1704,
    1853,
    1990,
    2132,
    2223,
    2369,
    2520,
    2677,
    2840,
    3009,
    3183,
    3351,
    3537,
    3729,
    3927,
    4087,
    4296,
)


def _b32encode_no_padding(raw: bytes) -> str:
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _b32decode_no_padding(data: str) -> bytes:
    padding = "=" * ((8 - (len(data) % 8)) % 8)
    return base64.b32decode((data + padding).encode("ascii"), casefold=True)


def _deflate_raw(raw: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-10)
    return compressor.compress(raw) + compressor.flush()


def _inflate_raw(raw: bytes) -> bytes:
    return zlib.decompress(raw, wbits=-10)


def encode_bbqr_data(raw: bytes, encoding_preference: str = "auto") -> tuple[str, str]:
    """
    Returns ``(encoding, payload)`` for BBQr.

    We prefer raw-deflate if it helps; otherwise fall back to base32, matching
    the behavior BlueWallet expects.
    """
    preferred = encoding_preference.upper()
    if preferred not in {"AUTO", *VALID_ENCODINGS}:
        raise ValueError(f"Unsupported BBQr encoding preference: {encoding_preference}")
    if preferred == "H":
        return "H", raw.hex().upper()
    if preferred == "2":
        return "2", _b32encode_no_padding(raw)
    if preferred == "Z":
        return "Z", _b32encode_no_padding(_deflate_raw(raw))

    compressed = _deflate_raw(raw)
    if len(compressed) < len(raw):
        return "Z", _b32encode_no_padding(compressed)
    return "2", _b32encode_no_padding(raw)


def decode_bbqr_data(payload: str, encoding: str) -> bytes:
    if encoding == "H":
        return bytes.fromhex(payload)

    raw = _b32decode_no_padding(payload)
    if encoding == "Z":
        return _inflate_raw(raw)
    if encoding == "2":
        return raw
    raise ValueError(f"Unsupported BBQr encoding: {encoding}")


def _version_to_chars(version: int) -> int:
    if not 1 <= version <= len(ALNUM_QR_CAPACITY_L):
        raise ValueError(f"Unsupported BBQr QR version: {version}")
    return ALNUM_QR_CAPACITY_L[version - 1]


def _num_qr_needed(version: int, encoded_length: int, encoding: str) -> tuple[int, int]:
    split_mod = ENCODING_SPLIT_MOD[encoding]
    base_capacity = _version_to_chars(version) - HEADER_LEN
    adjusted_capacity = base_capacity - (base_capacity % split_mod)
    if adjusted_capacity <= 0:
        raise ValueError("BBQr QR capacity is too small")

    estimated_count = max(1, (encoded_length + adjusted_capacity - 1) // adjusted_capacity)
    if estimated_count == 1:
        return 1, encoded_length

    estimated_capacity = ((estimated_count - 1) * adjusted_capacity) + base_capacity
    if estimated_capacity >= encoded_length:
        return estimated_count, adjusted_capacity
    return estimated_count + 1, adjusted_capacity


def _find_best_split_version(
    encoded_length: int,
    encoding: str,
    min_version: int,
    max_version: int,
    min_split: int,
    max_split: int,
) -> tuple[int, int]:
    candidates: list[tuple[int, int, int]] = []
    for version in range(min_version, max_version + 1):
        count, per_each = _num_qr_needed(version, encoded_length, encoding)
        if min_split <= count <= max_split:
            candidates.append((count, version, per_each))

    if not candidates:
        raise ValueError("BBQr payload does not fit the requested QR settings")

    count, version, per_each = min(candidates, key=lambda item: (item[0], item[1]))
    return version, per_each


def parse_bbqr_header(part: str) -> tuple[str, str, int, int]:
    if len(part) < HEADER_LEN or not part.startswith("B$"):
        raise ValueError("Invalid BBQr header")

    encoding = part[2].upper()
    file_type = part[3].upper()
    if encoding not in VALID_ENCODINGS:
        raise ValueError(f"Unsupported BBQr encoding: {encoding}")

    total = int(part[4:6], 36)
    index = int(part[6:8], 36)
    if total < 1:
        raise ValueError("Invalid BBQr total part count")
    if index >= total:
        raise ValueError("Invalid BBQr part index")

    return encoding, file_type, total, index


@dataclass
class BBQrParts:
    file_type: str
    encoding: str
    parts: list[str]

    @classmethod
    def from_payload(
        cls,
        raw: bytes,
        file_type: str = "P",
        *,
        encoding_preference: str = "auto",
        min_version: int = 5,
        max_version: int = 40,
        min_split: int = 1,
        max_split: int = 1295,
    ) -> "BBQrParts":
        if len(file_type) != 1 or not file_type.isalpha() or not file_type.isupper():
            raise ValueError("BBQr file_type must be a single uppercase letter")

        encoding, payload = encode_bbqr_data(raw, encoding_preference=encoding_preference)
        if not 1 <= min_version <= max_version <= len(ALNUM_QR_CAPACITY_L):
            raise ValueError("BBQr QR version range is invalid")
        if not 1 <= min_split <= max_split <= 1295:
            raise ValueError("BBQr split range is invalid")

        _version, chunk_size = _find_best_split_version(
            encoded_length=len(payload),
            encoding=encoding,
            min_version=min_version,
            max_version=max_version,
            min_split=min_split,
            max_split=max_split,
        )

        parts = [payload[i:i + chunk_size] for i in range(0, len(payload), chunk_size)] or [""]
        total = len(parts)
        if total > 1295:
            raise ValueError("BBQr payload too large")

        rendered = [
            f"B${encoding}{file_type}{base36_two_digits(total)}{base36_two_digits(index)}{part}"
            for index, part in enumerate(parts)
        ]
        return cls(file_type=file_type, encoding=encoding, parts=rendered)


def base36_two_digits(value: int) -> str:
    if value < 0 or value > 1295:
        raise ValueError("BBQr value out of range")
    return base36(value).rjust(2, "0")


def base36(value: int) -> str:
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if value == 0:
        return "0"
    result = []
    while value:
        value, rem = divmod(value, 36)
        result.append(digits[rem])
    return "".join(reversed(result))
