# PDF Chinese Image Translator Skill

Codex skill for translating English PDF files into Simplified Chinese visual PDFs through a whole-page raster workflow.

## Workflow

1. Render selected PDF pages to full-page images.
2. Use the built-in image generation skill to regenerate each whole page as a clean Chinese page image.
3. Normalize generated page dimensions back to the source render dimensions.
4. Bind normalized translated page images into `translated.pdf`.
5. Bind each original page and matching translated page into `bilingual-comparison.pdf`.
6. Audit image dimensions and both PDF page counts.

## Outputs

- `translated.pdf`: Chinese translated pages only.
- `bilingual-comparison.pdf`: original English page and translated Chinese page placed side by side on the same page.

## Dependencies

The helper scripts use Python 3 and Pillow. `prepare_pdf_pages.py` prefers PyMuPDF (`fitz`) for rendering and text extraction. On macOS it can fall back to the bundled Swift/PDFKit renderer plus `pypdf` text extraction.

Typical setup:

```bash
python3 -m pip install pillow pymupdf pypdf
```

## Safety Boundary

This package intentionally does not include sample PDFs, generated images, API keys, tokens, local user paths, or external AI bridge configuration.

The skill is designed to avoid external OCR/translation tools such as Gemini, Ollama, DeepLX, Google Translate, and pdf2zh unless the user explicitly requests a comparison outside this workflow.

## License

MIT. See `LICENSE`.
