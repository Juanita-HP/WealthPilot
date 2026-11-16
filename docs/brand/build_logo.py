"""WealthPilot logo, exactly as in the site header: three gold bars and "WealthPilot" in DM Sans Bold.

    python docs/brand/build_logo.py <path to dm-sans-latin-700-normal.woff2>
    node docs/brand/render.js            # PNG exports

Geometry from web/src/styles.css (.logo, .brand strong): bars 6px wide, 4px apart, 12/20/29px high, bottom-aligned
in a 31px box; 14px gap; text 29px bold, letter-spacing -1.4px. The text is converted to outlines (shaped with
HarfBuzz, kerning included), so the SVG looks the same without the font installed.
DM Sans: SIL Open Font License, via @fontsource/dm-sans.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INK, GOLD, PAPER = "#172025", "#c5ad83", "#f7f5f1"

TEXT, SIZE, TRACKING = "WealthPilot", 29.0, -1.4
BARS = [(0, 12), (10, 20), (20, 29)]     # (x, height) in px, 6px wide
BOX, GAP, PAD = 31.0, 14.0, 8.0


def text_path(font_file: str) -> tuple[str, float, float, float]:
    """SVG path of the shaped text at SIZE px, its advance width, ascender and descender (px)."""
    import uharfbuzz as hb
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont

    import io
    tt = TTFont(font_file)
    tt.flavor = None                       # HarfBuzz reads TrueType/OpenType, not WOFF2: decompress first
    raw = io.BytesIO()
    tt.save(raw)
    data = raw.getvalue()
    tt = TTFont(io.BytesIO(data))
    upem = tt["head"].unitsPerEm
    font = hb.Font(hb.Face(hb.Blob(data)))
    buf = hb.Buffer()
    buf.add_str(TEXT)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    scale = SIZE / upem
    glyphs, order = tt.getGlyphSet(), tt.getGlyphOrder()
    pen = SVGPathPen(glyphs)
    x = 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        # font units -> px, y flipped (SVG y grows downwards); baseline at y = 0
        glyphs[order[info.codepoint]].draw(
            TransformPen(pen, (scale, 0, 0, -scale, x + pos.x_offset * scale, -pos.y_offset * scale)))
        x += pos.x_advance * scale + TRACKING
    hhea = tt["hhea"]
    return pen.getCommands(), x - TRACKING, hhea.ascent * scale, -hhea.descent * scale


def logo(font_file: str, text_color: str, background: str | None) -> str:
    d, width, asc, desc = text_path(font_file)
    height = max(BOX, asc + desc)
    text_x = 26 + GAP                                  # bars span 0..26
    baseline = (height - (asc + desc)) / 2 + asc       # text centred vertically, like align-items: center
    bars_top = (height - BOX) / 2
    w, h = text_x + width + 2 * PAD, height + 2 * PAD
    bars = "".join(f'<rect x="{PAD + bx}" y="{PAD + bars_top + BOX - bh:.2f}" width="6" height="{bh}" fill="{GOLD}"/>'
                   for bx, bh in BARS)
    bg = f'<rect width="{w:.2f}" height="{h:.2f}" fill="{background}"/>' if background else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}" height="{h:.2f}" viewBox="0 0 {w:.2f} {h:.2f}">'
            f'<title>WealthPilot</title>{bg}{bars}'
            f'<path transform="translate({PAD + text_x:.2f} {PAD + baseline:.2f})" d="{d}" fill="{text_color}"/></svg>')


def icon() -> str:
    """Square icon: the three bars on ink, same proportions as in the header."""
    s = 9.0
    bars = "".join(f'<rect x="{256 - 13 * s + bx * s:.2f}" y="{256 + 14.5 * s - bh * s:.2f}" width="{6 * s}" '
                   f'height="{bh * s}" fill="{GOLD}"/>' for bx, bh in BARS)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">'
            f'<title>WealthPilot</title><rect width="512" height="512" rx="112" fill="{INK}"/>{bars}</svg>')


if __name__ == "__main__":
    font_file = sys.argv[1]
    (HERE / "wealthpilot-logo.svg").write_text(logo(font_file, INK, None))
    (HERE / "wealthpilot-logo-dark.svg").write_text(logo(font_file, PAPER, INK))
    (HERE / "wealthpilot-icon.svg").write_text(icon())
    print("wrote", ", ".join(p.name for p in sorted(HERE.glob("*.svg"))))
