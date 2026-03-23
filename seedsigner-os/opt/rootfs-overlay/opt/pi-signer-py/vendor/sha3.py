from __future__ import annotations

from typing import Union

_ROTATIONS = [
    0,
    1,
    62,
    28,
    27,
    36,
    44,
    6,
    55,
    20,
    3,
    10,
    43,
    25,
    39,
    41,
    45,
    15,
    21,
    8,
    18,
    2,
    61,
    56,
    14,
]
_PERMUTATION = [
    1,
    6,
    9,
    22,
    14,
    20,
    2,
    12,
    13,
    19,
    23,
    15,
    4,
    24,
    21,
    8,
    16,
    5,
    3,
    18,
    17,
    11,
    7,
    10,
]
_ROUND_CONSTANTS = [
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
]


def _rol64(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (64 - shift))) & ((1 << 64) - 1)


def _keccak_f1600(state: list[int]) -> None:
    for round_constant in _ROUND_CONSTANTS:
        column_parity = [0] * 5
        for index in range(25):
            column_parity[index % 5] ^= state[index]

        delta = [0] * 5
        for index in range(5):
            delta[index] = column_parity[(index + 4) % 5] ^ _rol64(
                column_parity[(index + 1) % 5], 1
            )
        for index in range(25):
            state[index] ^= delta[index % 5]

        for index, rotation in enumerate(_ROTATIONS):
            state[index] = _rol64(state[index], rotation)

        temp = state[_PERMUTATION[0]]
        for index in range(len(_PERMUTATION) - 1):
            state[_PERMUTATION[index]] = state[_PERMUTATION[index + 1]]
        state[_PERMUTATION[-1]] = temp

        for row in range(0, 25, 5):
            snapshot = [
                state[row],
                state[row + 1],
                state[row + 2],
                state[row + 3],
                state[row + 4],
                state[row],
                state[row + 1],
            ]
            for column in range(5):
                state[row + column] = snapshot[column] ^ (
                    (~snapshot[column + 1]) & snapshot[column + 2]
                )

        state[0] ^= round_constant


class _Keccak256:
    _rate_bytes = 136

    def __init__(self, data: Union[bytes, bytearray] = b"") -> None:
        self._buffer = bytearray(data)

    def update(self, data: Union[bytes, bytearray]) -> None:
        self._buffer.extend(data)

    def copy(self) -> "_Keccak256":
        return _Keccak256(bytes(self._buffer))

    def digest(self) -> bytes:
        state = [0] * 25
        data = bytes(self._buffer)
        offset = 0
        full_blocks = len(data) // self._rate_bytes

        for _ in range(full_blocks):
            block = data[offset : offset + self._rate_bytes]
            for lane_index in range(self._rate_bytes // 8):
                lane = int.from_bytes(
                    block[lane_index * 8 : lane_index * 8 + 8], "little"
                )
                state[lane_index] ^= lane
            offset += self._rate_bytes
            _keccak_f1600(state)

        final_block = bytearray(data[offset:])
        final_block.append(0x01)
        while len(final_block) < self._rate_bytes:
            final_block.append(0)
        final_block[-1] |= 0x80

        for lane_index in range(self._rate_bytes // 8):
            lane = int.from_bytes(
                final_block[lane_index * 8 : lane_index * 8 + 8], "little"
            )
            state[lane_index] ^= lane
        _keccak_f1600(state)

        output = bytearray()
        while len(output) < 32:
            for lane in state[: self._rate_bytes // 8]:
                output.extend(lane.to_bytes(8, "little"))
            if len(output) >= 32:
                break
            _keccak_f1600(state)
        return bytes(output[:32])


def keccak_256(data: Union[bytes, bytearray] = b"") -> _Keccak256:
    return _Keccak256(data)
