# PDF 中文图片翻译 Skill

这是一个给 Codex 使用的 PDF 视觉翻译 skill。它把英文 PDF 按页渲染成图片，然后调用 `gpt-image` / `gpt-image-2` 对整页图片进行中文化重绘，最后把翻译后的页面图片归一化尺寸并合成为 PDF。

## 适用场景

- 英文说明书、手册、表格型 PDF 需要翻译成简体中文。
- 希望保留原 PDF 的版式、图片、图表、页眉页脚和页码。
- 需要同时输出中文 PDF 和英中对照 PDF。

## 工作流程

1. 使用 `prepare_pdf_pages.py` 渲染指定 PDF 页面，并生成每页的 `gpt-image` prompt。
2. 使用 `run_gpt_image_pages.py` 批量调用 `gpt-image`，默认模型为 `gpt-image-2`。
3. 将原始生成图保存到 `translated_pages_raw/page-NNN.png`。
4. 使用 `normalize_page_images.py` 把生成图缩放回原始渲染尺寸。
5. 使用 `make_contact_sheet.py` 生成 QA 联系表，快速检查页面效果。
6. 使用 `merge_page_images_to_pdf.py` 生成中文 PDF：`translated.pdf`。
7. 使用 `build_bilingual_comparison_pdf.py` 生成英中对照 PDF：`bilingual-comparison.pdf`。
8. 使用 `audit_translation_package.py` 检查页数、图片尺寸和 PDF 输出。

## 默认设置

- 默认图片模型：`gpt-image-2`
- 默认图片接口：`https://img.proxy2it.com/v1`
- 默认质量：`high`
- 默认按源页面渲染尺寸传入 `gpt-image --size`，避免落回 `1024x1024` 方图导致比例失真。
- 支持断点续跑：已有 `translated_pages_raw/page-NNN.png` 时会跳过，除非传入 `--force`。

## 快速使用

```bash
python scripts/prepare_pdf_pages.py \
  --pdf "/path/to/source.pdf" \
  --out "/path/to/workdir" \
  --start-page 1 \
  --end-page 5 \
  --dpi 200

python scripts/run_gpt_image_pages.py \
  --workdir "/path/to/workdir" \
  --model gpt-image-2 \
  --base-url "https://img.proxy2it.com/v1" \
  --quality high

python scripts/normalize_page_images.py \
  --image-dir "/path/to/workdir/translated_pages_raw" \
  --manifest "/path/to/workdir/manifest.json" \
  --out-dir "/path/to/workdir/translated_pages"

python scripts/merge_page_images_to_pdf.py \
  --image-dir "/path/to/workdir/translated_pages" \
  --manifest "/path/to/workdir/manifest.json" \
  --out "/path/to/workdir/translated.pdf" \
  --dpi 200

python scripts/build_bilingual_comparison_pdf.py \
  --source-image-dir "/path/to/workdir/pages" \
  --translated-image-dir "/path/to/workdir/translated_pages" \
  --manifest "/path/to/workdir/manifest.json" \
  --out "/path/to/workdir/bilingual-comparison.pdf" \
  --dpi 200
```

## 依赖

建议使用 Python 3.11+，并安装：

```bash
python -m pip install pillow pymupdf pypdf
```

图片生成部分依赖 `gpt-image` skill 或已安装的 `gpt-image` CLI。API Key 通过环境变量 `OPENAI_API_KEY` 读取。

## 输出文件

- `translated.pdf`：仅中文翻译页。
- `bilingual-comparison.pdf`：原英文页和中文翻译页并排对照。
- `qa-contact-sheet.png`：翻译页缩略图联系表。
- `gpt_image_run_log.jsonl`：每页图片生成日志。

## 安全边界

仓库不包含 API Key、令牌、`.env`、本地 PDF、生成图片或任何用户私有文件。默认不使用 `pdf2zh`、Gemini、Google Translate、DeepLX、Ollama 等外部 OCR/翻译链路。

## 许可证

MIT，详见 `LICENSE`。
