#!/usr/bin/env python3
"""Render selected PDF pages and prepare imagegen page prompts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from textwrap import shorten


def load_fitz():
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        return None
    return fitz


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path, help="Source PDF path")
    parser.add_argument("--out", required=True, type=Path, help="Output work directory")
    parser.add_argument("--start-page", type=int, default=1, help="1-based inclusive start page")
    parser.add_argument("--end-page", type=int, help="1-based inclusive end page")
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI")
    parser.add_argument(
        "--max-prompt-text-chars",
        type=int,
        default=9000,
        help="Maximum extracted text characters embedded in each imagegen prompt",
    )
    return parser.parse_args()


def clean_text(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def extract_text_blocks_fitz(page, scale: float) -> list[dict]:
    data = page.get_text("dict")
    blocks: list[dict] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        font_sizes = []
        for line in block.get("lines", []):
            line_text = ""
            for span in line.get("spans", []):
                text = span.get("text", "")
                if text:
                    line_text += text
                    if span.get("size"):
                        font_sizes.append(float(span["size"]))
            line_text = clean_text(line_text)
            if line_text:
                lines.append(line_text)
        text = "\n".join(lines).strip()
        if not text:
            continue
        bbox = [float(v) for v in block.get("bbox", [0, 0, 0, 0])]
        blocks.append(
            {
                "bbox_pt": [round(v, 2) for v in bbox],
                "bbox_px": [round(v * scale) for v in bbox],
                "avg_font_size_pt": round(sum(font_sizes) / len(font_sizes), 2) if font_sizes else None,
                "text": text,
            }
        )
    return blocks


def extract_text_blocks_pypdf(source_pdf: Path, start_page: int, end_page: int) -> tuple[int, dict[int, dict]]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise SystemExit(
            "PyMuPDF is unavailable and pypdf could not be imported for fallback text extraction."
        ) from exc

    reader = PdfReader(str(source_pdf))
    page_count = len(reader.pages)
    result: dict[int, dict] = {}
    for page_number in range(start_page, min(end_page, page_count) + 1):
        page = reader.pages[page_number - 1]
        text = clean_text(page.extract_text() or "")
        width_pt = float(page.mediabox.width)
        height_pt = float(page.mediabox.height)
        blocks = []
        if text:
            blocks.append(
                {
                    "bbox_pt": None,
                    "bbox_px": None,
                    "avg_font_size_pt": None,
                    "text": text,
                }
            )
        result[page_number] = {
            "width_pt": round(width_pt, 2),
            "height_pt": round(height_pt, 2),
            "text_blocks": blocks,
        }
    return page_count, result


def render_pages_with_swift(source_pdf: Path, pages_dir: Path, start_page: int, end_page: int, dpi: int) -> None:
    swift_script = Path(__file__).with_name("render_pdf_pages_macos.swift")
    if not swift_script.exists():
        raise SystemExit(f"macOS fallback renderer missing: {swift_script}")
    command = [
        "swift",
        str(swift_script),
        "--pdf",
        str(source_pdf),
        "--out-dir",
        str(pages_dir),
        "--start-page",
        str(start_page),
        "--end-page",
        str(end_page),
        "--dpi",
        str(dpi),
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode != 0:
        raise SystemExit(
            "Swift/PDFKit fallback renderer failed.\n"
            f"Command: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except Exception as exc:
        raise SystemExit("Pillow is required to inspect fallback-rendered image dimensions.") from exc
    with Image.open(path) as image:
        return image.size


def prompt_for_page(page_number: int, blocks: list[dict], max_chars: int) -> str:
    block_lines = []
    used = 0
    for idx, block in enumerate(blocks, start=1):
        text = block["text"]
        bbox = block.get("bbox_px")
        line = f"{idx}. bbox_px={bbox} text={text}"
        if used + len(line) > max_chars:
            remaining = len(blocks) - idx + 1
            block_lines.append(f"... {remaining} additional text blocks omitted; inspect text/page-{page_number:03d}.json if needed.")
            break
        block_lines.append(line)
        used += len(line)

    extracted = "\n".join(block_lines) if block_lines else "(No embedded text was extracted. Translate visible page text from the image.)"
    return f"""Use case: text-localization
Asset type: translated PDF page raster
Primary request: Translate all visible English text on PDF page {page_number} into accurate Simplified Chinese.
Input image: the displayed page image is the edit target.
Source-of-truth text extracted from the PDF:
{extracted}

Constraints:
- Preserve the original page size, layout, margins, photos, diagrams, charts, line art, colors, background, and visual hierarchy.
- Replace only English text with Simplified Chinese. Keep numerals, equations, citations, URLs, page numbers, dataset values, and proper nouns unless a standard Chinese rendering is obvious.
- Fit the Chinese translation inside the original text areas. Use similar weight, alignment, and spacing; reduce font size only when necessary.
- Do not add explanations, summaries, watermarks, new decorative elements, or extra labels.
- Keep all non-text visual content unchanged.
Avoid: blurry text, garbled Chinese characters, invented data, altered charts, changed images, missing headers/footers, or leaving obvious English text untranslated.
"""


def main() -> int:
    args = parse_args()
    fitz = load_fitz()

    source_pdf = args.pdf.expanduser().resolve()
    if not source_pdf.exists():
        raise SystemExit(f"PDF not found: {source_pdf}")
    if args.start_page < 1:
        raise SystemExit("--start-page must be >= 1")
    if args.end_page is not None and args.end_page < args.start_page:
        raise SystemExit("--end-page must be >= --start-page")
    if args.dpi < 72:
        raise SystemExit("--dpi must be at least 72")

    out_dir = args.out.expanduser().resolve()
    pages_dir = out_dir / "pages"
    text_dir = out_dir / "text"
    prompt_dir = out_dir / "prompts"
    translated_dir = out_dir / "translated_pages"
    for directory in (pages_dir, text_dir, prompt_dir, translated_dir):
        directory.mkdir(parents=True, exist_ok=True)

    scale = args.dpi / 72.0
    manifest_pages = []

    if fitz is not None:
        doc = fitz.open(source_pdf)
        page_count = doc.page_count
        end_page = args.end_page or page_count
        end_page = min(end_page, page_count)
        if args.start_page > page_count:
            raise SystemExit(f"--start-page {args.start_page} exceeds PDF page count {page_count}")
        matrix = fitz.Matrix(scale, scale)

        for page_number in range(args.start_page, end_page + 1):
            page = doc.load_page(page_number - 1)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image_path = pages_dir / f"page-{page_number:03d}.png"
            text_path = text_dir / f"page-{page_number:03d}.json"
            prompt_path = prompt_dir / f"page-{page_number:03d}.txt"
            pix.save(image_path)

            blocks = extract_text_blocks_fitz(page, scale)
            text_payload = {
                "page_number": page_number,
                "width_pt": round(page.rect.width, 2),
                "height_pt": round(page.rect.height, 2),
                "render_width_px": pix.width,
                "render_height_px": pix.height,
                "text_blocks": blocks,
                "text_preview": shorten(" ".join(block["text"] for block in blocks), width=500, placeholder=" ..."),
            }
            text_path.write_text(json.dumps(text_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            prompt_path.write_text(prompt_for_page(page_number, blocks, args.max_prompt_text_chars), encoding="utf-8")

            manifest_pages.append(
                {
                    "page_number": page_number,
                    "width_pt": round(page.rect.width, 2),
                    "height_pt": round(page.rect.height, 2),
                    "render_width_px": pix.width,
                    "render_height_px": pix.height,
                    "image_path": str(image_path),
                    "text_json_path": str(text_path),
                    "prompt_path": str(prompt_path),
                    "expected_translated_image_path": str(translated_dir / f"page-{page_number:03d}.png"),
                    "text_block_count": len(blocks),
                }
            )
    else:
        fallback_end = args.end_page or 999999
        page_count, text_by_page = extract_text_blocks_pypdf(source_pdf, args.start_page, fallback_end)
        end_page = min(fallback_end, page_count)
        if args.start_page > page_count:
            raise SystemExit(f"--start-page {args.start_page} exceeds PDF page count {page_count}")
        render_pages_with_swift(source_pdf, pages_dir, args.start_page, end_page, args.dpi)

        for page_number in range(args.start_page, end_page + 1):
            image_path = pages_dir / f"page-{page_number:03d}.png"
            if not image_path.exists():
                raise SystemExit(f"Fallback renderer did not create expected page image: {image_path}")
            width_px, height_px = image_size(image_path)
            text_path = text_dir / f"page-{page_number:03d}.json"
            prompt_path = prompt_dir / f"page-{page_number:03d}.txt"
            page_text = text_by_page.get(page_number, {})
            blocks = page_text.get("text_blocks", [])
            text_payload = {
                "page_number": page_number,
                "width_pt": page_text.get("width_pt"),
                "height_pt": page_text.get("height_pt"),
                "render_width_px": width_px,
                "render_height_px": height_px,
                "text_blocks": blocks,
                "text_preview": shorten(" ".join(block["text"] for block in blocks), width=500, placeholder=" ..."),
                "renderer": "swift-pdfkit-fallback",
            }
            text_path.write_text(json.dumps(text_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            prompt_path.write_text(prompt_for_page(page_number, blocks, args.max_prompt_text_chars), encoding="utf-8")
            manifest_pages.append(
                {
                    "page_number": page_number,
                    "width_pt": page_text.get("width_pt"),
                    "height_pt": page_text.get("height_pt"),
                    "render_width_px": width_px,
                    "render_height_px": height_px,
                    "image_path": str(image_path),
                    "text_json_path": str(text_path),
                    "prompt_path": str(prompt_path),
                    "expected_translated_image_path": str(translated_dir / f"page-{page_number:03d}.png"),
                    "text_block_count": len(blocks),
                    "renderer": "swift-pdfkit-fallback",
                }
            )

    manifest = {
        "source_pdf": str(source_pdf),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "dpi": args.dpi,
        "pdf_page_count": page_count,
        "start_page": args.start_page,
        "end_page": end_page,
        "prepared_page_count": len(manifest_pages),
        "renderer": "pymupdf" if fitz is not None else "swift-pdfkit-fallback",
        "pages_dir": str(pages_dir),
        "translated_pages_dir": str(translated_dir),
        "prompts_dir": str(prompt_dir),
        "text_dir": str(text_dir),
        "pages": manifest_pages,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Prepared {len(manifest_pages)} page(s)")
    print(f"Manifest: {manifest_path}")
    print(f"Rendered pages: {pages_dir}")
    print(f"Imagegen prompts: {prompt_dir}")
    print(f"Translated output target: {translated_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
