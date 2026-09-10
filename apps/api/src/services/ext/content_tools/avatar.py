# -*- coding: utf-8 -*-
"""网页虚拟助教（数字人）：讲稿 → 链接。

移植自教学工具 skill 的 `avatar.py`（SYSU-SAM）。原理一句话：托管着一个**纯静态
单文件 HTML** 页面，讲稿不存在服务器上，而是压缩成 base64url 塞进链接的 `#` 后面。
页面读 hash 拿到讲稿，用浏览器自带的 `speechSynthesis` 念出来，同时驱动卡通头像的
嘴部开合和字幕高亮。所以零 GPU、零 API key、零后端，代价是链接很长（这是正常的）。

**这里的 `embed_node` 故意不过 `to_embed_url()`**：那条路会对未知域名做归一化甚至
短链解析，而数字人链接的 hash 一旦被动过，讲稿就没了，学生看到的是一个空页面。
"""
import base64
import gzip
import json
import re

DEFAULT_HEIGHT = 560
#: 单句上限。Chrome 对超过 ~15 秒的 utterance 会静默截断，所以句子要短。
MAX_LINE_CHARS = 80
#: 短于这个长度的句子会和后一句合并，避免字幕碎成一地
MIN_LINE_CHARS = 6
#: 段落之间的停顿（毫秒）
PARA_PAUSE_MS = 450
#: 超过这个长度就上 gzip；短讲稿用明文 base64url，兼容最老的浏览器
GZIP_THRESHOLD = 4000

#: 组织配置 ext 段里的 key，以及对应的环境变量。三层回退由
#: `src/services/ext/config.py` 的 `get_ext_config` 统一负责。
#: 注意**前端读不到环境变量**，所以这个地址应当写进组织配置的 ext 段。
CONFIG_KEY = "avatar_page_url"
ENV_PAGE_URL = "LEARNHOUSE_EXT_AVATAR_PAGE_URL"
#: 当前部署已经上线的地址（见 skill/reference/avatar.md「当前部署」一节）。
DEFAULT_PAGE_URL = "https://blog.sysu-sam.com/@zhuyizhang/lh-avatar"

_SENT_END = "。！？!?；;"
_STRIP_PREFIX = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*(?:\[![a-z]+\])?\s*)")
_INLINE_MD = re.compile(r"(\*\*|__|\*|_|`|~~)")
_LINK_MD = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_IMG_LINE = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$")
_HR_LINE = re.compile(r"^\s*(?:---|\*\*\*|___)\s*$")
_TABLE_LINE = re.compile(r"^\s*\|")
_FENCE = re.compile(r"^\s*```")


class AvatarError(ValueError):
    """讲稿或配置的问题。路由会翻成 400。"""


# ------------------------------------------------------------ 讲稿


def _clean(line):
    """把一行 Markdown 洗成能念出来的纯文本。"""
    line = _STRIP_PREFIX.sub("", line)
    line = _LINK_MD.sub(r"\1", line)          # [文字](链接) -> 文字
    line = _INLINE_MD.sub("", line)           # 去掉 ** __ * _ ` ~~
    return line.strip()


def _split_sentence(text):
    """按句末标点断句，再对超长句强行按逗号/长度切开。"""
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in _SENT_END:
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())

    final = []
    for s in out:
        while len(s) > MAX_LINE_CHARS:
            cut = -1
            for sep in ("，", "、", ",", " "):
                cut = max(cut, s.rfind(sep, MIN_LINE_CHARS, MAX_LINE_CHARS))
            if cut <= 0:
                cut = MAX_LINE_CHARS - 1
            final.append(s[:cut + 1].strip())
            s = s[cut + 1:].strip()
        if s:
            final.append(s)
    return final


def split_script(text):
    """讲稿 → `[{"text": ..., "pause": ...}]`。

    规则：空行分段，段末补一个停顿；段内按 。！？；断句；超长句按逗号再切；
    过短的句子并进下一句。代码块、图片行、表格行、分隔线会被跳过（念不出来）。
    """
    paras, cur, in_fence = [], [], False
    for raw in (text or "").splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _IMG_LINE.match(raw) or _HR_LINE.match(raw) or _TABLE_LINE.match(raw):
            continue
        if not raw.strip():
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        c = _clean(raw)
        if c:
            cur.append(c)
    if cur:
        paras.append(" ".join(cur))

    lines = []
    for p in paras:
        sents = _split_sentence(p)
        # 太短的句子并到后一句去
        merged = []
        for s in sents:
            if merged and len(merged[-1]) < MIN_LINE_CHARS:
                merged[-1] = merged[-1] + s
            else:
                merged.append(s)
        for i, s in enumerate(merged):
            lines.append({"text": s, "pause": PARA_PAUSE_MS if i == len(merged) - 1 else 0})
    if lines:
        lines[-1]["pause"] = 0
    return lines


# ------------------------------------------------------------ 链接


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64url(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def encode_payload(data, compress=None):
    """讲稿 dict → hash 片段（不含 `#`）。

    compress=None 时按长度自动决定：短讲稿用明文 `j=`（所有浏览器都认），
    长讲稿用 gzip `s=`（需要 DecompressionStream，Chrome 80+ / Safari 16.4+）。
    """
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    plain = _b64url(raw)
    if compress is None:
        compress = len(plain) > GZIP_THRESHOLD
    if not compress:
        return "j=" + plain
    # mtime=0 让同一份讲稿每次生成的链接完全一致
    return "s=" + _b64url(gzip.compress(raw, mtime=0))


def decode_payload(fragment):
    """hash 片段 → 讲稿 dict。给测试和排查用，和页面里的 JS 是一套规则。"""
    frag = (fragment or "").lstrip("#")
    m = re.search(r"(?:^|&)([sj])=([A-Za-z0-9\-_]+)", frag)
    if not m:
        raise AvatarError("链接里没有讲稿片段（应该形如 #s=… 或 #j=…）")
    raw = _unb64url(m.group(2))
    if m.group(1) == "s":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def normalize_page_url(url):
    """校验并规整数字人页面地址。空字符串或非 http(s) 一律拒。

    组织配置和环境变量都是人手填的，填错了要在生成链接**之前**报出来，
    而不是让老师拿到一条打不开的链接。
    """
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise AvatarError("数字人页面地址要以 http:// 或 https:// 开头，当前是：%s" % url[:80])
    return url.rstrip("#").rstrip("/")


def build_url(script, page_url, title=None, compress=None):
    """讲稿 → 完整的数字人链接。纯函数，页面地址由调用方解析好传进来。

    地址的三层回退（组织配置 → 环境变量 → 默认值）走
    `src/services/ext/config.py` 的 `get_ext_config`，那是全组共用的读法，
    不在这里各写一套。

    返回 `{url, title, line_count, url_length, encoding, lines, page_url}`。
    """
    base = normalize_page_url(page_url)
    lines = split_script(script)
    if not lines:
        raise AvatarError("讲稿是空的，或者只剩下代码块 / 图片 / 表格这类念不出来的内容")
    data = {"title": title or "虚拟助教", "lines": lines}
    frag = encode_payload(data, compress=compress)
    url = base + "#" + frag
    return {"url": url, "title": data["title"], "line_count": len(lines),
            "url_length": len(url), "encoding": frag[0],
            "lines": [ln["text"] for ln in lines], "page_url": base}


def embed_node(url, height=DEFAULT_HEIGHT):
    """数字人对应的 TipTap `blockEmbed` 节点。地址原样保留，不做任何归一化。"""
    return {"type": "blockEmbed", "attrs": {
        "embedUrl": url, "embedType": "url",
        "embedHeight": int(height), "embedWidth": "100%", "alignment": "center",
    }}
