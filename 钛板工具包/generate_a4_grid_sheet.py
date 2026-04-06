from pathlib import Path


PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 297.0
BIG_SQUARE_MM = 50.0
GAP_MM = 2.0
INNER_COLS = 11
INNER_ROWS = 13

OUTER_STROKE_MM = 0.25
INNER_STROKE_MM = 0.10
DOT_RADIUS_MM = 0.28


def mm(value: float) -> str:
    return f"{value:.3f}"


def build_svg(*, include_xml_declaration: bool = True) -> str:
    cols = int((PAGE_WIDTH_MM + GAP_MM) // (BIG_SQUARE_MM + GAP_MM))
    rows = int((PAGE_HEIGHT_MM + GAP_MM) // (BIG_SQUARE_MM + GAP_MM))
    total_width = cols * BIG_SQUARE_MM + max(0, cols - 1) * GAP_MM
    total_height = rows * BIG_SQUARE_MM + max(0, rows - 1) * GAP_MM
    offset_x = (PAGE_WIDTH_MM - total_width) / 2
    offset_y = (PAGE_HEIGHT_MM - total_height) / 2
    cell_w = BIG_SQUARE_MM / INNER_COLS
    cell_h = BIG_SQUARE_MM / INNER_ROWS

    parts = []

    if include_xml_declaration:
        parts.append('<?xml version="1.0" encoding="UTF-8"?>')

    parts.extend([
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{mm(PAGE_WIDTH_MM)}mm" height="{mm(PAGE_HEIGHT_MM)}mm" '
            f'viewBox="0 0 {mm(PAGE_WIDTH_MM)} {mm(PAGE_HEIGHT_MM)}">'
        ),
        "  <defs>",
        "    <style>",
        "      .outer { fill: none; stroke: #000; stroke-width: 0.25; }",
        "      .inner { stroke: #000; stroke-width: 0.10; }",
        "      .dot { fill: #000; }",
        "    </style>",
        "  </defs>",
        f'  <rect width="{mm(PAGE_WIDTH_MM)}" height="{mm(PAGE_HEIGHT_MM)}" fill="#fff"/>',
    ])

    for row in range(rows):
        for col in range(cols):
            x0 = offset_x + col * (BIG_SQUARE_MM + GAP_MM)
            y0 = offset_y + row * (BIG_SQUARE_MM + GAP_MM)

            parts.append(f'  <g transform="translate({mm(x0)} {mm(y0)})">')
            parts.append(
                f'    <rect class="outer" x="0" y="0" width="{mm(BIG_SQUARE_MM)}" height="{mm(BIG_SQUARE_MM)}"/>'
            )

            for inner_col in range(1, INNER_COLS):
                x = inner_col * cell_w
                parts.append(
                    f'    <line class="inner" x1="{mm(x)}" y1="0" x2="{mm(x)}" y2="{mm(BIG_SQUARE_MM)}"/>'
                )

            for inner_row in range(1, INNER_ROWS):
                y = inner_row * cell_h
                parts.append(
                    f'    <line class="inner" x1="0" y1="{mm(y)}" x2="{mm(BIG_SQUARE_MM)}" y2="{mm(y)}"/>'
                )

            for inner_row in range(INNER_ROWS):
                cy = (inner_row + 0.5) * cell_h
                for inner_col in range(INNER_COLS):
                    cx = (inner_col + 0.5) * cell_w
                    parts.append(
                        f'    <circle class="dot" cx="{mm(cx)}" cy="{mm(cy)}" r="{mm(DOT_RADIUS_MM)}"/>'
                    )

            parts.append("  </g>")

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def build_html(svg: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>A4 5cm Grid Sheet</title>
    <style>
      @page {{
        size: A4 portrait;
        margin: 0;
      }}

      html,
      body {{
        margin: 0;
        padding: 0;
        background: #fff;
        overflow: hidden;
      }}

      body {{
        width: {mm(PAGE_WIDTH_MM)}mm;
        height: {mm(PAGE_HEIGHT_MM)}mm;
      }}

      svg {{
        display: block;
        width: {mm(PAGE_WIDTH_MM)}mm;
        height: {mm(PAGE_HEIGHT_MM)}mm;
      }}
    </style>
  </head>
  <body>
{svg}
  </body>
</html>
"""


def main() -> None:
    base = Path(__file__).resolve().parent
    svg = build_svg()
    embedded_svg = build_svg(include_xml_declaration=False)
    (base / "a4_5cm_grid_sheet.svg").write_text(svg, encoding="utf-8")
    (base / "a4_5cm_grid_sheet.html").write_text(build_html(embedded_svg), encoding="utf-8")


if __name__ == "__main__":
    main()
