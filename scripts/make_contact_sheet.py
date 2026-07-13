#!/usr/bin/env python3
"""Create a labeled contact sheet for translated page image QA."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", required=True, type=Path, help="Directory containing page-NNN images")
    parser.add_argument("--manifest", required=True, type=Path, help="Manifest created by prepare_pdf_pages.py")
    parser.add_argument("--out", required=True, type=Path, help="Output PNG contact sheet")
    parser.add_argument("--columns", type=int, default=3, help="Number of columns")
    parser.add_argument("--thumb-width", type=int, default=360, help="Thumbnail width in pixels")
    return parser.parse_args()


def page_image_path(image_dir: Path, page_number: int) -> Path:
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = image_dir / f"page-{page_number:03d}{suffix}"
        if candidate.exists():
            return candidate
    return image_dir / f"page-{page_number:03d}.png"


def main() -> int:
    args = parse_args()
    image_dir = args.image_dir.expanduser().resolve()
    manifest = json.loads(args.manifest.expanduser().resolve().read_text(encoding="utf-8"))
    out_path = args.out.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pages = manifest.get("pages", [])
    if not pages:
        raise SystemExit("Manifest has no pages.")
    if args.columns < 1:
        raise SystemExit("--columns must be >= 1")

    font = ImageFont.load_default()
    padding = 16
    label_height = 24
    cells = []
    max_cell_height = 0

    for page in pages:
        page_number = int(page["page_number"])
        path = page_image_path(image_dir, page_number)
        if not path.exists():
            raise SystemExit(f"Missing page image for contact sheet: {path}")
        with Image.open(path) as image:
            image = image.convert("RGB")
            ratio = args.thumb_width / image.width
            thumb_height = max(1, round(image.height * ratio))
            thumb = image.resize((args.thumb_width, thumb_height), Image.Resampling.LANCZOS)
        page_type = page.get("page_type", "unknown")
        label = f"page {page_number:03d} | {page_type}"
        cells.append((label, thumb))
        max_cell_height = max(max_cell_height, label_height + thumb.height)

    rows = math.ceil(len(cells) / args.columns)
    sheet_width = padding + args.columns * (args.thumb_width + padding)
    sheet_height = padding + rows * (max_cell_height + padding)
    sheet = Image.new("RGB", (sheet_width, sheet_height), "white")
    draw = ImageDraw.Draw(sheet)

    for index, (label, thumb) in enumerate(cells):
        row = index // args.columns
        col = index % args.columns
        x = padding + col * (args.thumb_width + padding)
        y = padding + row * (max_cell_height + padding)
        draw.text((x, y), label, fill=(20, 20, 20), font=font)
        sheet.paste(thumb, (x, y + label_height))

    sheet.save(out_path)
    print(f"Contact sheet: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
