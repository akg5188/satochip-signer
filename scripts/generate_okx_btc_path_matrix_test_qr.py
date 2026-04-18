#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MNEMONIC = "law idea shy genuine satisfy acoustic salad despair share coffee risk gaze"
OUTPUT_STEM = "okx-btc-path-matrix-test-20260416"
INTERVAL_MS = 450


@dataclass(frozen=True)
class Variant:
    slug: str
    title: str
    note: str
    btc_paths: tuple[str, ...]


VARIANTS = [
    Variant(
        slug="okx-btc84-only",
        title="1. 只保留 BTC 84'",
        note="这是刚才失败的目标版，放在这里用于对照。",
        btc_paths=("m/84'/0'/0'",),
    ),
    Variant(
        slug="okx-btc44-84",
        title="2. BTC 44' + 84'",
        note="推荐先扫这个。如果 OKX 需要 44' 触发 BTC 入口，这个应该能出比特币。",
        btc_paths=("m/44'/0'/0'", "m/84'/0'/0'"),
    ),
    Variant(
        slug="okx-btc49-84",
        title="3. BTC 49' + 84'",
        note="如果 44' + 84' 不出，再测这个，看 OKX 是否需要 49' 触发。",
        btc_paths=("m/49'/0'/0'", "m/84'/0'/0'"),
    ),
    Variant(
        slug="okx-btc44-49-84",
        title="4. BTC 44' + 49' + 84'",
        note="旧动态全量版 BTC 路径，用来确认 OKX 是否必须三种一起给才显示 BTC。",
        btc_paths=("m/44'/0'/0'", "m/49'/0'/0'", "m/84'/0'/0'"),
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


def _render_variant(seed, qr, UR, UREncoder, tp_views, variant: Variant) -> dict:
    original_btc_paths = tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS
    try:
        tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS = variant.btc_paths
        web3_account = tp_views._export_web3_account_from_seed(seed, tp_views.DEFAULT_DERIVATION_PATH)
        pages = tp_views._build_web3_connect_qr_pages(web3_account, tp_views.WEB3_WALLET_PROFILE_OKX)
        ur = UR("crypto-multi-accounts", tp_views._build_web3_okx_multi_accounts_cbor_bytes(web3_account))
        static_ur = UREncoder.encode(ur).upper()
    finally:
        tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS = original_btc_paths

    frame_names = []
    for index, page in enumerate(pages, start=1):
        frame_name = f"{OUTPUT_STEM}-{variant.slug}-frame-{index:02d}.png"
        frame_names.append(frame_name)
        image = qr.qrimage_io(
            page,
            width=240,
            height=240,
            border=2,
            background_color="ffffff",
        )
        image.save(DIST / frame_name)

    return {
        "slug": variant.slug,
        "title": variant.title,
        "note": variant.note,
        "btc_paths": list(variant.btc_paths),
        "static_length": len(static_ur),
        "frame_count": len(pages),
        "frames": frame_names,
        "address": web3_account["address"],
    }


def _write_html(results: list[dict], tp_views) -> Path:
    html_path = DIST / f"{OUTPUT_STEM}.html"
    cards = []
    for index, item in enumerate(results, start=1):
        paths = " + ".join(item["btc_paths"])
        first_frame = item["frames"][0]
        cards.append(
            f"""<section class="card" id="{item["slug"]}" data-frames='{json.dumps(item["frames"], ensure_ascii=False)}'>
  <div class="headline">
    <div class="badge">{index}</div>
    <div>
      <h2>{item["title"]}</h2>
      <p class="hint">{item["note"]}</p>
    </div>
  </div>
  <p>BTC 路径: <code>{paths}</code></p>
  <p>长度: <code>{item["static_length"]}</code>，动态帧数: <code>{item["frame_count"]}</code></p>
  <div class="qrwrap"><img class="qr" src="{first_frame}" alt="{item["title"]}"></div>
  <p><small class="label"></small></p>
  <div class="toolbar">
    <button type="button" class="toggle">暂停</button>
    <button type="button" class="restart">重头播放</button>
    <button type="button" class="size" data-size="240">240</button>
    <button type="button" class="size" data-size="320">320</button>
    <button type="button" class="size" data-size="420">420</button>
  </div>
</section>"""
        )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OKX BTC 路径排查测试页</title>
<style>
:root {{ color-scheme: light; --ink:#111827; --muted:#475569; --paper:#fff; --line:#d7dee8; --soft:#f6f8fb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:linear-gradient(180deg,#f8fafc 0%,#ffffff 28%,#eef2f7 100%); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
header, main {{ max-width:1040px; margin:0 auto; }}
header {{ padding:24px 16px 8px; }}
main {{ padding:8px 16px 30px; }}
h1 {{ margin:0 0 12px; font-size:30px; }}
h2 {{ margin:0 0 6px; font-size:24px; }}
p {{ margin:6px 0; line-height:1.55; }}
code {{ background:var(--soft); border:1px solid #e2e8f0; border-radius:7px; padding:2px 6px; }}
.note {{ border-left:5px solid #111827; padding:10px 12px; background:white; border-radius:12px; margin:14px 0; }}
.card {{ background:var(--paper); border:1px solid var(--line); border-radius:24px; box-shadow:0 18px 50px rgba(15,23,42,.10); padding:18px; margin:16px 0; }}
.headline {{ display:flex; gap:12px; align-items:flex-start; }}
.badge {{ flex:0 0 auto; width:36px; height:36px; border-radius:50%; background:#111827; color:white; display:grid; place-items:center; font-weight:700; }}
.hint, small {{ color:var(--muted); }}
.qrwrap {{ display:grid; place-items:center; margin:16px auto 6px; }}
.qr {{ display:block; width:320px; height:320px; image-rendering:pixelated; background:white; border:1px solid #e2e8f0; }}
.toolbar {{ display:flex; justify-content:center; flex-wrap:wrap; gap:8px; margin:12px 0 0; }}
button {{ border:1px solid var(--line); background:white; border-radius:999px; padding:8px 14px; font:inherit; cursor:pointer; }}
small {{ display:block; text-align:center; }}
</style>
</head>
<body>
<header>
  <h1>OKX BTC 路径排查测试页</h1>
  <p class="note">只排查一件事：OKX 为什么 <code>84' only</code> 不显示比特币。这里所有方案都保持 <code>OKX 动态 crypto-multi-accounts</code> 和 <code>10 个 OKX EVM</code> 不变，只改 BTC 路径。</p>
  <p>推荐顺序：先扫第 2 个。如果第 2 个能出 BTC，就不用扫第 3/4 个。</p>
  <p>测试助记词: <code>{MNEMONIC}</code></p>
  <p>播放间隔: <code>{INTERVAL_MS}ms</code>，分片上限: <code>{tp_views.WEB3_OKX_CONNECT_QR_MAX_FRAGMENT_LEN}</code></p>
</header>
<main>
{''.join(cards)}
</main>
<script>
const intervalMs = {INTERVAL_MS};
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
  card.querySelectorAll('.size').forEach((button) => {{
    button.addEventListener('click', () => {{
      const size = button.dataset.size + 'px';
      qr.style.width = size;
      qr.style.height = size;
    }});
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
    results = [_render_variant(seed, qr, UR, UREncoder, tp_views, variant) for variant in VARIANTS]
    html_path = _write_html(results, tp_views)

    build_info = {
        "mnemonic": MNEMONIC,
        "address": results[0]["address"] if results else "",
        "ledger_live_count": tp_views.WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT,
        "dynamic_max_fragment_len": tp_views.WEB3_OKX_CONNECT_QR_MAX_FRAGMENT_LEN,
        "dynamic_interval_ms": INTERVAL_MS,
        "html": html_path.name,
        "variants": results,
    }
    (DIST / f"{OUTPUT_STEM}.build-info.json").write_text(
        json.dumps(build_info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(str(html_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
