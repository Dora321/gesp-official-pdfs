#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
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
OVERRIDES_PATH = ROOT / "scripts" / "code_overrides.json"


@dataclass(frozen=True)
class PdfMeta:
    year: int | None
    month: int | None
    level: int | None


@dataclass(frozen=True)
class CodeOverride:
    file: str | None
    page: int | None
    y: float | None
    code: str
    language: str = "cpp"
    key: str | None = None
    skip: bool = False


@dataclass(frozen=True)
class ConversionRecord:
    pdf_path: Path
    md_path: Path
    title: str
    meta: PdfMeta
    page_count: int
    text_pages: int
    code_blocks_inserted: int
    code_anchors_without_override: int


def slugify_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).strip()
    normalized = normalized.replace("/", "-").replace("\\", "-")
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff+_.()-]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-._")
    return normalized or "document"


def parse_filename_meta(name: str) -> PdfMeta:
    match = re.search(r"(20\d{2})年(\d{1,2})月-C\+\+(\d+)级", unicodedata.normalize("NFKC", name))
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


def load_code_overrides() -> list[CodeOverride]:
    if not OVERRIDES_PATH.exists():
        return []
    data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    overrides: list[CodeOverride] = []
    for item in data:
        overrides.append(
            CodeOverride(
                file=item.get("file"),
                page=int(item["page"]) if "page" in item else None,
                y=float(item["y"]) if "y" in item else None,
                code=item.get("code", "").rstrip(),
                language=item.get("language", "cpp"),
                key=item.get("key"),
                skip=bool(item.get("skip", False)),
            )
        )
    return overrides


def find_override(
    overrides: list[CodeOverride],
    *,
    file_stem: str,
    page_no: int,
    y: float,
    key: str,
    tolerance: float = 8.0,
) -> CodeOverride | None:
    candidates = [
        item
        for item in overrides
        if item.file == file_stem
        and item.page == page_no
        and item.y is not None
        and abs(item.y - y) <= tolerance
    ]
    if candidates:
        return min(candidates, key=lambda item: abs((item.y or 0) - y))

    for item in overrides:
        if item.key == key:
            return item
    return None


def is_probable_code_anchor(block: tuple) -> bool:
    x0, y0, x1, y1, text, *_ = block
    width = x1 - x0
    height = y1 - y0
    return not text.strip() and 0 < width <= 20 and 5 <= height <= 30


def render_page_markdown(
    page: fitz.Page,
    *,
    file_stem: str,
    page_no: int,
    overrides: list[CodeOverride],
) -> tuple[list[str], int, int, bool]:
    events: list[tuple[float, int, str, str]] = []
    inserted = 0
    missing = 0
    has_text = False
    anchor_count = 0

    for block in page.get_text("blocks", sort=True):
        x0, y0, x1, y1, text, *_ = block
        cleaned = clean_text(text)
        if cleaned:
            has_text = True
            events.append((y0, 1, "text", cleaned))
            continue

        if is_probable_code_anchor(block):
            anchor_count += 1
            key = f"{file_stem}__p{page_no:03d}__c{anchor_count:02d}"
            override = find_override(overrides, file_stem=file_stem, page_no=page_no, y=y0, key=key)
            if override is not None:
                if not override.skip:
                    events.append((y0, 0, "code", fenced(override.code, override.language)))
                    inserted += 1
            else:
                missing += 1

    events.sort(key=lambda item: (item[0], item[1]))

    parts: list[str] = []
    for _, _, kind, content in events:
        if not content:
            continue
        parts.append(content)
        parts.append("")

    if not parts:
        parts.extend(["> 本页未提取到可用文本，请以原始 PDF 为准。", ""])

    return parts, inserted, missing, has_text


def convert_pdf(pdf_path: Path, *, overrides: list[CodeOverride]) -> ConversionRecord:
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)

    title = pdf_path.stem
    safe_stem = slugify_filename(title)
    md_path = MARKDOWN_DIR / f"{safe_stem}.md"

    doc = fitz.open(str(pdf_path))
    meta = parse_filename_meta(pdf_path.name)
    text_pages = 0
    inserted_total = 0
    missing_total = 0

    parts: list[str] = [
        f"# {title}",
        "",
        f"- 原始 PDF: [pdfs/{pdf_path.name}]({md_link('../pdfs/' + pdf_path.name)})",
        f"- 页数: {doc.page_count}",
        "- 转换方式: PDF 文本层为主，缺失的题目代码以人工校对的 Markdown 代码块补入。",
        f"- PDF SHA-256: `{sha256_file(pdf_path)}`",
        "",
        "> 注: 官方 PDF 中有些代码不是文字层，而是图片或矢量对象。已校对的缺失代码会以 `cpp` 代码块显示；暂未校对的空白锚点不会用图片替代。",
        "",
    ]

    for index in range(doc.page_count):
        page_no = index + 1
        page_parts, inserted, missing, has_text = render_page_markdown(
            doc.load_page(index),
            file_stem=title,
            page_no=page_no,
            overrides=overrides,
        )
        if has_text:
            text_pages += 1
        inserted_total += inserted
        missing_total += missing

        parts.extend([f"## 第 {page_no} 页", ""])
        parts.extend(page_parts)

    page_count = doc.page_count
    doc.close()

    md_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return ConversionRecord(
        pdf_path=pdf_path,
        md_path=md_path,
        title=title,
        meta=meta,
        page_count=page_count,
        text_pages=text_pages,
        code_blocks_inserted=inserted_total,
        code_anchors_without_override=missing_total,
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
        "本目录按年份、月份、等级列出 `pdfs/` 中每份真题对应的 Markdown 文件。Markdown 以文本为主，题目代码使用 fenced code block 表示。",
        "",
        "| 年份 | 月份 | 等级 | Markdown | PDF | 页数 | 已补代码块 | 待补代码锚点 |",
        "| --- | ---: | ---: | --- | --- | ---: | ---: | ---: |",
    ]
    for record in records:
        meta = record.meta
        year = str(meta.year) if meta.year is not None else ""
        month = str(meta.month) if meta.month is not None else ""
        level = str(meta.level) if meta.level is not None else ""
        md = f"[{record.title}]({md_link(record.md_path.name)})"
        pdf = f"[PDF]({md_link('../pdfs/' + record.pdf_path.name)})"
        lines.append(
            f"| {year} | {month} | {level} | {md} | {pdf} | {record.page_count} | "
            f"{record.code_blocks_inserted} | {record.code_anchors_without_override} |"
        )

    (MARKDOWN_DIR / "INDEX.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def generate_notes() -> None:
    content = """# 转换说明

## 目标

将 `pdfs/` 目录中的 GESP C++ 真题 PDF 转换为对应的 Markdown 文本文件。

## 输出结构

- `markdown/<试卷名>.md`: 每份 PDF 对应一份 Markdown。
- `markdown/INDEX.md`: Markdown 索引。
- `markdown/CONVERSION_REPORT.md`: 本次转换统计报告。

## 转换方法

脚本: [`scripts/convert_pdfs_to_markdown.py`](../scripts/convert_pdfs_to_markdown.py)

核心流程:

1. 扫描 `pdfs/*.pdf`。
2. 使用 PyMuPDF 提取 PDF 文本层，按页面和文本块输出到 Markdown。
3. 对官方 PDF 中文本层缺失的代码块，使用 `scripts/code_overrides.json` 中人工校对的内容补入 fenced code block。
4. 生成索引和转换报告，报告中会列出已补代码块数量和仍待补的代码锚点数量。

## 质量说明

- Markdown 正文不再使用页面截图或代码截图作为主要内容。
- 代码块使用 C++ fenced code block，便于 GitHub 预览、搜索和复制。
- 如果 PDF 中某处代码本身不是文本层，且尚未人工校对补录，脚本不会用图片冒充文本；报告会记录为待补锚点。

## 复现

```bash
py scripts/convert_pdfs_to_markdown.py
```
"""
    (MARKDOWN_DIR / "CONVERSION_NOTES.md").write_text(content, encoding="utf-8")


def generate_report(records: list[ConversionRecord]) -> None:
    records = sorted(records, key=lambda record: sort_key(record.pdf_path))
    pdf_count = len(list(PDF_DIR.glob("*.pdf")))
    total_pages = sum(record.page_count for record in records)
    text_pages = sum(record.text_pages for record in records)
    inserted = sum(record.code_blocks_inserted for record in records)
    missing = sum(record.code_anchors_without_override for record in records)
    missing_markdown = sorted({slugify_filename(p.stem) for p in PDF_DIR.glob("*.pdf")} - {r.md_path.stem for r in records})

    lines: list[str] = [
        "# 转换报告",
        "",
        f"- 转换日期: {date.today().isoformat()}",
        f"- PDF 数量: {pdf_count}",
        f"- 试卷 Markdown 数量: {len(records)}",
        "- 索引/说明/报告 Markdown 数量: 3",
        f"- PDF 总页数: {total_pages}",
        f"- 成功提取文本的页面数: {text_pages}",
        f"- 已人工补录代码块: {inserted}",
        f"- 待人工补录代码锚点: {missing}",
        f"- 缺失 Markdown: {'无' if not missing_markdown else ', '.join(missing_markdown)}",
        "",
        "## 明细",
        "",
        "| 试卷 | 元信息 | 页数 | 文本页 | 已补代码块 | 待补锚点 | Markdown |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]

    for record in records:
        md = f"[{record.md_path.name}]({md_link(record.md_path.name)})"
        lines.append(
            f"| {record.title} | {meta_label(record.meta)} | {record.page_count} | "
            f"{record.text_pages} | {record.code_blocks_inserted} | "
            f"{record.code_anchors_without_override} | {md} |"
        )

    (MARKDOWN_DIR / "CONVERSION_REPORT.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def convert_all() -> list[ConversionRecord]:
    pdf_paths = sorted(PDF_DIR.glob("*.pdf"), key=sort_key)
    if not pdf_paths:
        raise SystemExit(f"No PDF files found in {PDF_DIR}")
    overrides = load_code_overrides()
    records = [convert_pdf(pdf_path, overrides=overrides) for pdf_path in pdf_paths]
    generate_index(records)
    generate_notes()
    generate_report(records)
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert GESP official PDFs to text-first Markdown.")
    return parser.parse_args()


def main() -> None:
    parse_args()
    records = convert_all()
    total_pages = sum(record.page_count for record in records)
    inserted = sum(record.code_blocks_inserted for record in records)
    missing = sum(record.code_anchors_without_override for record in records)
    print(
        f"Converted {len(records)} PDFs ({total_pages} pages) into {MARKDOWN_DIR}. "
        f"Inserted {inserted} code blocks; {missing} code anchors still need manual text."
    )


if __name__ == "__main__":
    main()
