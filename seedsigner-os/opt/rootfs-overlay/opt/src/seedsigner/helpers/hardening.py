import os


HARDENED_ENV_VAR = "TP_HARDENED_COLD_STORAGE"


def is_hardened_cold_storage() -> bool:
    return os.environ.get(HARDENED_ENV_VAR) == "1"


def allow_external_settings() -> bool:
    return not is_hardened_cold_storage()


def allow_microsd_runtime() -> bool:
    return not is_hardened_cold_storage()


def allow_backup_imports() -> bool:
    return not is_hardened_cold_storage()


def allow_gpg_tools() -> bool:
    return not is_hardened_cold_storage()


def allow_nfc_tools() -> bool:
    return not is_hardened_cold_storage()


def allow_smartcard_mutations() -> bool:
    return not is_hardened_cold_storage()


def allow_smartcard_pin_cache() -> bool:
    return not is_hardened_cold_storage()


def allow_seedkeeper_secret_flows() -> bool:
    return not is_hardened_cold_storage()


def allow_diagnostic_tools() -> bool:
    return not is_hardened_cold_storage()
