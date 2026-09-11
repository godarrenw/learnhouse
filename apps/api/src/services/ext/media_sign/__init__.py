"""重媒体的限时签名 URL（SYSU-SAM）。

## 为什么需要它

学堂经 Cloudflare Tunnel 对校外开放后，视频 / PDF 这类重媒体要分流到只在校园网
可解析的 `media.sysu-sam.com`。最初设想的做法是 nginx 302 重定向，但那条路被
**cookie 作用域**堵死了：单租户模式下 `LH_access` 恒为 host-only（前端
`services/auth/cookies.ts` 的 `getCookieDomain` 在 tenancy=single 时直接返回
undefined），只发给 learn 域名。于是非公开课程的媒体一到 media 域名就是 401/403，
而 `<video src>` / `<iframe src>` 这类载体又发不出 `Authorization` 头，没有补救余地。

放宽 cookie 域是另一条路，但那会让所有子域都拿到会话凭据，攻击面明显变大，
而且换域期间新旧 cookie 并存、`request.cookies.get()` 取哪个不确定。**不走那条路。**

这里改成**限时签名 URL**：页面里已登录的用户先用自己的会话向
`GET /api/v1/ext/media/sign` 换一个签名，前端把签名拼进 media 域名的地址；
媒体请求本身不需要任何 cookie。

## 授权在哪一步发生

**签名只回答「这个请求是谁发的」，不回答「他能不能看」。** 拿到签名后，
`local_content.py` 与 `stream.py` 原有的课程权限检查一字不改地照常跑，
只是把「匿名用户」换成签名里的那个用户。所以：

- 签名里的 `uid` 只能是换签名的人自己（服务端从会话取，不接受调用方指定），
  不存在拿别人 uid 签名的可能；
- 换到签名不等于能看，越权与否仍由原有 RBAC 决定；
- 因此签名端点**不做**业务权限预检，只要求「已登录的真人用户」。

## 已知的、接受的风险

1. **签名 URL 泄露 = 在有效期内可以拿它读那一个媒体路径**，身份是签名人。
   这是签名 URL 方案固有的性质。缓解：绑死单个路径、只读、默认 6 小时、
   媒体路径白名单（拿到一个视频的签名不能用来读别的接口）。
2. **签名参数会进 nginx access log**，等价于短期凭据落日志。本期不处理，
   要处理就在 nginx 里对 `sig` 参数做日志脱敏。
3. 换密钥（`LEARNHOUSE_EXT_MEDIA_SIGN_SECRET` 或 JWT secret）会让所有在途签名
   立刻失效，表现是正在看的视频下一次 seek 变 403。刷新页面即可恢复。

## 密钥

`LEARNHOUSE_EXT_MEDIA_SIGN_SECRET` 环境变量；没设就从现有 JWT secret 派生
（HMAC 一个固定的域分隔串）。派生而不是直接复用，是为了让这里的签名即使被
构造出碰撞也推不回 JWT secret。
"""

from .signer import (  # noqa: F401
    DEFAULT_TTL_SECONDS,
    MAX_TTL_SECONDS,
    SIGN_QUERY_KEYS,
    MediaSignatureError,
    is_signable_media_path,
    resolve_signed_user_id,
    sign_media_path,
    verify_media_signature,
)

__all__ = [
    "DEFAULT_TTL_SECONDS",
    "MAX_TTL_SECONDS",
    "SIGN_QUERY_KEYS",
    "MediaSignatureError",
    "is_signable_media_path",
    "resolve_signed_user_id",
    "sign_media_path",
    "verify_media_signature",
]
