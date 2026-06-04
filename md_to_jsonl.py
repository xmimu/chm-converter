"""Markdown to JSONL converter — 将 output 目录下的 md 文件转为微调语料。

Usage
-----
  uv run python md_to_jsonl.py output/WwiseHelp_en
  uv run python md_to_jsonl.py output/WwiseHelp_en output/WwiseSDK-Windows
  uv run python md_to_jsonl.py output/WwiseHelp_en -o corpus

每个版本目录汇总为一个 <版本名>.jsonl 文件（默认输出到 output/jsonl/），
文件内每个 md 文档一行 {"text": "..."}。

清洗规则:
  - 去掉首行重复标题（# Title (Version)）
  - 去掉面包屑导航行
  - 链接 [text](xxx.md / xxx.html / #anchor) → 纯文字 text
  - 图片 ![...](xxx) → 删除
  - 异形 heading 前缀 "# ## " → 规范化为 "## "
  - 退化提示框表格 (| Note | + 多余分隔行) → **Note**
  - 重复表格分隔行 → 保留一行
  - 去掉尾部 "* * *" 分割线
  - 压缩连续空行
"""

import argparse
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# 清洗函数
# ---------------------------------------------------------------------------

# 匹配面包屑行: 包含 " > " 且含页面链接
_BREADCRUMB_RE = re.compile(r"^.*\]\([^)]*\.(?:md|html?)[^)]*\).*>.*$")

# 匹配 markdown 链接 [text](target ...) — 不论后缀(.md/.html/锚点)，统一降级为 text。
# 排除图片(前面单独处理)，target 不含空格的第一段。
_LINK_RE = re.compile(r"(?<!\!)\[([^\]]*)\]\((?!https?://)[^)]*\)")

# 保留外部 http(s) 链接的文字(去掉 url)，避免训练语料里出现裸 url
_HTTP_LINK_RE = re.compile(r"(?<!\!)\[([^\]]*)\]\(https?://[^)]*\)")

# 匹配图片引用
_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

# 异形 heading: 行首 "#" 后跟多余的 "#"/空格 → 规范化
#   "# ## text" → "## text"，"# #text" → "# text"，"#  text" → "# text"
_ABNORMAL_HEADING_RE = re.compile(r"^#\s+(#{1,5})?\s*", re.MULTILINE)

# 退化的提示框表格: "| Note |\n| --- |\n| --- | --- |" → "**Note**"
# (源 HTML 的提示框 callout 转换后退化成空表头 + 多余分隔行)
_DEGENERATE_NOTE_RE = re.compile(
    r"^\|\s*([^|\n]+?)\s*\|\s*\n\|\s*-+\s*\|\s*\n\|(?:\s*-+\s*\|)+\s*$",
    re.MULTILINE,
)

# 重复的表格分隔行: 连续两行 "| --- | --- | ... |"，去掉第二行
_DUP_TABLE_SEP_RE = re.compile(
    r"^(\|(?:\s*:?-+:?\s*\|)+)\s*\n\|(?:\s*:?-+:?\s*\|)+\s*$",
    re.MULTILINE,
)

# 多余空行
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def clean_md(text: str) -> str:
    """将一个 md 文件内容清洗为干净的纯文本/简化 markdown。"""
    lines = text.splitlines()

    # 去掉首行标题 "# XXX (Version)" — 正文里还有个同名 heading
    if lines and lines[0].startswith("# "):
        lines = lines[1:]

    # 去掉面包屑行（通常在前6行内，含 " > " 和页面链接）
    cleaned = []
    for i, line in enumerate(lines):
        if i < 6 and " > " in line and (".md" in line or ".htm" in line):
            continue
        cleaned.append(line)
    lines = cleaned

    text = "\n".join(lines)

    # 规范化异形 heading: "# ## text"→"## text", "# #text"→"# text", "#  text"→"# text"
    def _fix_heading(m: re.Match) -> str:
        inner = m.group(1)
        return (inner + " ") if inner else "# "

    text = re.sub(_ABNORMAL_HEADING_RE, _fix_heading, text)

    # 图片引用 → 删除
    text = _IMG_RE.sub("", text)

    # 退化提示框表格 → 内联标签 **Note**
    text = _DEGENERATE_NOTE_RE.sub(r"**\1**", text)

    # 重复表格分隔行 → 保留一行
    text = _DUP_TABLE_SEP_RE.sub(r"\1", text)

    # 链接降级: 迭代替换直到稳定，以处理 html2text 产生的嵌套链接畸形
    #   如 [_[name](a.html)_](b.html) — 一次替换只能消去一层
    for _ in range(5):
        new_text = _LINK_RE.sub(r"\1", text)      # 内部链接 .md/.html/#anchor → text
        new_text = _HTTP_LINK_RE.sub(r"\1", new_text)  # 外部 http 链接 → 锚文本
        if new_text == text:
            break
        text = new_text

    # 去掉尾部 * * * 分割线
    text = text.rstrip()
    if text.endswith("* * *"):
        text = text[: -len("* * *")].rstrip()

    # 压缩多余空行
    text = _MULTI_BLANK_RE.sub("\n\n", text)

    # 去掉首尾空白
    text = text.strip()

    return text


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------

def convert_directory(input_dir: Path, out_dir: Path) -> None:
    """处理一个版本目录，将 data/*.md 汇总为单个 <版本名>.jsonl 文件。

    每个 md 文档输出为一行 {"text": ...}。
    """
    data_dir = input_dir / "data"
    if not data_dir.is_dir():
        print(f"跳过: {input_dir} (缺少 data 子目录)")
        return

    md_files = sorted(data_dir.glob("*.md"))
    if not md_files:
        print(f"跳过: {data_dir} (无 md 文件)")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_file = out_dir / (input_dir.name + ".jsonl")

    converted = 0
    skipped = 0

    with jsonl_file.open("w", encoding="utf-8") as f:
        for md_file in md_files:
            raw = md_file.read_text(encoding="utf-8")
            text = clean_md(raw)

            # 跳过清洗后为空的文件
            if not text:
                skipped += 1
                continue

            f.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
            converted += 1

    print(f"完成: {input_dir.name} → {jsonl_file}")
    print(f"  写入: {converted} 行, 跳过: {skipped} 个空文件")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将 output 下的 md 文档转换为 jsonl 微调语料",
    )
    parser.add_argument(
        "dirs",
        nargs="+",
        metavar="DIR",
        help="output 下的版本目录, 如 output/WwiseHelp_en",
    )
    parser.add_argument(
        "--out-dir", "-o",
        default="output/jsonl",
        metavar="DIR",
        help="jsonl 输出目录 (默认: output/jsonl)，每个版本一个 <版本名>.jsonl",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    for d in args.dirs:
        path = Path(d)
        if not path.is_dir():
            print(f"错误: 目录不存在 {d}", file=sys.stderr)
            continue
        convert_directory(path, out_dir)

    print("全部完成。")


if __name__ == "__main__":
    main()
