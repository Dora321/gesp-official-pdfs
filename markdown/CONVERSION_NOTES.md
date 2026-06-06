# 转换说明

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
3. 将每页渲染为 `144` DPI PNG，作为 Markdown 的主内容。
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
