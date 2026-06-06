# 转换说明

## 目标

将 `pdfs/` 目录中的 GESP C++ 真题 PDF 转换为对应的 Markdown 文件，并为每一页导出 PNG 页面图，保证文本可检索、页面可核验、图形和公式不丢失。

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
4. 对每页渲染 `144` DPI PNG 页面图。
5. 生成包含元信息、页面图和逐页文本的 Markdown。

## 质量说明

- Markdown 文本用于搜索、复制和快速阅读。
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
