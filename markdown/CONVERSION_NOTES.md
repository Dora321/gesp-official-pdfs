# 转换说明

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
