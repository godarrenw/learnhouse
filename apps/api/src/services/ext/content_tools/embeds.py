# -*- coding: utf-8 -*-
"""视频链接 → 可嵌入的播放器地址。

移植自教学工具 skill 的 `content.py`（SYSU-SAM），七种 bilibili 形态与 b23 短链
解析逐行照搬，只把「抛 ContentError」换成本模块自己的异常类型，并额外返回
provider / confirmed 两个字段，让前端能对未验证的站点给出提示。

**这个模块里的网络请求是同步的**（urllib）。在 async 路由里调用 `resolve_embed`
必须走 `run_in_threadpool`，不要直接 await。
"""
import re
import urllib.error
import urllib.parse
import urllib.request


class EmbedError(ValueError):
    """链接本身的问题（不是 HTTP 错误）。路由会翻成 400。"""


# bilibili 各种链接形态
BILI_IFRAME_SRC_RE = re.compile(r"""<iframe[^>]*?\ssrc\s*=\s*["']([^"']+)["']""", re.I | re.S)
BILI_B23_RE = re.compile(r"^https?://b23\.tv/[0-9A-Za-z]+", re.I)
BILI_BV_RE = re.compile(r"bilibili\.com/video/(BV[0-9A-Za-z]+)")
BILI_AV_RE = re.compile(r"bilibili\.com/video/av(\d+)", re.I)
BILI_PLAYER_RE = re.compile(r"player\.bilibili\.com/player\.html", re.I)
BILI_PLAYER_BASE = "https://player.bilibili.com/player.html"

VIDEO_HOST_RE = re.compile(
    r"(bilibili\.com|b23\.tv|player\.bilibili\.com|douyin\.com|v\.qq\.com|"
    r"youtube\.com|youtu\.be|vimeo\.com)", re.I
)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

#: 已经在真实浏览器里看到播放器渲染出来的站点。其余站点标 confirmed=False，
#: 前端据此提示「这个站点没验证过，请自己在浏览器里看一眼」。
CONFIRMED_PROVIDERS = {"bilibili"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """让 urllib 在 3xx 处停下，我们只要 Location 头，不想真的把页面拉下来。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _bili_player_url(bvid=None, aid=None, page=1):
    """统一的 bilibili 播放器地址。高清打开、不自动播放。"""
    key = "bvid=%s" % bvid if bvid else "aid=%s" % aid
    return "%s?%s&p=%d&autoplay=0&high_quality=1" % (BILI_PLAYER_BASE, key, int(page or 1))


def _page_of(url, default=1):
    """从链接里取分 P 号（?p=2）。取不到就是第 1 P。"""
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        return max(1, int(q.get("p", [default])[0]))
    except (ValueError, TypeError):
        return default


def resolve_b23_link(url, timeout=8):
    """把 b23.tv 短链换成真实的 bilibili 视频地址。

    只读 Location 头，不下载页面；绕过系统代理（b23.tv 国内直连可达）。最多跟 3 跳。
    每一跳先试两次 HEAD，再退回 GET —— b23.tv 偶尔会掐掉 HTTP/1.1 的 HEAD 连接。
    解析不出来就抛 EmbedError，**不会静默把短链当播放器地址塞进页面** ——
    因为短链直接放进 iframe 是放不出播放器的，静默失败等于给老师一个空白框。
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _one_hop(u):
        last = None
        for method in ("HEAD", "HEAD", "GET"):
            req = urllib.request.Request(u, method=method, headers={"User-Agent": _UA})
            try:
                resp = opener.open(req, timeout=timeout)
                return resp.headers.get("Location")
            except urllib.error.HTTPError as e:      # 3xx 走这里，Location 在头里
                return e.headers.get("Location") if e.headers else None
            except Exception as e:                   # 连接被掐、DNS、超时
                last = e
        raise EmbedError(
            "b23.tv 短链解析失败（%s: %s）。请在浏览器里打开这个短链，"
            "把地址栏里完整的 https://www.bilibili.com/video/BV... 地址贴过来。"
            % (type(last).__name__, str(last)[:120]))

    cur, hops = url.strip(), 0
    while hops < 3:
        hops += 1
        loc = _one_hop(cur)
        if not loc:
            break
        cur = urllib.parse.urljoin(cur, loc)
        if BILI_BV_RE.search(cur) or BILI_AV_RE.search(cur) or BILI_PLAYER_RE.search(cur):
            return cur
    raise EmbedError(
        "b23.tv 短链没有跳转到可识别的 bilibili 视频地址（跟到 %s）。请在浏览器里打开它，"
        "把地址栏里完整的 https://www.bilibili.com/video/BV... 地址贴过来。" % cur[:160])


def to_embed_url(url, resolve_short=True):
    """把常见视频链接转成可以放进 iframe 的播放器地址。

    bilibili 认这七种形态（skill 里已全部线上验证）：视频页、带分 P 参数的视频页、
    手机版 m.bilibili.com、av 号、b23.tv 短链、已经是 player.bilibili.com 的地址、
    官方 `<iframe …>` 嵌入代码整段。统一输出
    `https://player.bilibili.com/player.html?bvid=…&p=N&autoplay=0&high_quality=1`。

    `resolve_short=False` 关掉网络请求（离线测试用），此时短链直接抛错。
    """
    u = (url or "").strip()
    if not u:
        raise EmbedError("链接是空的")

    # 1) 整段 <iframe …> 官方嵌入代码 → 取 src 再走一遍
    if "<iframe" in u.lower():
        m = BILI_IFRAME_SRC_RE.search(u)
        if not m:
            raise EmbedError("这段 <iframe> 里没找到 src，请直接贴视频页链接")
        src = m.group(1).strip()
        if src.startswith("//"):          # 官方代码是协议相对地址
            src = "https:" + src
        return to_embed_url(src, resolve_short=resolve_short)

    # 2) b23.tv 短链 → 解析成真实地址再走一遍
    if BILI_B23_RE.match(u):
        if not resolve_short:
            raise EmbedError("b23.tv 短链需要联网解析（resolve_short=False 时不解析）")
        return to_embed_url(resolve_b23_link(u), resolve_short=False)

    # 3) 已经是播放器地址 → 归一化（取 bvid/aid + p 重拼），取不出就原样用
    if BILI_PLAYER_RE.search(u):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
        bvid = (q.get("bvid") or [None])[0]
        aid = (q.get("aid") or [None])[0]
        if bvid or aid:
            return _bili_player_url(bvid=bvid, aid=aid, page=_page_of(u))
        return u

    # 4) 普通视频页：BV 号 / av 号，分 P 参数保留
    m = BILI_BV_RE.search(u)
    if m:
        return _bili_player_url(bvid=m.group(1), page=_page_of(u))
    m = BILI_AV_RE.search(u)
    if m:
        return _bili_player_url(aid=m.group(1), page=_page_of(u))

    m = re.search(r"youtube\.com/watch\?.*?v=([\w-]+)", u) or re.search(r"youtu\.be/([\w-]+)", u)
    if m:
        # 国内网络打不开，仅为完整性保留
        return "https://www.youtube.com/embed/%s" % m.group(1)
    m = re.search(r"vimeo\.com/(\d+)", u)
    if m:
        return "https://player.vimeo.com/video/%s" % m.group(1)
    # 抖音、腾讯视频以及其他已经是播放器地址的，原样返回
    return u


def provider_of(url):
    """看这个链接属于哪个站点。认不出来返回 'unknown'。"""
    u = (url or "").lower()
    if "bilibili.com" in u or "b23.tv" in u:
        return "bilibili"
    if "douyin.com" in u:
        return "douyin"
    if "v.qq.com" in u or "qq.com/txp" in u:
        return "tencent"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "vimeo.com" in u:
        return "vimeo"
    return "unknown"


def is_video_link(url):
    """这条链接是不是我们认识的视频站点。编辑器粘贴规则的前置判断。"""
    return bool(VIDEO_HOST_RE.search(url or ""))


def resolve_embed(url, resolve_short=True):
    """路由层用的封装：返回 {embed_url, provider, confirmed, source_url}。

    `confirmed=False` 表示这个站点的 iframe 我们没在浏览器里亲眼验证过
    （抖音、腾讯视频），或者在国内网络根本打不开（YouTube、Vimeo）。
    前端应当照常插入，但给老师一句提示。
    """
    source = (url or "").strip()
    provider = provider_of(source)
    embed_url = to_embed_url(source, resolve_short=resolve_short)
    if provider == "unknown":
        provider = provider_of(embed_url)
    return {
        "embed_url": embed_url,
        "provider": provider,
        "confirmed": provider in CONFIRMED_PROVIDERS,
        "source_url": source,
    }
