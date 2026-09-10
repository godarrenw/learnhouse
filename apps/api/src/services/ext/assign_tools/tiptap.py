"""把内容页的 tiptap JSON 还原成 Markdown / 纯文本。

移植自 skill/learnhouse/content.py 的 `tiptap_to_markdown`。是有损的：
图片写成 `![](文件名)`，嵌入写成 `[[EMBED:url]]`，不认识的节点写成
`<!-- 节点类型 -->` 注释，方便人工确认漏了什么。
"""

import re


def _marks_wrap(text: str, marks) -> str:
    for mk in marks or []:
        t = mk.get("type")
        if t == "bold":
            text = f"**{text}**"
        elif t == "italic":
            text = f"*{text}*"
        elif t == "code":
            text = f"`{text}`"
        elif t == "link":
            text = f"[{text}]({(mk.get('attrs') or {}).get('href', '')})"
    return text


def _inline_md(nodes) -> str:
    return "".join(_marks_wrap(n.get("text", ""), n.get("marks")) for n in (nodes or []))


def tiptap_to_markdown(doc) -> str:
    """内容页 JSON → Markdown 文本。"""
    if isinstance(doc, dict) and doc.get("type") == "doc":
        nodes = doc.get("content", []) or []
    elif isinstance(doc, list):
        nodes = doc
    elif isinstance(doc, dict):
        nodes = doc.get("content", []) or []
    else:
        nodes = []

    out: list[str] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        t = n.get("type")
        attrs = n.get("attrs") or {}
        if t == "heading":
            try:
                level = int(attrs.get("level", 1))
            except (TypeError, ValueError):
                level = 1
            out.append("#" * max(1, min(6, level)) + " " + _inline_md(n.get("content")))
        elif t == "paragraph":
            out.append(_inline_md(n.get("content")))
        elif t == "codeBlock":
            lang = attrs.get("language") or ""
            body = "".join(c.get("text", "") for c in (n.get("content") or []))
            out.append(f"```{lang}\n{body}\n```")
        elif t in ("bulletList", "orderedList"):
            for idx, li in enumerate(n.get("content") or [], 1):
                txt = " ".join(_inline_md(p.get("content")) for p in (li.get("content") or []))
                out.append((f"{idx}. " if t == "orderedList" else "- ") + txt)
        elif t == "table":
            for ri, tr in enumerate(n.get("content") or []):
                cells = [
                    " ".join(_inline_md(p.get("content")) for p in (td.get("content") or []))
                    for td in (tr.get("content") or [])
                ]
                out.append("| " + " | ".join(cells) + " |")
                if ri == 0 and cells:
                    out.append("|" + "|".join(["---"] * len(cells)) + "|")
        elif t == "horizontalRule":
            out.append("---")
        elif t in ("calloutInfo", "calloutWarning"):
            tag = "info" if t == "calloutInfo" else "warning"
            out.append(f"> [!{tag}] " + _inline_md(n.get("content")))
        elif t == "blockImage":
            blk = attrs.get("blockObject") or {}
            fn = (blk.get("content") or {}).get("file_name", "image")
            out.append(f"![]({fn})")
        elif t == "blockEmbed":
            out.append(f"[[EMBED:{attrs.get('embedUrl', '')}]]")
        elif t == "flipcard":
            out.append(f"[[FLIP:{attrs.get('question', '')}|{attrs.get('answer', '')}]]")
        elif t == "flipcardGrid":
            for c in n.get("content") or []:
                a = c.get("attrs") or {}
                out.append(f"[[FLIP:{a.get('question', '')}|{a.get('answer', '')}]]")
        else:
            out.append(f"<!-- {t} -->")
        out.append("")
    return "\n".join(out).strip() + "\n"


_COMMENT_RE = re.compile(r"<!--.*?-->")
_MD_MARKS_RE = re.compile(r"[*`#>|]")


def tiptap_to_plain_text(doc) -> str:
    """内容页 JSON → 纯文本，给 LLM 当上下文用。

    在 Markdown 的基础上去掉占位注释和 Markdown 标记符号，避免模型把
    `<!-- xxx -->` 之类的东西当成题面素材。
    """
    md = tiptap_to_markdown(doc)
    md = _COMMENT_RE.sub("", md)
    md = _MD_MARKS_RE.sub("", md)
    lines = [ln.strip() for ln in md.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()
