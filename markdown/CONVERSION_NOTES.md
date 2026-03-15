# 转换说明

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
