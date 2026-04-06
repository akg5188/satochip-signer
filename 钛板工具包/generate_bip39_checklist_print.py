from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path


PAGE_WIDTH_MM = 210
PAGE_HEIGHT_MM = 297


def parse_markdown(text: str) -> tuple[str, list[str], list[tuple[str, list[str]]]]:
    title = ""
    intro: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_items: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            if current_title:
                sections.append((current_title, current_items))
            current_title = line[3:].strip()
            current_items = []
            continue
        if line.startswith("- [ ] "):
            current_items.append(line[6:].strip())
            continue
        if not current_title:
            intro.append(line)

    if current_title:
        sections.append((current_title, current_items))

    return title, intro, sections


def build_html(markdown_path: Path) -> str:
    title, intro, sections = parse_markdown(markdown_path.read_text(encoding="utf-8"))
    intro_html = "".join(f"<p>{html.escape(line)}</p>" for line in intro)
    section_html = []

    for section_title, items in sections:
        items_html = "".join(
            (
                '<li class="check-item">'
                '<span class="box" aria-hidden="true"></span>'
                f"<span>{html.escape(item)}</span>"
                "</li>"
            )
            for item in items
        )
        section_html.append(
            (
                '<section class="section">'
                f'<h2 class="section-title">{html.escape(section_title)}</h2>'
                f'<ul class="check-list">{items_html}</ul>'
                "</section>"
            )
        )

    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(title)}</title>
    <style>
      @page {{
        size: A4 portrait;
        margin: 0;
      }}

      :root {{
        --page-w: {PAGE_WIDTH_MM}mm;
        --page-h: {PAGE_HEIGHT_MM}mm;
        --ink: #1f1f1f;
        --subtle: #666;
        --line: #d6d6d6;
        --panel: #fafafa;
      }}

      * {{
        box-sizing: border-box;
      }}

      html,
      body {{
        margin: 0;
        padding: 0;
        background: #efefef;
        color: var(--ink);
        font-family: "Liberation Sans", "Noto Sans CJK SC", "DejaVu Sans", sans-serif;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}

      body {{
        padding: 4mm 0;
      }}

      .page {{
        width: var(--page-w);
        min-height: var(--page-h);
        margin: 0 auto;
        padding: 8mm 9mm 8mm;
        background: #fff;
        border: 0.25mm solid #ececec;
        box-shadow: 0 0 10px rgba(0, 0, 0, 0.08);
      }}

      .header {{
        display: flex;
        align-items: end;
        justify-content: space-between;
        gap: 6mm;
        border-bottom: 0.3mm solid var(--ink);
        padding-bottom: 2mm;
        margin-bottom: 3mm;
      }}

      .title {{
        margin: 0;
        font-size: 16pt;
        line-height: 1;
        letter-spacing: 0.03em;
        font-weight: 700;
      }}

      .stamp {{
        font-size: 7.5pt;
        color: var(--subtle);
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }}

      .intro {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 4mm;
        margin-bottom: 4mm;
        font-size: 9pt;
        line-height: 1.35;
        color: #333;
      }}

      .intro p {{
        margin: 0;
      }}

      .content {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 4mm;
        align-items: start;
      }}

      .section {{
        break-inside: avoid;
        border: 0.18mm solid var(--line);
        background: var(--panel);
        padding: 2.4mm 2.8mm 2.1mm;
        margin-bottom: 3mm;
      }}

      .section-title {{
        margin: 0 0 1.8mm;
        font-size: 10pt;
        line-height: 1.1;
        font-weight: 700;
      }}

      .check-list {{
        list-style: none;
        margin: 0;
        padding: 0;
      }}

      .check-item {{
        display: grid;
        grid-template-columns: 3.6mm 1fr;
        gap: 1.4mm;
        align-items: start;
        font-size: 8.4pt;
        line-height: 1.25;
        padding: 0.9mm 0;
        border-top: 0.14mm solid rgba(0, 0, 0, 0.07);
      }}

      .check-item:first-child {{
        border-top: none;
        padding-top: 0;
      }}

      .box {{
        width: 2.8mm;
        height: 2.8mm;
        border: 0.25mm solid #222;
        margin-top: 0.15mm;
      }}

      .footer {{
        margin-top: 3mm;
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 4mm;
      }}

      .notes,
      .signoff {{
        border: 0.18mm solid var(--line);
        min-height: 24mm;
        padding: 2.5mm 3mm;
        background: #fff;
      }}

      .footer-title {{
        margin: 0 0 1.8mm;
        font-size: 9pt;
        font-weight: 700;
      }}

      .rule {{
        height: 6mm;
        border-bottom: 0.14mm solid #bdbdbd;
      }}

      .sign-row {{
        display: grid;
        grid-template-columns: 12mm 1fr;
        gap: 2mm;
        align-items: center;
        font-size: 8.4pt;
        margin-top: 2.5mm;
      }}

      .line {{
        border-bottom: 0.18mm solid #888;
        height: 5mm;
      }}

      @media print {{
        html,
        body {{
          background: #fff;
          padding: 0;
        }}

        .page {{
          border: none;
          box-shadow: none;
        }}
      }}
    </style>
  </head>
  <body>
    <main class="page">
      <header class="header">
        <h1 class="title">{html.escape(title)}</h1>
        <div class="stamp">BIP39 titanium plate checklist</div>
      </header>
      <section class="intro">
        {intro_html}
      </section>
      <section class="content">
        <div>
          {''.join(section_html[0::2])}
        </div>
        <div>
          {''.join(section_html[1::2])}
        </div>
      </section>
      <footer class="footer">
        <div class="notes">
          <div class="footer-title">备注 / Notes</div>
          <div class="rule"></div>
          <div class="rule"></div>
          <div class="rule"></div>
        </div>
        <div class="signoff">
          <div class="footer-title">最终确认 / Sign-off</div>
          <div class="sign-row"><span>日期</span><span class="line"></span></div>
          <div class="sign-row"><span>复核人</span><span class="line"></span></div>
          <div class="sign-row"><span>备注</span><span class="line"></span></div>
        </div>
      </footer>
    </main>
  </body>
</html>
"""


def render_outputs(html_path: Path, pdf_path: Path, preview_path: Path) -> None:
    chrome = subprocess.run(
        ["which", "google-chrome"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    uri = html_path.resolve().as_uri()
    base_args = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox"]

    subprocess.run(
        base_args + ["--print-to-pdf-no-header", f"--print-to-pdf={pdf_path}", uri],
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


def main() -> None:
    base = Path(__file__).resolve().parent
    markdown_path = base / "bip39_最终检查清单.md"
    html_path = base / "bip39_最终检查清单_a4.html"
    pdf_path = base / "bip39_最终检查清单_a4.pdf"
    preview_path = base / "bip39_最终检查清单_a4_preview.png"

    html_path.write_text(build_html(markdown_path), encoding="utf-8")
    render_outputs(html_path, pdf_path, preview_path)

    print(f"Generated: {html_path}")
    print(f"Generated: {pdf_path}")
    print(f"Generated: {preview_path}")


if __name__ == "__main__":
    main()
