---
name: pdf-zh-image-translator
description: Translate English PDF files into Simplified Chinese visual PDFs by rendering pages to images, regenerating each page with imagegen, normalizing page dimensions, and merging the results back into a PDF. Use when Codex receives an English PDF and the user asks for a Chinese PDF version, page-image translation, PDF localization, or a translated PDF assembled from whole-page image edits.
---

# PDF Chinese Image Translator

## Core idea

Use a whole-page raster workflow. Render each selected PDF page to an image, use `$imagegen` in `text-localization` edit mode to regenerate the entire page as a clean Simplified Chinese page image, normalize the generated page image back to the original rendered page dimensions, then merge the normalized page images into one PDF. Keep the original PDF untouched.

This skill depends on `$imagegen` for the visual translation/edit pass. The bundled scripts handle deterministic preparation, page manifests, PDF assembly, and audits; they do not call imagegen themselves.

Important distinction: the render step is required PDF plumbing, not the translation style. `imagegen` cannot directly edit a multi-page PDF, so every run must first render PDF pages into full-page images and later normalize/merge the generated images. Do not describe or use region overlay / paint-over text replacement as the default workflow.

Do not substitute another PDF translation pipeline for the imagegen pass. In particular, do not use `pdf2zh`, Google Translate, Gemini, DeepLX bridges, Ollama, or other text-translation/layout tools to produce the deliverable unless the user explicitly asks to compare against a non-imagegen pipeline. The deliverable for this skill is generated page images from whole-page imagegen, followed by deterministic dimension normalization and PDF binding.

Do not call external AI tools for OCR or translation support either. Avoid shelling out to `gemini`, `ask-gemini`, `ollama`, translation CLIs, hosted translation APIs, or ad hoc AI bridge servers to create page copy. ChatGPT/Codex already has enough multimodal OCR and translation ability for prompt support. Allowed AI components are limited to:

- the current Codex/ChatGPT model reading rendered page images and drafting page-level OCR/translation support;
- Codex child agents, when the user has authorized subagents, for parallel page OCR/translation support;
- the built-in `$imagegen` skill for the final whole-page Chinese page image generation.

Child agents are not an alternate toolchain. They may only inspect assigned rendered page images and return page-level support text for the main agent to put into the imagegen prompt. They must not call Gemini, Ollama, pdf2zh, DeepLX, Google Translate, or any other external AI/OCR/translation service.

## Flow At A Glance

1. Decide the page scope.
   - Full PDF: translate all pages in order.
   - Sample: translate only the requested pages.
   - Review pass: translate a few representative pages first.
2. Render the selected pages to PNG.
3. Read each page image and draft a page prompt from the image plus extracted text.
4. Run whole-page `imagegen` on each page.
5. Normalize the generated pages back to the source render size.
6. Merge the normalized pages into the translated-only PDF.
7. Build a bilingual comparison PDF by placing each original page image and the matching translated page image on the same PDF page.
8. Audit page count, dimensions, and final PDF readability.

## Good Tuning Points

- Page selection: choose representative pages when the user only wants a sample.
- Prompt length: shorten prompts for dense tables and pages with many repeated labels.
- Source-text extraction: keep only the text needed to anchor layout and terminology.
- Retry strategy: retry once with a stricter prompt before escalating to manual review.
- Output checks: verify the final PDF only after normalized images are in place.
- Delivery outputs: always produce both a translated-only PDF and a bilingual comparison PDF unless the user explicitly asks for only one.

## Hard Rules

### Page Type Rules

- Treat each page as one of three types: `toc`, `table_dense`, or `general`.
- Use the `toc` rule for table-of-contents pages, index pages, and section lists.
- Use the `table_dense` rule for pages with heavy tables, parts lists, or repeated item rows.
- Use the `general` rule for everything else.
- Do not use one prompt shape for all pages when the page type is obvious.

### Extraction Rules

- Keep extracted source text under 2,500 characters for `toc` pages.
- Keep extracted source text under 1,500 characters for `table_dense` pages.
- Keep extracted source text under 4,000 characters for `general` pages.
- Prefer headings, labels, and row headers over full body text when the page is dense.
- Omit repeated lines, boilerplate footers, and page-number-only fragments unless they affect layout.
- If extracted text exceeds the limit, trim from the bottom first and preserve headings, key labels, and unique terminology.

### Retry Rules

- Allow at most one automatic retry per page.
- Retry only when the first page image shows one of these failures: obvious untranslated English, broken table alignment, missing major labels, or unreadable Chinese.
- On retry, shorten the prompt and remove non-essential extracted text.
- If the second pass still fails, mark the page as `manual_retry_needed` and continue with the remaining pages.

### Prompt Shape Rules

- `toc` prompt shape:
  - preserve section hierarchy
  - keep dots leaders and page numbers aligned
  - keep the page looking sparse and stable
- `table_dense` prompt shape:
  - preserve column order, row order, item codes, units, and numeric values
  - avoid long prose translation
  - favor compact Chinese labels that fit into existing cells
- `general` prompt shape:
  - preserve headings, captions, figures, callouts, and page furniture
  - keep the page image as the visual source of truth
- Never add decorative text, explanatory notes, or translated summaries outside the page content itself.

### Delivery Rules

- Always deliver two PDFs:
  - `translated.pdf`: Chinese translated pages only.
  - `bilingual-comparison.pdf`: original English page and translated Chinese page combined onto the same page for side-by-side comparison.
- In the bilingual comparison PDF, pair pages by the same `page-NNN` number.
- Preserve the page order from `manifest.json`.
- Do not build the bilingual comparison from raw imagegen outputs; use normalized translated pages so dimensions are stable.
- If any original or translated page image is missing, fail the bilingual build and report the missing page.

## Workflow

1. Create a work directory for the job, usually next to the source PDF or under a user-named output folder.
2. Choose the page set first.
   - If the user specifies pages, use exactly those pages.
   - If the user asks for a sample, pick distinct pages from the requested range.
   - If the user asks for the whole PDF, process all pages in order.
3. Prepare page images and prompts:
   ```bash
   SKILL_DIR="/path/to/pdf-zh-image-translator"
   python "$SKILL_DIR/scripts/prepare_pdf_pages.py" \
     --pdf "/path/to/source.pdf" \
     --out "/path/to/workdir" \
     --start-page 1 \
     --end-page 5 \
     --dpi 200
   ```
4. For each prepared page, inspect `pages/page-NNN.png` with `view_image`, then invoke `$imagegen` built-in edit mode using the corresponding `prompts/page-NNN.txt`.
5. Save each final whole-page imagegen output as `translated_pages_raw/page-NNN.png`. Use exactly the same page number in the filename. Do not overwrite original rendered pages.
6. Normalize the generated page images back to the manifest dimensions:
   ```bash
   SKILL_DIR="/path/to/pdf-zh-image-translator"
   python "$SKILL_DIR/scripts/normalize_page_images.py" \
     --image-dir "/path/to/workdir/translated_pages_raw" \
     --manifest "/path/to/workdir/manifest.json" \
     --out-dir "/path/to/workdir/translated_pages"
   ```
7. Merge normalized translated page images into the Chinese-only PDF:
   ```bash
   SKILL_DIR="/path/to/pdf-zh-image-translator"
   python "$SKILL_DIR/scripts/merge_page_images_to_pdf.py" \
     --image-dir "/path/to/workdir/translated_pages" \
     --manifest "/path/to/workdir/manifest.json" \
     --out "/path/to/workdir/translated.pdf" \
     --dpi 200
   ```
8. Build the bilingual comparison PDF:
   ```bash
   SKILL_DIR="/path/to/pdf-zh-image-translator"
   python "$SKILL_DIR/scripts/build_bilingual_comparison_pdf.py" \
     --source-image-dir "/path/to/workdir/pages" \
     --translated-image-dir "/path/to/workdir/translated_pages" \
     --manifest "/path/to/workdir/manifest.json" \
     --out "/path/to/workdir/bilingual-comparison.pdf" \
     --dpi 200
   ```
9. Audit the package:
   ```bash
   SKILL_DIR="/path/to/pdf-zh-image-translator"
   python "$SKILL_DIR/scripts/audit_translation_package.py" \
     --manifest "/path/to/workdir/manifest.json" \
     --translated-dir "/path/to/workdir/translated_pages" \
     --translated-pdf "/path/to/workdir/translated.pdf" \
     --bilingual-pdf "/path/to/workdir/bilingual-comparison.pdf"
   ```

## Imagegen Pass

Use the page image as a whole-page edit target, not as loose inspiration and not as a region-painting task. Keep the prompt strict and short enough that the page text remains the source of truth:

```text
Use case: text-localization
Asset type: translated PDF page raster
Primary request: Regenerate this entire PDF page as a clean Simplified Chinese version.
Input image: the displayed page image is the edit target.
Source-of-truth text: use the extracted text list in the prompt when present.
Constraints: preserve original composition, backgrounds, photos, charts, line art, colors, spacing, headings, captions, bullets, tables, page numbers, logos, and all non-text visual elements. Replace English text with Simplified Chinese while naturally re-typesetting it into the original layout. Keep numerals, formulas, citations, URLs, brand names, product names, and proper nouns unless a standard Chinese rendering is obvious. Fit Chinese text into the original text areas; reduce font size only as needed. Do not add summaries, watermarks, new labels, or decorative elements.
Avoid: overlay rectangles, painted fill boxes, smudged patches, blurry text, invented data, altered charts, changed photos, missing footers, extra commentary, mixed English/Chinese where a clean Chinese translation is possible.
```

Always try a whole-page imagegen pass first and treat it as the preferred output style. If the generated page changes pixel dimensions, do not repair it with painted regions; run `normalize_page_images.py` to scale the whole page back to the original dimensions before merging.

For dense pages:

- Keep the prompt anchored on the page image, not on long rewritten prose.
- Prefer a concise extracted-text list over a full transcription dump.
- Preserve numbers, units, formulas, part IDs, URLs, and proper nouns.
- If a page garbles on the first try, retry once with a shorter source-text section and a stricter prompt.
- If it still garbles, mark the page for manual retry instead of switching workflows.

If structured PDF text extraction returns zero blocks, do not switch tools. Use the rendered page image as the primary source, and optionally add plain text, word-mode extraction, or OCR text into the imagegen prompt as translation support. Empty or partial extracted text is a prompt-quality issue, not permission to replace the workflow with `pdf2zh` or an external translation model.

If the page is table-heavy, diagram-heavy, or otherwise dense, prefer this order:

1. Keep the page prompt shorter.
2. Preserve only the terms that matter most.
3. Let the layout come from the reference image, not from a long textual rewrite.
4. Retry once if the first pass loses column alignment or overflows a table cell.

For OCR/translation support on image-only or poorly encoded PDFs:

1. First use the current Codex/ChatGPT visual reading ability on `pages/page-NNN.png`.
2. If the user has authorized subagents and the page range is large, delegate page groups to Codex child agents. Give each child agent only rendered page images and ask for a compact page brief: visible English OCR, Simplified Chinese translation, terms to preserve, and layout notes. Tell child agents not to call external AI tools or create final images/PDFs.
3. Save or paste each page brief into the corresponding imagegen prompt. The brief is support material; the final translated page still comes from whole-page imagegen.

Recommended child-agent brief format:

```text
Page: <number>
OCR text: <visible English text, in reading order>
Chinese translation: <faithful Simplified Chinese, concise enough to fit the page>
Preserve: <proper nouns, product names, URLs, numbers, formulas>
Layout notes: <headings, tables, callouts, footer/header, dense areas>
Warnings: <uncertain OCR or text that needs visual review>
```

Do not use region overlay, paint-over, background fill boxes, or clone-stamp style text replacement as the default workflow. The user's preferred look is a clean full-page imagegen regeneration followed by deterministic size correction and PDF binding.

When reporting progress to the user, call script steps "PDF page rendering," "dimension normalization," and "PDF binding." Do not call them a script-based translation route, because the translation image is produced by whole-page imagegen.

## Quality Gates

- The translated page count must match the requested page range.
- Normalized page image dimensions must match `manifest.json`.
- Non-text content must remain visually unchanged.
- Charts, figure labels, table values, citations, and page numbers must remain correct.
- Output PDF must open and have the expected number of pages.
- The bilingual comparison PDF must open and have the expected number of pages.
- Report the work directory, raw imagegen page directory, normalized translated page directory, translated-only PDF path, bilingual comparison PDF path, and any pages that need manual retry.

## Script Notes

- `prepare_pdf_pages.py` prefers PyMuPDF (`fitz`) when available. On macOS, it can fall back to the bundled Swift/PDFKit renderer plus `pypdf` text extraction.
- `normalize_page_images.py` resizes whole-page imagegen outputs back to the original rendered dimensions from `manifest.json`.
- `merge_page_images_to_pdf.py` uses Pillow to bind normalized page images into a PDF.
- `build_bilingual_comparison_pdf.py` places each original rendered page and translated page side by side on one PDF page.
- `audit_translation_package.py` checks image count, dimensions, translated PDF page count, and bilingual PDF page count when `pypdf` is available.
