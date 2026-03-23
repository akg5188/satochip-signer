import json
import urllib.parse
import zlib
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class TpMultiFragment:
    index: int
    total: int
    chunk: str
    crc32: str


class FragmentParseError(ValueError):
    pass


class MultiFragmentAssembler:
    def __init__(self) -> None:
        self.expected_total: Optional[int] = None
        self.expected_crc: Optional[str] = None
        self.raw_fragments: Dict[int, str] = {}

    def reset(self) -> None:
        self.expected_total = None
        self.expected_crc = None
        self.raw_fragments.clear()

    def accept(self, fragment: TpMultiFragment) -> Tuple[str, Optional[str]]:
        total = fragment.total
        index = fragment.index
        if total <= 0:
            return "error", "分片总数不合法"

        valid_one_based = 1 <= index <= total
        valid_zero_based = 0 <= index < total
        if not valid_one_based and not valid_zero_based:
            return "error", f"分片索引不合法 (index={index} total={total})"

        if self.expected_total is None:
            self.expected_total = total
            self.expected_crc = fragment.crc32
        elif self.expected_total != total or self.expected_crc != fragment.crc32:
            self.reset()
            return "error", "分片属于不同二维码序列，已重置"

        self.raw_fragments[index] = fragment.chunk
        expected = self.expected_total or total
        if len(self.raw_fragments) < expected:
            return "progress", f"已接收分片 {len(self.raw_fragments)}/{expected}"

        payload = self._assemble_payload(expected)
        if payload is None:
            self.reset()
            return "error", "分片索引基准不一致或有缺片"

        crc_value = str(zlib.crc32(payload.encode("utf-8")) & 0xFFFFFFFF)
        if crc_value != self.expected_crc:
            self.reset()
            return "error", "分片 CRC 校验失败"

        self.reset()
        return "complete", payload

    def _assemble_payload(self, total: int) -> Optional[str]:
        if all(i in self.raw_fragments for i in range(1, total + 1)):
            return "".join(self.raw_fragments[i] for i in range(1, total + 1))
        if all(i in self.raw_fragments for i in range(0, total)):
            return "".join(self.raw_fragments[i] for i in range(0, total))
        return None


def parse_tp_multi_fragment(raw: str) -> TpMultiFragment:
    normalized = raw.strip()
    if not normalized.lower().startswith("tp:multifragment-"):
        raise FragmentParseError("不是 tp:multiFragment 分片")

    dash = normalized.find("-")
    if dash <= 0:
        raise FragmentParseError("无效分片格式")

    query_raw = normalized[dash + 1 :]
    if query_raw.startswith("?"):
        query_raw = query_raw[1:]

    params = _parse_query(query_raw)
    data_raw = params.get("data")
    if not data_raw:
        raise FragmentParseError("分片缺少 data")

    try:
        data = json.loads(data_raw)
    except Exception as error:
        raise FragmentParseError(f"分片 data JSON 无效: {error}")

    content = str(data.get("content") or "")
    if not content:
        raise FragmentParseError("分片缺少 content")

    index, total = _parse_position(data)

    split = content.rfind("_")
    if split <= 0 or split >= len(content) - 1:
        raise FragmentParseError("分片 content 格式无效")

    chunk = content[:split]
    crc = content[split + 1 :]

    return TpMultiFragment(index=index, total=total, chunk=chunk, crc32=crc)


def _parse_position(data: Dict[str, object]) -> Tuple[int, int]:
    index_raw = str(data.get("index") or "").strip()
    total_raw = (
        str(data.get("total") or "").strip()
        or str(data.get("count") or "").strip()
        or str(data.get("size") or "").strip()
    )

    if index_raw:
        parsed = _parse_index_total(index_raw)
        if parsed is not None:
            return parsed
        if total_raw:
            return int(index_raw), int(total_raw)

    raise FragmentParseError("分片缺少 index/total 信息")


def _parse_index_total(value: str) -> Optional[Tuple[int, int]]:
    if "/" in value:
        left, right = value.split("/", 1)
        return int(left.strip()), int(right.strip())
    if "-" in value:
        left, right = value.split("-", 1)
        return int(left.strip()), int(right.strip())
    return None


def _parse_query(query_raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    marker = query_raw.find("data=")
    if marker >= 0:
        before = query_raw[:marker]
        if before:
            for piece in before.split("&"):
                if not piece or "=" not in piece:
                    continue
                key, value = piece.split("=", 1)
                out[key] = _smart_decode(value)
        out["data"] = _smart_decode(query_raw[marker + 5 :])
        return out

    for piece in query_raw.split("&"):
        if not piece or "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        out[key] = _smart_decode(value)
    return out


def _smart_decode(value: str) -> str:
    try:
        return urllib.parse.unquote(value)
    except Exception:
        return value
