"""签名的生成与校验。纯函数，不碰数据库、不碰 FastAPI 依赖，方便单测。

设计说明见同目录 `__init__.py` 的模块文档。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from typing import Optional

from config.config import get_learnhouse_config

# 签名版本。改签名格式时把它加 1，旧签名会因为参与 HMAC 而自动失效。
SIGN_VERSION = "v1"

DEFAULT_TTL_SECONDS = 6 * 60 * 60      # 6 小时
MAX_TTL_SECONDS = 12 * 60 * 60         # 上限，防止调用方要一个超长有效期

# query 里的三个参数名。前端拼 URL、nginx 排查、日志脱敏都引用这里。
SIGN_QUERY_KEYS = ("sig", "exp", "uid")

# 派生密钥时的域分隔串。不要改，改了等于换密钥。
_SECRET_INFO = b"sysu-sam:ext-media-sign:v1"


class MediaSignatureError(Exception):
    """签名不合法。调用方自行决定翻成 401 还是 403。"""


# ---------------------------------------------------------------------------
# 可签名的路径白名单
#
# 只有「重媒体」才允许签名。这不是锦上添花的收窄，而是安全边界：签名等于
# 一张限定路径的身份凭据，路径面越小，泄露一条签名的后果越小。
#
# 这份正则必须与两处保持一致，改一处就要改另外两处：
#   - deploy/extra/nginx.prod.conf 顶部的 $media_path_hit
#   - apps/web/services/media/media.ts 的 isHeavyMediaPath()
#
# 路径依据（取自 apps/web/services/media/media.ts，不是照抄设计文档）：
#   getActivityMediaDirectory       -> /content/orgs/…/activities/…/video|documentpdf/…
#   getActivityBlockMediaDirectory  -> /content/orgs/…/activities/…/dynamic/blocks/
#                                        pdfBlock|videoBlock|audioBlock/…
#   getActivityVideoStreamUrl       -> /api/v1/stream/video/…
#   getVideoBlockStreamUrl          -> /api/v1/stream/block/…
#   getAudioBlockStreamUrl          -> /api/v1/stream/block/audio/…
#
# **刻意不在列**：
#   - imageBlock、课程封面、各类缩略图、机构 logo、用户头像 —— 校外要正常显示，
#     它们留在 learn 域名，走 cookie，本来就没问题
#   - 字幕 VTT（/api/v1/stream/captions/）与 HLS（/hls/、/block-hls/）—— 体积小，
#     而且字幕是 fetch(credentials:'include')，留在 learn 域名可以省掉一整层 CORS
#   - 作业参考文件、参考答案、**学生提交文件** —— 提交文件必须严格鉴权，
#     不进签名体系可以少一个泄露面
#   - 播客音频（/api/v1/stream/audio/）—— 本部署没在用播客。将来要用就加一条，
#     顺带把前端 getPodcastAudioStreamUrl 一起接进来
_SIGNABLE_PATTERNS = (
    re.compile(r"^/api/v1/stream/video/[^/]+/[^/]+/[^/]+/.+$"),
    # /block/ 与 /block/audio/ 都落在这一条里
    re.compile(r"^/api/v1/stream/block/.+$"),
    re.compile(
        r"^/content/orgs/[^/]+/courses/[^/]+/activities/[^/]+/"
        r"(?:video|documentpdf)/.+$"
    ),
    re.compile(
        r"^/content/orgs/[^/]+/courses/[^/]+/activities/[^/]+/dynamic/blocks/"
        r"(?:pdfBlock|videoBlock|audioBlock)/[^/]+/.+$"
    ),
)


def is_signable_media_path(path: str) -> bool:
    """这个 URL 路径允不允许签名 / 用签名访问。

    传的必须是 URL 路径（以 `/` 开头，未经 percent-decode）。
    `..` 之类的穿越形态在这里直接拒掉，不依赖调用方先规范化。
    """
    if not path or not path.startswith("/"):
        return False
    if ".." in path:
        return False
    return any(p.match(path) for p in _SIGNABLE_PATTERNS)


# ---------------------------------------------------------------------------


def _get_secret() -> bytes:
    """签名密钥。优先环境变量，否则从 JWT secret 派生。

    每次现算而不是缓存：HMAC 一个几十字节的串是纳秒级开销，
    而缓存会让测试里改环境变量不生效。
    """
    env = os.environ.get("LEARNHOUSE_EXT_MEDIA_SIGN_SECRET", "")
    if env.strip():
        return env.strip().encode("utf-8")

    jwt_secret = get_learnhouse_config().security_config.auth_jwt_secret_key
    if not jwt_secret:
        # 正常起不来：config.py 在启动时就会因为缺 JWT secret 而抛异常。
        raise MediaSignatureError("no signing secret available")
    return hmac.new(jwt_secret.encode("utf-8"), _SECRET_INFO, hashlib.sha256).digest()


def _message(path: str, exp: int, user_id: int) -> bytes:
    """参与 HMAC 的消息。

    用 `\\n` 分隔而不是 `|`：URL 路径里不可能出现换行，但完全可能出现 `|`，
    用 `|` 会让 (path="a|1", exp=2) 和 (path="a", exp="1|2") 撞成同一条消息。
    版本号放在最前面，换版本即整体失效。
    """
    return "\n".join([SIGN_VERSION, path, str(int(exp)), str(int(user_id))]).encode("utf-8")


def sign_media_path(
    path: str,
    user_id: int,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: Optional[int] = None,
) -> dict:
    """给一个媒体路径签名，返回 `{"path", "sig", "exp", "uid"}`。

    `path` 必须是**将来实际请求的那个 URL 路径**（`request.url.path` 的形态：
    以 `/` 开头、percent-encoding 保持原样、不带 query）。前端拼 URL 时不要再
    对它做二次编码，否则签的和验的对不上。
    """
    if not is_signable_media_path(path):
        raise MediaSignatureError(f"path is not a signable media path: {path!r}")
    if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
        raise MediaSignatureError(f"ttl out of range: {ttl_seconds}")

    current = int(now if now is not None else time.time())
    exp = current + int(ttl_seconds)
    sig = hmac.new(_get_secret(), _message(path, exp, user_id), hashlib.sha256).hexdigest()
    return {"path": path, "sig": sig, "exp": exp, "uid": int(user_id)}


def verify_media_signature(
    path: str,
    sig: str,
    exp: str | int,
    uid: str | int,
    now: Optional[int] = None,
) -> int:
    """校验签名，通过则返回签名里的 user_id，否则抛 `MediaSignatureError`。

    检查顺序刻意是「先形态、再路径白名单、再过期、最后比对 HMAC」：
    前几步都不涉及密钥，早失败可以少做一次 HMAC。
    """
    if not sig or not exp or uid in (None, ""):
        raise MediaSignatureError("incomplete signature")

    try:
        exp_i = int(exp)
        uid_i = int(uid)
    except (TypeError, ValueError):
        raise MediaSignatureError("malformed exp/uid") from None

    if uid_i <= 0:
        raise MediaSignatureError("malformed uid")

    if not is_signable_media_path(path):
        raise MediaSignatureError("path is not a signable media path")

    current = int(now if now is not None else time.time())
    if exp_i <= current:
        raise MediaSignatureError("signature expired")
    # 上限同样要卡：否则改大 exp 的攻击者虽然过不了 HMAC，但一个合法签名
    # 也不该因为服务端时钟回拨而变成近乎永久有效。
    if exp_i > current + MAX_TTL_SECONDS:
        raise MediaSignatureError("expiry too far in the future")

    expected = hmac.new(
        _get_secret(), _message(path, exp_i, uid_i), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, str(sig)):
        raise MediaSignatureError("signature mismatch")

    return uid_i


def resolve_signed_user_id(path: str, query_params, now: Optional[int] = None) -> Optional[int]:
    """从请求的 query 里取签名并校验，返回 user_id。

    没带签名参数返回 `None`（表示「这不是一个签名请求」，调用方照常走原有逻辑）；
    **带了但不合法则抛 `MediaSignatureError`** —— 不能静默降级成匿名，
    否则一个过期签名会表现成「公开课能看、非公开课 401」，排查起来毫无头绪。

    `query_params` 是任何支持 `.get(key)` 的映射（`request.query_params` 即可）。
    """
    sig = query_params.get("sig")
    exp = query_params.get("exp")
    uid = query_params.get("uid")
    if sig is None and exp is None and uid is None:
        return None
    return verify_media_signature(path, sig or "", exp or "", uid or "", now=now)
