import base64
import zlib
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class TpRelayFragment:
    index: int
    total: int
    chunk: str
    crc32: str


class RelayParseError(ValueError):
    pass


class RelayAssembler:
    def __init__(self) -> None:
        self.expected_total: Optional[int] = None
        self.expected_crc: Optional[str] = None
        self.raw_fragments: Dict[int, str] = {}

    def reset(self) -> None:
        self.expected_total = None
        self.expected_crc = None
        self.raw_fragments.clear()

    def accept(self, fragment: TpRelayFragment) -> Tuple[str, Optional[str]]:
        if fragment.total <= 0:
            return "error", "中转分片总数不合法"
        if fragment.index < 1 or fragment.index > fragment.total:
            return "error", f"中转分片索引不合法 (index={fragment.index} total={fragment.total})"

        if self.expected_total is None:
            self.expected_total = fragment.total
            self.expected_crc = fragment.crc32
        elif self.expected_total != fragment.total or self.expected_crc != fragment.crc32:
            self.reset()
            return "error", "中转分片属于不同二维码序列，已重置"

        self.raw_fragments[fragment.index] = fragment.chunk
        if len(self.raw_fragments) < fragment.total:
            return "progress", f"已接收中转分片 {len(self.raw_fragments)}/{fragment.total}"

        encoded = "".join(self.raw_fragments[i] for i in range(1, fragment.total + 1))
        crc_value = str(zlib.crc32(encoded.encode("utf-8")) & 0xFFFFFFFF)
        if crc_value != self.expected_crc:
            self.reset()
            return "error", "中转分片 CRC 校验失败"

        try:
            payload = _inflate_utf8(encoded)
        except Exception as error:
            self.reset()
            return "error", f"中转分片解压失败: {error}"

        self.reset()
        return "complete", payload


def parse_tp_relay_fragment(raw: str) -> TpRelayFragment:
    normalized = raw.strip()
    if not normalized.lower().startswith("tpr1:"):
        raise RelayParseError("不是 tpr1 中转分片")

    body = normalized[5:]
    first_dot = body.find(".")
    second_dot = body.find(".", first_dot + 1)
    if first_dot <= 0 or second_dot <= first_dot + 1:
        raise RelayParseError("中转分片格式无效")

    index_total = body[:first_dot]
    crc = body[first_dot + 1 : second_dot].strip()
    chunk = body[second_dot + 1 :].strip()
    if not crc or not chunk:
        raise RelayParseError("中转分片缺少 CRC 或数据")

    slash = index_total.find("/")
    if slash <= 0 or slash >= len(index_total) - 1:
        raise RelayParseError("中转分片缺少 index/total")

    try:
        index = int(index_total[:slash])
        total = int(index_total[slash + 1 :])
    except Exception as error:
        raise RelayParseError(f"中转分片 index/total 无效: {error}")

    return TpRelayFragment(index=index, total=total, chunk=chunk, crc32=crc)


def _inflate_utf8(encoded: str) -> str:
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    compressed = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
    return zlib.decompress(compressed).decode("utf-8")
