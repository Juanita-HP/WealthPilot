"""WealthPilot logo: the three ascending bars of the app, a flight path, and the wordmark.

    python docs/brand/build_logo.py      # writes the SVG files; render.js (same folder) exports the PNGs

Colours are the app's: ink #172025, gold #c5ad83, paper #f7f5f1.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
INK, GOLD, LIGHT_GOLD, PAPER = "#172025", "#c5ad83", "#e2cfa6", "#f7f5f1"


def mark(x: float, y: float, s: float, bars: str = GOLD, path: str = INK) -> str:
    """Symbol in a 100x100 box at (x, y), scale s: three rising bars and a flight path ending in an arrow."""
    def r(px, py, w, h):
        return f'<rect x="{x + px * s:.2f}" y="{y + py * s:.2f}" width="{w * s:.2f}" height="{h * s:.2f}" rx="{3 * s:.2f}" fill="{bars}"/>'
    p = lambda px, py: f"{x + px * s:.2f} {y + py * s:.2f}"  # noqa: E731
    return (r(10, 64, 20, 30) + r(40, 46, 20, 48) + r(70, 28, 20, 66) +
            f'<path d="M {p(6, 46)} C {p(30, 40)} {p(56, 24)} {p(84, 5)}" fill="none" stroke="{path}" '
            f'stroke-width="{4.5 * s:.2f}" stroke-linecap="round"/>' +
            f'<path d="M {p(72, 3)} L {p(88, 2)} L {p(84, 17)}" fill="none" stroke="{path}" stroke-width="{4.5 * s:.2f}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')


def horizontal(dark: bool = False) -> str:
    ink = PAPER if dark else INK
    bg = f'<rect width="1040" height="320" fill="{INK}"/>' if dark else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1040" height="320" viewBox="0 0 1040 320">
{bg}{mark(70, 60, 2.0, GOLD, LIGHT_GOLD if dark else INK)}
<text x="320" y="190" font-family="Inter, Helvetica, Arial, sans-serif" font-size="122" font-weight="800" letter-spacing="-4" fill="{ink}">Wealth<tspan fill="{GOLD}">Pilot</tspan></text>
<text x="326" y="248" font-family="Inter, Helvetica, Arial, sans-serif" font-size="27" font-weight="600" letter-spacing="7" fill="{GOLD if not dark else LIGHT_GOLD}">EXPLAINABLE INVESTMENT AI</text>
</svg>'''


def icon() -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
<rect width="512" height="512" rx="112" fill="{INK}"/>
{mark(96, 104, 3.2, GOLD, LIGHT_GOLD)}
</svg>'''


if __name__ == "__main__":
    (HERE / "wealthpilot-logo.svg").write_text(horizontal())
    (HERE / "wealthpilot-logo-dark.svg").write_text(horizontal(dark=True))
    (HERE / "wealthpilot-icon.svg").write_text(icon())
    print("wrote", ", ".join(p.name for p in sorted(HERE.glob("*.svg"))))
