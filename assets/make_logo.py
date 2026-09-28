"""Generate the Detaggarr logo (PNG + multi-size ICO). Requires Pillow."""

import math
import os

from PIL import Image, ImageDraw

S = 1024  # master canvas size; everything is downsampled from here
HERE = os.path.dirname(os.path.abspath(__file__))

BG_TOP, BG_BOTTOM = (38, 46, 66), (20, 24, 36)
TAG_A, TAG_B = (53, 197, 244), (255, 194, 48)  # Sonarr cyan -> Radarr gold
BADGE = (229, 72, 77)


def vertical_gradient(size, top, bottom):
    grad = Image.new("RGB", (1, size[1]))
    for y in range(size[1]):
        t = y / (size[1] - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return grad.resize(size)


def diagonal_gradient(size, a, b):
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x + (h - y)) / (w + h)
            px[x, y] = tuple(round(c1 + (c2 - c1) * t) for c1, c2 in zip(a, b))
    return img


def rotate(points, center, degrees):
    cx, cy = center
    r = math.radians(degrees)
    c, s = math.cos(r), math.sin(r)
    return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in points]


def build():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Rounded-square background
    bg_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(bg_mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=220, fill=255)
    img.paste(vertical_gradient((S, S), BG_TOP, BG_BOTTOM), (0, 0), bg_mask)

    # Tag: rectangle with a pointed end, rotated to point up-right
    center, angle = (500, 500), -40
    body = [(200, 330), (600, 330), (790, 500), (600, 670), (200, 670)]
    body = rotate(body, center, angle)
    hole = rotate([(655, 500)], center, angle)[0]

    tag_mask = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(tag_mask)
    d.polygon(body, fill=255)
    d.line(body + [body[0]], fill=255, width=70, joint="curve")  # rounds the corners
    for x, y in body:
        d.ellipse((x - 35, y - 35, x + 35, y + 35), fill=255)
    d.ellipse((hole[0] - 44, hole[1] - 44, hole[0] + 44, hole[1] + 44), fill=0)
    img.paste(diagonal_gradient((S, S), TAG_A, TAG_B), (0, 0), tag_mask)

    # Red "remove" badge, separated from the tag by a background-coloured ring
    bx, by, r, ring = 735, 735, 175, 34
    d = ImageDraw.Draw(img)
    d.ellipse((bx - r - ring, by - r - ring, bx + r + ring, by + r + ring), fill=BG_BOTTOM)
    d.ellipse((bx - r, by - r, bx + r, by + r), fill=BADGE)
    d.rounded_rectangle((bx - 100, by - 28, bx + 100, by + 28), radius=28, fill="white")

    # Keep the badge ring inside the rounded-square silhouette
    alpha = Image.composite(img.getchannel("A"), Image.new("L", (S, S), 0), bg_mask)
    img.putalpha(alpha)
    return img


def main():
    img = build()
    img.resize((512, 512), Image.LANCZOS).save(os.path.join(HERE, "logo.png"))
    img.resize((256, 256), Image.LANCZOS).save(
        os.path.join(HERE, "detaggarr.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("Wrote logo.png and detaggarr.ico")


if __name__ == "__main__":
    main()
