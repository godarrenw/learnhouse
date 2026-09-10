# -*- coding: utf-8 -*-
"""内容工具的纯逻辑测试。

这一层测的是 `src/services/ext/content_tools/` 里不碰数据库、不碰网络的部分：
Markdown ⇄ TipTap、bilibili 链接归一化、zip 安全闸、讲稿编码、二维码矩阵。
需要 DB / HTTP 的路径（导入导出真跑一门课）在本地预发环境上手工跑，记录在
`docs/sysu-sam/QA/content-tools.md`。
"""
import io
import zipfile

import pytest

from src.services.ext.content_tools import avatar, qrgen
from src.services.ext.content_tools.embeds import (
    EmbedError,
    provider_of,
    resolve_embed,
    to_embed_url,
)
from src.services.ext.content_tools.markdown import (
    front_matter,
    md_to_tiptap,
    parse_front_matter,
    scan_image_sources,
    strip_lost_nodes,
    tiptap_to_markdown,
)
from src.services.ext.content_tools.transfer import (
    MAX_ZIP_ENTRIES,
    TransferError,
    _find_asset,
    _image_block_location,
    _slug,
    locate_course_root,
    plan_import,
    read_zip_tree,
)


# ============================================================ Markdown → TipTap


def _types(doc):
    return [n["type"] for n in doc["content"]]


def test_每种块级语法都映射到对应的_tiptap_节点():
    md = "\n".join([
        "# 标题一",
        "",
        "一段正文，带 **粗体**、*斜体*、`代码` 和 [链接](https://example.com)。",
        "",
        "- 第一项",
        "- 第二项",
        "",
        "1. 甲",
        "2. 乙",
        "",
        "```python",
        "print('hi')",
        "```",
        "",
        "| 列一 | 列二 |",
        "|---|---|",
        "| a | b |",
        "",
        "---",
        "",
        "> [!info] 这是提示",
        "",
        "> [!warning] 这是警告",
        "",
        "[[FLIP:问题|答案]]",
    ])
    doc = md_to_tiptap(md)
    assert _types(doc) == [
        "heading", "paragraph", "bulletList", "orderedList", "codeBlock",
        "table", "horizontalRule", "calloutInfo", "calloutWarning", "flipcard",
    ]


def test_连续的翻转卡排成网格():
    doc = md_to_tiptap("[[FLIP:甲|A]]\n[[FLIP:乙|B]]\n[[FLIP:丙|C]]")
    assert _types(doc) == ["flipcardGrid"]
    grid = doc["content"][0]
    assert len(grid["content"]) == 3
    assert grid["attrs"]["columns"] == 3        # 奇数张排 3 列


def test_行内标记生成正确的_marks():
    doc = md_to_tiptap("普通 **粗** *斜* `码` [文字](https://a.b)")
    marks = [tuple(m["type"] for m in (n.get("marks") or []))
             for n in doc["content"][0]["content"]]
    assert ("bold",) in marks
    assert ("italic",) in marks
    assert ("code",) in marks
    assert ("link",) in marks


def test_段落遇到块级起始就断开():
    doc = md_to_tiptap("第一行\n第二行\n# 标题\n第三行")
    assert _types(doc) == ["paragraph", "heading", "paragraph"]
    assert doc["content"][0]["content"][0]["text"] == "第一行 第二行"


def test_独占一行的视频链接变成嵌入而普通链接不变():
    doc = md_to_tiptap("https://www.bilibili.com/video/BV1GJ411x7h7\n\n"
                       "[某课程](https://example.com/page)")
    assert _types(doc) == ["blockEmbed", "paragraph"]
    assert doc["content"][0]["attrs"]["embedUrl"].startswith(
        "https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7")


def test_没有上传成功的图片被跳过并记进_warnings():
    warns = []
    doc = md_to_tiptap("![图](../assets/a.png)", warnings=warns)
    assert _types(doc) == ["paragraph"]      # 空 doc 会兜底成一个空段落
    assert len(warns) == 1 and "a.png" in warns[0]


def test_图片有对应的块对象时生成_blockimage():
    blk = {"block_uuid": "block_1", "content": {"file_id": "f1", "file_format": "png",
                                                "file_name": "a.png"}}
    doc = md_to_tiptap("![图](../assets/a.png)", image_blocks={"../assets/a.png": blk})
    assert _types(doc) == ["blockImage"]
    assert doc["content"][0]["attrs"]["blockObject"] is blk


def test_scan_image_sources_按顺序去重():
    md = "![](a.png)\n\n文字\n\n![](b.png)\n\n![](a.png)"
    assert scan_image_sources(md) == ["a.png", "b.png"]


# ============================================================ 往返


ROUNDTRIP_MD = "\n".join([
    "# 第一章",
    "",
    "这是一段正文，带 **粗体** 和 [链接](https://example.com)。",
    "",
    "## 小节",
    "",
    "- 甲",
    "- 乙",
    "",
    "1. 一",
    "2. 二",
    "",
    "```js",
    "const a = 1",
    "```",
    "",
    "| 姓名 | 分数 |",
    "|---|---|",
    "| 张三 | 90 |",
    "",
    "---",
    "",
    "> [!info] 记得交作业",
    "",
    "> [!warning] 下周考试",
    "",
    "[[FLIP:什么是熵|系统混乱程度的度量]]",
    "",
])


def test_markdown_往返后节点结构一致():
    """md → tiptap → md → tiptap，两次的节点类型序列必须一样。

    文本层面不要求逐字相同（表格分隔行、空行会被规整），但结构不能漂。
    """
    doc1 = md_to_tiptap(ROUNDTRIP_MD)
    md2 = tiptap_to_markdown(doc1)
    doc2 = md_to_tiptap(md2)
    assert _types(doc1) == _types(doc2)


def test_往返保住了正文里的关键文字():
    md2 = tiptap_to_markdown(md_to_tiptap(ROUNDTRIP_MD))
    for keep in ("第一章", "**粗体**", "[链接](https://example.com)", "张三",
                 "> [!info] 记得交作业", "[[FLIP:什么是熵|系统混乱程度的度量]]"):
        assert keep in md2


def test_嵌入节点往返成_embed_标记():
    doc = md_to_tiptap("[[EMBED:https://www.bilibili.com/video/BV1GJ411x7h7]]")
    md = tiptap_to_markdown(doc)
    assert md.strip().startswith("[[EMBED:https://player.bilibili.com/player.html?bvid=BV")
    assert _types(md_to_tiptap(md)) == ["blockEmbed"]


def test_不认识的节点导出成注释而_strip_lost_nodes_把它剥掉():
    md = tiptap_to_markdown({"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "正文"}]},
        {"type": "blockVideo", "attrs": {}},
    ]})
    assert "<!-- blockVideo -->" in md
    body, lost = strip_lost_nodes(md)
    assert lost == ["blockVideo"]
    assert "<!--" not in body
    assert _types(md_to_tiptap(body)) == ["paragraph"]


# ============================================================ front matter


def test_front_matter_写了能读回来():
    text = front_matter({"type": "page", "name": "第一节", "published": "true",
                         "skipped": None}) + "# 正文\n"
    meta, body = parse_front_matter(text)
    assert meta == {"type": "page", "name": "第一节", "published": "true"}
    assert body.strip() == "# 正文"


def test_没有_front_matter_时原样返回():
    meta, body = parse_front_matter("# 只有正文\n")
    assert meta == {} and body == "# 只有正文\n"


def test_没有收尾分隔线时当作没有_front_matter():
    raw = "---\ntype: page\n# 正文"
    meta, body = parse_front_matter(raw)
    assert meta == {} and body == raw


# ============================================================ bilibili 七种形态


BILI_CASES = [
    ("视频页",
     "https://www.bilibili.com/video/BV1GJ411x7h7",
     "https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=1&autoplay=0&high_quality=1"),
    ("带分 P 与跟踪参数",
     "https://www.bilibili.com/video/BV1GJ411x7h7?p=2&spm_id_from=333.788",
     "https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=2&autoplay=0&high_quality=1"),
    ("手机版",
     "https://m.bilibili.com/video/BV1GJ411x7h7",
     "https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=1&autoplay=0&high_quality=1"),
    ("av 号",
     "https://www.bilibili.com/video/av170001",
     "https://player.bilibili.com/player.html?aid=170001&p=1&autoplay=0&high_quality=1"),
    ("已经是播放器地址（归一化）",
     "https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7&page=1&danmaku=0",
     "https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=1&autoplay=0&high_quality=1"),
    ("官方 iframe 代码整段",
     '<iframe src="//player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=3" '
     'scrolling="no" border="0" allowfullscreen="true"></iframe>',
     "https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=3&autoplay=0&high_quality=1"),
]


@pytest.mark.parametrize("label,raw,expected", BILI_CASES,
                         ids=[c[0] for c in BILI_CASES])
def test_bilibili_六种离线形态都归一化到同一个播放器地址(label, raw, expected):
    assert to_embed_url(raw, resolve_short=False) == expected


def test_b23_短链是第七种形态_跳转由_resolve_b23_link_负责(monkeypatch):
    """短链解析要联网，这里把跳转结果打桩，只验后半程的归一化。

    真解析在本地手工跑过一次，记录见 docs/sysu-sam/QA/content-tools.md。
    """
    import src.services.ext.content_tools.embeds as mod
    monkeypatch.setattr(mod, "resolve_b23_link",
                        lambda url, timeout=8: "https://www.bilibili.com/video/BV1GJ411x7h7?p=2")
    assert mod.to_embed_url("https://b23.tv/abcd1234") == (
        "https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=2&autoplay=0&high_quality=1")


def test_离线模式下短链直接抛错而不是静默返回原链接():
    with pytest.raises(EmbedError):
        to_embed_url("https://b23.tv/abcd1234", resolve_short=False)


def test_没有_src_的_iframe_报错():
    with pytest.raises(EmbedError):
        to_embed_url("<iframe width='640'></iframe>", resolve_short=False)


def test_空链接报错():
    with pytest.raises(EmbedError):
        to_embed_url("  ", resolve_short=False)


def test_抖音腾讯原样返回并标未确认():
    for url, provider in [("https://www.douyin.com/video/7123456789", "douyin"),
                          ("https://v.qq.com/x/page/abcdefg.html", "tencent")]:
        res = resolve_embed(url, resolve_short=False)
        assert res["embed_url"] == url
        assert res["provider"] == provider
        assert res["confirmed"] is False


def test_bilibili_标为已确认():
    res = resolve_embed("https://www.bilibili.com/video/BV1GJ411x7h7", resolve_short=False)
    assert res["provider"] == "bilibili" and res["confirmed"] is True


def test_youtube_能转但国内打不开所以不标已确认():
    res = resolve_embed("https://www.youtube.com/watch?v=dQw4w9WgXcQ", resolve_short=False)
    assert res["embed_url"] == "https://www.youtube.com/embed/dQw4w9WgXcQ"
    assert res["confirmed"] is False


def test_provider_of_认得出常见站点():
    assert provider_of("https://b23.tv/x") == "bilibili"
    assert provider_of("https://vimeo.com/123") == "vimeo"
    assert provider_of("https://example.com/x") == "unknown"


# ============================================================ zip 安全与结构


def _zip_of(files: dict, extra_names=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        for name in extra_names:
            zf.writestr(name, b"x")
    return buf.getvalue()


MINIMAL_EXPORT = {
    "我的课/README.md": "# 我的课\n",
    "我的课/01-第一章/01-第一节.md":
        "---\ntype: page\nname: 第一节\npublished: true\n---\n\n# 第一节\n\n![](../assets/pic.png)\n",
    "我的课/01-第一章/02-视频.md":
        "---\ntype: embed\nname: 视频\npublished: false\n---\n\n"
        "[[EMBED:https://player.bilibili.com/player.html?bvid=BV1&p=1]]\n",
    "我的课/assets/pic.png": b"\x89PNG\r\n\x1a\n" + b"0" * 40,
}


def test_读得出导出包的目录结构():
    tree = read_zip_tree(_zip_of(MINIMAL_EXPORT))
    root, chapters = plan_import(tree)
    assert root == "我的课"
    assert len(chapters) == 1
    ch_dir, entries = chapters[0]
    assert ch_dir == "01-第一章"
    assert [e[0] for e in entries] == ["01-第一节.md", "02-视频.md"]
    assert entries[0][1]["type"] == "page"
    assert entries[1][1]["type"] == "embed"


def test_zip_slip_路径直接拒绝():
    with pytest.raises(TransferError, match="非法路径"):
        read_zip_tree(_zip_of({"../../etc/passwd": "x"}))


def test_绝对路径直接拒绝():
    with pytest.raises(TransferError, match="非法路径"):
        read_zip_tree(_zip_of({"/etc/passwd": "x"}))


def test_条目太多直接拒绝():
    names = ["f%d.txt" % i for i in range(MAX_ZIP_ENTRIES + 1)]
    with pytest.raises(TransferError, match="上限"):
        read_zip_tree(_zip_of({}, extra_names=names))


def test_不是_zip_直接拒绝():
    with pytest.raises(TransferError, match="有效的 zip"):
        read_zip_tree("这不是压缩包".encode("utf-8"))


def test_空包直接拒绝():
    with pytest.raises(TransferError, match="空的"):
        read_zip_tree(_zip_of({}))


def test_macos_资源分叉被忽略():
    tree = read_zip_tree(_zip_of(dict(MINIMAL_EXPORT, **{
        "__MACOSX/我的课/._README.md": b"junk"})))
    assert all("__MACOSX" not in k for k in tree)


def test_没有_readme_报错():
    with pytest.raises(TransferError, match="README.md"):
        locate_course_root({"某目录/01-章/01-页.md": b""})


def test_多个课程目录报错():
    with pytest.raises(TransferError, match="多个课程目录"):
        locate_course_root({"甲课/README.md": b"", "乙课/README.md": b""})


def test_没有章节目录报错():
    with pytest.raises(TransferError, match="章节目录"):
        plan_import({"我的课/README.md": b"# x"})


def test_assets_目录不会被当成章节():
    tree = read_zip_tree(_zip_of(MINIMAL_EXPORT))
    _root, chapters = plan_import(tree)
    assert [c[0] for c in chapters] == ["01-第一章"]


def test_图片相对路径能在包里找到():
    tree = read_zip_tree(_zip_of(MINIMAL_EXPORT))
    data = _find_asset(tree, "我的课", "01-第一章", "../assets/pic.png")
    assert data is not None and data.startswith(b"\x89PNG")


def test_图片路径逃出压缩包时拿不到东西():
    tree = read_zip_tree(_zip_of(MINIMAL_EXPORT))
    assert _find_asset(tree, "我的课", "01-第一章", "../../../etc/passwd") is None
    assert _find_asset(tree, "我的课", "01-第一章", "/etc/passwd") is None
    assert _find_asset(tree, "我的课", "01-第一章", "https://example.com/a.png") is None


def test_文件名清洗掉了路径分隔符但留住中文():
    assert _slug("第一章 / 绪论") == "第一章 _ 绪论"
    assert _slug("") == "未命名"
    assert "/" not in _slug("a/b\\c")


def test_图片块位置能从_blockobject_反推():
    loc = _image_block_location("course_1", "activity_1", {
        "block_uuid": "block_1",
        "content": {"file_id": "abc", "file_format": "png"}})
    assert loc == ("courses/course_1/activities/activity_1/dynamic/blocks/imageBlock/block_1",
                   "abc.png")


def test_图片块缺字段时返回_none():
    assert _image_block_location("c", "a", {"block_uuid": "b", "content": {}}) is None
    assert _image_block_location("c", "a", None) is None


# ============================================================ 虚拟助教


def test_讲稿按句末标点断句():
    lines = avatar.split_script("同学们今天上课。这一章讲传热学！大家有问题吗？")
    assert [ln["text"] for ln in lines] == [
        "同学们今天上课。", "这一章讲传热学！", "大家有问题吗？"]


def test_过短的句子并进前一句免得字幕碎成一地():
    # "大家好。" 只有 4 个字，短于 MIN_LINE_CHARS，会和后一句合并
    lines = avatar.split_script("大家好。今天讲第一章的内容。")
    assert [ln["text"] for ln in lines] == ["大家好。今天讲第一章的内容。"]


def test_念不出来的内容被跳过():
    lines = avatar.split_script("\n".join([
        "开场白。", "", "```python", "print(1)", "```", "",
        "![图](a.png)", "---", "| 表 | 格 |", "", "结束语。"]))
    assert [ln["text"] for ln in lines] == ["开场白。", "结束语。"]


def test_超长句按逗号切开():
    long_sentence = "，".join(["这是一个很长的分句内容" * 2] * 6) + "。"
    lines = avatar.split_script(long_sentence)
    assert len(lines) > 1
    assert all(len(ln["text"]) <= avatar.MAX_LINE_CHARS for ln in lines)


def test_段末有停顿而最后一句没有():
    lines = avatar.split_script("第一段第一句。第一段第二句。\n\n第二段。")
    assert lines[0]["pause"] == 0
    assert lines[1]["pause"] == avatar.PARA_PAUSE_MS
    assert lines[-1]["pause"] == 0


def test_markdown_标记在讲稿里被洗掉():
    lines = avatar.split_script("# 标题\n\n- **重点**内容。")
    assert [ln["text"] for ln in lines] == ["标题", "重点内容。"]


def test_短讲稿用明文编码长讲稿用_gzip():
    short = avatar.encode_payload({"title": "x", "lines": [{"text": "短", "pause": 0}]})
    assert short.startswith("j=")
    long_data = {"title": "x", "lines": [{"text": "很长的一句话" * 5, "pause": 0}] * 200}
    assert avatar.encode_payload(long_data).startswith("s=")


@pytest.mark.parametrize("compress", [False, True])
def test_讲稿编码解码往返(compress):
    data = {"title": "第一章 导论", "lines": [{"text": "大家好。", "pause": 450},
                                              {"text": "开始上课。", "pause": 0}]}
    frag = avatar.encode_payload(data, compress=compress)
    assert avatar.decode_payload("#" + frag) == data


def test_同一份讲稿每次生成的链接完全一致():
    data = {"title": "x", "lines": [{"text": "一句话。", "pause": 0}]}
    assert avatar.encode_payload(data, compress=True) == avatar.encode_payload(data, compress=True)


def test_链接里没有讲稿片段时报错():
    with pytest.raises(avatar.AvatarError):
        avatar.decode_payload("#foo=bar")


def test_build_url_把讲稿塞进_hash():
    built = avatar.build_url("同学们今天上课。这一章讲传热学。",
                             "https://example.com/avatar", title="第一章")
    assert built["url"].startswith("https://example.com/avatar#")
    assert built["line_count"] == 2
    assert avatar.decode_payload(built["url"].split("#", 1)[1])["title"] == "第一章"


def test_空讲稿报错():
    with pytest.raises(avatar.AvatarError):
        avatar.build_url("```\nprint(1)\n```", "https://example.com/avatar")


def test_页面地址会被规整():
    assert avatar.normalize_page_url("https://example.com/a/") == "https://example.com/a"
    assert avatar.normalize_page_url("  https://example.com/a#  ") == "https://example.com/a"


@pytest.mark.parametrize("bad", ["", "   ", "javascript:alert(1)", "example.com/a",
                                 "file:///etc/passwd"])
def test_非_http_的页面地址一律拒(bad):
    """组织配置和环境变量都是人手填的，填错要在生成链接之前报出来。"""
    with pytest.raises(avatar.AvatarError):
        avatar.normalize_page_url(bad)


def test_数字人节点原样保留链接不做归一化():
    url = "https://blog.example.com/avatar#s=abcdef"
    node = avatar.embed_node(url)
    assert node["attrs"]["embedUrl"] == url          # hash 一个字符都不能少
    assert node["attrs"]["embedHeight"] == avatar.DEFAULT_HEIGHT


# ============================================================ 二维码


def _finder_at(m, r0, c0):
    """检查 (r0,c0) 起的 7x7 是不是一个定位图形：外环黑、内圈白、中心 3x3 黑。"""
    for r in range(7):
        for c in range(7):
            ring = r in (0, 6) or c in (0, 6)
            inner = 2 <= r <= 4 and 2 <= c <= 4
            expected = 1 if (ring or inner) else 0
            if m[r0 + r][c0 + c] != expected:
                return False
    return True


def test_矩阵尺寸与版本对得上():
    matrix, version, mask = qrgen.make_matrix("https://example.com/signup?code=ABC123")
    assert len(matrix) == version * 4 + 17
    assert all(len(row) == len(matrix) for row in matrix)
    assert 0 <= mask <= 7


def test_三个角上都有定位图形():
    matrix, _v, _m = qrgen.make_matrix("hello")
    size = len(matrix)
    assert _finder_at(matrix, 0, 0)
    assert _finder_at(matrix, 0, size - 7)
    assert _finder_at(matrix, size - 7, 0)


def test_定时图形是黑白交替():
    matrix, _v, _m = qrgen.make_matrix("hello")
    size = len(matrix)
    for c in range(8, size - 8):
        assert matrix[6][c] == (1 if c % 2 == 0 else 0)
    for r in range(8, size - 8):
        assert matrix[r][6] == (1 if r % 2 == 0 else 0)


@pytest.mark.parametrize("text", [
    "https://learn.example.com/signup?code=ABCD1234",
    "先进智造学堂 注册链接",
    "a",
    "x" * 180,
])
def test_二维码回读能拿回原文(text):
    """按国标反着走一遍：去掩码 → 按之字形取数据位 → 解 byte 模式载荷。

    这不是用第三方扫码器扫，但它独立于编码器的数据摆放顺序做了一次逆运算，
    掩码、格式信息、码字交织哪一步错了都会在这里露出来。
    与第三方 qrcode 库的逐格比对记录在 docs/sysu-sam/QA/content-tools.md。
    """
    matrix, version, mask = qrgen.make_matrix(text)
    # 下面的解码器按版本 1–9 的 8 位长度字段写的，版本 10 起是 16 位
    assert version <= 9
    assert _decode_qr(matrix, version, mask) == text


def _decode_qr(matrix, version, mask):
    """把矩阵还原成原文（只做数据码字，不做纠错——我们要验的是摆放和掩码）。"""
    size = len(matrix)
    reserved = qrgen._place_function_patterns([[None] * size for _ in range(size)], version)

    # 1) 去掩码
    unmasked = [row[:] for row in matrix]
    for r in range(size):
        for c in range(size):
            if not reserved[r][c] and qrgen._mask_fn(mask, r, c):
                unmasked[r][c] ^= 1

    # 2) 按之字形（从右下角起，两列一组，右列先）读出比特流
    bits = []
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:            # 第 6 列是竖向定时图形，跳过
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for c in (col, col - 1):
                if not reserved[r][c]:
                    bits.append(unmasked[r][c])
        upward = not upward
        col -= 2

    # 3) 把比特流切回码字，再按交织规则还原数据码字的原始顺序
    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits) - len(bits) % 8, 8)]
    blocks = qrgen.RS_BLOCKS_M[version]
    data_counts = []
    for count, _total, data_len in blocks:
        data_counts += [data_len] * count
    data_blocks = [[] for _ in data_counts]
    idx = 0
    for i in range(max(data_counts)):
        for b, n in enumerate(data_counts):
            if i < n:
                data_blocks[b].append(codewords[idx])
                idx += 1
    stream = [cw for blk in data_blocks for cw in blk]

    # 4) 解 byte 模式载荷：4 位模式 + 8 位长度（版本 1–9）+ 内容
    bitstr = "".join("{:08b}".format(cw) for cw in stream)
    assert bitstr[:4] == "0100", "不是 byte 模式"
    length = int(bitstr[4:12], 2)
    payload = bytes(int(bitstr[12 + i * 8:20 + i * 8], 2) for i in range(length))
    return payload.decode("utf-8")


def test_内容太长直接报错不静默截断():
    with pytest.raises(qrgen.QRError):
        qrgen.make_matrix("x" * 500)


def test_空内容报错():
    with pytest.raises(qrgen.QRError):
        qrgen.make_matrix("")


def test_svg_输出是合法的_svg_并且格子数对得上():
    matrix, _v, _m = qrgen.make_matrix("hello")
    svg = qrgen.to_svg(matrix, scale=8, quiet=4)
    assert svg.startswith("<svg xmlns=") and svg.rstrip().endswith("</svg>")
    side = (len(matrix) + 8) * 8
    assert 'width="%d"' % side in svg


def test_svg_里的说明文字做了转义():
    matrix, _v, _m = qrgen.make_matrix("hello")
    svg = qrgen.to_svg(matrix, caption='<script>&"')
    assert "<script>" not in svg
    assert "&lt;script&gt;&amp;" in svg


# ============================================================ 导入导出真跑一遍
#
# 下面这组用 conftest 的 SQLite 库跑真的 service 调用，验的是「zip 进去 → 数据库里
# 真的建出章节和页面 → 再导出来还是那些内容」。存储层（图片落盘）被打桩掉，
# 因为那部分是上游的、也不该在单测里往磁盘写东西。

from unittest.mock import AsyncMock, patch  # noqa: E402

from src.services.blocks.schemas.files import BlockFile  # noqa: E402
from src.services.ext.content_tools.transfer import (  # noqa: E402
    export_course_markdown,
    import_course_markdown,
)

_RBAC_TARGETS = [
    "src.services.ext.content_tools.transfer.check_resource_access",
    "src.services.courses.chapters.check_resource_access",
    "src.services.courses.activities.activities.check_resource_access",
    "src.services.blocks.block_types.imageBlock.imageBlock.check_resource_access",
]

IMPORT_ZIP_FILES = {
    "热工基础/README.md": "# 热工基础\n",
    "热工基础/01-绪论/01-课程简介.md": "\n".join([
        "---",
        "type: page",
        "name: 课程简介",
        "published: true",
        "---",
        "",
        "# 课程简介",
        "",
        "这门课讲 **传热** 与热力学。",
        "",
        "- 第一讲：导热",
        "- 第二讲：对流",
        "",
        "![示意图](../assets/pic.png)",
        "",
        "> [!info] 每周三上课",
        "",
    ]),
    "热工基础/01-绪论/02-导学视频.md": "\n".join([
        "---",
        "type: embed",
        "name: 导学视频",
        "published: false",
        "---",
        "",
        "[[EMBED:https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7&p=1]]",
        "",
    ]),
    "热工基础/01-绪论/03-讲义.md": "\n".join([
        "---", "type: pdf", "name: 讲义", "published: true", "---", "",
        "# 讲义\n", "",
    ]),
    "热工基础/assets/pic.png": b"\x89PNG\r\n\x1a\n" + b"0" * 64,
}


def _fake_block_file(*_args, **_kwargs):
    return BlockFile(file_id="fakefileid", file_format="png", file_name="pic.png",
                     file_size=72, file_type="image/png", activity_uuid="activity_x")


class TestImportExportRoundtrip:
    """zip → 数据库 → zip。"""

    def _patches(self):
        ctxs = [patch(t, new_callable=AsyncMock) for t in _RBAC_TARGETS]
        ctxs.append(patch(
            "src.services.blocks.block_types.imageBlock.imageBlock"
            ".upload_file_and_return_file_object",
            new_callable=AsyncMock, side_effect=_fake_block_file))
        # update_activity 会起一个后台任务重建向量索引，单测里没这套东西
        ctxs.append(patch(
            "src.services.courses.activities.activities._trigger_course_embedding",
            new_callable=AsyncMock))
        return ctxs

    async def _import(self, mock_request, db, admin_user, course, files=None):
        ctxs = self._patches()
        for c in ctxs:
            c.start()
        try:
            return await import_course_markdown(
                mock_request, course.course_uuid,
                _zip_of(files or IMPORT_ZIP_FILES), admin_user, db)
        finally:
            for c in ctxs:
                c.stop()

    @pytest.mark.asyncio
    async def test_导入建出章节与页面并跳过不支持的类型(
            self, mock_request, db, org, course, admin_user):
        res = await self._import(mock_request, db, admin_user, course)

        assert res["counts"]["chapters"] == 1
        assert res["chapters_created"][0]["name"] == "绪论"      # 序号前缀被剥掉
        assert res["counts"]["activities"] == 2                  # page + embed
        kinds = sorted(a["type"] for a in res["activities_created"])
        assert kinds == ["embed", "page"]
        # PDF 不还原，但必须逐条列出来而不是静默丢
        assert res["counts"]["skipped"] == 1
        assert res["skipped"][0]["type"] == "pdf"
        assert "重新上传" in res["skipped"][0]["reason"]

    @pytest.mark.asyncio
    async def test_导入的页面内容里图片真的变成了_blockimage(
            self, mock_request, db, org, course, admin_user):
        res = await self._import(mock_request, db, admin_user, course)
        page = next(a for a in res["activities_created"] if a["type"] == "page")
        assert page["node_types"] == [
            "heading", "paragraph", "bulletList", "blockImage", "calloutInfo"]
        assert page["warnings"] == []

    @pytest.mark.asyncio
    async def test_压缩包里没有的图片只记警告不让整页失败(
            self, mock_request, db, org, course, admin_user):
        files = dict(IMPORT_ZIP_FILES)
        del files["热工基础/assets/pic.png"]
        res = await self._import(mock_request, db, admin_user, course, files)
        page = next(a for a in res["activities_created"] if a["type"] == "page")
        assert "blockImage" not in page["node_types"]
        assert any("不在压缩包里" in w for w in page["warnings"])

    @pytest.mark.asyncio
    async def test_发布状态沿用_front_matter(
            self, mock_request, db, org, course, admin_user):
        from sqlmodel import select as _select

        from src.db.courses.activities import Activity as _Activity
        await self._import(mock_request, db, admin_user, course)
        rows = (await db.execute(_select(_Activity))).scalars().all()
        by_name = {a.name: a for a in rows}
        assert by_name["课程简介"].published is True
        assert by_name["导学视频"].published is False

    @pytest.mark.asyncio
    async def test_导出把刚导入的内容原样还原(
            self, mock_request, db, org, course, admin_user):
        await self._import(mock_request, db, admin_user, course)

        with patch("src.services.ext.content_tools.transfer.check_resource_access",
                   new_callable=AsyncMock):
            # 图片字节要从存储层读，单测里没有那个目录，所以关掉图片
            result = await export_course_markdown(
                mock_request, course.course_uuid, admin_user, db, download_images=False)

        names = zipfile.ZipFile(io.BytesIO(result["zip_bytes"])).namelist()
        assert "Test Course/README.md" in names
        assert "Test Course/01-绪论/01-课程简介.md" in names
        assert "Test Course/01-绪论/02-导学视频.md" in names
        assert result["summary"]["chapters"] == 1
        assert result["summary"]["files"] == 2
        assert result["filename"] == "Test Course.zip"

        zf = zipfile.ZipFile(io.BytesIO(result["zip_bytes"]))
        page_md = zf.read("Test Course/01-绪论/01-课程简介.md").decode("utf-8")
        meta, body = parse_front_matter(page_md)
        assert meta["type"] == "page" and meta["published"] == "true"
        assert "# 课程简介" in body
        assert "**传热**" in body
        assert "> [!info] 每周三上课" in body

        embed_md = zf.read("Test Course/01-绪论/02-导学视频.md").decode("utf-8")
        assert "[[EMBED:https://player.bilibili.com/player.html?bvid=BV1GJ411x7h7" in embed_md

        readme = zf.read("Test Course/README.md").decode("utf-8")
        assert "## 目录" in readme
        assert "只能还原" in readme          # 有损导出的说明必须在

    @pytest.mark.asyncio
    async def test_导出的包能再导入回去且结构一致(
            self, mock_request, db, org, course, admin_user):
        await self._import(mock_request, db, admin_user, course)
        with patch("src.services.ext.content_tools.transfer.check_resource_access",
                   new_callable=AsyncMock):
            exported = await export_course_markdown(
                mock_request, course.course_uuid, admin_user, db, download_images=False)

        tree = read_zip_tree(exported["zip_bytes"])
        _root, chapters = plan_import(tree)
        assert [c[0] for c in chapters] == ["01-绪论"]
        assert [e[1]["type"] for e in chapters[0][1]] == ["page", "embed"]

    @pytest.mark.asyncio
    async def test_课程不存在时报_404(self, mock_request, db, org, admin_user):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await import_course_markdown(
                mock_request, "course_不存在", _zip_of(IMPORT_ZIP_FILES), admin_user, db)
        assert exc.value.status_code == 404


class TestAvatarAppend:
    """虚拟助教追加到内容页。用的是真的 service 调用，不是打桩。"""

    async def _append(self, mock_request, db, admin_user, activity_uuid, script="大家好，今天讲第一章。"):
        from src.services.ext.content_tools.activities import append_avatar_embed

        ctxs = [
            patch("src.services.courses.activities.activities.check_resource_access",
                  new_callable=AsyncMock),
            patch("src.services.courses.activities.activities._trigger_course_embedding",
                  new_callable=AsyncMock),
        ]
        for c in ctxs:
            c.start()
        try:
            return await append_avatar_embed(
                mock_request, activity_uuid, script, admin_user, db,
                page_url="https://example.com/avatar")
        finally:
            for c in ctxs:
                c.stop()

    @pytest.mark.asyncio
    async def test_追加到已有内容的页面(self, mock_request, db, org, course, chapter,
                                        activity, admin_user):
        activity.content = {"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "原有正文"}]}]}
        db.add(activity)
        await db.commit()

        res = await self._append(mock_request, db, admin_user, activity.activity_uuid)
        assert res["nodes_before"] == 1
        assert res["nodes_after"] == 2
        assert res["url_length"] > 0
        assert res["embed_url"].startswith("https://example.com/avatar#")

        await db.refresh(activity)
        nodes = activity.content["content"]
        assert nodes[0]["content"][0]["text"] == "原有正文"      # 原有内容没被动
        assert nodes[-1]["type"] == "blockEmbed"
        assert nodes[-1]["attrs"]["embedHeight"] == avatar.DEFAULT_HEIGHT

    @pytest.mark.asyncio
    async def test_还没写过正文的页面也能加(self, mock_request, db, org, course, chapter,
                                            activity, admin_user):
        """新建的内容页 content 是 `{}`，既不是 doc 也不是别的。

        这是老师最想加虚拟助教的场景（新建一页只放一个数字人），
        按 content 长相判断会把它误判成「不是内容页」拒掉。
        """
        activity.content = {}
        db.add(activity)
        await db.commit()

        res = await self._append(mock_request, db, admin_user, activity.activity_uuid)
        assert res["nodes_before"] == 0
        assert res["nodes_after"] == 1

        await db.refresh(activity)
        assert activity.content["type"] == "doc"
        assert activity.content["content"][0]["type"] == "blockEmbed"

    @pytest.mark.asyncio
    async def test_带小标题时多插一个二级标题(self, mock_request, db, org, course, chapter,
                                              activity, admin_user):
        from src.services.ext.content_tools.activities import append_avatar_embed

        activity.content = {}
        db.add(activity)
        await db.commit()
        ctxs = [
            patch("src.services.courses.activities.activities.check_resource_access",
                  new_callable=AsyncMock),
            patch("src.services.courses.activities.activities._trigger_course_embedding",
                  new_callable=AsyncMock),
        ]
        for c in ctxs:
            c.start()
        try:
            res = await append_avatar_embed(
                mock_request, activity.activity_uuid, "大家好，今天讲第一章。", admin_user, db,
                page_url="https://example.com/avatar", title="本节要点")
        finally:
            for c in ctxs:
                c.stop()

        assert res["nodes_after"] == 2
        await db.refresh(activity)
        assert activity.content["content"][0]["type"] == "heading"
        assert activity.content["content"][1]["type"] == "blockEmbed"

    @pytest.mark.asyncio
    async def test_不是内容页的活动被拒(self, mock_request, db, org, course, chapter,
                                        activity, admin_user):
        from fastapi import HTTPException

        from src.db.courses.activities import ActivitySubTypeEnum
        activity.activity_sub_type = ActivitySubTypeEnum.SUBTYPE_DYNAMIC_EMBED
        activity.content = {"embed_url": "https://player.bilibili.com/player.html?bvid=BV1"}
        db.add(activity)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await self._append(mock_request, db, admin_user, activity.activity_uuid)
        assert exc.value.status_code == 400
        assert "不是富文本内容页" in exc.value.detail

    @pytest.mark.asyncio
    async def test_活动不存在报_404(self, mock_request, db, org, admin_user):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await self._append(mock_request, db, admin_user, "activity_不存在")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_空讲稿在动页面之前就报错(self, mock_request, db, org, course, chapter,
                                            activity, admin_user):
        """先算链接再动页面：讲稿有问题时页面一个字都不该被改。"""
        activity.content = {"type": "doc", "content": []}
        db.add(activity)
        await db.commit()

        with pytest.raises(avatar.AvatarError):
            await self._append(mock_request, db, admin_user, activity.activity_uuid,
                               script="```\nprint(1)\n```")
        await db.refresh(activity)
        assert activity.content == {"type": "doc", "content": []}


# ============================================================ 短链跳转白名单


class TestRedirectAllowlist:
    """`resolve_b23_link` 是**服务端**发起的请求，跟的是第三方给的 Location。

    一条被做过手脚的短链可以把服务端引到内网地址上去（SSRF），所以每一跳都要
    查白名单。这几条把行为钉死。
    """

    def test_白名单认自身与子域(self):
        import src.services.ext.content_tools.embeds as mod
        for good in ["https://b23.tv/x", "https://www.bilibili.com/video/BV1",
                     "https://m.bilibili.com/video/BV1",
                     "https://player.bilibili.com/player.html?bvid=BV1",
                     "https://space.bilibili.com/123"]:
            assert mod._host_allowed(good), good

    def test_白名单拒掉内网与他站(self):
        import src.services.ext.content_tools.embeds as mod
        for bad in ["http://127.0.0.1:8000/x", "http://169.254.169.254/latest/meta-data",
                    "http://localhost/admin", "https://evil.com/x",
                    # 后缀相似但不是子域：bilibili.com.evil.com
                    "https://bilibili.com.evil.com/x",
                    "https://notbilibili.com/x", "not-a-url", ""]:
            assert not mod._host_allowed(bad), bad

    def test_入口地址不是_bilibili_直接拒(self):
        import src.services.ext.content_tools.embeds as mod
        with pytest.raises(EmbedError, match="只解析"):
            mod.resolve_b23_link("https://evil.com/x")

    def test_跳到站外就中止(self, monkeypatch):
        """第一跳把我们引到元数据服务地址，必须报错而不是继续跟。"""
        import urllib.error

        import src.services.ext.content_tools.embeds as mod

        class _Redirect(urllib.error.HTTPError):
            """伪造一次 302，Location 指向内网。"""

            def __init__(self):
                self.headers = {"Location": "http://169.254.169.254/latest/meta-data"}

        class _Opener:
            def open(self, _req, timeout=None):
                raise _Redirect()

        monkeypatch.setattr(mod.urllib.request, "build_opener", lambda *a, **k: _Opener())
        with pytest.raises(EmbedError, match="bilibili 以外"):
            mod.resolve_b23_link("https://b23.tv/abcd")


# ============================================================ zip 炸弹


class TestZipBomb:
    def test_不信_zip_头声明的大小(self, monkeypatch):
        """把「解压后总大小」的上限临时调小，验证是按**实际读到的字节**计的。

        真正的 zip 炸弹会把头里的 file_size 写成很小的数骗过预检，
        然后 zf.read() 一把解出几个 G。所以这里读的时候边读边数。
        """
        import src.services.ext.content_tools.transfer as mod

        payload = b"A" * 200_000          # 高度可压缩，压缩包本身很小
        raw = _zip_of({"课程/README.md": "# x", "课程/big.bin": payload})

        monkeypatch.setattr(mod, "MAX_UNCOMPRESSED_BYTES", 50_000)
        with pytest.raises(TransferError, match="上限"):
            mod.read_zip_tree(raw)

    def test_伪造的_file_size_骗不过去(self, monkeypatch):
        """直接把 zip 头里的 file_size 改成 1，旧写法会放行。"""
        import src.services.ext.content_tools.transfer as mod

        raw = _zip_of({"课程/README.md": "# x", "课程/big.bin": b"B" * 200_000})
        zf = zipfile.ZipFile(io.BytesIO(raw))
        # 预检若信头，这个和会小得离谱
        forged_total = 1 * len(zf.infolist())
        assert forged_total < 50_000

        monkeypatch.setattr(mod, "MAX_UNCOMPRESSED_BYTES", 50_000)
        with pytest.raises(TransferError):
            mod.read_zip_tree(raw)

    def test_正常包不受影响(self):
        tree = read_zip_tree(_zip_of(MINIMAL_EXPORT))
        assert "我的课/README.md" in tree


# ============================================================ 作业导出


class _FakeTask:
    def __init__(self, **kw):
        self.title = kw.get("title", "")
        self.description = kw.get("description", "")
        self.hint = kw.get("hint", "")
        self.assignment_type = kw["assignment_type"]
        self.contents = kw.get("contents", {})
        self.max_grade_value = kw.get("max_grade_value", 100)


class _FakeAssignment:
    def __init__(self, **kw):
        self.title = kw.get("title", "第一次作业")
        self.description = kw.get("description", "")
        self.due_date = kw.get("due_date")
        self.published = kw.get("published", True)
        self.grading_type = kw.get("grading_type", "NUMERIC")
        self.show_correct_answers = kw.get("show_correct_answers", False)


class TestAssignmentMarkdown:
    """作业导出：题目 + 参考答案。只读上游的两张表，不依赖作业工具那条线的模块。"""

    def test_抬头写清楚了含参考答案(self):
        from src.services.ext.content_tools.assignments_md import render_assignment_markdown

        md = render_assignment_markdown(_FakeAssignment(due_date="2026-10-01"), [])
        assert md.startswith("# 第一次作业")
        assert "> [!info]" in md and "截止 2026-10-01" in md
        assert "参考答案是给老师看的" in md
        assert "这份作业还没有题目" in md

    def test_选择题列出选项并标出正确项(self):
        from src.services.ext.content_tools.assignments_md import render_assignment_markdown
        from src.db.courses.assignments import AssignmentTaskTypeEnum

        task = _FakeTask(
            title="判断导热方式", assignment_type=AssignmentTaskTypeEnum.QUIZ,
            contents={"questions": [{
                "questionText": "下面哪些属于传热方式？",
                "options": [
                    {"text": "导热", "assigned_right_answer": True},
                    {"text": "对流", "assigned_right_answer": True},
                    {"text": "折射", "assigned_right_answer": False},
                ]}]})
        md = render_assignment_markdown(_FakeAssignment(), [task])
        assert "第 1 题 · 判断导热方式（选择题，满分 100）" in md
        assert "- A. 导热" in md and "- C. 折射" in md
        assert "**参考答案**：A、B" in md

    def test_简答数值编程各有参考答案(self):
        from src.services.ext.content_tools.assignments_md import render_assignment_markdown
        from src.db.courses.assignments import AssignmentTaskTypeEnum

        tasks = [
            _FakeTask(assignment_type=AssignmentTaskTypeEnum.SHORT_ANSWER,
                      contents={"prompt": "什么是熵？", "correct_answers": ["混乱程度"],
                                "match_mode": "contains"}),
            _FakeTask(assignment_type=AssignmentTaskTypeEnum.NUMBER_ANSWER,
                      contents={"prompt": "水的沸点？", "correct_value": 100,
                                "unit": "℃", "tolerance": 0.5}),
            _FakeTask(assignment_type=AssignmentTaskTypeEnum.CODE,
                      contents={"language": "python", "starter_code": "def f():\n    pass",
                                "solution_code": "def f():\n    return 1"}),
        ]
        md = render_assignment_markdown(_FakeAssignment(), tasks)
        assert "**参考答案**：混乱程度（匹配方式 contains）" in md
        assert "**参考答案**：100 ℃（容差 ±0.5）" in md
        assert "**参考解法**：" in md and "return 1" in md

    def test_文件提交题说明没有标准答案(self):
        from src.services.ext.content_tools.assignments_md import render_assignment_markdown
        from src.db.courses.assignments import AssignmentTaskTypeEnum

        md = render_assignment_markdown(_FakeAssignment(), [
            _FakeTask(assignment_type=AssignmentTaskTypeEnum.FILE_SUBMISSION)])
        assert "学生上传文件作答，没有标准答案" in md

    def test_没填答案时说没填而不是留空(self):
        from src.services.ext.content_tools.assignments_md import render_assignment_markdown
        from src.db.courses.assignments import AssignmentTaskTypeEnum

        md = render_assignment_markdown(_FakeAssignment(), [
            _FakeTask(assignment_type=AssignmentTaskTypeEnum.QUIZ,
                      contents={"questions": [{"questionText": "问", "options": [
                          {"text": "甲", "assigned_right_answer": False}]}]})])
        assert "没有标正确选项" in md

    def test_认不出的题型不炸只提示(self):
        from src.services.ext.content_tools.assignments_md import render_assignment_markdown

        md = render_assignment_markdown(_FakeAssignment(), [
            _FakeTask(assignment_type="SOME_FUTURE_TYPE", contents={"x": 1})])
        assert "SOME_FUTURE_TYPE" in md
        assert "请到网页上查看" in md

    def test_提示会带出来(self):
        from src.services.ext.content_tools.assignments_md import render_assignment_markdown
        from src.db.courses.assignments import AssignmentTaskTypeEnum

        md = render_assignment_markdown(_FakeAssignment(), [
            _FakeTask(assignment_type=AssignmentTaskTypeEnum.FILE_SUBMISSION,
                      hint="记得写单位")])
        assert "> [!info] 提示：记得写单位" in md

    def test_超过_26_个选项退回数字标号(self):
        from src.services.ext.content_tools.assignments_md import render_assignment_markdown
        from src.db.courses.assignments import AssignmentTaskTypeEnum

        options = [{"text": "选项%d" % i, "assigned_right_answer": i == 26}
                   for i in range(30)]
        md = render_assignment_markdown(_FakeAssignment(), [
            _FakeTask(assignment_type=AssignmentTaskTypeEnum.QUIZ,
                      contents={"questions": [{"questionText": "问", "options": options}]})])
        assert "**参考答案**：27" in md

    def test_题干为空时明说而不是只留个标题(self):
        """本地库里就有这种数据：题目建了但 contents 还是 {}。

        只输出一个光秃秃的标题会让老师以为导出坏了。
        """
        from src.services.ext.content_tools.assignments_md import render_assignment_markdown
        from src.db.courses.assignments import AssignmentTaskTypeEnum

        md = render_assignment_markdown(_FakeAssignment(), [
            _FakeTask(title="第 1 题", assignment_type=AssignmentTaskTypeEnum.QUIZ,
                      contents={})])
        assert "这道题还没有录入内容" in md
