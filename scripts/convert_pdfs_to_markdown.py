#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

import fitz


ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "pdfs"
MARKDOWN_DIR = ROOT / "markdown"
ASSETS_DIR = ROOT / "markdown_assets"
DEFAULT_IMAGE_DPI = 144


@dataclass(frozen=True)
class PdfMeta:
    year: int | None
    month: int | None
    level: int | None


@dataclass(frozen=True)
class ConversionRecord:
    pdf_path: Path
    md_path: Path
    asset_dir: Path
    title: str
    meta: PdfMeta
    page_count: int
    image_count: int
    text_pages: int


def slugify_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).strip()
    normalized = normalized.replace("/", "-").replace("\\", "-")
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff+_.()-]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-._")
    return normalized or "document"


def parse_filename_meta(name: str) -> PdfMeta:
    match = re.search(r"(20\d{2})年(\d{1,2})月-C\+\+(\d+)级", name)
    if not match:
        return PdfMeta(None, None, None)
    return PdfMeta(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def sort_key(path: Path) -> tuple[int, int, int, str]:
    meta = parse_filename_meta(path.name)
    return (
        meta.year if meta.year is not None else 9999,
        meta.month if meta.month is not None else 9999,
        meta.level if meta.level is not None else 9999,
        path.name,
    )


def md_link(target: str) -> str:
    return quote(target.replace("\\", "/"), safe="/:+#%?=&,._-()")


def page_image_name(page_no: int) -> str:
    return f"page-{page_no:03d}.png"


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\x00", "").replace("\x0c", "\n")
    lines = [line.rstrip() for line in text.splitlines()]

    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip():
            cleaned.append(line)
            blank_run = 0
        else:
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
    return "\n".join(cleaned).strip()


def fenced(text: str, language: str = "text") -> str:
    longest = 2
    for match in re.finditer(r"~+", text):
        longest = max(longest, len(match.group(0)))
    fence = "~" * (longest + 1)
    return f"{fence}{language}\n{text.rstrip()}\n{fence}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def convert_pdf(pdf_path: Path, *, image_dpi: int, overwrite_images: bool) -> ConversionRecord:
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    title = pdf_path.stem
    safe_stem = slugify_filename(title)
    md_path = MARKDOWN_DIR / f"{safe_stem}.md"
    asset_dir = ASSETS_DIR / safe_stem
    asset_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    meta = parse_filename_meta(pdf_path.name)
    matrix = fitz.Matrix(image_dpi / 72.0, image_dpi / 72.0)
    text_pages = 0
    page_image_paths: list[Path] = []

    parts: list[str] = [
        f"# {title}",
        "",
        f"- 原始 PDF: [pdfs/{pdf_path.name}]({md_link('../pdfs/' + pdf_path.name)})",
        f"- 页数: {doc.page_count}",
        f"- 转换方式: 每页 {image_dpi} DPI 原卷面图片 + 折叠的辅助文本层",
        f"- PDF SHA-256: `{sha256_file(pdf_path)}`",
        "",
        "> 说明: 页面图片是主内容，完整保留原卷面的题干、代码、表格、图形和排版。PDF 文本层可能缺失题目代码，因此提取文本只作为搜索辅助，默认折叠显示。",
        "",
    ]

    for index in range(doc.page_count):
        page_no = index + 1
        page = doc.load_page(index)
        image_path = asset_dir / page_image_name(page_no)
        page_image_paths.append(image_path)

        if overwrite_images or not image_path.exists() or image_path.stat().st_size == 0:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            pix.save(image_path)

        text = clean_text(page.get_text("text", sort=True))
        if text:
            text_pages += 1
        else:
            text = "本页未提取到可用文本，请以页面图片为准。"

        rel_image = Path("..") / "markdown_assets" / safe_stem / image_path.name
        parts.extend(
            [
                f"## 第 {page_no} 页",
                "",
                f"![{title} 第 {page_no} 页]({md_link(rel_image.as_posix())})",
                "",
                "<details>",
                "<summary>提取文本（辅助搜索，可能缺少图片/代码内容）</summary>",
                "",
                fenced(text, "text"),
                "",
                "</details>",
                "",
            ]
        )

    for stale_image in asset_dir.glob("page-*.png"):
        if stale_image not in page_image_paths:
            stale_image.unlink()
    for stale_code_image in asset_dir.glob("code-*.png"):
        stale_code_image.unlink()

    md_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    page_count = doc.page_count
    doc.close()

    return ConversionRecord(
        pdf_path=pdf_path,
        md_path=md_path,
        asset_dir=asset_dir,
        title=title,
        meta=meta,
        page_count=page_count,
        image_count=len(page_image_paths),
        text_pages=text_pages,
    )


def meta_label(meta: PdfMeta) -> str:
    if meta.year is None or meta.month is None or meta.level is None:
        return "未解析"
    return f"{meta.year} 年 {meta.month} 月 / C++ {meta.level} 级"


def generate_index(records: list[ConversionRecord]) -> None:
    records = sorted(records, key=lambda record: sort_key(record.pdf_path))
    lines: list[str] = [
        "# GESP 真题 Markdown 索引",
        "",
        "本目录按年份、月份、等级列出 `pdfs/` 中每份真题对应的 Markdown 文件。Markdown 以原卷面页面图为主，确保题目代码和图形不丢失；提取文本仅作为折叠的搜索辅助。",
        "",
        "| 年份 | 月份 | 等级 | Markdown | PDF | 页面图 | 页数 |",
        "| --- | ---: | ---: | --- | --- | --- | ---: |",
    ]
    for record in records:
        meta = record.meta
        year = str(meta.year) if meta.year is not None else ""
        month = str(meta.month) if meta.month is not None else ""
        level = str(meta.level) if meta.level is not None else ""
        md = f"[{record.title}]({md_link(record.md_path.name)})"
        pdf = f"[PDF]({md_link('../pdfs/' + record.pdf_path.name)})"
        assets = f"[页面图]({md_link('../markdown_assets/' + record.asset_dir.name + '/')})"
        lines.append(f"| {year} | {month} | {level} | {md} | {pdf} | {assets} | {record.page_count} |")

    (MARKDOWN_DIR / "INDEX.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def generate_notes(image_dpi: int) -> None:
    content = f"""# 转换说明

## 目标

将 `pdfs/` 目录中的 GESP C++ 真题 PDF 转换为对应的 Markdown 文件，并保证题目代码、图形、表格和原始排版可见。

## 输出结构

- `markdown/<试卷名>.md`: 每份 PDF 对应一份 Markdown。
- `markdown_assets/<试卷名>/page-XXX.png`: 每页 PDF 的原卷面页面图。
- `markdown/INDEX.md`: Markdown 索引。
- `markdown/CONVERSION_REPORT.md`: 本次转换统计报告。

## 转换方法

脚本: [`scripts/convert_pdfs_to_markdown.py`](../scripts/convert_pdfs_to_markdown.py)

核心流程:

1. 扫描 `pdfs/*.pdf`。
2. 使用 PyMuPDF 打开 PDF。
3. 将每页渲染为 `{image_dpi}` DPI PNG，作为 Markdown 的主内容。
4. 提取 PDF 文本层，放入折叠区作为搜索辅助。

## 质量说明

- 页面图片是主内容，完整保留题目代码、表格、图形、公式和版式。
- PDF 文本层常常缺失代码，尤其是作为图片/矢量对象嵌入的代码块；因此提取文本不再作为主阅读内容。
- Markdown 中的折叠文本仅用于搜索、复制和粗略定位，若与页面图不一致，以页面图和原始 PDF 为准。
- 默认复用已存在的页面图，只在页面图缺失或指定 `--overwrite-images` 时重新渲染。

## 复现

```bash
py scripts/convert_pdfs_to_markdown.py
```

如需强制重新生成所有页面图:

```bash
py scripts/convert_pdfs_to_markdown.py --overwrite-images
```
"""
    (MARKDOWN_DIR / "CONVERSION_NOTES.md").write_text(content, encoding="utf-8")


def generate_report(records: list[ConversionRecord], image_dpi: int) -> None:
    records = sorted(records, key=lambda record: sort_key(record.pdf_path))
    pdf_count = len(list(PDF_DIR.glob("*.pdf")))
    total_images = sum(record.image_count for record in records)
    total_pages = sum(record.page_count for record in records)
    text_pages = sum(record.text_pages for record in records)
    missing_markdown = sorted({p.stem for p in PDF_DIR.glob("*.pdf")} - {r.md_path.stem for r in records})

    lines: list[str] = [
        "# 转换报告",
        "",
        f"- 转换日期: {date.today().isoformat()}",
        f"- PDF 数量: {pdf_count}",
        f"- 试卷 Markdown 数量: {len(records)}",
        f"- 索引/说明/报告 Markdown 数量: 3",
        f"- PDF 总页数: {total_pages}",
        f"- 页面图数量: {total_images}",
        f"- 页面图 DPI: {image_dpi}",
        f"- 成功提取文本的页面数: {text_pages}",
        f"- 缺失 Markdown: {'无' if not missing_markdown else ', '.join(missing_markdown)}",
        "",
        "## 明细",
        "",
        "| 试卷 | 元信息 | 页数 | 文本页 | 页面图 | Markdown |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]

    for record in records:
        md = f"[{record.md_path.name}]({md_link(record.md_path.name)})"
        lines.append(
            f"| {record.title} | {meta_label(record.meta)} | {record.page_count} | "
            f"{record.text_pages} | {record.image_count} | {md} |"
        )

    (MARKDOWN_DIR / "CONVERSION_REPORT.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def convert_all(*, image_dpi: int, overwrite_images: bool) -> list[ConversionRecord]:
    pdf_paths = sorted(PDF_DIR.glob("*.pdf"), key=sort_key)
    if not pdf_paths:
        raise SystemExit(f"No PDF files found in {PDF_DIR}")
    records = [
        convert_pdf(pdf_path, image_dpi=image_dpi, overwrite_images=overwrite_images)
        for pdf_path in pdf_paths
    ]
    generate_index(records)
    generate_notes(image_dpi)
    generate_report(records, image_dpi)
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert GESP official PDFs to Markdown.")
    parser.add_argument("--image-dpi", type=int, default=DEFAULT_IMAGE_DPI, help="PNG render DPI for page images.")
    parser.add_argument("--overwrite-images", action="store_true", help="Regenerate all page images.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = convert_all(image_dpi=args.image_dpi, overwrite_images=args.overwrite_images)
    total_pages = sum(record.page_count for record in records)
    print(f"Converted {len(records)} PDFs ({total_pages} pages) into {MARKDOWN_DIR}")


if __name__ == "__main__":
    main()
