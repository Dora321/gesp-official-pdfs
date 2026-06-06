#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import fitz


ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "pdfs"
MARKDOWN_DIR = ROOT / "markdown"
ASSETS_DIR = ROOT / "markdown_assets"
DEFAULT_IMAGE_DPI = 144


CODE_TOKEN_RE = re.compile(
    r"("
    r"#include|using\s+namespace|int\s+main|std::|cout|cin|printf|scanf|return|"
    r"\b(for|while|if|else|switch|case|class|struct|void|long|double|string|vector|"
    r"bool|char|const|auto)\b|"
    r"->|::|==|<=|>=|!=|\+\+|--|&&|\|\||[{};]"
    r")"
)
NUMBERED_CODE_RE = re.compile(r"^\s*\d{1,3}\s{1,4}\S")
NUMBER_ONLY_RE = re.compile(r"^\s*\d{1,3}\s*$")
QUESTION_RE = re.compile(r"^\s*(第\s*\d+\s*题|[A-D]\.|[（(]?[A-D][）).])")


@dataclass(frozen=True)
class PdfMeta:
    year: int | None
    month: int | None
    level: int | None


@dataclass(frozen=True)
class PageRender:
    markdown: str
    has_text: bool
    code_block_count: int


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
    code_block_count: int


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


def title_for_pdf(pdf_path: Path) -> str:
    return pdf_path.stem


def looks_like_code_line(line: str, in_code_block: bool = False) -> bool:
    stripped = line.strip()
    if not stripped:
        return in_code_block
    if QUESTION_RE.match(stripped) and not NUMBERED_CODE_RE.match(line):
        return False
    if NUMBERED_CODE_RE.match(line) and CODE_TOKEN_RE.search(stripped):
        return True
    if in_code_block:
        if NUMBER_ONLY_RE.match(line):
            return True
        if NUMBERED_CODE_RE.match(line):
            return True
        if stripped in {"{", "}", "};", "};"}:
            return True
        if line.startswith((" ", "\t")) and CODE_TOKEN_RE.search(stripped):
            return True
    if stripped.startswith(("#include", "using namespace")):
        return True
    if re.match(r"^\s*(int|void|long|double|bool|char|string|auto|class|struct)\b", line) and CODE_TOKEN_RE.search(stripped):
        return True
    return False


def normalize_code_block(lines: list[str]) -> str:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    nonblank = [line for line in lines if line.strip()]
    if not nonblank:
        return ""
    min_indent = min(len(line) - len(line.lstrip(" ")) for line in nonblank)
    return "\n".join(line[min_indent:] if len(line) >= min_indent else line for line in lines)


def flush_paragraph(output: list[str], paragraph: list[str]) -> None:
    if not paragraph:
        return
    while paragraph and not paragraph[0].strip():
        paragraph.pop(0)
    while paragraph and not paragraph[-1].strip():
        paragraph.pop()
    if paragraph:
        output.extend(paragraph)
        output.append("")
    paragraph.clear()


def flush_code(output: list[str], code_lines: list[str]) -> int:
    code = normalize_code_block(code_lines)
    code_lines.clear()
    if not code:
        return 0
    output.append(fenced(code, "cpp"))
    output.append("")
    return 1


def render_page_content(text: str) -> PageRender:
    text = clean_text(text)
    if not text:
        return PageRender("本页未提取到可用文本，请以页面图为准。", False, 0)

    output: list[str] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    in_code_block = False
    code_block_count = 0

    for line in text.splitlines():
        is_code = looks_like_code_line(line, in_code_block)
        if is_code:
            flush_paragraph(output, paragraph)
            code_lines.append(line)
            in_code_block = True
            continue

        if in_code_block:
            if not line.strip():
                code_lines.append(line)
                continue
            code_block_count += flush_code(output, code_lines)
            in_code_block = False

        paragraph.append(line)

    if in_code_block:
        code_block_count += flush_code(output, code_lines)
    flush_paragraph(output, paragraph)

    rendered = "\n".join(output).rstrip()
    return PageRender(rendered, True, code_block_count)


def convert_pdf(pdf_path: Path, *, image_dpi: int, overwrite_images: bool) -> ConversionRecord:
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    title = title_for_pdf(pdf_path)
    safe_stem = slugify_filename(pdf_path.stem)
    md_path = MARKDOWN_DIR / f"{safe_stem}.md"
    asset_dir = ASSETS_DIR / safe_stem
    asset_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    meta = parse_filename_meta(pdf_path.name)
    matrix = fitz.Matrix(image_dpi / 72.0, image_dpi / 72.0)
    text_pages = 0
    code_blocks = 0
    page_image_paths: list[Path] = []

    parts: list[str] = [
        f"# {title}",
        "",
        f"- 原始 PDF: [pdfs/{pdf_path.name}]({md_link('../pdfs/' + pdf_path.name)})",
        f"- 页数: {doc.page_count}",
        f"- 转换方式: PyMuPDF 文本提取 + 代码片段重排 + 每页 {image_dpi} DPI PNG 页面图",
        f"- PDF SHA-256: `{sha256_file(pdf_path)}`",
        "",
        "> 说明: Markdown 中保留每页页面图作为排版与图形校验；正文按阅读顺序排版，检测到的代码片段会单独渲染为代码块。复杂公式、表格、插图或排版细节请以页面图为准。",
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

        rendered = render_page_content(page.get_text("text", sort=True))
        if rendered.has_text:
            text_pages += 1
        code_blocks += rendered.code_block_count

        rel_image = Path("..") / "markdown_assets" / safe_stem / image_path.name
        parts.extend(
            [
                f"## 第 {page_no} 页",
                "",
                f"![{title} 第 {page_no} 页]({md_link(rel_image.as_posix())})",
                "",
                "### 页面内容",
                "",
                rendered.markdown,
                "",
            ]
        )

    for stale_image in asset_dir.glob("page-*.png"):
        if stale_image not in page_image_paths:
            stale_image.unlink()

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
        code_block_count=code_blocks,
    )


def meta_label(meta: PdfMeta) -> str:
    if meta.year is None or meta.month is None or meta.level is None:
        return "未解析"
    return f"{meta.year} 年 {meta.month} 月 / C++ {meta.level} 级"


def generate_index(records: Iterable[ConversionRecord]) -> None:
    records = sorted(records, key=lambda record: sort_key(record.pdf_path))
    lines: list[str] = [
        "# GESP 真题 Markdown 索引",
        "",
        "本目录按年份、月份、等级列出 `pdfs/` 中每份真题对应的 Markdown 文件。每份 Markdown 都包含原 PDF 链接、逐页截图、可阅读正文和独立渲染的代码片段。",
        "",
        "| 年份 | 月份 | 等级 | Markdown | PDF | 页面图 | 页数 | 代码块 |",
        "| --- | ---: | ---: | --- | --- | --- | ---: | ---: |",
    ]
    for record in records:
        meta = record.meta
        year = str(meta.year) if meta.year is not None else ""
        month = str(meta.month) if meta.month is not None else ""
        level = str(meta.level) if meta.level is not None else ""
        md = f"[{record.title}]({md_link(record.md_path.name)})"
        pdf = f"[PDF]({md_link('../pdfs/' + record.pdf_path.name)})"
        assets = f"[页面图]({md_link('../markdown_assets/' + record.asset_dir.name + '/')})"
        lines.append(
            f"| {year} | {month} | {level} | {md} | {pdf} | {assets} | "
            f"{record.page_count} | {record.code_block_count} |"
        )

    (MARKDOWN_DIR / "INDEX.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def generate_notes(image_dpi: int) -> None:
    content = f"""# 转换说明

## 目标

将 `pdfs/` 目录中的 GESP C++ 真题 PDF 转换为对应的 Markdown 文件，并为每一页导出 PNG 页面图，保证文本可检索、代码可阅读、页面可核验、图形和公式不丢失。

## 输出结构

- `markdown/<试卷名>.md`: 每份 PDF 对应一份 Markdown。
- `markdown_assets/<试卷名>/page-XXX.png`: 每页 PDF 的页面图。
- `markdown/INDEX.md`: Markdown 索引。
- `markdown/CONVERSION_REPORT.md`: 本次转换统计报告。

## 转换方法

脚本: [`scripts/convert_pdfs_to_markdown.py`](../scripts/convert_pdfs_to_markdown.py)

核心流程:

1. 扫描 `pdfs/*.pdf`。
2. 使用 PyMuPDF 打开 PDF。
3. 对每页执行文本提取: `page.get_text("text", sort=True)`。
4. 按题面特征识别代码行，将连续代码片段单独渲染为 `cpp` fenced code block。
5. 对每页渲染 `{image_dpi}` DPI PNG 页面图。
6. 生成包含元信息、页面图、可阅读正文和代码块的 Markdown。

## 质量说明

- Markdown 正文用于搜索、复制和快速阅读。
- 检测到的代码片段会从整页文本中拆出，单独显示为代码块，避免整页 `text` 代码块导致的横向滚动和代码不可见问题。
- 页面图用于保留原始版式、公式、表格、代码缩进、插图和题面排版。
- 如果文本提取与页面图存在差异，以页面图和原始 PDF 为准。
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


def generate_report(records: Iterable[ConversionRecord], image_dpi: int) -> None:
    records = sorted(records, key=lambda record: sort_key(record.pdf_path))
    pdf_count = len(list(PDF_DIR.glob("*.pdf")))
    per_pdf_markdown_count = len(records)
    extra_markdown_count = 3
    total_images = sum(record.image_count for record in records)
    total_pages = sum(record.page_count for record in records)
    full_text_pages = sum(record.text_pages for record in records)
    total_code_blocks = sum(record.code_block_count for record in records)
    missing_markdown = sorted({p.stem for p in PDF_DIR.glob("*.pdf")} - {r.md_path.stem for r in records})

    lines: list[str] = [
        "# 转换报告",
        "",
        f"- 转换日期: {date.today().isoformat()}",
        f"- PDF 数量: {pdf_count}",
        f"- 试卷 Markdown 数量: {per_pdf_markdown_count}",
        f"- 索引/说明/报告 Markdown 数量: {extra_markdown_count}",
        f"- PDF 总页数: {total_pages}",
        f"- 页面图数量: {total_images}",
        f"- 页面图 DPI: {image_dpi}",
        f"- 成功提取文本的页面数: {full_text_pages}",
        f"- 独立渲染代码块数量: {total_code_blocks}",
        f"- 缺失 Markdown: {'无' if not missing_markdown else ', '.join(missing_markdown)}",
        "",
        "## 明细",
        "",
        "| 试卷 | 元信息 | 页数 | 文本页 | 页面图 | 代码块 | Markdown |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]

    for record in records:
        md = f"[{record.md_path.name}]({md_link(record.md_path.name)})"
        lines.append(
            f"| {record.title} | {meta_label(record.meta)} | {record.page_count} | "
            f"{record.text_pages} | {record.image_count} | {record.code_block_count} | {md} |"
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
    parser = argparse.ArgumentParser(description="Convert GESP official PDFs to high-quality Markdown.")
    parser.add_argument("--image-dpi", type=int, default=DEFAULT_IMAGE_DPI, help="PNG render DPI for page images.")
    parser.add_argument("--overwrite-images", action="store_true", help="Regenerate all page images.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = convert_all(image_dpi=args.image_dpi, overwrite_images=args.overwrite_images)
    total_pages = sum(record.page_count for record in records)
    total_code_blocks = sum(record.code_block_count for record in records)
    print(f"Converted {len(records)} PDFs ({total_pages} pages, {total_code_blocks} code blocks) into {MARKDOWN_DIR}")


if __name__ == "__main__":
    main()
