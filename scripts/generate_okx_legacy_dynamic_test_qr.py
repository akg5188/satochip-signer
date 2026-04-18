#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
OKX_LEGACY_LEDGER_LIVE_COUNT = 10
OKX_LEGACY_BTC_PATHS = ("m/44'/0'/0'", "m/49'/0'/0'", "m/84'/0'/0'")
OKX_DYNAMIC_MAX_FRAGMENT_LEN = 160
OKX_DYNAMIC_INTERVAL_MS = 450


def _load_smoke_module():
    smoke_path = ROOT / "scripts/smoke_tp_features.py"
    spec = importlib.util.spec_from_file_location("smoke_tp_features", smoke_path)
    smoke = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(smoke)
    return smoke


def _load_runtime():
    smoke = _load_smoke_module()
    smoke.install_import_stubs()
    sys.path.insert(0, str(ROOT / "seedsigner-os/opt/rootfs-overlay/opt/src"))
    sys.path.insert(0, str(ROOT / "pi-signer-py/vendor"))

    from seedsigner.models.seed import Seed
    from seedsigner.helpers.qr import QR
    from seedsigner.helpers.ur2.ur import UR
    from seedsigner.helpers.ur2.ur_encoder import UREncoder
    import seedsigner.views.tp_views as tp_views

    return Seed, QR, UR, UREncoder, tp_views


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    Seed, QR, UR, UREncoder, tp_views = _load_runtime()

    original_ledger_count = tp_views.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT
    original_btc_paths = tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS

    try:
        tp_views.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT = OKX_LEGACY_LEDGER_LIVE_COUNT
        tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS = OKX_LEGACY_BTC_PATHS

        seed = Seed(MNEMONIC.split())
        web3_account = tp_views._export_web3_account_from_seed(seed, tp_views.DEFAULT_DERIVATION_PATH)
        ur = UR("crypto-multi-accounts", tp_views._build_web3_okx_multi_accounts_cbor_bytes(web3_account))
        static_ur = UREncoder.encode(ur).upper()
        encoder = UREncoder(ur, OKX_DYNAMIC_MAX_FRAGMENT_LEN)
        part_count = max(1, int(encoder.fountain_encoder.seq_len()))
        parts = [encoder.next_part().upper() for _ in range(part_count)]
    finally:
        tp_views.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT = original_ledger_count
        tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS = original_btc_paths

    qr = QR()
    frame_names = []
    for index, part in enumerate(parts, start=1):
        frame_name = f"okx-legacy-dynamic-frame-{index:02d}.png"
        frame_names.append(frame_name)
        image = qr.qrimage_io(
            part,
            width=240,
            height=240,
            border=2,
            background_color="ffffff",
        )
        image.save(DIST / frame_name)

    html_path = DIST / "okx-legacy-dynamic-test-20260416.html"
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OKX 旧动态全量测试页</title>
<style>
:root {{ color-scheme: light; --ink:#111827; --muted:#475569; --paper:#fff; --line:#d7dee8; --soft:#f6f8fb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:linear-gradient(180deg,#f8fafc 0%,#ffffff 28%,#eef2f7 100%); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ max-width:980px; margin:0 auto; padding:24px 16px 32px; }}
.card {{ background:var(--paper); border:1px solid var(--line); border-radius:24px; box-shadow:0 18px 50px rgba(15,23,42,.10); padding:20px; }}
h1 {{ margin:0 0 12px; font-size:30px; }}
p {{ margin:6px 0; line-height:1.55; }}
code {{ background:var(--soft); border:1px solid #e2e8f0; border-radius:7px; padding:2px 6px; }}
.note {{ border-left:5px solid #111827; padding:10px 12px; background:white; border-radius:12px; margin:14px 0; }}
img {{ display:block; width:240px; height:240px; margin:18px auto 8px; image-rendering:pixelated; background:white; border:1px solid #e2e8f0; }}
.toolbar {{ display:flex; flex-wrap:wrap; gap:8px; margin:16px 0 0; }}
button {{ border:1px solid var(--line); background:white; border-radius:999px; padding:8px 14px; font:inherit; cursor:pointer; }}
small {{ color:var(--muted); }}
</style>
</head>
<body>
<main>
  <section class="card">
    <h1>OKX 旧动态全量测试页</h1>
    <p class="note">这页按你说的“以前动态的是好的”来出：<code>OKX old dynamic</code>，包含 <code>ETH + OKX 10 个额外 EVM + BTC 44'/49'/84'</code>，不再压成单张静态码。</p>
    <p>静态整串长度: <code>{len(static_ur)}</code> 字符</p>
    <p>动态分片: <code>{len(parts)}</code> 帧，单帧上限 <code>{OKX_DYNAMIC_MAX_FRAGMENT_LEN}</code> bytewords 负载，播放间隔 <code>{OKX_DYNAMIC_INTERVAL_MS}ms</code></p>
    <p>测试助记词: <code>{MNEMONIC}</code></p>
    <p>当前地址: <code>{web3_account["address"]}</code></p>
    <img id="qr" src="{frame_names[0]}" alt="OKX legacy dynamic frame">
    <p><small id="frameLabel"></small></p>
    <div class="toolbar">
      <button type="button" id="toggleBtn">暂停</button>
      <button type="button" id="restartBtn">重头播放</button>
    </div>
  </section>
</main>
<script>
const frames = {json.dumps(frame_names, ensure_ascii=False)};
const intervalMs = {OKX_DYNAMIC_INTERVAL_MS};
const qr = document.getElementById('qr');
const label = document.getElementById('frameLabel');
const toggleBtn = document.getElementById('toggleBtn');
const restartBtn = document.getElementById('restartBtn');
let index = 0;
let timer = null;
function render() {{
  qr.src = frames[index];
  label.textContent = `Frame ${{index + 1}} / ${{frames.length}}`;
}}
function start() {{
  if (timer || frames.length <= 1) return;
  timer = setInterval(() => {{
    index = (index + 1) % frames.length;
    render();
  }}, intervalMs);
  toggleBtn.textContent = '暂停';
}}
function stop() {{
  if (!timer) return;
  clearInterval(timer);
  timer = null;
  toggleBtn.textContent = '继续播放';
}}
toggleBtn.addEventListener('click', () => {{
  if (timer) stop();
  else start();
}});
restartBtn.addEventListener('click', () => {{
  index = 0;
  render();
}});
render();
start();
</script>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")

    build_info = {
        "mnemonic": MNEMONIC,
        "address": web3_account["address"],
        "ledger_live_count": OKX_LEGACY_LEDGER_LIVE_COUNT,
        "btc_paths": list(OKX_LEGACY_BTC_PATHS),
        "static_length": len(static_ur),
        "dynamic_frame_count": len(parts),
        "dynamic_max_fragment_len": OKX_DYNAMIC_MAX_FRAGMENT_LEN,
        "dynamic_interval_ms": OKX_DYNAMIC_INTERVAL_MS,
        "html": html_path.name,
        "frames": frame_names,
    }
    (DIST / "okx-legacy-dynamic-test-20260416.build-info.json").write_text(
        json.dumps(build_info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(str(html_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
