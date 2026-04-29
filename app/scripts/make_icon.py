from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


def _draw_android_style_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (8, 10, 18, 255))
    d = ImageDraw.Draw(img)

    # Subtle vignette
    vignette = Image.new("L", (size, size), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse(
        (int(size * -0.2), int(size * -0.2), int(size * 1.2), int(size * 1.2)),
        fill=255,
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=size * 0.12))
    img.putalpha(ImageChops.screen(img.split()[-1], vignette))  # type: ignore[name-defined]

    # Connor-inspired (not copied): clean blue triangle + ring, minimal HUD feel.
    cx = cy = size // 2
    ring_r = int(size * 0.34)
    ring_w = max(2, int(size * 0.06))
    blue = (66, 165, 255, 255)
    blue_dim = (66, 165, 255, 110)

    # Glow
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse(
        (cx - ring_r - ring_w, cy - ring_r - ring_w, cx + ring_r + ring_w, cy + ring_r + ring_w),
        outline=blue_dim,
        width=ring_w * 2,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size * 0.05))
    img = Image.alpha_composite(img, glow)

    d = ImageDraw.Draw(img)
    d.ellipse(
        (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
        outline=blue,
        width=ring_w,
    )

    # Triangular mark
    tri_h = int(size * 0.30)
    tri_w = int(size * 0.26)
    top = (cx, cy - int(size * 0.06))
    left = (cx - tri_w // 2, cy + int(size * 0.08) + tri_h // 2)
    right = (cx + tri_w // 2, cy + int(size * 0.08) + tri_h // 2)
    tri = [top, left, right]

    tri_fill = (11, 18, 34, 230)
    d.polygon(tri, fill=tri_fill)
    d.line([top, left], fill=blue, width=max(1, ring_w // 2))
    d.line([left, right], fill=blue, width=max(1, ring_w // 2))
    d.line([right, top], fill=blue, width=max(1, ring_w // 2))

    # Small LED dot
    led_r = max(2, int(size * 0.018))
    led = (cx + int(size * 0.18), cy - int(size * 0.12))
    d.ellipse((led[0] - led_r, led[1] - led_r, led[0] + led_r, led[1] + led_r), fill=blue)

    # Tiny grid accents
    grid_color = (255, 255, 255, 20)
    step = max(8, int(size * 0.08))
    for x in range(step, size, step):
        d.line([(x, 0), (x, size)], fill=grid_color, width=1)
    for y in range(step, size, step):
        d.line([(0, y), (size, y)], fill=grid_color, width=1)

    return img


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--png", required=True, help="Path to write PNG.")
    parser.add_argument("--ico", required=True, help="Path to write ICO.")
    args = parser.parse_args()

    png_path = Path(args.png)
    ico_path = Path(args.ico)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    ico_path.parent.mkdir(parents=True, exist_ok=True)

    base = _draw_android_style_icon(512)
    base.save(png_path, format="PNG")

    # Multi-size ICO for Windows shortcuts
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icons = [base.resize(s, Image.Resampling.LANCZOS) for s in sizes]
    icons[0].save(ico_path, format="ICO", sizes=sizes)


if __name__ == "__main__":
    main()
