#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import fitz


ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "pdfs"
MARKDOWN_DIR = ROOT / "markdown"
ASSETS_DIR = ROOT / "markdown_assets"
IMAGE_DPI = 144
IMAGE_ZOOM = IMAGE_DPI / 72.0


@dataclass
class ConversionRecord:
    pdf_path: Path
    md_path: Path
    asset_dir: Path
    page_count: int
    safe_stem: str
    title: str
    year: int | None
    month: int | None
    level: int | None


def slugify_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).strip()
    normalized = normalized.replace("/", "-").replace("\\", "-")
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff+_.()-]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-._")
    return normalized or "document"


def extract_sort_key(pdf_name: str) -> tuple[int, int, int, str]:
    year = month = level = 9999
    m = re.search(r"(20\d{2})年(\d{1,2})月.*?(\d+)级", pdf_name)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        level = int(m.group(3))
    return year, month, level, pdf_name


def parse_filename_meta(pdf_name: str) -> tuple[int | None, int | None, int | None]:
    m = re.search(r"(20\d{2})年(\d{1,2})月.*?(\d+)级", pdf_name)
    if not m:
        return None, None, None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def page_image_name(page_no: int) -> str:
    return f"page-{page_no:03d}.png"


def clean_text(text: str) -> str:
    text = text.replace("\x0c", "\n")
    lines = [line.rstrip() for line in text.splitlines()]
    # keep blank lines but collapse long blank runs
    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip():
            cleaned.append(line)
            blank_run = 0
        else:
            blank_run += 1
            if blank_run <= 2:
                cleaned.append("")
    return "\n".join(cleaned).strip()


def title_for_pdf(pdf_path: Path, doc: fitz.Document) -> str:
    meta_title = (doc.metadata or {}).get("title", "").strip()
    if meta_title:
        return meta_title
    return pdf_path.stem


def convert_pdf(pdf_path: Path) -> ConversionRecord:
    ensure_dir(MARKDOWN_DIR)
    ensure_dir(ASSETS_DIR)

    safe_stem = slugify_filename(pdf_path.stem)
    md_path = MARKDOWN_DIR / f"{safe_stem}.md"
    asset_dir = ASSETS_DIR / safe_stem
    ensure_dir(asset_dir)

    doc = fitz.open(pdf_path)
    title = title_for_pdf(pdf_path, doc)
    year, month, level = parse_filename_meta(pdf_path.name)

    parts: list[str] = []
    parts.append(f"# {title}")
    parts.append("")
    parts.append(f"- 原始 PDF：[`pdfs/{pdf_path.name}`](../pdfs/{pdf_path.name})")
    parts.append(f"- 页数：{doc.page_count}")
    parts.append(f"- 转换脚本：[`scripts/convert_pdfs_to_markdown.py`](../scripts/convert_pdfs_to_markdown.py)")
    parts.append("")
    parts.append("> 为尽量避免信息丢失，每页均附带页面图片；文本提取结果保留原有顺序与换行特征，个别公式、图形、特殊排版请以页面图片为准。")
    parts.append("")

    matrix = fitz.Matrix(IMAGE_ZOOM, IMAGE_ZOOM)
    for idx in range(doc.page_count):
        page_no = idx + 1
        page = doc.load_page(idx)
        image_filename = page_image_name(page_no)
        image_path = asset_dir / image_filename
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        pix.save(image_path)

        text = clean_text(page.get_text("text", sort=True))
        if not text:
            text = "[未提取到可用文本，请以本页图片为准。]"

        rel_image = Path("..") / "markdown_assets" / safe_stem / image_filename
        parts.append(f"## 第 {page_no} 页")
        parts.append("")
        parts.append(f"![{title} - 第 {page_no} 页]({rel_image.as_posix()})")
        parts.append("")
        parts.append("### 提取文本")
        parts.append("")
        parts.append("```")
        parts.append(text)
        parts.append("```")
        parts.append("")

    md_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    doc.close()
    return ConversionRecord(pdf_path, md_path, asset_dir, len(list(asset_dir.glob('page-*.png'))), safe_stem, title, year, month, level)


def generate_index(records: Iterable[ConversionRecord]) -> None:
    records = sorted(records, key=lambda r: extract_sort_key(r.pdf_path.name))
    lines = ["# PDF Markdown 索引", "", "按年份 / 月份 / 等级（无法解析时按文件名）排序。", ""]
    for record in records:
        meta = []
        if record.year is not None:
            meta.append(f"{record.year}年{record.month}月")
        if record.level is not None:
            meta.append(f"C++ {record.level}级")
        meta_str = " / ".join(meta) if meta else "未解析元信息"
        lines.append(f"- [{record.title}]({record.md_path.name})")
        lines.append(f"  - 原 PDF：[`pdfs/{record.pdf_path.name}`](../pdfs/{record.pdf_path.name})")
        lines.append(f"  - 页面图片目录：[`markdown_assets/{record.safe_stem}`](../markdown_assets/{record.safe_stem})")
        lines.append(f"  - 元信息：{meta_str}；页数：{record.page_count}")
    (MARKDOWN_DIR / "INDEX.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def generate_notes() -> None:
    content = """# 转换说明

## 目标

将 `pdfs/` 下全部试卷 PDF 转换为 Markdown，并为每一页导出 PNG 图片，以最大化保留题面信息、版式线索、图形与公式可追溯性。

## 方法

转换脚本：[`scripts/convert_pdfs_to_markdown.py`](../scripts/convert_pdfs_to_markdown.py)

核心流程：

1. 扫描 `pdfs/*.pdf`。
2. 使用 PyMuPDF（`fitz`）逐个打开 PDF。
3. 对每页执行两类输出：
   - 文本提取：`page.get_text("text", sort=True)`，尽量保持阅读顺序；
   - 页面渲染：按 144 DPI 导出 PNG，保存到 `markdown_assets/<pdf_name>/page-XXX.png`。
4. 为每个 PDF 生成一个对应的 `markdown/<pdf_name>.md`，内容至少包含：
   - 文档标题
   - 原始 PDF 链接
   - 分页小节
   - 每页图片引用
   - 每页文本提取结果
5. 生成：
   - `markdown/INDEX.md`
   - `markdown/CONVERSION_REPORT.md`
   - 本说明文档

## 依赖

- Python 3.9+
- PyMuPDF / fitz

安装示例：

```bash
python3 -m pip install pymupdf
```

## 复现

在仓库根目录执行：

```bash
python3 scripts/convert_pdfs_to_markdown.py
```

脚本会自动创建或覆盖：

- `markdown/*.md`
- `markdown/INDEX.md`
- `markdown/CONVERSION_NOTES.md`
- `markdown/CONVERSION_REPORT.md`
- `markdown_assets/<pdf_name>/page-XXX.png`

## 局限

- PDF 文本层若本身缺失、错乱或包含复杂对象（如公式、流程图、扫描图片），文本提取可能不完整。
- Markdown 无法原样复现 PDF 的全部版式；因此每页图片是本转换方案的重要兜底，确保信息不丢失、可回溯。
- 图片按 144 DPI 导出，在可读性与仓库体积之间做了折中；若后续希望更高保真，可提升 `IMAGE_DPI`。
"""
    (MARKDOWN_DIR / "CONVERSION_NOTES.md").write_text(content, encoding="utf-8")


def generate_report(records: Iterable[ConversionRecord]) -> None:
    records = list(records)
    pdf_count = len(list(PDF_DIR.glob("*.pdf")))
    asset_dirs = [p for p in ASSETS_DIR.iterdir() if p.is_dir()]
    total_images = sum(len(list(d.glob("page-*.png"))) for d in asset_dirs)
    total_pages = sum(r.page_count for r in records)
    missing_md = sorted({p.stem for p in PDF_DIR.glob('*.pdf')} - {r.pdf_path.stem for r in records})
    generated_md_count = len(records) + 3  # per-PDF markdown + INDEX + NOTES + REPORT

    lines = [
        "# 转换报告",
        "",
        f"- PDF 数量：{pdf_count}",
        f"- 生成的 Markdown 文件数量（含索引/说明/报告）：{generated_md_count}",
        f"- 其中 PDF 对应 Markdown 数量：{len(records)}",
        f"- 资产目录数量：{len(asset_dirs)}",
        f"- 导出页面图片总数：{total_images}",
        f"- 页面总数：{total_pages}",
        f"- 校验结果：{'通过' if pdf_count == len(records) == len(asset_dirs) else '存在不一致'}",
        "",
        "## 明细",
        "",
    ]
    for record in sorted(records, key=lambda r: extract_sort_key(r.pdf_path.name)):
        lines.append(f"- {record.pdf_path.name}: {record.page_count} 页 -> `{record.md_path.name}` / `{record.asset_dir.name}`")
    if missing_md:
        lines.extend(["", "## 缺失项", ""] + [f"- {name}" for name in missing_md])
    (MARKDOWN_DIR / "CONVERSION_REPORT.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    if not PDF_DIR.exists():
        print(f"PDF directory not found: {PDF_DIR}", file=sys.stderr)
        return 1

    ensure_dir(MARKDOWN_DIR)
    ensure_dir(ASSETS_DIR)

    pdf_paths = sorted(PDF_DIR.glob("*.pdf"), key=lambda p: extract_sort_key(p.name))
    records: list[ConversionRecord] = []
    for pdf_path in pdf_paths:
        print(f"Converting {pdf_path.name} ...")
        records.append(convert_pdf(pdf_path))

    generate_index(records)
    generate_notes()
    generate_report(records)
    print(f"Done. Converted {len(records)} PDFs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
