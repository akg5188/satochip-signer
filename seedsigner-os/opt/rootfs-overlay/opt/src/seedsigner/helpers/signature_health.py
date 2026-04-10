from __future__ import annotations

from dataclasses import dataclass, field

from embit.psbt import PSBT
from embit.transaction import Transaction
from embit.util import secp256k1


SECP256K1_N = int(
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141",
    16,
)


@dataclass
class ParsedEcdsaSignature:
    input_index: int
    source: str
    r: int
    s: int
    sighash_type: int | None = None


@dataclass
class SignatureHealthReport:
    source_label: str
    parsed_signatures: list[ParsedEcdsaSignature] = field(default_factory=list)
    duplicate_r_groups: list[list[int]] = field(default_factory=list)
    non_low_s_inputs: list[int] = field(default_factory=list)
    parse_error_inputs: list[int] = field(default_factory=list)
    unsupported_inputs: list[int] = field(default_factory=list)
    error: str | None = None

    @property
    def parsed_count(self) -> int:
        return len(self.parsed_signatures)


def _iter_script_pushes(script_bytes: bytes) -> list[bytes]:
    pushes: list[bytes] = []
    i = 0
    data = bytes(script_bytes or b"")
    while i < len(data):
        opcode = data[i]
        i += 1
        if opcode == 0:
            continue
        if opcode <= 75:
            push_len = opcode
        elif opcode == 76:
            if i >= len(data):
                break
            push_len = data[i]
            i += 1
        elif opcode == 77:
            if i + 1 >= len(data):
                break
            push_len = int.from_bytes(data[i:i + 2], "little")
            i += 2
        elif opcode == 78:
            if i + 3 >= len(data):
                break
            push_len = int.from_bytes(data[i:i + 4], "little")
            i += 4
        else:
            continue
        if i + push_len > len(data):
            break
        pushes.append(data[i:i + push_len])
        i += push_len
    return pushes


def _parse_ecdsa_signature(blob: bytes) -> tuple[int, int, int | None]:
    candidates: list[tuple[bytes, int | None]] = []
    if len(blob) > 1:
        candidates.append((blob[:-1], blob[-1]))
    candidates.append((blob, None))

    seen: set[bytes] = set()
    for der_sig, sighash_type in candidates:
        if not der_sig or der_sig in seen:
            continue
        seen.add(der_sig)
        sig_obj = secp256k1.ecdsa_signature_parse_der(der_sig)
        compact = secp256k1.ecdsa_signature_serialize_compact(sig_obj)
        r = int.from_bytes(compact[:32], "big")
        s = int.from_bytes(compact[32:], "big")
        return r, s, sighash_type
    raise ValueError("No valid DER-encoded ECDSA signature found")


def _finalize_report(report: SignatureHealthReport) -> SignatureHealthReport:
    duplicate_map: dict[int, list[ParsedEcdsaSignature]] = {}
    for signature in report.parsed_signatures:
        duplicate_map.setdefault(signature.r, []).append(signature)

    report.duplicate_r_groups = []
    for matches in duplicate_map.values():
        if len(matches) <= 1:
            continue
        group = sorted({sig.input_index for sig in matches})
        if group:
            report.duplicate_r_groups.append(group)

    report.non_low_s_inputs = sorted(
        {
            signature.input_index
            for signature in report.parsed_signatures
            if signature.s > (SECP256K1_N // 2)
        }
    )
    report.parse_error_inputs = sorted(set(report.parse_error_inputs))
    report.unsupported_inputs = sorted(set(report.unsupported_inputs))
    report.duplicate_r_groups.sort()
    return report


def analyze_tx_signature_health(tx_hex: str) -> SignatureHealthReport:
    report = SignatureHealthReport(source_label="rawtx")
    value = str(tx_hex or "").strip()
    if not value:
        report.error = "签名结果为空"
        return report
    try:
        tx = Transaction.from_string(value)
    except Exception as exc:
        report.error = f"无法解析交易: {exc}"
        return report

    for input_index, tx_input in enumerate(tx.vin):
        found_candidate = False

        for witness_item in list(getattr(tx_input.witness, "items", []) or []):
            if not witness_item:
                continue
            if witness_item[:1] == b"\x30":
                found_candidate = True
                try:
                    r, s, sighash_type = _parse_ecdsa_signature(bytes(witness_item))
                except Exception:
                    report.parse_error_inputs.append(input_index)
                else:
                    report.parsed_signatures.append(
                        ParsedEcdsaSignature(
                            input_index=input_index,
                            source="witness",
                            r=r,
                            s=s,
                            sighash_type=sighash_type,
                        )
                    )
            elif len(witness_item) in (64, 65):
                report.unsupported_inputs.append(input_index)

        for push in _iter_script_pushes(getattr(tx_input.script_sig, "data", b"")):
            if not push:
                continue
            if push[:1] == b"\x30":
                found_candidate = True
                try:
                    r, s, sighash_type = _parse_ecdsa_signature(push)
                except Exception:
                    report.parse_error_inputs.append(input_index)
                else:
                    report.parsed_signatures.append(
                        ParsedEcdsaSignature(
                            input_index=input_index,
                            source="scriptSig",
                            r=r,
                            s=s,
                            sighash_type=sighash_type,
                        )
                    )

        if not found_candidate and getattr(tx_input.witness, "items", None):
            if any(len(item) in (64, 65) for item in tx_input.witness.items):
                report.unsupported_inputs.append(input_index)

    return _finalize_report(report)


def analyze_psbt_signature_health(psbt_base64: str) -> SignatureHealthReport:
    report = SignatureHealthReport(source_label="psbt")
    value = str(psbt_base64 or "").strip()
    if not value:
        report.error = "签名结果为空"
        return report
    try:
        psbt = PSBT.from_base64(value)
    except Exception as exc:
        report.error = f"无法解析 PSBT: {exc}"
        return report

    for input_index, psbt_input in enumerate(psbt.inputs):
        partial_sigs = getattr(psbt_input, "partial_sigs", {}) or {}
        if not partial_sigs:
            continue
        for signature_blob in partial_sigs.values():
            try:
                r, s, sighash_type = _parse_ecdsa_signature(bytes(signature_blob))
            except Exception:
                report.parse_error_inputs.append(input_index)
            else:
                report.parsed_signatures.append(
                    ParsedEcdsaSignature(
                        input_index=input_index,
                        source="psbt",
                        r=r,
                        s=s,
                        sighash_type=sighash_type,
                    )
                )

    return _finalize_report(report)


def build_signature_health_lines(report: SignatureHealthReport) -> list[str]:
    if report.error:
        return [
            "本次签名: 无法检查",
            f"原因: {report.error}",
            "建议: 先做真伪检查",
        ]

    if report.parsed_count == 0:
        if report.unsupported_inputs:
            return [
                "本次签名: 暂未覆盖",
                "类型: 可能是 Taproot",
                "或 Schnorr 签名",
                "建议: 结合真伪检查",
            ]
        return [
            "本次签名: 暂未覆盖",
            "原因: 未解析到 ECDSA",
            "建议: 结合真伪检查",
        ]

    if report.duplicate_r_groups:
        return [
            "本次签名: 有风险",
            f"本笔签名数: {report.parsed_count}",
            f"随机数重复: 发现 {len(report.duplicate_r_groups)} 组",
            "建议: 先停用此卡",
        ]

    if report.parse_error_inputs or report.non_low_s_inputs:
        lines = [
            "本次签名: 需复查",
            f"本笔签名数: {report.parsed_count}",
            "随机数重复: 未发现",
        ]
        if report.non_low_s_inputs:
            lines.append("签名格式: 需复查")
        if report.parse_error_inputs:
            lines.append(
                "部分签名: 未读出"
            )
        lines.append("建议: 暂时只做测试")
        return lines

    return [
        "本次签名: 未见异常",
        f"本笔签名数: {report.parsed_count}",
        "随机数重复: 未发现",
        "签名格式: 正常",
    ]
