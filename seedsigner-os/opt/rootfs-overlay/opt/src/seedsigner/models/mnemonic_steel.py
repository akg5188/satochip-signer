from __future__ import annotations

import unicodedata
from pathlib import Path

from embit import bip39


DEFAULT_SHIFT_VALUES = [8, 7, 6, 7, 6, 7, 7, 3, 5, 2, 4, 2]
DEFAULT_SHIFT_OPERATOR = "+"
WEIGHTS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
_SOLVE_WEIGHTS_DESC = list(reversed(WEIGHTS))
WEIGHT_SET = set(WEIGHTS)
def _load_bip39_english_wordlist() -> list[str]:
    candidates = [
        Path("/usr/lib/python3.12/site-packages/mnemonic/wordlist/english.txt"),
        Path(__file__).resolve().parents[4] / "usr/lib/python3.12/site-packages/mnemonic/wordlist/english.txt",
        Path(__file__).resolve().parents[4] / "output/target/usr/lib/python3.12/site-packages/mnemonic/wordlist/english.txt",
    ]

    for path in candidates:
        try:
            if not path.is_file():
                continue
            words = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(words) == 2048 and words[734] == "forward" and words[1225] == "odor" and words[1282] == "park":
                return words
        except Exception:
            continue

    words = list(bip39.WORDLIST)
    if len(words) == 2048 and words[734] == "forward" and words[1225] == "odor" and words[1282] == "park":
        return words
    raise RuntimeError("BIP39 英文词表自检失败。")


WORDLIST = _load_bip39_english_wordlist()
WORD_TO_INDEX = {word: index for index, word in enumerate(WORDLIST)}
OPERATOR_LABELS = {
    "+": "加法(+)",
    "-": "减法(-)",
    "*": "乘法(*)",
    "/": "除法(/)",
}


def _is_valid_bip39_wordlist(words: list[str]) -> bool:
    return (
        len(words) == 2048
        and words[734] == "forward"
        and words[1225] == "odor"
        and words[1282] == "park"
    )


def _iter_runtime_wordlists():
    seen_signatures = set()

    def yield_if_valid(words):
        if not words or not _is_valid_bip39_wordlist(words):
            return
        signature = (words[0], words[734], words[1225], words[1282], words[-1])
        if signature in seen_signatures:
            return
        seen_signatures.add(signature)
        yield words

    for words in yield_if_valid(WORDLIST):
        yield words

    candidates = [
        Path("/usr/lib/python3.12/site-packages/mnemonic/wordlist/english.txt"),
        Path(__file__).resolve().parents[4] / "usr/lib/python3.12/site-packages/mnemonic/wordlist/english.txt",
        Path(__file__).resolve().parents[4] / "output/target/usr/lib/python3.12/site-packages/mnemonic/wordlist/english.txt",
    ]

    for path in candidates:
        try:
            if not path.is_file():
                continue
            words = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            for valid_words in yield_if_valid(words):
                yield valid_words
        except Exception:
            continue

    for words in yield_if_valid(list(bip39.WORDLIST)):
        yield words


def lookup_word_index(word: str) -> int:
    normalized = _normalize_word(word)
    if not normalized:
        raise ValueError("请输入英文单词。")

    for words in _iter_runtime_wordlists():
        try:
            return words.index(normalized)
        except ValueError:
            continue

    raise ValueError(f"不是官方 BIP39 英文词：{normalized}")


def get_word_at_index(index: int) -> str:
    normalized_index = int(index)
    if normalized_index < 0 or normalized_index >= len(WORDLIST):
        raise ValueError("编号必须在 0 到 2047 之间。")

    for words in _iter_runtime_wordlists():
        if normalized_index < len(words):
            return words[normalized_index]

    raise ValueError("BIP39 英文词表自检失败。")


def _normalize_word(word: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(word or "")).lower()
    normalized = "".join(ch for ch in normalized if "a" <= ch <= "z")
    return normalized


def normalize_words(words: list[str]) -> list[str]:
    normalized_words = []
    for word in words:
        normalized = _normalize_word(word)
        if normalized:
            normalized_words.append(normalized)
    return normalized_words


def normalize_operator(operator: str | None) -> str:
    normalized = (operator or DEFAULT_SHIFT_OPERATOR).strip()
    if normalized not in OPERATOR_LABELS:
        raise ValueError("不支持的运算方式。")
    return normalized


def parse_shift_values(raw: str, expected_len: int, default_values: list[int] | None = None) -> list[int]:
    default_values = list(default_values or DEFAULT_SHIFT_VALUES[:expected_len])
    normalized = (raw or "").replace("，", " ").replace(",", " ").strip()
    if not normalized:
        return default_values

    tokens = [token for token in normalized.split() if token]
    if len(tokens) == 1:
        try:
            value = int(tokens[0])
        except ValueError as exc:
            raise ValueError("移动数字必须是整数。") from exc
        if value < 0:
            raise ValueError("移动数字必须是非负整数。")
        return [value] * expected_len

    if len(tokens) != expected_len:
        raise ValueError(f"需要输入 {expected_len} 个移动数字，当前输入了 {len(tokens)} 个。")

    try:
        values = [int(token) for token in tokens]
    except ValueError as exc:
        raise ValueError("移动数字必须全部是整数。") from exc
    if any(value < 0 for value in values):
        raise ValueError("移动数字必须全部是非负整数。")
    return values


def format_shift_values(shift_values: list[int]) -> str:
    return " ".join(str(value) for value in shift_values)


def _normalize_positive_operand(value: int, label: str) -> int:
    normalized = int(value)
    if normalized <= 0:
        raise ValueError(f"{label}的数字必须大于 0。")
    return normalized


def _normalize_divisor(value: int) -> int:
    return _normalize_positive_operand(value, "除法")


def _normalize_multiplier(value: int) -> int:
    return _normalize_positive_operand(value, "乘法")


def _transform_index(word_index: int, operator: str, operand: int, encrypt: bool) -> int:
    size = len(WORDLIST)
    operator = normalize_operator(operator)

    if operator == "+":
        return (word_index + operand) % size if encrypt else (word_index - operand) % size
    if operator == "-":
        return (word_index - operand) % size if encrypt else (word_index + operand) % size

    if operator == "/":
        divisor = _normalize_divisor(operand)
        if encrypt:
            return word_index // divisor
        return min(word_index * divisor, size - 1)

    if operator == "*":
        factor = _normalize_multiplier(operand)
        if encrypt:
            return min(word_index * factor, size - 1)
        return word_index // factor

    raise ValueError("不支持的运算方式。")


def shift_mnemonic(
    words: list[str],
    shift_values: list[int | None],
    encrypt: bool = True,
    operator: str = DEFAULT_SHIFT_OPERATOR,
    operators: list[str | None] | None = None,
) -> list[str]:
    normalized_words = normalize_words(words)
    if len(normalized_words) != len(shift_values):
        raise ValueError("助记词数量和移动数字数量不一致。")

    if operators is None:
        normalized_operators = [normalize_operator(operator)] * len(shift_values)
    else:
        if len(operators) != len(shift_values):
            raise ValueError("助记词数量、运算方式数量和移动数字数量不一致。")
        normalized_operators = [
            None if value in (None, "") else normalize_operator(value)
            for value in operators
        ]

    result = []
    for index, word in enumerate(normalized_words):
        operator_value = normalized_operators[index]
        operand_value = shift_values[index]
        if operator_value in (None, "") or operand_value in (None, ""):
            result.append(word)
            continue
        try:
            word_index = lookup_word_index(word)
        except ValueError:
            raise ValueError(f"第 {index + 1} 个单词不在 BIP39 英文词库中：{word}")
        transformed_index = _transform_index(
            word_index,
            operator=operator_value,
            operand=int(operand_value),
            encrypt=encrypt,
        )
        result.append(get_word_at_index(transformed_index))
    return result


def solve_weights(index: int) -> list[int]:
    if index < 0 or index >= len(WORDLIST):
        raise ValueError("索引超出范围。")

    result = []
    remaining = index
    for weight in _SOLVE_WEIGHTS_DESC:
        if remaining >= weight:
            result.append(weight)
            remaining -= weight
    return sorted(result)


def words_to_indices(words: list[str]) -> list[int]:
    normalized_words = normalize_words(words)
    indices = []
    for index, word in enumerate(normalized_words):
        try:
            indices.append(lookup_word_index(word))
        except ValueError:
            raise ValueError(f"第 {index + 1} 个单词不在 BIP39 英文词库中：{word}")
    return indices


def indices_to_plate_groups(indices: list[int]) -> list[str]:
    return [" ".join(str(weight) for weight in solve_weights(index)) or "0" for index in indices]


def words_to_plate_groups(words: list[str]) -> list[str]:
    return indices_to_plate_groups(words_to_indices(words))


def parse_restore_indices(raw: str, expected_len: int = 12) -> list[int]:
    normalized = (raw or "").replace("，", ",").replace("；", ",").replace("\n", ",").strip()
    if not normalized:
        raise ValueError("请输入钢板数字。")

    if "," in normalized:
        groups = [group.strip() for group in normalized.split(",")]
        if len(groups) != expected_len:
            raise ValueError(f"需要输入 {expected_len} 组数字，当前输入了 {len(groups)} 组。")

        indices = []
        errors = []
        for position, group in enumerate(groups, 1):
            if not group:
                errors.append(f"第{position:02d}组为空")
                continue

            tokens = group.split()
            if any(not token.isdigit() for token in tokens):
                bad = next(token for token in tokens if not token.isdigit())
                errors.append(f"第{position:02d}组含非法内容：{bad}")
                continue

            numbers = [int(token) for token in tokens]
            if len(numbers) == 1 and 0 <= numbers[0] < len(WORDLIST):
                indices.append(numbers[0])
                continue

            invalid_weights = [number for number in numbers if number not in WEIGHT_SET]
            if invalid_weights:
                errors.append(f"第{position:02d}组存在非法权重：{'/'.join(map(str, invalid_weights))}")
                continue

            if len(set(numbers)) != len(numbers):
                errors.append(f"第{position:02d}组有重复权重")
                continue

            total = sum(numbers)
            if total >= len(WORDLIST):
                errors.append(f"第{position:02d}组权重和超出范围：{total}")
                continue

            indices.append(total)

        if errors:
            raise ValueError("；".join(errors))
        return indices

    tokens = normalized.split()
    if len(tokens) != expected_len:
        raise ValueError(f"请输入 {expected_len} 个索引数字，或者 {expected_len} 组权重数字。")

    indices = []
    errors = []
    for position, token in enumerate(tokens, 1):
        if not token.isdigit():
            errors.append(f"第{position:02d}个不是整数：{token}")
            continue

        index = int(token)
        if index < 0 or index >= len(WORDLIST):
            errors.append(f"第{position:02d}个超出范围：{index}")
            continue
        indices.append(index)

    if errors:
        raise ValueError("；".join(errors))
    return indices


def indices_to_words(indices: list[int]) -> list[str]:
    words = []
    for position, index in enumerate(indices, 1):
        try:
            words.append(get_word_at_index(index))
        except ValueError:
            raise ValueError(f"第{position:02d}个索引超出范围：{index}")
    return words
