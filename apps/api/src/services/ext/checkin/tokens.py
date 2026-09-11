"""动态签到码的派生与校验（纯函数，无 IO，便于单测）。

设计：

- 时间被切成长度为 ``refresh_seconds`` 的窗口，``window = floor(now / refresh_seconds)``。
- ``mac = HMAC-SHA256(secret, "<session_uuid>:<window>")``。
- 二维码 token 取 ``mac`` 十六进制串的前 ``TOKEN_LENGTH`` 位。
- 数字口令由**同一个** mac 派生：取其后 8 字节转成整数再对 ``10**code_length`` 取模。
  所以口令和 token 一一对应，服务端校验口令时能反查出它属于哪个窗口的 token。
- 校验时接受**当前窗口与上一窗口**，避免学生在窗口切换的瞬间提交失败。
"""

import hashlib
import hmac
import secrets
import time
from typing import Optional

TOKEN_LENGTH = 16
SECRET_BYTES = 32


def generate_secret() -> str:
    """生成一场签到的 HMAC 密钥（32 字节随机数的 hex 串）。"""
    return secrets.token_hex(SECRET_BYTES)


def current_window(refresh_seconds: int, now: Optional[float] = None) -> int:
    now = time.time() if now is None else now
    return int(now // refresh_seconds)


def seconds_remaining(refresh_seconds: int, now: Optional[float] = None) -> int:
    """当前窗口还剩多少秒（用于投屏页的倒计时环）。"""
    now = time.time() if now is None else now
    elapsed = now % refresh_seconds
    return max(1, int(refresh_seconds - elapsed))


def _mac(secret: str, session_uuid: str, window: int) -> bytes:
    return hmac.new(
        secret.encode("utf-8"),
        f"{session_uuid}:{window}".encode("utf-8"),
        hashlib.sha256,
    ).digest()


def token_for_window(secret: str, session_uuid: str, window: int) -> str:
    return _mac(secret, session_uuid, window).hex()[:TOKEN_LENGTH]


def code_for_window(
    secret: str, session_uuid: str, window: int, code_length: int
) -> str:
    digest = _mac(secret, session_uuid, window)
    value = int.from_bytes(digest[-8:], "big")
    return str(value % (10**code_length)).zfill(code_length)


def accepted_windows(refresh_seconds: int, now: Optional[float] = None) -> list[int]:
    """服务端接受的窗口：当前窗口 + 上一窗口。"""
    w = current_window(refresh_seconds, now)
    return [w, w - 1]


def verify_submission(
    *,
    secret: str,
    session_uuid: str,
    refresh_seconds: int,
    code_length: int,
    token: Optional[str] = None,
    code: Optional[str] = None,
    now: Optional[float] = None,
) -> Optional[tuple[str, str]]:
    """校验一次提交。

    命中则返回 ``(method, token)``，其中 method 是 ``"qr"`` 或 ``"code"``，
    token 是该窗口的二维码 token（口令签到也归一化成 token 记录，方便审计）。
    不命中返回 ``None``。

    token 优先于 code：两个都给时按 token 判。
    """
    submitted_token = (token or "").strip().lower()
    submitted_code = (code or "").strip()

    for window in accepted_windows(refresh_seconds, now):
        expected_token = token_for_window(secret, session_uuid, window)
        if submitted_token and hmac.compare_digest(submitted_token, expected_token):
            return ("qr", expected_token)

    for window in accepted_windows(refresh_seconds, now):
        expected_token = token_for_window(secret, session_uuid, window)
        expected_code = code_for_window(secret, session_uuid, window, code_length)
        if submitted_code and hmac.compare_digest(submitted_code, expected_code):
            return ("code", expected_token)

    return None
