from __future__ import annotations

import html
import math
import subprocess
from pathlib import Path
from urllib.request import urlopen

from PIL import ImageFont

PAGE_WIDTH_MM = 210
PAGE_HEIGHT_MM = 297
PAGE_MARGIN_X_MM = 8
PAGE_MARGIN_TOP_MM = 8
PAGE_MARGIN_BOTTOM_MM = 7
HEADER_HEIGHT_MM = 8
FOOTER_HEIGHT_MM = 5
COLUMN_GAP_MM = 2.8
COLUMNS_PER_PAGE = 3
ROWS_PER_COLUMN = 60
BITS = 11
CSS_DPI = 96
MM_PER_INCH = 25.4
LABEL_FONT_SIZE_PT = 6.45
LABEL_FONT_PATHS = (
    "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
)

WORDLIST_URL = "https://raw.githubusercontent.com/bitcoin/bips/master/bip-0039/english.txt"


def load_wordlist(wordlist_path: Path) -> list[str]:
    if wordlist_path.exists():
        words = [
            line.strip()
            for line in wordlist_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        with urlopen(WORDLIST_URL, timeout=20) as response:
            text = response.read().decode("utf-8")
        wordlist_path.write_text(text, encoding="utf-8")
        words = [line.strip() for line in text.splitlines() if line.strip()]

    if len(words) != 2048:
        raise ValueError(f"Expected 2048 BIP39 words, got {len(words)}")

    return words


def build_row(index: int, word: str) -> str:
    bits = format(index, f"0{BITS}b")[::-1]
    label = html.escape(f"{index}-{word}")
    bit_nodes = "".join(
        f'<span class="bit {"on" if bit == "1" else "off"}"></span>'
        for bit in bits
    )
    return (
        '<div class="row">'
        f'<span class="label">{label}</span>'
        f'<span class="bits" aria-label="{bits}">{bit_nodes}</span>'
        "</div>"
    )


def build_empty_row() -> str:
    return '<div class="row empty"><span class="label"></span><span class="bits"></span></div>'


def measure_label_width_mm(labels: list[str]) -> float:
    font_path = next((path for path in LABEL_FONT_PATHS if Path(path).exists()), None)
    if font_path is None:
        max_chars = max((len(label) for label in labels), default=1)
        return max_chars * 1.45 + 0.3

    font_size_px = max(1, round(LABEL_FONT_SIZE_PT * CSS_DPI / 72))
    font = ImageFont.truetype(font_path, font_size_px)
    width_px = max((font.getlength(label) for label in labels), default=0.0)
    return width_px * MM_PER_INCH / CSS_DPI + 0.35


def build_column(entries: list[tuple[int, str]]) -> str:
    labels = [f"{index}-{word}" for index, word in entries]
    label_width_mm = measure_label_width_mm(labels)
    rows = [build_row(index, word) for index, word in entries]
    rows.extend(build_empty_row() for _ in range(max(0, ROWS_PER_COLUMN - len(rows))))
    return f'<div class="column" style="--label-w: {label_width_mm:.2f}mm;">' + "".join(rows) + "</div>"


def build_page(page_number: int, total_pages: int, entries: list[tuple[int, str]]) -> str:
    columns = []
    for column_index in range(COLUMNS_PER_PAGE):
        start = column_index * ROWS_PER_COLUMN
        stop = start + ROWS_PER_COLUMN
        columns.append(build_column(entries[start:stop]))

    start_index = entries[0][0]
    end_index = entries[-1][0]

    return f"""
    <section class="page">
      <div class="page-inner">
        <header class="page-header">
          <div class="title">BIP39 English Binary Print Sheet</div>
          <div class="meta">Range {start_index}-{end_index} | Filled=1 Hollow=0 | Left to right: 1 2 4 8 16 ... 1024</div>
        </header>
        <main class="columns">
          {''.join(columns)}
        </main>
        <footer class="page-footer">Page {page_number} / {total_pages}</footer>
      </div>
    </section>
    """


def build_html(words: list[str]) -> str:
    entries = list(enumerate(words))
    per_page = COLUMNS_PER_PAGE * ROWS_PER_COLUMN
    total_pages = math.ceil(len(entries) / per_page)
    pages = []

    for page_index, offset in enumerate(range(0, len(entries), per_page), start=1):
        page_entries = entries[offset : offset + per_page]
        pages.append(build_page(page_index, total_pages, page_entries))

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>BIP39 Binary Print Sheet</title>
    <style>
      @page {{
        size: A4 portrait;
        margin: 0;
      }}

      :root {{
        --page-w: {PAGE_WIDTH_MM}mm;
        --page-h: {PAGE_HEIGHT_MM}mm;
        --margin-x: {PAGE_MARGIN_X_MM}mm;
        --margin-top: {PAGE_MARGIN_TOP_MM}mm;
        --margin-bottom: {PAGE_MARGIN_BOTTOM_MM}mm;
        --header-h: {HEADER_HEIGHT_MM}mm;
        --footer-h: {FOOTER_HEIGHT_MM}mm;
        --gap: {COLUMN_GAP_MM}mm;
        --ink: #3a3a3a;
        --ink-strong: #1f1f1f;
        --meta: #5a5a5a;
        --dot-off: #fbfbfb;
        --dot-off-border: #c7c7c7;
        --dot-on: #0b0b0b;
        --bit-size: 2.1mm;
      }}

      * {{
        box-sizing: border-box;
      }}

      html,
      body {{
        margin: 0;
        padding: 0;
        background: #f6f6f6;
        color: var(--ink);
        font-family: "Liberation Sans Narrow", "Arial Narrow", "DejaVu Sans", sans-serif;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}

      body {{
        padding: 2mm 0 6mm;
      }}

      .page {{
        width: var(--page-w);
        height: var(--page-h);
        background: #fff;
        margin: 0 auto 4mm auto;
        page-break-after: always;
        overflow: hidden;
        border: 0.25mm solid #ececec;
        box-shadow: 0 0 10px rgba(0, 0, 0, 0.08);
      }}

      .page:last-child {{
        page-break-after: auto;
      }}

      .page-inner {{
        width: 100%;
        height: 100%;
        padding:
          var(--margin-top)
          var(--margin-x)
          var(--margin-bottom)
          var(--margin-x);
        display: grid;
        grid-template-rows: var(--header-h) 1fr var(--footer-h);
      }}

      .page-header {{
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 6mm;
        border-bottom: 0.12mm solid rgba(0, 0, 0, 0.18);
        padding-bottom: 1mm;
      }}

      .title {{
        font-size: 9.25pt;
        font-weight: 700;
        color: var(--ink-strong);
        letter-spacing: 0.03em;
        text-transform: uppercase;
      }}

      .meta {{
        font-size: 6pt;
        color: var(--meta);
        letter-spacing: 0.06em;
      }}

      .columns {{
        display: grid;
        grid-template-columns: repeat({COLUMNS_PER_PAGE}, 1fr);
        gap: var(--gap);
        align-items: start;
        padding-top: 2mm;
      }}

      .column {{
        display: flex;
        flex-direction: column;
        gap: 0.1mm;
      }}

      .row {{
        display: grid;
        grid-template-columns: var(--label-w) minmax(0, 1fr);
        align-items: center;
        column-gap: 0.35mm;
        min-height: 4.15mm;
        border-bottom: 0.05mm solid rgba(0, 0, 0, 0.15);
        padding: 0.28mm 0;
        white-space: nowrap;
      }}

      .row:last-child {{
        border-bottom: none;
      }}

      .label {{
        width: var(--label-w);
        min-width: 0;
        font-size: 6.45pt;
        line-height: 1;
        letter-spacing: 0;
        color: var(--ink);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: clip;
        font-variant-numeric: tabular-nums;
        font-family: "Liberation Sans Narrow", "DejaVu Sans Condensed", "DejaVu Sans", sans-serif;
      }}

      .bits {{
        display: flex;
        width: 100%;
        align-items: center;
        justify-content: space-between;
      }}

      .bit {{
        width: var(--bit-size);
        height: var(--bit-size);
        border-radius: 50%;
        border: 0.18mm solid var(--dot-off-border);
        background: var(--dot-off);
        flex: 0 0 var(--bit-size);
      }}

      .bit.on {{
        background: var(--dot-on);
        border-color: var(--dot-on);
      }}

      .row.empty .label,
      .row.empty .bits {{
        visibility: hidden;
      }}

      .page-footer {{
        display: flex;
        align-items: end;
        justify-content: center;
        font-size: 6pt;
        color: var(--meta);
        letter-spacing: 0.1em;
      }}

      @media print {{
        html,
        body {{
          background: #fff;
          padding: 0;
        }}

        .page {{
          margin: 0;
          border: none;
          box-shadow: none;
        }}
      }}
    </style>
  </head>
  <body>
    {''.join(pages)}
  </body>
</html>
"""


def try_render_pdf(html_path: Path, pdf_path: Path, preview_path: Path) -> None:
    chrome = shutil_which("google-chrome")
    if not chrome:
        return

    base_args = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
    ]

    uri = html_path.resolve().as_uri()

    subprocess.run(
        base_args
        + [
            "--print-to-pdf-no-header",
            f"--print-to-pdf={pdf_path}",
            uri,
        ],
        check=True,
    )

    subprocess.run(
        base_args
        + [
            "--window-size=1240,1754",
            "--force-device-scale-factor=2",
            f"--screenshot={preview_path}",
            uri,
        ],
        check=True,
    )


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def main() -> None:
    base = Path(__file__).resolve().parent
    wordlist_path = base / "bip39_english.txt"
    html_path = base / "bip39_a4_binary_print.html"
    pdf_path = base / "bip39_a4_binary_print.pdf"
    preview_path = base / "bip39_a4_binary_print_preview.png"

    words = load_wordlist(wordlist_path)
    html_path.write_text(build_html(words), encoding="utf-8")
    try_render_pdf(html_path, pdf_path, preview_path)

    print(f"Generated: {html_path}")
    if pdf_path.exists():
        print(f"Generated: {pdf_path}")
    if preview_path.exists():
        print(f"Generated: {preview_path}")
    print(f"Wordlist: {wordlist_path}")


if __name__ == "__main__":
    main()
