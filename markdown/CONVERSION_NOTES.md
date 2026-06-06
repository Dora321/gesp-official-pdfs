# 转换说明

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
5. 对 PDF 文本层缺失、但页面中存在的代码区域，利用空文本锚点裁剪对应页面片段并插入题干附近。
6. 对每页渲染 `144` DPI PNG 页面图。
7. 生成包含元信息、页面图、可阅读正文、代码块和代码裁图的 Markdown。

## 质量说明

- Markdown 正文用于搜索、复制和快速阅读。
- 检测到的代码片段会从整页文本中拆出，单独显示为代码块，避免整页 `text` 代码块导致的横向滚动和代码不可见问题。
- 如果题目代码在 PDF 中不是文本层而是图片/矢量内容，脚本会裁剪该代码区域并插入 Markdown，确保题目对应代码可见。
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
