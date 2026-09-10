# -*- coding: utf-8 -*-
"""Markdown ⇄ LearnHouse 富文本（TipTap JSON）。

移植自教学工具 skill 的 `content.py`（SYSU-SAM）。语法与节点映射逐行照搬，
**唯一的结构性改动是图片**：skill 版在解析过程中同步上传图片（它手里有 HTTP client），
后端这边上传是 async 的，所以拆成两步：

    srcs = scan_image_sources(md)          # 先扫出所有图片引用
    blocks = {src: await 上传(src) …}       # 调用方 async 上传，拿到 BlockRead
    doc = md_to_tiptap(md, image_blocks=blocks)   # 解析器保持纯函数

这样解析器没有 IO，可以直接单测。

支持的语法：# ## ### 标题、段落（连续行合并）、**粗体** *斜体* `代码` [链接]()、
无序/有序列表、``` 代码块、| 表格 |、--- 分割线、> [!info] / > [!warning] 提示框、
![alt](src) 图片、[[FLIP:问题|答案]] 翻转卡、[[EMBED:url]] 嵌入、
以及独占一行的视频链接（自动转播放器）。
"""
import re

from .embeds import VIDEO_HOST_RE, to_embed_url

DEFAULT_IMG_WIDTH = 620
DEFAULT_EMBED_HEIGHT = 400

_INLINE_SPLIT = re.compile(
    r"(!\[[^\]]*\]\([^)]+\)|\*\*.+?\*\*|\*[^*\n]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))"
)
IMG_LINE_RE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)]+)\)\s*$")
FLIP_RE = re.compile(r"^\s*\[\[FLIP:(.+?)\|(.+?)\]\]\s*$")
EMBED_RE = re.compile(r"^\s*\[\[EMBED:(\S+?)\]\]\s*$")
CALLOUT_RE = re.compile(r"^\s*>\s*\[!(info|warn|warning|note|tip)\]\s*(.*)$", re.I)
FENCE_RE = re.compile(r"^\s*```([A-Za-z0-9_+-]*)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
HR_RE = re.compile(r"^\s*(---|\*\*\*|___)\s*$")
UL_RE = re.compile(r"^\s*([-*+])\s+")
OL_RE = re.compile(r"^\s*\d+[.)]\s+")
LI_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
BARE_URL_RE = re.compile(r"^\s*(https?://\S+)\s*$")
LINK_LINE_RE = re.compile(r"^\s*\[([^\]]*)\]\(([^)]+)\)\s*$")


# ------------------------------------------------------------ 节点构造


def _inline(text):
    """行内标记 -> TipTap text 节点数组。图片语法在行内会被忽略（图片必须独占一行）。"""
    nodes, pos = [], 0
    for m in _INLINE_SPLIT.finditer(text):
        if m.start() > pos:
            s = text[pos:m.start()]
            if s:
                nodes.append({"type": "text", "text": s})
        tk = m.group(0)
        if tk.startswith("!["):
            pass  # 行内图片不支持，丢弃标记
        elif tk.startswith("**"):
            inner = tk[2:-2]
            if inner:
                nodes.append({"type": "text", "text": inner, "marks": [{"type": "bold"}]})
        elif tk.startswith("`"):
            inner = tk[1:-1]
            if inner:
                nodes.append({"type": "text", "text": inner, "marks": [{"type": "code"}]})
        elif tk.startswith("["):
            mm = re.match(r"\[([^\]]+)\]\(([^)]+)\)", tk)
            if mm:
                nodes.append({"type": "text", "text": mm.group(1),
                              "marks": [{"type": "link", "attrs": {"href": mm.group(2)}}]})
        else:
            inner = tk[1:-1]
            if inner:
                nodes.append({"type": "text", "text": inner, "marks": [{"type": "italic"}]})
        pos = m.end()
    if pos < len(text):
        s = text[pos:]
        if s:
            nodes.append({"type": "text", "text": s})
    return nodes or [{"type": "text", "text": text or " "}]


def _para(t):
    return {"type": "paragraph", "content": _inline(t)}


def _cell(t, header=False):
    return {"type": "tableHeader" if header else "tableCell",
            "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None},
            "content": [_para(t)]}


def _flipcard(q, a, color="blue"):
    return {"type": "flipcard", "attrs": {
        "question": q, "answer": a, "color": color,
        "alignment": "center", "size": "medium"}}


def embed_node(embed_url, height=DEFAULT_EMBED_HEIGHT):
    """已经归一化过的播放器地址 → blockEmbed 节点。"""
    return {"type": "blockEmbed", "attrs": {
        "embedUrl": embed_url, "embedType": "url",
        "embedHeight": int(height), "embedWidth": "100%", "alignment": "center",
    }}


def _embed_node_from_link(url, height=DEFAULT_EMBED_HEIGHT):
    return embed_node(to_embed_url(url, resolve_short=False), height=height)


def _is_video_link_line(line):
    """这一行是不是「独占一行的 [文字](视频链接)」。段落合并时用它断行。"""
    m = LINK_LINE_RE.match(line)
    return bool(m and VIDEO_HOST_RE.search(m.group(2)))


# ------------------------------------------------------------ 图片预扫描


def scan_image_sources(md):
    """扫出正文里所有独占一行的图片引用，按出现顺序去重返回。

    调用方拿它去上传，再把 {src: blockObject} 传回 `md_to_tiptap`。
    """
    seen, out = set(), []
    for raw in (md or "").replace("\r\n", "\n").split("\n"):
        m = IMG_LINE_RE.match(raw.rstrip())
        if not m:
            continue
        src = m.group(2).strip()
        if src not in seen:
            seen.add(src)
            out.append(src)
    return out


# ------------------------------------------------------------ 主转换


def md_to_tiptap(md, image_blocks=None, img_width=DEFAULT_IMG_WIDTH, warnings=None):
    """Markdown 文本 -> TipTap doc（dict）。纯函数，不做任何 IO。

    `image_blocks` 是 `{图片 src: BlockRead dict}`；某个 src 不在里面就跳过并记
    warning，页面不会因为一张图挂掉。`warnings` 传一个 list 进来能收集所有跳过原因。
    """
    warn = warnings if warnings is not None else []
    blocks = image_blocks or {}
    out, i = [], 0
    lines = (md or "").replace("\r\n", "\n").split("\n")

    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1
            continue

        # 代码块（必须先于段落判断）
        m = FENCE_RE.match(ln)
        if m:
            lang = m.group(1) or None
            i += 1
            buf = []
            while i < len(lines) and not FENCE_RE.match(lines[i].rstrip()):
                buf.append(lines[i])
                i += 1
            i += 1  # 吃掉收尾的 ```
            out.append({
                "type": "codeBlock", "attrs": {"language": lang},
                "content": [{"type": "text", "text": "\n".join(buf) or " "}],
            })
            continue

        # 图片
        m = IMG_LINE_RE.match(ln)
        if m:
            src = m.group(2).strip()
            i += 1
            blk = blocks.get(src)
            if not blk:
                warn.append("图片 %s 被跳过：没有拿到上传后的块对象" % src)
                continue
            out.append({"type": "blockImage", "attrs": {
                "blockObject": blk, "size": {"width": img_width}, "alignment": "center"}})
            continue

        # 翻转卡（连续多张排成网格）
        m = FLIP_RE.match(ln)
        if m:
            cards = []
            while i < len(lines):
                mm = FLIP_RE.match(lines[i].rstrip())
                if not mm:
                    break
                cards.append(_flipcard(mm.group(1).strip(), mm.group(2).strip()))
                i += 1
            if len(cards) == 1:
                out.append(cards[0])
            else:
                out.append({"type": "flipcardGrid",
                            "attrs": {"columns": 2 if len(cards) % 2 == 0 else 3},
                            "content": cards})
            continue

        # 显式嵌入
        m = EMBED_RE.match(ln)
        if m:
            out.append(_embed_node_from_link(m.group(1)))
            i += 1
            continue

        # 独占一行的视频链接（裸链接）
        m = BARE_URL_RE.match(ln)
        if m and VIDEO_HOST_RE.search(m.group(1)):
            out.append(_embed_node_from_link(m.group(1)))
            i += 1
            continue

        # 独占一行的 [文字](视频链接) —— 老师从 bilibili 复制过来常常带着标题
        m = LINK_LINE_RE.match(ln)
        if m and VIDEO_HOST_RE.search(m.group(2)):
            out.append(_embed_node_from_link(m.group(2).strip()))
            i += 1
            continue
        # 注意：不是视频站的 [文字](链接) 不在这里 continue，
        # 让它落到下面的段落分支，仍然渲染成普通超链接

        # 提示框
        m = CALLOUT_RE.match(ln)
        if m:
            kind = m.group(1).lower()
            buf = [m.group(2).strip()]
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith(">") \
                    and not CALLOUT_RE.match(lines[i]):
                buf.append(lines[i].lstrip()[1:].strip())
                i += 1
            txt = " ".join(x for x in buf if x)
            node = "calloutWarning" if kind in ("warn", "warning") else "calloutInfo"
            out.append({"type": node, "content": _inline(txt)})
            continue

        # 标题
        m = HEADING_RE.match(ln)
        if m:
            out.append({"type": "heading", "attrs": {"level": min(len(m.group(1)), 6)},
                        "content": _inline(m.group(2).strip())})
            i += 1
            continue

        # 表格
        if ln.lstrip().startswith("|") and ln.rstrip().endswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                raw = lines[i].strip()
                if not re.match(r"^[\s:|-]+$", raw):  # 跳过 |---|---| 分隔行
                    rows.append([c.strip() for c in raw.strip("|").split("|")])
                i += 1
            if rows:
                trs = [{"type": "tableRow", "content": [_cell(c, True) for c in rows[0]]}]
                for r in rows[1:]:
                    trs.append({"type": "tableRow", "content": [_cell(c) for c in r]})
                out.append({"type": "table", "content": trs})
            continue

        # 分割线
        if HR_RE.match(ln):
            out.append({"type": "horizontalRule"})
            i += 1
            continue

        # 列表
        if UL_RE.match(ln) or OL_RE.match(ln):
            ordered = bool(OL_RE.match(ln))
            items = []
            while i < len(lines):
                mm = LI_RE.match(lines[i].rstrip())
                if not mm:
                    break
                items.append({"type": "listItem", "content": [_para(mm.group(1).strip())]})
                i += 1
            out.append({"type": "orderedList" if ordered else "bulletList", "content": items})
            continue

        # 普通引用退化成段落
        if ln.lstrip().startswith(">"):
            out.append(_para(ln.lstrip()[1:].strip()))
            i += 1
            continue

        # 段落：连续几行合并，遇到任何块级起始就停
        buf = []
        while i < len(lines) and lines[i].strip():
            cur = lines[i]
            if buf and (HEADING_RE.match(cur) or UL_RE.match(cur) or OL_RE.match(cur)
                        or cur.lstrip().startswith(">") or cur.lstrip().startswith("|")
                        or FENCE_RE.match(cur.rstrip()) or HR_RE.match(cur)
                        or IMG_LINE_RE.match(cur) or FLIP_RE.match(cur)
                        or EMBED_RE.match(cur) or BARE_URL_RE.match(cur)
                        or _is_video_link_line(cur)):
                break
            buf.append(cur.strip())
            i += 1
        if buf:
            out.append(_para(" ".join(buf)))
        else:
            i += 1

    return {"type": "doc", "content": out or [_para(" ")]}


# ------------------------------------------------------------ 反向：TipTap -> Markdown


def _marks_wrap(text, marks):
    for mk in marks or []:
        t = mk.get("type")
        if t == "bold":
            text = "**%s**" % text
        elif t == "italic":
            text = "*%s*" % text
        elif t == "code":
            text = "`%s`" % text
        elif t == "link":
            text = "[%s](%s)" % (text, (mk.get("attrs") or {}).get("href", ""))
    return text


def _inline_md(nodes):
    return "".join(_marks_wrap(n.get("text", ""), n.get("marks")) for n in (nodes or []))


def tiptap_to_markdown(doc):
    """把页面内容大致还原成 Markdown。

    是有损的：图片写成 `![](上传文件名)`，嵌入写成 `[[EMBED:url]]`，
    不认识的节点写成 `<!-- 节点类型 -->` 注释，方便人工确认。
    """
    if isinstance(doc, dict) and doc.get("type") == "doc":
        nodes = doc.get("content", [])
    elif isinstance(doc, list):
        nodes = doc
    else:
        nodes = (doc or {}).get("content", []) if isinstance(doc, dict) else []
    out = []
    for n in nodes:
        t = n.get("type")
        attrs = n.get("attrs") or {}
        if t == "heading":
            out.append("#" * int(attrs.get("level", 1)) + " " + _inline_md(n.get("content")))
        elif t == "paragraph":
            out.append(_inline_md(n.get("content")))
        elif t == "codeBlock":
            lang = attrs.get("language") or ""
            body = "".join(c.get("text", "") for c in n.get("content", []))
            out.append("```%s\n%s\n```" % (lang, body))
        elif t in ("bulletList", "orderedList"):
            for idx, li in enumerate(n.get("content", []), 1):
                txt = " ".join(_inline_md(p.get("content")) for p in li.get("content", []))
                out.append(("%d. " % idx if t == "orderedList" else "- ") + txt)
        elif t == "table":
            rows = n.get("content", [])
            for ri, tr in enumerate(rows):
                cells = [" ".join(_inline_md(p.get("content"))
                                  for p in td.get("content", []))
                         for td in tr.get("content", [])]
                out.append("| " + " | ".join(cells) + " |")
                if ri == 0:
                    out.append("|" + "|".join(["---"] * len(cells)) + "|")
        elif t == "horizontalRule":
            out.append("---")
        elif t in ("calloutInfo", "calloutWarning"):
            tag = "info" if t == "calloutInfo" else "warning"
            out.append("> [!%s] " % tag + _inline_md(n.get("content")))
        elif t == "blockImage":
            blk = attrs.get("blockObject") or {}
            fn = (blk.get("content") or {}).get("file_name", "image")
            out.append("![](%s)" % fn)
        elif t == "blockEmbed":
            out.append("[[EMBED:%s]]" % attrs.get("embedUrl", ""))
        elif t == "flipcard":
            out.append("[[FLIP:%s|%s]]" % (attrs.get("question", ""), attrs.get("answer", "")))
        elif t == "flipcardGrid":
            for c in n.get("content", []):
                a = c.get("attrs") or {}
                out.append("[[FLIP:%s|%s]]" % (a.get("question", ""), a.get("answer", "")))
        else:
            out.append("<!-- %s -->" % t)
        out.append("")
    return "\n".join(out).strip() + "\n"


# ------------------------------------------------------------ front matter


def front_matter(fields):
    """写一段极简的 key: value 头（不引 PyYAML，也不假装是 YAML 全集）。"""
    lines = ["---"]
    for k, v in fields.items():
        if v is None:
            continue
        lines.append("%s: %s" % (k, v))
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def parse_front_matter(text):
    """把 `---` 包起来的头解析成 dict，返回 (头, 正文)。没有头就返回 ({}, 原文)。"""
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return {}, text
    meta, i = {}, 1
    while i < len(lines) and lines[i].strip() != "---":
        k, sep, v = lines[i].partition(":")
        if sep:
            meta[k.strip()] = v.strip()
        i += 1
    if i >= len(lines):
        return {}, text                      # 没有收尾的 ---，当没有头
    return meta, "\n".join(lines[i + 1:]).lstrip("\n")


_LOST_NODE_RE = re.compile(r"^<!--\s*(\w+)\s*-->$")


def strip_lost_nodes(body):
    """剥掉 `tiptap_to_markdown` 为不认识的节点留下的 `<!-- blockVideo -->` 注释行。

    不剥的话，`md_to_tiptap` 会把这一行当成**普通段落**塞进页面，
    学生看到的就是一行字面的 `<!-- blockVideo -->`。
    返回 (剥干净的正文, 被剥掉的节点类型列表)。
    """
    kept, lost = [], []
    for line in body.split("\n"):
        m = _LOST_NODE_RE.match(line.strip())
        if m:
            lost.append(m.group(1))
            continue
        kept.append(line)
    return "\n".join(kept), lost


#: 给同包其他模块用的公开别名（行内 Markdown -> TipTap text 节点数组）
inline_nodes = _inline
