# Pi Signer (Linux / Raspberry Pi)

`pi-signer` is a JVM CLI signer for offline TP watch-wallet workflows on Raspberry Pi.
It reuses the same TP parser + Satochip signing logic as the Android app, but talks to smartcards through PC/SC (`ACR39U`).

## Build

From project root:

```bash
./gradlew :pi-signer:installDist
```

Output directory:

- `pi-signer/build/install/pi-signer/`

Release bundle task:

```bash
./gradlew :pi-signer:assembleReleaseBundle
```

Bundle directory:

- `pi-signer/build/release/tp-pi-signer/`

## Runtime dependencies on Pi OS

```bash
sudo apt-get install -y openjdk-17-jre-headless pcscd pcsc-tools libpcsclite1
sudo systemctl enable --now pcscd
```

## Usage

Unlock and show address:

```bash
./pi-signer/bin/pi-signer unlock --pin 123456
```

Sign request (payload from file):

```bash
./pi-signer/bin/pi-signer sign \
  --pin 123456 \
  --payload-file request.txt \
  --out response.txt \
  --qr response.png
```

If `request.txt` contains multi-line `tp:multiFragment-...` entries, the tool auto-assembles fragments.

Sign Electrum PSBT:

```bash
./pi-signer/bin/pi-signer sign-psbt \
  --pin 123456 \
  --psbt-file unsigned.psbt \
  --out-psbt signed.psbt \
  --out-psbt-base64 signed.psbt.txt \
  --out-tx signed.tx.hex
```

`sign-psbt` accepts either:

- raw binary PSBT (`.psbt`)
- base64 PSBT text from file / stdin / `--psbt`

Current first version support:

- `P2PKH`
- `P2WPKH`
- `P2SH-P2WPKH`

Current first version limitations:

- `Taproot` is rejected for now
- complex multisig / `P2WSH` inputs are signed as partial PSBT only and may not auto-finalize
- the PSBT must contain BIP32 derivation paths so the signer can match inputs to the card

## Notes

- Supports `signTransaction`, `personalSign`, `signTypeData/signTypeDataV4`.
- Supports Electrum-style `PSBT` signing via `sign-psbt` for the common single-sig Bitcoin flow.
- `signTypedDataLegacy` array format is intentionally rejected (same as Android).
- This is CLI-first. Camera/screen UI can be added later as a separate module.
