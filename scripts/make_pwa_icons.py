"""Draw the installable app's icons from the favicon's design (frontend/public/favicon.svg).

    docker run --rm -v "$PWD:/repo" sitesense-backend python /repo/scripts/make_pwa_icons.py

Needs Pillow (the backend image has it). Writes PNGs into frontend/public/icons/:

- icon-192.png, icon-512.png: the favicon as it is, a rounded dark square (purpose "any").
- icon-maskable-512.png: full-bleed background, the house inside the central 60% safe zone, so a
  launcher can crop it to a circle or squircle (purpose "maskable").
- apple-touch-icon.png (180): full-bleed, iOS rounds the corners itself.

The favicon is drawn on a 32-unit grid; every shape below uses the same coordinates.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "icons"
INK = "#1b1a16"  # background
SIGNAL = "#ffc21a"  # ground line and door
PAPER = "#f3f1ea"  # house outline
SUPERSAMPLE = 4  # draw large, then shrink: smooth edges without an SVG renderer


def _house(draw: ImageDraw.ImageDraw, unit: float, dx: float, dy: float) -> None:
    def p(x: float, y: float) -> tuple[float, float]:
        return (dx + x * unit, dy + y * unit)

    stroke = round(2.5 * unit)
    # Ground line, M7 23h18 (square caps reach 1.25 units past each end).
    draw.rectangle([p(7 - 1.25, 23 - 1.25), p(25 + 1.25, 23 + 1.25)], fill=SIGNAL)
    # House, M9 23V12l7-4 7 4v11: drawn as a thick polyline with mitred corners.
    draw.line([p(9, 23), p(9, 12), p(16, 8), p(23, 12), p(23, 23)], fill=PAPER, width=stroke, joint="curve")
    # Door, M14 23v-6h4v6.
    draw.rectangle([p(14, 17), p(18, 23)], fill=SIGNAL)


def draw(size: int, *, full_bleed: bool, glyph_share: float) -> Image.Image:
    big = size * SUPERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    canvas = ImageDraw.Draw(image)
    if full_bleed:
        canvas.rectangle([0, 0, big, big], fill=INK)
    else:
        canvas.rounded_rectangle([0, 0, big - 1, big - 1], radius=big * 6 / 32, fill=INK)
    # The house spans x 5.75..26.25 and y 6.6..24.25 of the 32 grid: centre it in glyph_share.
    unit = big * glyph_share / 32
    offset = (big - 32 * unit) / 2
    _house(canvas, unit, offset, offset + unit * 0.6)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icons = {
        "icon-192.png": draw(192, full_bleed=False, glyph_share=1.0),
        "icon-512.png": draw(512, full_bleed=False, glyph_share=1.0),
        "icon-maskable-512.png": draw(512, full_bleed=True, glyph_share=0.62),
        "apple-touch-icon.png": draw(180, full_bleed=True, glyph_share=0.8),
    }
    for name, image in icons.items():
        image.save(OUT / name, optimize=True)
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
