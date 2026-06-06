# GESP Official PDFs and Markdown

This repository stores the official GESP C++ exam PDFs and high-quality Markdown conversions.

## Contents

- `pdfs/`: original PDF files.
- `markdown/`: one Markdown file per PDF, plus index and conversion notes.
- `markdown_assets/`: per-page PNG renders referenced by the Markdown files.
- `scripts/convert_pdfs_to_markdown.py`: reproducible conversion script.

## Current Archive

- PDF files: 92
- Paper Markdown files: 92
- Rendered page images: 961

Start from [`markdown/INDEX.md`](markdown/INDEX.md) to browse all converted papers.

## Rebuild

Run from the repository root:

```bash
py scripts/convert_pdfs_to_markdown.py
```

The script preserves existing page images by default and renders only missing images. Use `--overwrite-images` to regenerate all page images.

## Integrity

Each generated Markdown file records the SHA-256 digest of its source PDF. See [`manifest.csv`](manifest.csv) for the imported PDF manifest.
