#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
OKX_DYNAMIC_MAX_FRAGMENT_LEN = 160
OKX_DYNAMIC_INTERVAL_MS = 450


@dataclass(frozen=True)
class Variant:
    slug: str
    title: str
    note: str
    ledger_live_count: int
    btc_paths: tuple[str, ...]


VARIANTS = [
    Variant(
        slug="okx-dynamic-evm-only",
        title="方案 1: 动态 EVM only",
        note="只导出 1 个标准 EVM 账户，授权提示应该最少。",
        ledger_live_count=0,
        btc_paths=tuple(),
    ),
    Variant(
        slug="okx-dynamic-evm-btc84",
        title="方案 2: 动态 EVM + BTC84",
        note="导出 1 个标准 EVM 账户 + BTC Native SegWit 84'，这是最符合你现在目标的精简多链版。",
        ledger_live_count=0,
        btc_paths=("m/84'/0'/0'",),
    ),
    Variant(
        slug="okx-dynamic-1evm-btc84",
        title="方案 3: 动态 EVM + 1 个 OKX EVM + BTC84",
        note="比方案 2 多一个 OKX Ledger Live EVM 账户，用来测试 OKX 是否必须要这个账户才稳定。",
        ledger_live_count=1,
        btc_paths=("m/84'/0'/0'",),
    ),
]


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


def _build_parts(tp_views, UREncoder, UR, web3_account):
    ur = UR("crypto-multi-accounts", tp_views._build_web3_okx_multi_accounts_cbor_bytes(web3_account))
    static_ur = UREncoder.encode(ur).upper()
    encoder = UREncoder(ur, OKX_DYNAMIC_MAX_FRAGMENT_LEN)
    part_count = max(1, int(encoder.fountain_encoder.seq_len()))
    parts = [encoder.next_part().upper() for _ in range(part_count)]
    return static_ur, parts


def _render_variant(seed, qr, tp_views, UREncoder, UR, variant: Variant) -> dict:
    original_ledger_count = tp_views.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT
    original_btc_paths = tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS
    try:
        tp_views.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT = variant.ledger_live_count
        tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS = variant.btc_paths
        web3_account = tp_views._export_web3_account_from_seed(seed, tp_views.DEFAULT_DERIVATION_PATH)
        static_ur, parts = _build_parts(tp_views, UREncoder, UR, web3_account)
    finally:
        tp_views.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT = original_ledger_count
        tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS = original_btc_paths

    frame_names = []
    for index, part in enumerate(parts, start=1):
        frame_name = f"{variant.slug}-frame-{index:02d}.png"
        frame_names.append(frame_name)
        image = qr.qrimage_io(
            part,
            width=240,
            height=240,
            border=2,
            background_color="ffffff",
        )
        image.save(DIST / frame_name)
    (DIST / f"{variant.slug}.txt").write_text("\n".join(parts) + "\n", encoding="utf-8")

    return {
        "slug": variant.slug,
        "title": variant.title,
        "note": variant.note,
        "ledger_live_count": variant.ledger_live_count,
        "btc_paths": list(variant.btc_paths),
        "static_length": len(static_ur),
        "frame_count": len(parts),
        "frames": frame_names,
        "address": web3_account["address"],
    }


def _write_html(results: list[dict]) -> Path:
    html_path = DIST / "okx-dynamic-slim-test-20260416.html"
    nav = []
    cards = []
    for index, item in enumerate(results, start=1):
        nav.append(f'<a href="#item-{index}">{index}. {item["title"]}</a>')
        btc_label = ", ".join(item["btc_paths"]) if item["btc_paths"] else "无 BTC"
        first_frame = item["frames"][0]
        cards.append(
            f"""<section class="card" id="item-{index}" data-frames='{json.dumps(item["frames"], ensure_ascii=False)}'>
  <div class="meta">
    <div class="number">{index}</div>
    <div>
      <h2>{item["title"]}</h2>
      <p>静态长度: <code>{item["static_length"]}</code>，动态帧数: <code>{item["frame_count"]}</code></p>
      <p>额外 OKX EVM: <code>{item["ledger_live_count"]}</code>，BTC: <code>{btc_label}</code></p>
      <p class="hint">{item["note"]}</p>
    </div>
  </div>
  <img class="qr" src="{first_frame}" alt="{item["title"]}">
  <p><small class="label"></small></p>
  <div class="toolbar">
    <button type="button" class="toggle">暂停</button>
    <button type="button" class="restart">重头播放</button>
  </div>
</section>"""
        )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OKX 动态精简测试页</title>
<style>
:root {{ color-scheme: light; --ink:#111827; --muted:#475569; --paper:#fff; --line:#d7dee8; --soft:#f6f8fb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:linear-gradient(180deg,#f8fafc 0%,#ffffff 28%,#eef2f7 100%); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
header {{ max-width:1040px; margin:0 auto; padding:26px 18px 10px; }}
main {{ max-width:1040px; margin:0 auto; padding:12px 14px 28px; }}
h1 {{ margin:0 0 10px; font-size:30px; }}
p {{ margin:6px 0; line-height:1.55; }}
.nav {{ display:flex; flex-wrap:wrap; gap:8px; margin:16px 0 0; }}
.nav a {{ color:#0f172a; text-decoration:none; border:1px solid var(--line); background:white; border-radius:999px; padding:7px 11px; }}
.card {{ background:var(--paper); border:1px solid var(--line); border-radius:24px; box-shadow:0 18px 50px rgba(15,23,42,.10); margin:18px 0; padding:18px; }}
.meta {{ display:flex; gap:14px; align-items:flex-start; text-align:left; }}
.number {{ flex:0 0 auto; width:38px; height:38px; border-radius:50%; background:#111827; color:white; display:grid; place-items:center; font-weight:700; }}
h2 {{ margin:0 0 8px; font-size:24px; }}
.hint {{ color:var(--muted); }}
code {{ background:var(--soft); border:1px solid #e2e8f0; border-radius:7px; padding:2px 6px; }}
.note {{ border-left:5px solid #111827; padding:10px 12px; background:white; border-radius:12px; }}
.qr {{ display:block; width:240px; height:240px; margin:18px auto 8px; image-rendering:pixelated; background:white; border:1px solid #e2e8f0; }}
.toolbar {{ display:flex; justify-content:center; flex-wrap:wrap; gap:8px; margin:12px 0 0; }}
button {{ border:1px solid var(--line); background:white; border-radius:999px; padding:8px 14px; font:inherit; cursor:pointer; }}
small {{ color:var(--muted); display:block; text-align:center; }}
</style>
</head>
<body>
<header>
  <h1>OKX 动态精简测试页</h1>
  <p class="note">上一张旧动态全量能出账户，但授权提示太多。这页保留动态播放方式，只减少账户数量，测试能不能既出账户又减少授权提示。</p>
  <p>测试助记词: <code>{MNEMONIC}</code></p>
  <p>播放间隔: <code>{OKX_DYNAMIC_INTERVAL_MS}ms</code>，分片上限: <code>{OKX_DYNAMIC_MAX_FRAGMENT_LEN}</code></p>
  <div class="nav">{''.join(nav)}</div>
</header>
<main>
{''.join(cards)}
</main>
<script>
const intervalMs = {OKX_DYNAMIC_INTERVAL_MS};
document.querySelectorAll('.card').forEach((card) => {{
  const frames = JSON.parse(card.dataset.frames);
  const qr = card.querySelector('.qr');
  const label = card.querySelector('.label');
  const toggle = card.querySelector('.toggle');
  const restart = card.querySelector('.restart');
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
    toggle.textContent = '暂停';
  }}
  function stop() {{
    if (!timer) return;
    clearInterval(timer);
    timer = null;
    toggle.textContent = '继续播放';
  }}
  toggle.addEventListener('click', () => timer ? stop() : start());
  restart.addEventListener('click', () => {{
    index = 0;
    render();
  }});
  render();
  start();
}});
</script>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return html_path


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    Seed, QR, UR, UREncoder, tp_views = _load_runtime()
    seed = Seed(MNEMONIC.split())
    qr = QR()
    results = [_render_variant(seed, qr, tp_views, UREncoder, UR, variant) for variant in VARIANTS]
    html_path = _write_html(results)
    (DIST / "okx-dynamic-slim-test-20260416.build-info.json").write_text(
        json.dumps(
            {
                "mnemonic": MNEMONIC,
                "interval_ms": OKX_DYNAMIC_INTERVAL_MS,
                "max_fragment_len": OKX_DYNAMIC_MAX_FRAGMENT_LEN,
                "html": html_path.name,
                "variants": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(str(html_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
