# Changelog

本项目所有重要变更都记录在此文件。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 新增 `md_to_jsonl.py`：将 `output/` 下转换后的 Markdown 文档转为 LLM 微调语料（JSONL）。
  - 输入为版本目录（如 `output/WwiseHelp_en`），读取其中的 `data/*.md`。
  - 每个版本汇总为单个 `<版本名>.jsonl` 文件，默认输出到 `output/jsonl/`，可用 `-o/--out-dir` 指定输出目录。
  - 每个文档输出为一行 `{"text": "..."}`。
  - 用法：`uv run python md_to_jsonl.py output/WwiseHelp_en output/WwiseSDK-Windows`
- 清洗规则（面向微调语料，将页面依赖关系抹平为纯文本）：
  - 删除首行重复标题与面包屑导航行。
  - 内联/页面互引链接 `[text](xxx.md|.html|#anchor)` 降级为纯锚文本；迭代替换以处理嵌套链接畸形。
  - 外部 `http(s)` 链接仅保留锚文本，去掉 URL。
  - 删除图片引用。
  - 规范化异形 heading 前缀（如 `# ## ` → `## `）。
  - 退化的提示框表格（空 `| Note |` 表）还原为 `**Note**`。
  - 去重表格分隔行、删除尾部 `* * *` 分割线、压缩多余空行。
