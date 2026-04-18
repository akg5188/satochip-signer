import hashlib
import unicodedata
from collections import Counter
import math
import re

from embit import bip39
from seedsigner.models.settings_definition import SettingsConstants
from seedsigner.models.seed import Seed

"""
    This is SeedSigner's internal mnemonic generation utility.
     
    It can also be run as an independently-executable CLI to facilitate external
    verification of SeedSigner's results for a given input entropy.

    see: docs/dice_verification.md (the "Command Line Tool" section).
"""

# Supported mnemonic word lengths
SUPPORTED_WORD_LENGTHS = [12, 15, 18, 21, 24]

# Dice roll counts required to generate sufficient entropy for each
# supported mnemonic length. Each dice roll provides ~2.585 bits of
# entropy which we round up to the next whole roll.
DICE_ROLLS_REQUIRED = {
    12: 50,
    15: 62,
    18: 75,
    21: 87,
    24: 99,
}

# Number of entropy bytes needed for each mnemonic length
ENTROPY_BYTES_REQUIRED = {
    12: 16,
    15: 20,
    18: 24,
    21: 28,
    24: 32,
    20: 16,  # SLIP39 compatibility
    33: 32,  # SLIP39 compatibility
}

# Reverse lookup from dice roll count to mnemonic length
ROLL_COUNT_TO_LENGTH = {v: k for k, v in DICE_ROLLS_REQUIRED.items()}

# Backwards-compatible constants
DICE__NUM_ROLLS__12WORD = DICE_ROLLS_REQUIRED[12]
DICE__NUM_ROLLS__24WORD = DICE_ROLLS_REQUIRED[24]

CARD_EVENT_BITS = {
    "ac": "00000",
    "2c": "00001",
    "3c": "00010",
    "4c": "00011",
    "5c": "00100",
    "6c": "00101",
    "7c": "00110",
    "8c": "00111",
    "9c": "01000",
    "tc": "01001",
    "jc": "01010",
    "qc": "01011",
    "kc": "01100",
    "ad": "01101",
    "2d": "01110",
    "3d": "01111",
    "4d": "10000",
    "5d": "10001",
    "6d": "10010",
    "7d": "10011",
    "8d": "10100",
    "9d": "10101",
    "td": "10110",
    "jd": "10111",
    "qd": "11000",
    "kd": "11001",
    "ah": "11010",
    "2h": "11011",
    "3h": "11100",
    "4h": "11101",
    "5h": "11110",
    "6h": "11111",
    "7h": "0000",
    "8h": "0001",
    "9h": "0010",
    "th": "0011",
    "jh": "0100",
    "qh": "0101",
    "kh": "0110",
    "as": "0111",
    "2s": "1000",
    "3s": "1001",
    "4s": "1010",
    "5s": "1011",
    "6s": "1100",
    "7s": "1101",
    "8s": "1110",
    "9s": "1111",
    "ts": "00",
    "js": "01",
    "qs": "10",
    "ks": "11",
}
CARD_MATCHER = re.compile(r"([A2-9TJQK][CDHS])", re.IGNORECASE)
HEX_MATCHER = re.compile(r"[0-9A-F]", re.IGNORECASE)
CARD_SUIT_SYMBOLS = {
    "C": "\u2663",
    "D": "\u2666",
    "H": "\u2665",
    "S": "\u2660",
}



def calculate_checksum(mnemonic: list | str, wordlist_language_code: str = SettingsConstants.WORDLIST_LANGUAGE__ENGLISH) -> list[str]:
    """
        Provide 12- or 24-word mnemonic, returns complete mnemonic w/checksum as a list.

        Mnemonic may be a list of words or a string of words separated by spaces or commas.

        If 11- or 23-words are provided, append word `0000` to end of list as temp final
        word.
    """
    if type(mnemonic) == str:
        import re
        # split on commas or spaces
        mnemonic = re.findall(r'[^,\s]+', mnemonic)

    if len(mnemonic) in [11, 14, 17, 20, 23]:
        # Keep a private string copy so secure wiping generated words cannot
        # mutate shared global wordlist string objects.
        temp_final_word = "".join(Seed.get_wordlist(wordlist_language_code)[0])
        mnemonic.append(temp_final_word)

    if len(mnemonic) not in SUPPORTED_WORD_LENGTHS:
        raise Exception("Pass in a 12, 15, 18, 21, or 24-word mnemonic")
    
    # Work on a copy of the input list
    mnemonic_copy = mnemonic.copy()

    # Convert the resulting mnemonic to bytes, but we `ignore_checksum` validation
    # because we assume it's incorrect since we either let the user select their own
    # final word OR we injected the 0000 word from the wordlist.
    mnemonic_bytes = bip39.mnemonic_to_bytes(unicodedata.normalize("NFKD", " ".join(mnemonic_copy)), ignore_checksum=True, wordlist=Seed.get_wordlist(wordlist_language_code))

    # This function will convert the bytes back into a mnemonic, but it will also
    # calculate the proper checksum bits while doing so. For a 12-word seed it will just
    # overwrite the last 4 bits from the above result with the checksum; for a 24-word
    # seed it'll overwrite the last 8 bits.
    return bip39.mnemonic_from_bytes(
        mnemonic_bytes,
        wordlist=Seed.get_wordlist(wordlist_language_code),
    ).split()



def generate_mnemonic_from_bytes(entropy_bytes, wordlist_language_code: str = SettingsConstants.WORDLIST_LANGUAGE__ENGLISH) -> list[str]:
    return bip39.mnemonic_from_bytes(entropy_bytes, wordlist=Seed.get_wordlist(wordlist_language_code)).split()


def normalize_hex_for_iancoleman(hex_data: str) -> str:
    return "".join(HEX_MATCHER.findall(str(hex_data))).upper()


def format_hex_for_iancoleman_hash(hex_data: str) -> str:
    """
    iancoleman.io/bip39 "Hex [0-9A-F]" mode does not treat the filtered hex
    text as raw BIP39 entropy unless "Use Raw Entropy" is selected.

    For the normal 12/15/18/21/24-word flow, it hashes the filtered hex text
    with SHA-256 and then truncates the hash to the requested entropy length.
    We normalize to lowercase here so the device matches the common website
    workflow even though the on-device keyboard shows A-F in uppercase.
    """
    return "".join(HEX_MATCHER.findall(str(hex_data))).lower()


def hex_entropy_bit_length(hex_data: str) -> int:
    return len(normalize_hex_for_iancoleman(hex_data)) * 4


def hex_entropy_has_even_digits(hex_data: str) -> bool:
    return len(normalize_hex_for_iancoleman(hex_data)) % 2 == 0


def hex_entropy_required_chars(word_length: int) -> int:
    return ENTROPY_BYTES_REQUIRED[word_length] * 2


def hex_entropy_matches_word_length(hex_data: str, word_length: int) -> bool:
    return len(normalize_hex_for_iancoleman(hex_data)) == hex_entropy_required_chars(word_length)


def generate_mnemonic_from_hex(
    hex_data: str,
    word_length: int,
    wordlist_language_code: str = SettingsConstants.WORDLIST_LANGUAGE__ENGLISH,
) -> list[str]:
    if word_length not in ENTROPY_BYTES_REQUIRED:
        raise Exception("Unsupported mnemonic length")

    clean_hex = normalize_hex_for_iancoleman(hex_data)
    required_chars = hex_entropy_required_chars(word_length)
    if len(clean_hex) != required_chars:
        raise Exception("Hex entropy length does not match requested mnemonic length")

    hash_input = format_hex_for_iancoleman_hash(hex_data)
    entropy_bytes = hashlib.sha256(hash_input.encode("utf-8")).digest()
    entropy_bytes = entropy_bytes[:ENTROPY_BYTES_REQUIRED[word_length]]
    return bip39.mnemonic_from_bytes(entropy_bytes, wordlist=Seed.get_wordlist(wordlist_language_code)).split()


def parse_card_entropy_events(card_data: str) -> list[str]:
    return [event.upper() for event in CARD_MATCHER.findall(str(card_data))]


def normalize_cards_for_iancoleman(card_data: str) -> str:
    return " ".join(parse_card_entropy_events(card_data))


def format_cards_for_iancoleman_hash(card_data: str) -> str:
    clean_cards = normalize_cards_for_iancoleman(card_data)
    for suit, symbol in CARD_SUIT_SYMBOLS.items():
        clean_cards = clean_cards.replace(suit, symbol)
    return clean_cards


def card_entropy_binary_str(card_data: str) -> str:
    return "".join(CARD_EVENT_BITS[event.lower()] for event in parse_card_entropy_events(card_data))


def card_entropy_bit_length(card_data: str) -> int:
    return len(card_entropy_binary_str(card_data))


def card_entropy_is_sufficient(card_data: str, word_length: int) -> bool:
    required_bits = ENTROPY_BYTES_REQUIRED[word_length] * 8
    return card_entropy_bit_length(card_data) >= required_bits


def generate_mnemonic_from_cards(
    card_data: str,
    word_length: int,
    wordlist_language_code: str = SettingsConstants.WORDLIST_LANGUAGE__ENGLISH,
) -> list[str]:
    if word_length not in ENTROPY_BYTES_REQUIRED:
        raise Exception("Unsupported mnemonic length")

    clean_cards = format_cards_for_iancoleman_hash(card_data)
    entropy_bytes = hashlib.sha256(clean_cards.encode("utf-8")).digest()
    entropy_bytes = entropy_bytes[:ENTROPY_BYTES_REQUIRED[word_length]]
    return bip39.mnemonic_from_bytes(entropy_bytes, wordlist=Seed.get_wordlist(wordlist_language_code)).split()



def normalize_dice_rolls_for_iancoleman(roll_data: str) -> str:
    """
        Normalize dice input to iancoleman.io/bip39 "Dice" mode semantics:
        * keep only digits 0-6
        * convert 6 -> 0 so the cleaned string becomes base-6 text
    """
    normalized = []
    for ch in str(roll_data):
        if ch in "012345":
            normalized.append(ch)
        elif ch == "6":
            normalized.append("0")
    return "".join(normalized)


def _hash_dice_rolls(roll_data: str) -> bytes:
    normalized_rolls = normalize_dice_rolls_for_iancoleman(roll_data)
    return hashlib.sha256(normalized_rolls.encode()).digest()


def generate_mnemonic_from_dice(roll_data: str, wordlist_language_code: str = SettingsConstants.WORDLIST_LANGUAGE__ENGLISH) -> list[str]:
    """
        Takes a string of dice rolls and returns a mnemonic of the appropriate length.

        Uses the iancoleman.io/bip39 "Dice" mode preprocessing:
        * dice rolls are normalized to base-6 text by converting 6 -> 0.
        * hashed via SHA256.
    """
    normalized_rolls = normalize_dice_rolls_for_iancoleman(roll_data)
    entropy_bytes = _hash_dice_rolls(normalized_rolls)

    word_length = ROLL_COUNT_TO_LENGTH.get(len(normalized_rolls), 24)

    entropy_bytes = entropy_bytes[:ENTROPY_BYTES_REQUIRED[word_length]]

    # Return as a list
    return bip39.mnemonic_from_bytes(entropy_bytes, wordlist=Seed.get_wordlist(wordlist_language_code)).split()


def generate_bytes_from_dice(roll_data: str, length_bytes: int | None = None) -> bytes:
    """Return entropy bytes from dice rolls without converting to mnemonic."""
    normalized_rolls = normalize_dice_rolls_for_iancoleman(roll_data)
    entropy_bytes = _hash_dice_rolls(normalized_rolls)
    if length_bytes is None:
        word_length = ROLL_COUNT_TO_LENGTH.get(len(normalized_rolls), 24)
        length_bytes = ENTROPY_BYTES_REQUIRED[word_length]
    return entropy_bytes[:length_bytes]



def generate_mnemonic_from_coin_flips(coin_flips: str, wordlist_language_code: str = SettingsConstants.WORDLIST_LANGUAGE__ENGLISH) -> list[str]:
    """
        Takes a string of binary digits and returns a mnemonic of the appropriate length.

        Uses the iancoleman.io/bip39 and bitcoiner.guide/seed "Binary" mode approach:
        * binary digit stream is treated as string data.
        * hashed via SHA256.
    """
    entropy_bytes = hashlib.sha256(coin_flips.encode()).digest()

    length_map = {
        128: 12,
        160: 15,
        192: 18,
        224: 21,
        256: 24,
    }
    word_length = length_map.get(len(coin_flips))
    if word_length is None:
        raise Exception("Unsupported number of coin flips")

    entropy_bytes = entropy_bytes[:ENTROPY_BYTES_REQUIRED[word_length]]

    # Return as a list
    return bip39.mnemonic_from_bytes(entropy_bytes, wordlist=Seed.get_wordlist(wordlist_language_code)).split()



def get_partial_final_word(coin_flips: str, wordlist_language_code: str = SettingsConstants.WORDLIST_LANGUAGE__ENGLISH) -> str:
    """ Look up the partial final word for the given coin flips.
        7 coin flips: 0101010 + **** where the final 4 bits will be replaced with the checksum
        3 coin flips: 010 + ******** where the final 8 bits will be replaced with the checksum
    """
    binary_string = coin_flips + "0" * (11 - len(coin_flips))
    wordlist_index = int(binary_string, 2)

    return Seed.get_wordlist(wordlist_language_code)[wordlist_index]



# Note: This currently isn't being used since we're now chaining hashed bytes for the
#   image-based entropy and aren't just ingesting a single image.
def generate_mnemonic_from_image(image, wordlist_language_code: str = SettingsConstants.WORDLIST_LANGUAGE__ENGLISH) -> list[str]:
    import hashlib
    hash = hashlib.sha256(image.tobytes())

    # Return as a list
    return bip39.mnemonic_from_bytes(hash.digest(), wordlist=Seed.get_wordlist(wordlist_language_code)).split()


def _shannon_entropy(data: bytes | str) -> float:
    """Return the Shannon entropy of the provided data."""
    if isinstance(data, str):
        data = data.encode()
    counts = Counter(data)
    length = len(data)
    shannon_entropy = -sum((count / length) * math.log2(count / length) for count in counts.values())
    return shannon_entropy


def dice_entropy_is_sufficient(roll_data: str, threshold: float = 2.0) -> bool:
    """Simple randomness check for dice roll input."""
    return _shannon_entropy(roll_data) >= threshold


def byte_entropy_is_sufficient(data: bytes, threshold: float = 3.5) -> bool:
    """Simple randomness check for byte data."""
    return _shannon_entropy(data) >= threshold
