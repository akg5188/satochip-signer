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


@dataclass(frozen=True)
class Variant:
    slug: str
    title: str
    note: str
    btc_paths: tuple[str, ...]


VARIANTS = [
    Variant(
        slug="okx-source-current-49-84",
        title="方案 1: 当前固件原样版",
        note="这张码和当前源码逻辑完全一致: 1 个标准 EVM + BTC 49' + 84'。这是目前实测能让 OKX 出比特币的最小组合。",
        btc_paths=("m/49'/0'/0'", "m/84'/0'/0'"),
    ),
    Variant(
        slug="okx-source-evm-only",
        title="方案 2: 极限排查版",
        note="只保留 1 个标准 EVM 账户，不带 BTC。若这张能出账户，就说明问题在 OKX 对 BTC multi-accounts 的兼容上。",
        btc_paths=tuple(),
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
    import seedsigner.views.tp_views as tp_views

    return smoke, Seed, QR, tp_views


def _render_variant(seed, qr_helper, tp_views, variant: Variant) -> dict:
    original_btc_paths = tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS
    try:
        tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS = variant.btc_paths
        web3_account = tp_views._export_web3_account_from_seed(seed, tp_views.DEFAULT_DERIVATION_PATH)
        qr_pages = tp_views._build_web3_connect_qr_pages(web3_account, tp_views.WEB3_WALLET_PROFILE_OKX)
        qr_text = qr_pages[0]
    finally:
        tp_views.WEB3_OKX_BTC_ACCOUNT_PATHS = original_btc_paths

    image_name = f"{variant.slug}-240x240-whitebg.png"
    text_name = f"{variant.slug}.txt"

    image = qr_helper.qrimage_io(
        qr_text,
        width=240,
        height=240,
        border=2,
        background_color="ffffff",
    )
    image.save(DIST / image_name)
    (DIST / text_name).write_text(qr_text, encoding="utf-8")

    return {
        "slug": variant.slug,
        "title": variant.title,
        "note": variant.note,
        "image": image_name,
        "text": text_name,
        "length": len(qr_text),
        "btc_paths": list(variant.btc_paths),
        "okx_extra_evm_count": len(web3_account["keystoneKeys"].get("okxLedgerLive", [])),
        "okx_btc_count": len(web3_account["keystoneKeys"].get("okxBitcoin", [])),
        "address": web3_account["address"],
    }


def _write_html(results: list[dict]) -> Path:
    html_path = DIST / "okx-source-exact-test-20260416.html"
    nav = []
    cards = []
    for index, item in enumerate(results, start=1):
        nav.append(f'<a href="#item-{index}">{index}. {item["title"]}</a>')
        btc_label = ", ".join(item["btc_paths"]) if item["btc_paths"] else "无 BTC"
        cards.append(
            f"""<section class="card" id="item-{index}">
  <div class="meta">
    <div class="number">{index}</div>
    <div>
      <h2>{item["title"]}</h2>
      <p class="wallet">协议: <code>crypto-multi-accounts</code></p>
      <p>长度: <code>{item["length"]}</code> 字符</p>
      <p>额外 OKX EVM: <code>{item["okx_extra_evm_count"]}</code>，BTC: <code>{btc_label}</code></p>
      <p class="hint">{item["note"]}</p>
    </div>
  </div>
  <img class="qr" src="{item["image"]}" alt="{item["title"]}">
</section>"""
        )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OKX 当前源码测试页</title>
<style>
:root {{ color-scheme: light; --ink:#111827; --muted:#475569; --paper:#fff; --line:#d7dee8; --soft:#f6f8fb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:linear-gradient(180deg,#f8fafc 0%,#ffffff 28%,#eef2f7 100%); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
header {{ max-width:1040px; margin:0 auto; padding:26px 18px 10px; }}
h1 {{ margin:0 0 10px; font-size:30px; }}
p {{ margin:6px 0; line-height:1.55; }}
.nav {{ display:flex; flex-wrap:wrap; gap:8px; margin:16px 0 0; }}
.nav a {{ color:#0f172a; text-decoration:none; border:1px solid var(--line); background:white; border-radius:999px; padding:7px 11px; }}
main {{ max-width:1040px; margin:0 auto; padding:12px 14px 28px; }}
.card {{ background:var(--paper); border:1px solid var(--line); border-radius:24px; box-shadow:0 18px 50px rgba(15,23,42,.10); margin:18px 0; padding:18px; }}
.meta {{ display:flex; gap:14px; align-items:flex-start; text-align:left; }}
.number {{ flex:0 0 auto; width:38px; height:38px; border-radius:50%; background:#111827; color:white; display:grid; place-items:center; font-weight:700; }}
h2 {{ margin:0 0 8px; font-size:24px; }}
.wallet,.hint {{ color:var(--muted); }}
code {{ background:var(--soft); border:1px solid #e2e8f0; border-radius:7px; padding:2px 6px; }}
.note {{ border-left:5px solid #111827; padding:10px 12px; background:white; border-radius:12px; }}
.qr {{ display:block; width:240px; height:240px; margin:18px auto 4px; image-rendering:pixelated; background:white; border:1px solid #e2e8f0; }}
@media (max-width:700px) {{ h1 {{ font-size:24px; }} h2 {{ font-size:20px; }} .card {{ padding:12px; border-radius:18px; }} }}
</style>
</head>
<body>
<header>
  <h1>OKX 当前源码测试页</h1>
  <p class="note">这页直接调用当前源码生成 OKX 连接码，不再手搓协议。先测哪个方案能把账户列表拉出来，再决定固件保留哪条。</p>
  <p>测试助记词: <code>{MNEMONIC}</code></p>
  <div class="nav">{''.join(nav)}</div>
</header>
<main>
{''.join(cards)}
</main>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return html_path


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    _smoke, Seed, QR, tp_views = _load_runtime()
    seed = Seed(MNEMONIC.split())
    qr_helper = QR()
    results = [_render_variant(seed, qr_helper, tp_views, variant) for variant in VARIANTS]
    html_path = _write_html(results)
    build_info_path = DIST / "okx-source-exact-test-20260416.build-info.json"
    build_info_path.write_text(
        json.dumps(
            {
                "mnemonic": MNEMONIC,
                "variants": results,
                "html": html_path.name,
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
